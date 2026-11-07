"""Exercise lazy URDF bring-up with stub preflight/exporter executables."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'parameter_studio'))
from datum_parameter_studio.lazy_urdf import bring_up_urdf

# Stub preflight: scans the passed project directory for the assembly and
# reports a passing source check with the assembly as the single source.
PREFLIGHT = r'''#!/usr/bin/env python3
import json, os, sys
root, assembly = sys.argv[1], sys.argv[2]
exists = os.path.isfile(os.path.join(root, assembly))
print(json.dumps({
    'source_checks': 'pass' if exists else 'fail',
    'sources': [assembly] if exists else [],
    'source_fidelity': {'status': 'structural-only', 'coupling': False},
    'evidence': 'Source preflight failed (stub)',
}))
'''

STL = '''solid arm
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 1 0
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 0 0 0
  vertex 0 0 1
  vertex 0 1 0
 endloop
endfacet
endsolid arm
'''

STEP_CONTENT = 'ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((\'stub\'));;\nEND-ISO-10303-21;\n'

# Stub exporter: accepts the worker CLI shape (possibly repeated --out) and
# writes a minimal structurally valid URDF referencing one mesh, plus any
# STEP output it was given.
MINIMAL_URDF = '''<robot name="lazy">
  <link name="base_link"/>
  <link name="arm">
    <inertial>
      <mass value="1"/>
      <inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/>
    </inertial>
    <visual>
      <geometry><mesh filename="robot-arm.stl"/></geometry>
    </visual>
  </link>
  <joint name="base_to_arm" type="fixed">
    <parent link="base_link"/>
    <child link="arm"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/>
  </joint>
</robot>
'''
EXPORTER = r'''#!/usr/bin/env python3
import pathlib, sys
args = sys.argv
if '--version' in args:
    print('stub-exporter 1')
    sys.exit(0)
outputs = []
index = 0
while index < len(args):
    if args[index] == '--out':
        outputs.append(pathlib.Path(args[index + 1]))
        index += 1
    index += 1
for out in outputs:
    if out.suffix == '.step':
        out.write_text(%r)
    else:
        out.write_text(%r)
        out.with_name('robot-arm.stl').write_text(%r)
''' % (STEP_CONTENT, MINIMAL_URDF, STL)

# Stub variant that refuses the extra STEP output (exercises the degrade path).
EXPORTER_URDF_ONLY = r'''#!/usr/bin/env python3
import pathlib, sys
args = sys.argv
if '--version' in args:
    print('stub-exporter 1')
    sys.exit(0)
outputs = []
index = 0
while index < len(args):
    if args[index] == '--out':
        out = pathlib.Path(args[index + 1])
        if out.suffix != '.step':
            out.write_text(%r)
            out.with_name('robot-arm.stl').write_text(%r)
        outputs.append(out)
        index += 1
    index += 1
print('unexpected extra output argument')
''' % (MINIMAL_URDF, STL)
def write_stub(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | 0o111)

def write_source_with_blobs(path):
    """A real ZIP-shaped source with content-addressed STEP blobs.

    One blob is named after its own SHA-256 (kept); one is named after a
    different content (skipped with a diagnostic).
    """
    good = hashlib.sha256(STEP_CONTENT.encode()).hexdigest()
    decoy_content = 'ISO-10303-21;\nnot the named content\n'
    decoy_name = hashlib.sha256(b'other').hexdigest()
    entries = {
        'container.json': '{}',
        'document.json': '{}',
        'blobs/%s.step' % good: STEP_CONTENT,
        'blobs/%s.step' % decoy_name: decoy_content,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return good, decoy_name

class LazyUrdfTest(unittest.TestCase):
    def make_project(self, root, assembly='cad/robot.solidcraft', blobs=False):
        target = root / assembly
        if blobs:
            good, decoy = write_source_with_blobs(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'stub-solidcraft-file')
            good = decoy = None
        return good, decoy

    def test_bring_up_exports_checks_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            exporter = root / 'exporter'
            write_stub(preflight, PREFLIGHT)
            write_stub(exporter, EXPORTER)
            self.make_project(root)
            result = bring_up_urdf(root, 'cad/robot.solidcraft', preflight=preflight, exporter=exporter)
            self.assertEqual('<robot name="lazy">', result.text.splitlines()[0])
            self.assertEqual(result.sha256, hashlib.sha256(result.text.encode()).hexdigest())
            report = result.report
            self.assertEqual(report['execution'], 'complete')
            self.assertEqual(report['structural_checks']['status'], 'pass')
            self.assertEqual(report['freshness'], 'current')
            self.assertEqual(report['capture']['mode'], 'lazy saved-files')
            self.assertEqual(report['schema'], 'datum.lazy-urdf-report/2')
            self.assertEqual(report['outputs_sha256']['robot.urdf'], hashlib.sha256(result.text.encode()).hexdigest())
            # Geometry lives in the bundle and is reported with hashes.
            geometry = report['geometry']
            self.assertEqual(list(geometry['meshes']), ['robot-arm.stl'])
            self.assertEqual(geometry['mesh_links']['robot-arm.stl'], ['arm'])
            self.assertEqual(geometry['meshes']['robot-arm.stl'], hashlib.sha256(STL.encode()).hexdigest())
            self.assertEqual(geometry['assembly_step']['path'], 'assembly.step')
            self.assertEqual(geometry['assembly_step']['sha256'], hashlib.sha256(STEP_CONTENT.encode()).hexdigest())
            self.assertIn('hash-verified', geometry['note'])
            self.assertIn('blob-to-URDF-link correspondence is not established', geometry['note'])

    def test_part_step_blobs_are_extracted_with_verified_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            exporter = root / 'exporter'
            write_stub(preflight, PREFLIGHT)
            write_stub(exporter, EXPORTER)
            good, decoy = self.make_project(root, blobs=True)
            result = bring_up_urdf(root, 'cad/robot.solidcraft', preflight=preflight, exporter=exporter)
            geometry = result.report['geometry']
            self.assertEqual(geometry['part_steps']['blobs'], {good: 'cad/robot.solidcraft'})
            diagnostics = geometry['part_steps']['diagnostics']
            self.assertTrue(any('%s' % decoy in entry['reason'] for entry in diagnostics))
            self.assertEqual(set(result.report['outputs_sha256']), {'robot.urdf', 'robot-arm.stl', 'assembly.step', 'steps/%s.step' % good})

    def test_exporter_without_step_output_degrades_to_urdf_and_meshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            exporter = root / 'exporter'
            write_stub(preflight, PREFLIGHT)
            write_stub(exporter, EXPORTER_URDF_ONLY)
            self.make_project(root, blobs=True)
            result = bring_up_urdf(root, 'cad/robot.solidcraft', preflight=preflight, exporter=exporter)
            report = result.report
            self.assertEqual(report['structural_checks']['status'], 'pass')
            geometry = report['geometry']
            self.assertIsNone(geometry['assembly_step'])
            self.assertIn('unavailable_reason', geometry)
            self.assertEqual(list(geometry['meshes']), ['robot-arm.stl'])
            self.assertIn(good := hashlib.sha256(STEP_CONTENT.encode()).hexdigest(), geometry['part_steps']['blobs'])

    def test_missing_assembly_fails_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            write_stub(preflight, PREFLIGHT)
            with self.assertRaisesRegex(ValueError, 'Source preflight failed'):
                bring_up_urdf(root, 'cad/absent.solidcraft', preflight=preflight, exporter=root / 'exporter')

    def test_cli_prints_urdf_and_writes_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            exporter = root / 'exporter'
            write_stub(preflight, PREFLIGHT)
            write_stub(exporter, EXPORTER)
            self.make_project(root)
            evidence = root / 'evidence/urdf-report.json'
            result = subprocess.run(
                [sys.executable, '-m', 'datum_parameter_studio.lazy_urdf',
                 '--project', str(root), '--assembly', 'cad/robot.solidcraft',
                 '--preflight', str(preflight), '--exporter', str(exporter), '--evidence', str(evidence)],
                capture_output=True, text=True,
                env={'PYTHONPATH': str(ROOT / 'parameter_studio'), 'PATH': '/usr/bin:/bin'},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], '<robot name="lazy">')
            report = json.loads(result.stderr.splitlines()[-1])
            self.assertEqual(report['schema'], 'datum.lazy-urdf-report/2')
            saved = json.loads(evidence.read_text())
            self.assertEqual(saved['outputs_sha256']['robot.urdf'], report['outputs_sha256']['robot.urdf'])
            self.assertEqual(saved['geometry']['meshes'], report['geometry']['meshes'])

if __name__ == '__main__':
    unittest.main()
