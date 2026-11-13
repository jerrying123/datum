"""Studio prefers immutable updates when a shared mount caches an old inode."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

STUDIO = Path(__file__).resolve().parents[1] / 'datum_parameter_studio'

@unittest.skipUnless(shutil.which('node') and (STUDIO / 'node_modules/express').exists(), 'Node Studio dependencies required')
class SnapshotApiTests(unittest.TestCase):
    def test_fresh_snapshot_and_final_ack_win_over_stale_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); sid = 'a' * 32; cid = 'b' * 32
            session = root / sid; (session / 'acks').mkdir(parents=True)
            def write(path, value): path.write_text(json.dumps(value))
            write(session / 'request.json', {'backend': 'mujoco', 'assembly': 'robot.solidcraft'})
            write(session / 'status.json', {'state': 'queued'})
            write(session / 'status-00000000000000000001.json', {'state': 'paused'})
            write(session / 'state.json', {'epoch': 0, 'time': 0})
            write(session / 'state-00000000000000000001.json', {'epoch': 1, 'time': 2})
            write(session / 'acks' / (cid + '.json'), {'id': cid, 'status': 'processing'})
            write(session / 'acks' / (cid + '.done.json'), {'id': cid, 'status': 'applied'})
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            env = os.environ.copy(); env.update(DATUM_PROJECT_ROOT=temp, DATUM_SIM_SPOOL=temp, DATUM_STUDIO_PORT=str(port))
            server = subprocess.Popen(['node', str(STUDIO / 'server.js')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f'http://127.0.0.1:{port}/api/simulation/sessions/{sid}'
            def get(path):
                with urlopen(base + path, timeout=2) as response: return json.load(response)
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        status = get(''); break
                    except (URLError, OSError):
                        if time.monotonic() > deadline: raise
                        time.sleep(.05)
                self.assertEqual(status['state'], 'paused')
                self.assertEqual(get('/state')['epoch'], 1)
                self.assertEqual(get('/commands/' + cid)['status'], 'applied')
            finally:
                server.terminate()
                try: server.wait(timeout=5)
                except subprocess.TimeoutExpired: server.kill(); server.wait()
