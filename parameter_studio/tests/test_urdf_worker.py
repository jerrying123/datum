import json
import shutil
import threading
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datum_parameter_studio.urdf_worker import run


class WorkerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('solidcraft-cli') and (Path(__file__).resolve().parents[2]/'rust/target/debug/studio-urdf-preflight').is_file(), 'native CAD tools optional')
    def test_preview_reflects_gripper_configuration(self):
        import hashlib
        import zipfile
        from datum_parameter_studio.configurations import discover
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source in (repo/'examples/cad_history').glob('*.solidcraft'):
                shutil.copyfile(source, root/source.name)
            original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.solidcraft')}
            digest = discover(root/'assembly.solidcraft')['sha256']
            outputs = []
            for index, name in enumerate(('Parallel gripper', 'Rotary gripper', 'Mount only')):
                job = root / ('job' + str(index)); job.mkdir()
                (job/'request.json').write_text(json.dumps({'assembly':'assembly.solidcraft','preview':True,
                    'cad_state':{'kind':'configuration','value':name,'sha256':digest}}))
                run(root, job, repo/'rust/target/debug/studio-urdf-preflight', shutil.which('solidcraft-cli'))
                status = json.loads((job/'status.json').read_text())
                self.assertEqual(status['state'], 'succeeded', status)
                with zipfile.ZipFile(job/'model.3mf') as archive:
                    outputs.append(archive.read('3D/3dmodel.model'))
            self.assertEqual(len({hashlib.sha256(x).hexdigest() for x in outputs}), 3)
            self.assertEqual(original, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.solidcraft')})

    def test_cancel_and_failed_preflight(self):
        for cancel in (True, False):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                job = root / 'job'; job.mkdir()
                (job / 'request.json').write_text(json.dumps({'assembly':'arm.solidcraft'}))
                if cancel: (job / 'cancel').touch()
                with patch('datum_parameter_studio.urdf_worker.subprocess.run') as scan:
                    scan.return_value.stdout = json.dumps({'source_checks':'pass' if cancel else 'fail', 'sources':{}})
                    self.assertIsNone(run(root, job, '/fake/preflight', '/fake/exporter'))
                self.assertEqual(json.loads((job / 'status.json').read_text())['state'], 'cancelled' if cancel else 'failed')
                self.assertFalse((job / 'bundle.zip').exists())
                self.assertFalse((job / 'bundle.zip.tmp').exists())

    def test_capture_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); job = root / 'job'; job.mkdir()
            (root / 'arm.solidcraft').write_bytes(b'fake')
            (job / 'request.json').write_text('{"assembly":"arm.solidcraft"}')
            with patch('datum_parameter_studio.urdf_worker.subprocess.run') as scan:
                from types import SimpleNamespace
                scan.side_effect = [SimpleNamespace(stdout=json.dumps({'source_checks':'pass','sources':{'arm.solidcraft':digest}})) for digest in ('a','b')]
                run(root, job, '/fake/preflight', '/fake/exporter')
            self.assertIn('changed', json.loads((job / 'status.json').read_text())['error'])
            self.assertEqual((root / 'arm.solidcraft').read_bytes(), b'fake')

    @unittest.skipUnless(shutil.which('solidcraft-cli') and (Path(__file__).resolve().parents[2]/'rust/target/debug/studio-urdf-preflight').is_file(), 'native CAD tools optional')
    def test_cancel_during_state_activation(self):
        from datum_parameter_studio.configurations import discover
        root_repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); job = root / 'job'; job.mkdir()
            for source in (root_repo/'examples/cad_history').glob('*.solidcraft'):
                shutil.copyfile(source, root/source.name)
            data = discover(root/'assembly.solidcraft')
            (job/'request.json').write_text(json.dumps({'assembly':'assembly.solidcraft', 'cad_state':{'kind':'history','value':3,'sha256':data['sha256']}}))
            marker = root/'started'
            exporter = root/'slow-exporter'
            exporter.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexec sleep 30\n')
            exporter.chmod(0o755)
            thread = threading.Thread(target=run, args=(root,job,root_repo/'rust/target/debug/studio-urdf-preflight',exporter))
            thread.start()
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertTrue(marker.exists(), 'activation did not start')
            (job/'cancel').touch()
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'worker did not stop after cancellation')
            self.assertEqual(json.loads((job/'status.json').read_text())['state'], 'cancelled')
            self.assertFalse((job/'bundle.zip').exists())
