import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import shutil

from datum_parameter_studio.fidelity_check import check_fidelity
from datum_parameter_studio.runtime_urdf import bring_up_urdf
from datum_parameter_studio.urdf_worker import run as run_worker


class FidelityTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('solidcraft-cli') and shutil.which('studio-urdf-preflight'), 'native tools optional')
    def test_real_export_joint_comparison(self):
        project = Path(__file__).resolve().parents[2] / 'examples/pybullet_sim/cad'
        with bring_up_urdf(project, 'assembly.solidcraft') as result:
            report = result.report['cad_urdf_fidelity_checks']
            self.assertEqual(report['status'], 'unknown')
            self.assertEqual(report['checks'][0]['status'], 'pass')
            self.assertEqual(report['checks'][0]['source_name'], 'hinge')

    @unittest.skipUnless(shutil.which('solidcraft-cli') and shutil.which('studio-urdf-preflight'), 'native tools optional')
    def test_worker_reports_real_export_diagnostics(self):
        fixture = Path(__file__).resolve().parents[2] / 'examples/pybullet_sim/cad'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, job = root / 'project', root / 'job'
            shutil.copytree(fixture, project)
            job.mkdir()
            (job / 'request.json').write_text(json.dumps({'assembly': 'assembly.solidcraft'}))
            report = run_worker(project, job, shutil.which('studio-urdf-preflight'), shutil.which('solidcraft-cli'))
            self.assertIsNotNone(report)
            self.assertEqual(report['cad_urdf_fidelity_checks']['checks'][0]['status'], 'pass')
            self.assertIn('mass_inertia', report['physics_checks']['checks'])
            self.assertEqual(json.loads((job / 'status.json').read_text())['state'], 'succeeded')

    def test_joint_type_limits_and_ambiguous_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.solidcraft'
            output = root / 'robot.urdf'
            doc = {'assembly': {'joints': [{'id': 2, 'name': 'hinge', 'kind': 'revolute', 'limits': [[-1, 1]]}]}}
            with zipfile.ZipFile(source, 'w') as z:
                z.writestr('document.json', json.dumps(doc))
            def evaluate(kind, lower):
                output.write_text(f'<robot><joint name="hinge" type="{kind}"><limit lower="{lower}" upper="1"/></joint></robot>')
                return check_fidelity(source, output)
            good = evaluate('revolute', -1)
            self.assertEqual(good['status'], 'unknown')
            self.assertEqual(good['checks'][0]['status'], 'pass')
            self.assertEqual(evaluate('prismatic', -1)['status'], 'fail')
            self.assertEqual(evaluate('revolute', -2)['status'], 'fail')
            output.write_text('<robot/>')
            self.assertEqual(check_fidelity(source, output)['checks'][0]['status'], 'unknown')
