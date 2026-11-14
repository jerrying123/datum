import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class GenerationStateAPI(unittest.TestCase):
    def test_selected_state_is_rejected_before_generation(self):
        studio = Path(__file__).resolve().parents[1] / 'datum_parameter_studio'
        with tempfile.TemporaryDirectory() as root, socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            sock.close()
            env = dict(os.environ, DATUM_PROJECT_ROOT=root, DATUM_STUDIO_PORT=str(port))
            server = subprocess.Popen(['node', str(studio / 'server.js')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url + '/healthz', timeout=0.1).close()
                        break
                    except OSError:
                        time.sleep(0.05)
                for state in ({'kind': 'configuration', 'value': 'unknown', 'sha256': '0' * 64}, {'kind': 'history', 'value': 1, 'sha256': 'f' * 64}, {}):
                    req = urllib.request.Request(url + '/api/generate', data=json.dumps({'cad_state': state}).encode(), headers={'Content-Type': 'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as result:
                        urllib.request.urlopen(req)
                    self.assertEqual(result.exception.code, 400)
                    self.assertEqual(json.load(result.exception)['code'], 'CAD_STATE_EXTRACTION_UNSUPPORTED')
            finally:
                server.terminate()
                server.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
