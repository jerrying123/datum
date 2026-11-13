"""Isolated transport contract tests; run with unittest discovery in this directory."""
import os
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from datum_parameter_studio.simulations.gazebo import GazeboEngine, parse_pose, capability, mimic_physics_engine
from datum_parameter_studio.simulations.worker import Session, atomic


def write_coupled_fixture(path):
    inertial = '<inertial><mass value="1"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial>'
    visual = '<visual><geometry><box size=".1 .1 .1"/></geometry></visual>'
    path.write_text('<robot name="robot"><link name="base">' + inertial + '</link>' +
        '<link name="left">' + inertial + visual + '</link><link name="right">' + inertial + visual + '</link>' +
        '<joint name="left_finger" type="prismatic"><parent link="base"/><child link="left"/>'
        '<axis xyz="1 0 0"/><limit lower="0" upper="1" effort="100" velocity="10"/></joint>'
        '<joint name="right_finger" type="prismatic"><parent link="base"/><child link="right"/>'
        '<axis xyz="1 0 0"/><limit lower="0" upper="1" effort="100" velocity="10"/></joint></robot>')

COUPLINGS = [{'driver': 'left_finger', 'driven': 'right_finger', 'ratio': 1.0, 'offset': 0.0}]


class ProtocolTests(unittest.TestCase):
    def test_control_acknowledgement(self):
        engine = GazeboEngine.__new__(GazeboEngine)
        engine.control_process = Mock()
        engine.control_process.poll.return_value = None
        engine.control_process.stdout.readline.return_value = '{"ok": true}\n'
        with patch('datum_parameter_studio.simulations.gazebo.select.select', return_value=([engine.control_process.stdout], [], [])):
            engine.control(pause=True, multi_step=1)
            engine.control_process.stdin.write.assert_called_once_with('{"pause": true, "multi_step": 1}\n')
            engine.control_process.stdout.readline.return_value = '{"ok": false}\n'
            with self.assertRaises(RuntimeError): engine.control(pause=True)
        with patch('datum_parameter_studio.simulations.gazebo.select.select', return_value=([], [], [])):
            with self.assertRaisesRegex(RuntimeError, 'outcome is unknown'): engine.control(pause=True, multi_step=1)

    def test_step_does_not_block_transport_callbacks(self):
        engine = GazeboEngine.__new__(GazeboEngine)
        engine.condition = threading.Condition()
        engine.generation = 0
        engine.sample = {'time': 0.0}
        engine.joints = []
        engine.actuators = {}
        def control(**_kwargs):
            def callback():
                with engine.condition:
                    engine.generation += 1
                    engine.sample['time'] += engine.timestep
                    engine.condition.notify_all()
            thread = threading.Thread(target=callback, daemon=True)
            thread.start()
            thread.join(timeout=.5)
            if thread.is_alive(): raise RuntimeError('callback blocked by world control')
        engine.control = control
        engine.step()
        self.assertEqual(engine.generation, 1)

    def test_coupling_requires_matching_mimic_capable_physics(self):
        result = NS(returncode=0, stdout='8.15.0')
        with patch('datum_parameter_studio.simulations.gazebo.subprocess.run', return_value=result), \
             patch('datum_parameter_studio.simulations.gazebo.ctypes.util.find_library', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'mimic support'): mimic_physics_engine()
        result = NS(returncode=0, stdout='8.15.0\n9.0.0')
        with patch('datum_parameter_studio.simulations.gazebo.subprocess.run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'ambiguous'): mimic_physics_engine()

    def test_pose_units_and_quaternion_order(self):
        pose = NS(name='robot::arm', position=NS(x=1., y=2., z=3.),
                  orientation=NS(x=.1, y=.2, z=.3, w=.9))
        result = parse_pose(NS(header=NS(stamp=NS(sec=2, nsec=500000000)), pose=[pose]))
        self.assertEqual(result['time'], 2.5)
        self.assertEqual(result['links'][0], {'id': 'arm', 'position': [1., 2., 3.],
                                              'quaternion': [.1, .2, .3, .9]})

    @unittest.skipUnless(os.environ.get('DATUM_TEST_GAZEBO') == '1', 'opt-in real Gazebo test')
    def test_real_server(self):
        self.assertTrue(capability()['supported'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'robot.urdf'
            path.write_text('''<robot name="robot"><link name="base"><inertial>
< mass value="1"/></inertial></link></robot>'''.replace('< mass', '<mass'))
            # Full positive inertia is required by the physics engine.
            path.write_text('<robot name="robot"><link name="base"><inertial><mass value="1"/>'
                '<inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/>'
                '</inertial></link></robot>')
            engine = GazeboEngine(path)
            try:
                before = engine.snapshot()['time']
                engine.step()
                self.assertGreater(engine.snapshot()['time'], before)
                engine.reset()
            finally: engine.close()

    @unittest.skipUnless(os.environ.get('DATUM_TEST_GAZEBO') == '1', 'opt-in real Gazebo test')
    def test_real_coupled_sliders_follow_under_force_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'robot.urdf'
            write_coupled_fixture(path)
            couplings = COUPLINGS
            engine = GazeboEngine(path, couplings)
            try:
                with self.assertRaises(ValueError):
                    engine.set_position_control('right_finger', .1, {'kp': 10, 'kd': 1, 'max_force': 5})
                engine.set_position_control('left_finger', .1, {'kp': 10, 'kd': 1, 'max_force': 5})
                for _ in range(120): engine.step()
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertGreater(positions['left_finger'], .01)
                self.assertAlmostEqual(positions['left_finger'], positions['right_finger'], delta=.005)
                engine.reset()
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertAlmostEqual(positions['left_finger'], positions['right_finger'], delta=.001)
                self.assertFalse(engine.actuators)
            finally: engine.close()

    @unittest.skipUnless(os.environ.get('DATUM_TEST_GAZEBO') == '1', 'opt-in real Gazebo test')
    def test_real_coupled_session_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); bundle = root / 'source'; bundle.mkdir()
            urdf = bundle / 'robot.urdf'; write_coupled_fixture(urdf)
            directory = root / 'session'; directory.mkdir()
            atomic(directory / 'request.json', {'backend': 'gazebo', 'assembly': 'robot.solidcraft'})
            source = NS(bundle=bundle, urdf_path=urdf, couplings=COUPLINGS, result=NS(report={}), close=lambda: None)
            session = Session(root, directory)
            with patch('datum_parameter_studio.simulations.worker.simulation_input', return_value=source):
                try:
                    session.start()
                    atomic(directory / 'commands' / '0.json', {'id':'0', 'command':'set_position_control', 'joint':'left_finger', 'position':.1, 'profile':{'kp':10,'kd':1,'max_force':5}})
                    session.tick()
                    self.assertFalse(session.error, session.error)
                    atomic(directory / 'commands' / '1.json', {'id':'1','command':'resume'})
                    for _ in range(120): session.tick()
                    joints = {j['id']: j['position'] for j in session.engine.snapshot()['joints']}
                    self.assertGreater(joints['left_finger'], .01)
                    self.assertAlmostEqual(joints['left_finger'], joints['right_finger'], delta=.005)
                    atomic(directory / 'commands' / '2.json', {'id':'2','command':'reset'})
                    session.tick()
                    self.assertEqual(session.epoch, 1)
                    self.assertFalse(session.engine.actuators)
                finally: session.close()

    @unittest.skipUnless(os.environ.get('DATUM_TEST_GAZEBO_URDF'), 'real exported URDF not supplied')
    def test_real_exported_robot(self):
        engine = GazeboEngine(os.environ['DATUM_TEST_GAZEBO_URDF'])
        try:
            for _ in range(10):
                engine.step()
                sample = engine.snapshot()
                if any(j['id'] == 'hinge' for j in sample['joints']): break
                time.sleep(.05)
            self.assertTrue({'base', 'arm'}.issubset({link['id'] for link in sample['links']}))
            self.assertTrue(any(j['id'] == 'hinge' for j in sample['joints']))
            self.assertGreater(sample['time'], .005)
            engine.reset()
            self.assertLess(engine.snapshot()['time'], sample['time'])
        finally: engine.close()

    @unittest.skipUnless(os.environ.get('DATUM_TEST_GAZEBO_URDF'), 'real exported URDF not supplied')
    def test_real_gazebo_session_recording(self):
        source_path = Path(os.environ['DATUM_TEST_GAZEBO_URDF'])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'session'; directory.mkdir()
            atomic(directory / 'request.json', {'backend':'gazebo','assembly':'robot.solidcraft'})
            source = NS(bundle=source_path.parent, urdf_path=source_path, result=NS(report={}), close=lambda: None)
            session = Session(tmp, directory)
            with patch('datum_parameter_studio.simulations.worker.simulation_input', return_value=source):
                try:
                    session.start()
                    for i, name in enumerate(('record_start','step','reset','record_stop','stop')):
                        atomic(directory / 'commands' / f'{i}.json', {'id':str(i), 'command':name})
                        session.tick()
                        self.assertFalse(session.error, session.error)
                    self.assertEqual(session.state, 'stopped')
                    self.assertTrue(list((directory / 'recordings').glob('*.jsonl')))
                finally: session.close()
