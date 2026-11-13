import os
from pathlib import Path
import subprocess
import tempfile
import time
import json
import sys
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

    def test_down_waits_for_owned_worker_before_removing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); spool = root / '.dparams-studio' / 'sim-jobs'
            spool.mkdir(parents=True)
            worker = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.simulations.worker', '--serve', '--project', str(root), '--spool', str(spool)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                (spool / 'worker.pid').write_text(json.dumps({'pid': worker.pid, 'start': Path(f'/proc/{worker.pid}/stat').read_text().split()[21]}))
                deadline = time.monotonic() + 5
                while not list(spool.glob('worker-endpoint-*.json')) and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(list(spool.glob('worker-endpoint-*.json')))
                with patch('sys.argv', ['dparam-std', 'down', '--project', str(root)]), \
                     patch('datum_parameter_studio.cli.shutil.which', return_value='/usr/bin/docker'), \
                     patch('datum_parameter_studio.cli.subprocess.run'):
                    cli.main()
                worker.wait(timeout=1)
                self.assertFalse((spool / 'worker.pid').exists())
            finally:
                if worker.poll() is None: worker.kill(); worker.wait(timeout=5)

    def test_up_detaches_compose_and_keeps_supervisor_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'rust').mkdir()
            (root / 'rust/Cargo.toml').write_text('')
            (root / 'parameter_studio/datum_parameter_studio').mkdir(parents=True)
            (root / 'parameter_studio/datum_parameter_studio/Dockerfile').write_text('')
            process = Mock(pid=os.getpid())
            with patch('sys.argv', ['dparam-std', 'up', '--project', str(root), '--source-repo', str(root)]), \
                 patch('datum_parameter_studio.cli.shutil.which', side_effect=lambda name: '/usr/bin/docker' if name == 'docker' else None), \
                 patch('datum_parameter_studio.cli.subprocess.Popen', return_value=process), \
                 patch('datum_parameter_studio.cli.subprocess.run') as run:
                cli.main()
            self.assertIn('--detach', run.call_args.args[0])
            process.terminate.assert_not_called()
            self.assertTrue((root / '.dparams-studio/sim-jobs/worker.pid').exists())
