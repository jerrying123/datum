import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from datum_parameter_studio.configurations import discover, activate
from datum_parameter_studio.runtime_urdf import _run_exporter, bring_up_urdf

ROOT = Path(__file__).resolve().parents[2]

class ConfigurationTests(unittest.TestCase):
    def test_discovery_and_stale_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'part.solidcraft'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('document.json', json.dumps({'features': [{'id': 1, 'name': 'First'}, {'id': 2, 'name': 'Second'}], 'configs': {'rows': [{'name': 'Wide'}]}}))
            data = discover(path)
            self.assertEqual([x['name'] for x in data['history']], ['First', 'Second'])
            self.assertEqual(data['configurations'], ['Wide'])
            with self.assertRaisesRegex(ValueError, 'stale'):
                activate(path, {'kind':'history','value':1,'sha256':'0'*64}, 'unused', _run_exporter, 1)

    @unittest.skipUnless(shutil.which('solidcraft-cli') and (ROOT/'rust/target/debug/studio-urdf-preflight').is_file(), 'native CAD tools optional')
    def test_real_history_and_native_configuration_export_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for file in (ROOT/'examples/cad_history').glob('*.solidcraft'):
                shutil.copyfile(file, project/file.name)
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.glob('*.solidcraft')}
            data = discover(project/'assembly.solidcraft')
            self.assertIn('Mount only', data['configurations'])
            exported = []
            for state in [None, {'kind':'history','value':3,'sha256':data['sha256']}, {'kind':'configuration','value':'Mount only','sha256':data['sha256']}]:
                with bring_up_urdf(project, 'assembly.solidcraft', preflight=ROOT/'rust/target/debug/studio-urdf-preflight', cad_state=state) as result:
                    self.assertEqual(result.report['freshness'], 'current')
                    self.assertEqual(result.report['capture']['cad_state'], state)
                    exported.append(result.text)
            self.assertNotEqual(exported[0], exported[1])
            self.assertNotEqual(exported[0], exported[2])
            self.assertEqual(before, {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in project.glob('*.solidcraft')})

    @unittest.skipUnless(shutil.which('solidcraft-cli') and (ROOT/'rust/target/debug/studio-urdf-preflight').is_file(), 'native CAD tools optional')
    def test_unsuppressing_uncaptured_linked_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for file in (ROOT/'examples/cad_history').glob('*.solidcraft'):
                shutil.copyfile(file, project/file.name)
            source = project/'assembly.solidcraft'
            script = project/'script.json'
            script.write_text(json.dumps({'commands':[{'command':'config.activate','params':{'row':'Mount only'}}]}))
            suppressed = project/'suppressed.solidcraft'
            subprocess.run(['solidcraft-cli','run',str(script),'--in',str(source),'--save',str(suppressed),'--quiet'], check=True)
            suppressed.replace(source)
            data = discover(source)
            original = source.read_bytes()
            with self.assertRaisesRegex(ValueError, 'activates an import absent'):
                bring_up_urdf(project, 'assembly.solidcraft', preflight=ROOT/'rust/target/debug/studio-urdf-preflight',
                              cad_state={'kind':'configuration','value':'Default','sha256':data['sha256']})
            self.assertEqual(source.read_bytes(), original)
