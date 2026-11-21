import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from datum_parameter_studio.cli import main

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('solidcraft-cli'), 'solidcraft-cli is required for native CAD activation')
class MaterializeConfiguration(unittest.TestCase):
    def test_configuration_is_materialized_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            shutil.copytree(ROOT / 'examples/cad_history', project)
            source = project / 'assembly.solidcraft'
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = project / 'parallel.solidcraft'
            argv = ['dparam-std', 'materialize', '--project', str(project), '--assembly', 'assembly.solidcraft',
                    '--configuration', 'Parallel gripper', '--output', str(output)]
            with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                main()
            with zipfile.ZipFile(output) as archive:
                document = json.loads(archive.read('document.json'))
            self.assertEqual(document['configs']['active'], 'Parallel gripper')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_history_point_is_materialized_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            shutil.copytree(ROOT / 'examples/cad_history', project)
            source = project / 'assembly.solidcraft'
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = project / 'history.solidcraft'
            argv = ['dparam-std', 'materialize', '--project', str(project), '--assembly', 'assembly.solidcraft',
                    '--feature-id', '3', '--output', str(output)]
            with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                main()
            self.assertTrue(output.is_file())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
