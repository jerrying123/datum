import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datum_parameter_studio.urdf_worker import run


class WorkerTests(unittest.TestCase):
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
