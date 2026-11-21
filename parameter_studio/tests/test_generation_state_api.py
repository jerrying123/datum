import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

STUDIO = Path(__file__).resolve().parents[1] / 'datum_parameter_studio'

@unittest.skipUnless(shutil.which('node') and (STUDIO / 'node_modules/express').exists(), 'Node Studio dependencies required')
class GenerationStateAPI(unittest.TestCase):
    def test_selected_state_is_rejected_before_generation(self):
        studio = Path(__file__).resolve().parents[1] / 'datum_parameter_studio'
        with tempfile.TemporaryDirectory() as root, socket.socket() as sock:
            assembly = Path(root) / 'assembly.solidcraft'
            fixture = Path(__file__).resolve().parents[2] / 'examples' / 'cad_history' / 'assembly.solidcraft'
            shutil.copyfile(fixture, assembly)
            digest = hashlib.sha256(assembly.read_bytes()).hexdigest()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            sock.close()
            env = dict(os.environ, DATUM_PROJECT_ROOT=root, DATUM_STUDIO_PORT=str(port))
            server = subprocess.Popen(['node', str(studio / 'server.js')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                url = f'http://127.0.0.1:{port}'
                deadline = time.monotonic() + 10
                while True:
                    if server.poll() is not None:
                        self.fail('Studio exited before becoming ready: ' + server.stderr.read())
                    try:
                        with urllib.request.urlopen(url + '/healthz', timeout=0.5):
                            pass
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self.fail('Studio did not become ready within 10 seconds')
                        time.sleep(0.05)
                for state in ({'kind': 'configuration', 'value': 'Parallel gripper', 'sha256': digest}, {'kind': 'history', 'value': 3, 'sha256': digest}):
                    req = urllib.request.Request(url + '/api/generate', data=json.dumps({'cad_state': state, 'assembly': 'assembly.solidcraft'}).encode(), headers={'Content-Type': 'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as result:
                        urllib.request.urlopen(req)
                    self.assertEqual(result.exception.code, 400)
                    self.assertEqual(json.load(result.exception)['code'], 'CAD_STATE_EXTRACTION_UNSUPPORTED')
                    result.exception.close()
                stale = {'kind': 'configuration', 'value': 'Parallel gripper', 'sha256': '0' * 64}
                req = urllib.request.Request(url + '/api/generate', data=json.dumps({'cad_state': stale, 'assembly': 'assembly.solidcraft'}).encode(), headers={'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen(req)
                self.assertEqual(result.exception.code, 409)
                result.exception.close()
                req = urllib.request.Request(url + '/api/generate', data=json.dumps({'cad_state': {'kind': 'configuration'}}).encode(), headers={'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen(req)
                self.assertEqual(result.exception.code, 400)
                result.exception.close()
            finally:
                server.terminate()
                server.wait(timeout=5)
                server.stderr.close()


if __name__ == '__main__':
    unittest.main()
