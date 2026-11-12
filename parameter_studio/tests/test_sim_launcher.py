import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from datum_parameter_studio import cli


class LauncherTest(unittest.TestCase):
    def test_start_failure_stops_new_simulation_supervisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'rust').mkdir()
            (root/'rust/Cargo.toml').write_text('')
            (root/'parameter_studio/datum_parameter_studio').mkdir(parents=True)
            (root/'parameter_studio/datum_parameter_studio/Dockerfile').write_text('')
            process = Mock(pid=os.getpid())
            process.poll.return_value = None
            with patch('sys.argv', ['dparam-std', 'up', '--project', str(root), '--source-repo', str(root)]), \
                 patch('datum_parameter_studio.cli.shutil.which', side_effect=lambda name: '/usr/bin/'+name), \
                 patch('datum_parameter_studio.cli.subprocess.Popen', return_value=process), \
                 patch('datum_parameter_studio.cli.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'cargo')):
                with self.assertRaises(subprocess.CalledProcessError): cli.main()
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertFalse((root/'.dparams-studio/sim-jobs/worker.pid').exists())
