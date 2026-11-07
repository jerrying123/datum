"""Lazy URDF bring-up: export from saved CAD at runtime, never from a stale file.

The URDF exists in most stacks only because simulation systems cannot load the
native CAD. This module brings it up on demand: it captures the exact saved
sources with the same preflight the Studio spool uses, exports with the
SolidCraft CLI into an isolated scratch directory, structurally checks the
output, and returns the URDF text plus a machine-readable report. No checked-in
URDF file is required or updated, so a node can never bring up a URDF that has
drifted from its CAD: the output is generated from the live sources at
evaluation time and stamped with their hashes.

Note document shape: exported URDF text comes from the proprietary exporter in
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

from datum_parameter_studio.urdf_check import check_urdf

_REPORT_SCHEMA = 'datum.lazy-urdf-report/1'


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
        returncode, output = _run_exporter([str(exporter), 'run', '--quiet', '--in', str(scratch / assembly), '--out', str(urdf)], time.monotonic() + timeout)
        if returncode or not urdf.is_file():
            raise RuntimeError('URDF export failed (%s): %s' % (returncode, output))
        checks = check_urdf(urdf, bundle, synthetic_base='base_link')
        if checks['status'] != 'pass':
            raise ValueError('URDF structural checks failed: %s' % '; '.join(checks['findings']))
        try:
            fresh = scan(project).get('sources') == before.get('sources')
        except Exception:
            fresh = False
        version = subprocess.run([str(exporter), '--version'], capture_output=True, text=True, timeout=10)
        report = {
            'schema': _REPORT_SCHEMA,
            'execution': 'complete',
            'capture': {'mode': 'lazy saved-files', 'assembly': assembly, 'hash_algorithm': 'blake3'},
            'exporter': {'version': version.stdout.strip() if version.returncode == 0 else None},
            'outputs_sha256': {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in bundle.rglob('*') if path.is_file()},
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
