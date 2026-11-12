import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from datum_parameter_studio.simulations.worker import Engine, Session, atomic, mark_unfinished_commands

URDF = '''<robot name="test"><link name="base"><inertial><mass value="1"/><inertia ixx=".1" iyy=".1" izz=".1" ixy="0" ixz="0" iyz="0"/></inertial><visual><geometry><box size=".1 .1 .1"/></geometry></visual><collision><geometry><box size=".1 .1 .1"/></geometry></collision></link><link name="arm"><inertial><mass value="1"/><inertia ixx=".1" iyy=".1" izz=".1" ixy="0" ixz="0" iyz="0"/></inertial></link><joint name="slide" type="prismatic"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/><limit lower="-10" upper="10" effort="100" velocity="100"/></joint></robot>'''

class WorkerTests(unittest.TestCase):
    def test_supervisor_reconciles_terminal_session_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); session = root / ('a' * 32)
            (session / 'commands').mkdir(parents=True); (session / 'acks').mkdir()
            atomic(session / 'status.json', {'state':'stopped'})
            atomic(session / 'commands' / 'b.json', {'id':'b','command':'step'})
            atomic(session / 'acks' / 'b.json', {'id':'b','status':'processing'})
            process = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.simulations.worker', '--serve', '--project', tmp, '--spool', tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ.copy())
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    ack = json.loads((session / 'acks' / 'b.json').read_text())
                    if ack['status'] == 'unknown': break
                    time.sleep(.05)
                self.assertEqual(ack['status'], 'unknown')
            finally:
                process.terminate(); process.wait(timeout=5)

    def test_interrupted_command_outcome_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'commands').mkdir(); (root / 'acks').mkdir()
            atomic(root / 'commands' / 'a.json', {'id':'a','command':'step'})
            atomic(root / 'acks' / 'a.json', {'id':'a','status':'processing'})
            mark_unfinished_commands(root)
            self.assertEqual(json.loads((root / 'acks' / 'a.json').read_text())['status'], 'unknown')

    @unittest.skipUnless(importlib.util.find_spec('pybullet'), 'PyBullet optional')
    def test_pybullet_base_pose_is_link_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'robot.urdf'
            path.write_text(URDF.replace('<mass value="1"/>', '<origin xyz="0.1 0.2 0.3"/><mass value="1"/>', 1))
            engine = Engine('pybullet', path)
            try:
                base = engine.snapshot()['links'][0]
                for value in base['position']: self.assertAlmostEqual(value, 0, places=6)
            finally: engine.close()

    def test_failure_is_reported_when_snapshot_raises(self):
        class Broken:
            def snapshot(self): raise RuntimeError('engine lost')
            def close(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(tmp, tmp)
            def start():
                session.engine = Broken()
                raise RuntimeError('engine lost')
            with patch.object(session, 'start', start): session.run()
            self.assertEqual(json.loads((Path(tmp) / 'status.json').read_text())['state'], 'failed')

    def test_engines(self):
        for backend in ('mujoco', 'pybullet'):
            if importlib.util.find_spec(backend) is None:
                continue
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bundle = root / 'source'; bundle.mkdir()
                urdf = bundle / 'robot.urdf'; urdf.write_text(URDF)
                class Source:
                    def close(self): self.closed = True
                source = Source(); source.bundle = bundle; source.urdf_path = urdf; source.result = Source(); source.result.report = {}
                directory = root / 'session'; directory.mkdir()
                atomic(directory / 'request.json', {'backend': backend, 'assembly': 'synthetic'})
                worker = Session(root, directory)
                with patch('datum_parameter_studio.simulations.worker.simulation_input', return_value=source) as load:
                    try:
                        worker.start()
                        load.assert_called_once_with(root, 'synthetic')
                        self.assertEqual(worker.state, 'paused')
                        worker.tick()
                        self.assertEqual(worker.engine.snapshot()['time'], 0)
                        for i, command in enumerate(('record_start', 'step', 'reset', 'resume', 'pause', 'record_stop', 'stop')):
                            atomic(directory / 'commands' / f'{i}.json', {'id': str(i), 'command': command})
                            worker.tick()
                            if command == 'step': self.assertGreater(worker.engine.snapshot()['time'], 0)
                            if command == 'reset': self.assertEqual(worker.epoch, 1)
                        self.assertEqual(worker.state, 'stopped')
                        self.assertTrue(list((directory / 'recordings').glob('*.jsonl')))
                        self.assertTrue(json.loads((directory / 'state.json').read_text())['links'])
                    finally: worker.close()
                self.assertTrue(source.closed)

    def test_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic(Path(tmp) / 'request.json', {'backend': 'gazebo', 'assembly': 'x'})
            Session(tmp, tmp).run()
            self.assertEqual(json.loads((Path(tmp) / 'status.json').read_text())['state'], 'failed')
