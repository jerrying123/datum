"""Isolated transport contract tests; run with unittest discovery in this directory."""
import os
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from datum_parameter_studio.simulations.gazebo import GazeboEngine, parse_pose, capability
from datum_parameter_studio.simulations.worker import Session, atomic


class ProtocolTests(unittest.TestCase):
    def test_control_acknowledgement(self):
        engine = GazeboEngine.__new__(GazeboEngine)
        engine.messages = {'world_control': NS(WorldControl=lambda **kw: kw),
                           'boolean': NS(Boolean=object)}
        engine.node = Mock()
        engine.node.request.return_value = (True, NS(data=True))
        engine.control(pause=True, multi_step=1)
        engine.node.request.assert_called_once_with('/world/datum/control',
            {'pause': True, 'multi_step': 1}, engine.messages['world_control'].WorldControl, object, 1000)
        engine.node.request.return_value = (True, NS(data=False))
        with self.assertRaises(RuntimeError): engine.control(pause=True)

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
