"""Pacing and state restoration for the interactive simulation timeline."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datum_parameter_studio.simulations.worker import Engine, Session

URDF = '''<robot name="playback"><link name="base"><inertial><mass value="1"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial></link><link name="arm"><inertial><mass value="1"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial></link><joint name="slide" type="prismatic"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/><limit lower="-10" upper="10" effort="100" velocity="100"/></joint></robot>'''

class PlaybackTests(unittest.TestCase):
    def test_scheduler_advances_against_elapsed_wall_time(self):
        class EngineFake:
            timestep = .01
            def __init__(self): self.steps = 0
            def step(self): self.steps += 1
            def snapshot(self): return {'time': self.steps * self.timestep, 'links': [], 'joints': []}
            def checkpoint(self): return self.steps
            def release_checkpoint(self, _state): pass
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'commands').mkdir(); (root / 'acks').mkdir()
            session = Session(root, root); session.engine = EngineFake(); session.state = 'running'
            session.last_tick = 100.0
            with patch('datum_parameter_studio.simulations.worker.time.monotonic', return_value=100.1): session.tick()
            self.assertIn(session.engine.steps, (9, 10))
            previous = session.engine.steps; session.speed = 2
            with patch('datum_parameter_studio.simulations.worker.time.monotonic', return_value=100.2): session.tick()
            self.assertIn(session.engine.steps - previous, (19, 20, 21))
            session.state = 'paused'; previous = session.engine.steps
            with patch('datum_parameter_studio.simulations.worker.time.monotonic', return_value=101): session.tick()
            self.assertEqual(session.engine.steps, previous)

    def check_engine(self, backend):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'robot.urdf'; path.write_text(URDF)
            engine = Engine(backend, path)
            session = Session(root, root); session.engine = engine; session.state = 'paused'
            try:
                session.capture_checkpoint()
                for _ in range(10):
                    engine.step(); session.capture_checkpoint()
                at_ten = engine.snapshot()
                engine.set_position_control('slide', .5, {'kp': 10, 'kd': 1, 'max_force': 5})
                checkpoint = engine.checkpoint()
                engine.set_position_control('slide', 1, {'kp': 1, 'kd': 0, 'max_force': 2})
                engine.restore_checkpoint(checkpoint)
                self.assertEqual(next(iter(engine.actuators.values())), (.5, 10, 1, 5))
                engine.release_checkpoint(checkpoint)
                engine.actuators.clear()
                for _ in range(5):
                    engine.step(); session.capture_checkpoint()
                generation = session.history_generation
                session.seek(10, generation)
                restored = engine.snapshot()
                self.assertAlmostEqual(restored['time'], at_ten['time'], places=8)
                self.assertAlmostEqual(restored['joints'][0]['position'], at_ten['joints'][0]['position'], places=7)
                self.assertEqual(session.epoch, 1)
                session.seek(15, generation)
                self.assertGreater(engine.snapshot()['time'], restored['time'])
                session.seek(10, generation)
                engine.step(); session.capture_checkpoint()
                self.assertEqual(len(session.history), 12)
                with self.assertRaisesRegex(ValueError, 'Timeline changed'): session.seek(11, generation)
                session.state = 'running'
                with self.assertRaisesRegex(ValueError, 'Pause'): session.seek(0, session.history_generation)
            finally: session.close()

    @unittest.skipUnless(importlib.util.find_spec('mujoco'), 'MuJoCo optional')
    def test_mujoco_restore(self): self.check_engine('mujoco')

    @unittest.skipUnless(importlib.util.find_spec('pybullet'), 'PyBullet optional')
    def test_pybullet_restore(self): self.check_engine('pybullet')
