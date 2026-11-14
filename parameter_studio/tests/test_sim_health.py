"""The supervisor health endpoint authenticates and reports actual process death."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class SimulationHealthTests(unittest.TestCase):
    def test_simulation_health(self):
        self.check_health('datum_parameter_studio.simulations.worker', [])

    def test_urdf_health(self):
        self.check_health('datum_parameter_studio.urdf_worker', ['--preflight', '/bin/false', '--exporter', '/bin/false'])

    def check_health(self, module, extra):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worker = subprocess.Popen([sys.executable, '-m', module, '--serve', '--project', temp, '--spool', temp, *extra], env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                endpoint = []
                while time.monotonic() < deadline:
                    endpoint = list(root.glob('worker-endpoint-*.json'))
                    if endpoint:
                        try:
                            data = json.loads(endpoint[0].read_text())
                            break
                        except (ValueError, OSError): pass
                    time.sleep(.05)
                else: self.fail('health endpoint was not published')
                self.assertEqual(endpoint[0].stat().st_mode & 0o777, 0o600)
                url = 'http://127.0.0.1:%d/health' % data['port']
                with self.assertRaises(HTTPError) as denied:
                    urlopen(url, timeout=2)
                self.assertEqual(denied.exception.code, 404)
                denied.exception.close()
                with urlopen(Request(url, headers={'Authorization':'Bearer '+data['token']}), timeout=2) as response:
                    self.assertTrue(json.load(response)['available'])
                worker.terminate(); worker.wait(timeout=5)
                with self.assertRaises((HTTPError, URLError, OSError)):
                    urlopen(Request(url, headers={'Authorization':'Bearer '+data['token']}), timeout=2)
                self.assertFalse(endpoint[0].exists())
            finally:
                if worker.poll() is None:
                    worker.kill(); worker.wait(timeout=5)
