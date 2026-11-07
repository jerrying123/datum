"""Lazy URDF bring-up: export from saved CAD at runtime, never from a stale file.

The URDF exists in most stacks only because simulation systems cannot load the
native CAD. This module brings it up on demand: it captures the exact saved
sources with the same preflight the Studio spool uses, exports with the
SolidCraft CLI into an isolated scratch directory, structurally checks the
output, and returns the URDF text plus a machine-readable report. No checked-in
URDF file is required or updated, so a node can never bring up a URDF that has
drifted from its CAD: the output is generated from the live sources at
evaluation time and stamped with their hashes.

Geometry is generated in the same evaluation, so meshes and CAD output cannot
drift from the URDF either: every URDF-referenced STL is exported from the
captured sources into the bundle (the structural check rejects a URDF whose
meshes are missing), a whole-assembly STEP is requested from the exporter, and
content-addressed per-part STEP blobs embedded in the saved files are extracted
into the bundle after verifying each blob's SHA-256 against its own name.
Per-part STEP blobs are not mapped to URDF links; that correspondence is not
established here.

Note document shape: exported geometry comes from the proprietary exporter in
an isolated scratch; fidelity to native CAD geometry is the exporter's
contract, not a runtime guarantee.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from datum_parameter_studio.urdf_check import check_urdf

_REPORT_SCHEMA = 'datum.lazy-urdf-report/2'


def _resolve_executable(name, env_key, role):
    configured = os.environ.get(env_key)
    path = Path(configured or name)
    if not path.is_file():
        found = shutil.which(str(path))
        if found:
            path = Path(found)
    if not path.is_file():
        raise ValueError('missing %s executable: set %s or install %s' % (role, env_key, path))
    return path


def _run_exporter(child, deadline):
    log = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(child, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while process.poll() is None:
            if time.monotonic() > deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise TimeoutError('URDF export timed out')
            time.sleep(.05)
        log.seek(0)
        output = log.read(65536).decode(errors='replace')
    finally:
        log.close()
    return process.returncode, output


def _mesh_bundle_mapping(urdf_path):
    """Map each URDF-referenced mesh filename to the links that reference it."""
    mapping = {}
    for link in ET.parse(urdf_path).getroot().findall('link'):
        for mesh in link.iter('mesh'):
            mapping.setdefault(mesh.get('filename', ''), []).append(link.get('name'))
    return mapping


def _extract_part_steps(scratch, sources, steps_dir):
    """Extract embedded content-addressed STEP blobs from captured sources.

    SolidCraft assemblies store geometry as blobs/<sha256>.step; the entry
    name is the content hash, so extraction verifies each blob against it.
    Returns {blob_sha256: source_path} for the kept blobs and a list of
    {source, reason} diagnostics for skipped files or blobs.
    """
    extracted = {}
    diagnostics = []
    for name in sources:
        archive = scratch / name
        try:
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.namelist():
                    filename = entry.rsplit('/', 1)[-1]
                    stem = filename[:-5] if filename.endswith('.step') else None
                    if not entry.startswith('blobs/') or not stem or len(stem) != 64 or any(ch not in '0123456789abcdef' for ch in stem):
                        continue
                    if stem in extracted:
                        continue
                    payload = bundle.read(entry)
                    if hashlib.sha256(payload).hexdigest() != stem:
                        diagnostics.append({'source': name, 'reason': 'blob content does not match its %s entry name' % entry.rsplit('/', 1)[-1]})
                        continue
                    if not payload.startswith(b'ISO-10303-21;'):
                        diagnostics.append({'source': name, 'reason': 'blob is not STEP text: %s' % entry.rsplit('/', 1)[-1]})
                        continue
                    if len(payload) > 64 * 1024 * 1024:
                        diagnostics.append({'source': name, 'reason': 'blob exceeds size limit: %s' % entry.rsplit('/', 1)[-1]})
                        continue
                    steps_dir.mkdir(parents=True, exist_ok=True)
                    (steps_dir / ('%s.step' % stem)).write_bytes(payload)
                    extracted[stem] = name
        except (zipfile.BadZipFile, KeyError, OSError) as error:
            diagnostics.append({'source': name, 'reason': 'not an extractable SolidCraft archive: %s' % error})
    return extracted, diagnostics


def bring_up_urdf(project, assembly, *, preflight=None, exporter=None, timeout=120):
    """Export the saved CAD assembly to URDF text at runtime and check it.

    Returns LazyUrdf with .text (the URDF), .report (capture/export/check
    record incl. source hashes and freshness) and .sha256. The export bundle
    directory lives on the returned object until it is garbage collected.
    preflight and exporter override the studio-urdf-preflight and SolidCraft
    CLI executables; they must accept the same CLI shapes.
    """
    project = Path(project).resolve(strict=True)
    root_assembly = Path(assembly)
    if root_assembly.is_absolute() or '..' in root_assembly.parts or '.\\' in assembly:
        raise ValueError('assembly must be a project-relative path')
    preflight = Path(preflight) if preflight else _resolve_executable('studio-urdf-preflight', 'DATUM_URDF_PREFLIGHT', 'preflight')
    exporter = Path(exporter) if exporter else _resolve_executable('solidcraft-cli', 'DATUM_URDF_EXPORTER', 'exporter')

    def scan(root):
        result = subprocess.run([str(preflight), str(root), assembly], capture_output=True, text=True, timeout=30)
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ValueError('source preflight produced no JSON') from error
        if data.get('source_checks') != 'pass':
            raise ValueError(data.get('evidence', 'Source preflight failed'))
        return data

    holder = tempfile.TemporaryDirectory(prefix='datum-lazy-urdf-')
    try:
        scratch = Path(holder.name) / 'project'
        scratch.mkdir()
        before = scan(project)
        for name in before.get('sources', []):
            relative = Path(name)
            if relative.is_absolute() or any(part in ('', '.', '..') for part in relative.parts):
                raise ValueError('invalid dependency path')
            source = (project / relative).resolve(strict=True)
            if not source.is_relative_to(project) or not source.is_file():
                raise ValueError('dependency escapes project')
            destination = scratch / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        captured = scan(scratch)
        if before.get('sources') != captured.get('sources') or before.get('sources') != scan(project).get('sources'):
            raise ValueError('Source changed during capture')
        bundle = Path(holder.name) / 'bundle'
        bundle.mkdir()
        urdf = bundle / 'robot.urdf'
        assembly_step = bundle / 'assembly.step'
        deadline = time.monotonic() + timeout
        returncode, output = _run_exporter([str(exporter), 'run', '--quiet', '--in', str(scratch / assembly), '--out', str(urdf), '--out', str(assembly_step)], deadline)
        if (returncode or not urdf.is_file() or not assembly_step.is_file()):
            # Exporters without the extra STEP output must still give a fresh
            # URDF with its meshes; retry and report the STEP as unavailable.
            returncode, output = _run_exporter([str(exporter), 'run', '--quiet', '--in', str(scratch / assembly), '--out', str(urdf)], deadline)
            if returncode or not urdf.is_file():
                raise RuntimeError('URDF export failed (%s): %s' % (returncode, output))
            assembly_step.unlink(missing_ok=True)
            geometry_note = 'exporter rejected the whole-assembly STEP output: %s' % output.strip()[-200:]
        else:
            geometry_note = ''
        checks = check_urdf(urdf, bundle, synthetic_base='base_link')
        if checks['status'] != 'pass':
            raise ValueError('URDF structural checks failed: %s' % '; '.join(checks['findings']))
        mesh_links = _mesh_bundle_mapping(urdf)
        mesh_sha256 = {}
        for name in mesh_links:
            path = (urdf.parent / name).resolve()
            if path.is_file() and path.is_relative_to(bundle):
                mesh_sha256[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        blobs, blob_diagnostics = _extract_part_steps(scratch, list(before.get('sources') or []), bundle / 'steps')
        try:
            fresh = scan(project).get('sources') == before.get('sources')
        except Exception:
            fresh = False
        version = subprocess.run([str(exporter), '--version'], capture_output=True, text=True, timeout=10)
        geometry = {
            'meshes': mesh_sha256,
            'mesh_links': mesh_links,
            'assembly_step': {'path': assembly_step.relative_to(bundle).as_posix(), 'sha256': hashlib.sha256(assembly_step.read_bytes()).hexdigest()} if assembly_step and assembly_step.is_file() else None,
            'part_steps': {'blobs': {stem: source for stem, source in blobs.items()}, 'diagnostics': blob_diagnostics},
            'note': 'Meshes and the whole-assembly STEP are exported from the captured sources at evaluation time and live in this bundle, so a URDF cannot reference geometry the CAD no longer produces. Content-addressed per-part STEP blobs were extracted with hash-verified names; blob-to-URDF-link correspondence is not established.',
        }
        if geometry_note:
            geometry['unavailable_reason'] = geometry_note
        report = {
            'schema': _REPORT_SCHEMA,
            'execution': 'complete',
            'capture': {'mode': 'lazy saved-files', 'assembly': assembly, 'hash_algorithm': 'blake3'},
            'exporter': {'version': version.stdout.strip() if version.returncode == 0 else None},
            'outputs_sha256': {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob('*') if path.is_file()},
            'geometry': geometry,
            'source_preflight': before,
            'structural_checks': checks,
            'assembly_fidelity': before.get('source_fidelity'),
            'freshness': 'current' if fresh else 'stale',
            'physics_readiness': 'unknown',
            'note': 'Exports from saved CAD at evaluation time. Physics and source-to-URDF equivalence are not verified.',
        }
        (bundle / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        return LazyUrdf(urdf.read_text(), report, holder, urdf)
    except Exception:
        holder.cleanup()
        raise


class LazyUrdf:
    """Runtime URDF text plus its report; the temp bundle is released on GC."""

    def __init__(self, text, report, holder, urdf_path):
        self._holder = holder
        self.text = text
        self.report = report
        self.sha256 = hashlib.sha256(text.encode()).hexdigest()
        self.urdf_path = urdf_path

    def write(self, path):
        """Write the URDF text to a file of your choosing."""
        Path(path).write_text(self.text)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Print a lazily exported URDF to stdout')
    parser.add_argument('--project', required=True)
    parser.add_argument('--assembly', required=True)
    parser.add_argument('--preflight')
    parser.add_argument('--exporter')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--evidence', help='optional path for the machine-readable report')
    args = parser.parse_args()
    try:
        result = bring_up_urdf(args.project, args.assembly, preflight=args.preflight, exporter=args.exporter, timeout=args.timeout)
    except Exception as error:
        print('%s' % error, file=__import__('sys').stderr)
        return 1
    __import__('sys').stderr.write(json.dumps(result.report) + '\n')
    if args.evidence:
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(json.dumps(result.report, indent=2) + '\n')
    print(result.text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
