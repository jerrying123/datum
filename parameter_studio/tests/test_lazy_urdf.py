"""Exercise lazy URDF bring-up with stub preflight/exporter executables."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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

# Stub exporter: accepts the worker CLI shape (run --quiet --in X --out Y) and
# writes a minimal structurally valid URDF.
MINIMAL_URDF = '''<robot name="lazy">
  <link name="base_link"/>
  <link name="arm">
    <inertial>
      <mass value="1"/>
      <inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/>
    </inertial>
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
out = pathlib.Path(args[args.index('--out') + 1])
out.write_text(%r)
''' % MINIMAL_URDF

def write_stub(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | 0o111)

class LazyUrdfTest(unittest.TestCase):
    def make_project(self, root, assembly):
        target = root / assembly
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'stub-solidcraft-file')

    def test_bring_up_exports_checks_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / 'preflight'
            exporter = root / 'exporter'
            write_stub(preflight, PREFLIGHT)
            write_stub(exporter, EXPORTER)
            self.make_project(root, 'cad/robot.solidcraft')
            result = bring_up_urdf(root, 'cad/robot.solidcraft', preflight=preflight, exporter=exporter)
            self.assertEqual('<robot name="lazy">', result.text.splitlines()[0])
            self.assertEqual(result.sha256, hashlib.sha256(result.text.encode()).hexdigest())
            report = result.report
            self.assertEqual(report['execution'], 'complete')
            self.assertEqual(report['structural_checks']['status'], 'pass')
            self.assertEqual(report['freshness'], 'current')
            self.assertEqual(report['capture']['mode'], 'lazy saved-files')
            self.assertEqual(report['outputs_sha256']['robot.urdf'], hashlib.sha256(result.text.encode()).hexdigest())
            self.assertIn('not verified', report['note'])

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
            self.make_project(root, 'cad/robot.solidcraft')
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
            self.assertEqual(report['schema'], 'datum.lazy-urdf-report/1')
            saved = json.loads(evidence.read_text())
            self.assertEqual(saved['outputs_sha256']['robot.urdf'], report['outputs_sha256']['robot.urdf'])

if __name__ == '__main__':
    unittest.main()
