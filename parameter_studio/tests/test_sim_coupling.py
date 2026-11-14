"""Checks for the supported CAD motion-link subset and engine constraints."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from datum_parameter_studio.simulation import SimulationInput
from datum_parameter_studio.simulations.worker import Engine

URDF = '''<robot name="coupled"><link name="base_link"/><link name="left"><inertial><mass value="1"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial><visual><geometry><box size=".1 .1 .1"/></geometry></visual></link><link name="right"><inertial><mass value="1"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial><visual><geometry><box size=".1 .1 .1"/></geometry></visual></link><joint name="left_finger" type="prismatic"><parent link="base_link"/><child link="left"/><axis xyz="1 0 0"/><limit lower="0" upper="1" effort="100" velocity="10"/></joint><joint name="right_finger" type="prismatic"><parent link="base_link"/><child link="right"/><axis xyz="1 0 0"/><limit lower="0" upper="1" effort="100" velocity="10"/></joint></robot>'''

class CouplingTests(unittest.TestCase):
    def fixture(self, root, link):
        project = root / 'project'; project.mkdir()
        document = {'assembly': {'joints': [
            {'id': 1, 'name': 'left_finger', 'kind': 'slider', 'limits': [[0, 1000]]},
            {'id': 2, 'name': 'right_finger', 'kind': 'slider', 'limits': [[0, 1000]]}], 'links': [link]}}
        with zipfile.ZipFile(project / 'assembly.solidcraft', 'w') as z:
            z.writestr('document.json', json.dumps(document))
        urdf = root / 'robot.urdf'; urdf.write_text(URDF)
        class Holder: name = str(root)
        class Result:
            _holder = Holder()
            bundle = root
            urdf_path = urdf
            report = {'freshness': 'current', 'assembly_fidelity': 'fail',
                      'source_preflight': {'issues': ['unsupported_assembly_links'], 'sources': {'assembly.solidcraft': 'hash'}},
                      'cad_urdf_fidelity_checks': {'status': 'unknown'}}
            def close(self): pass
        return Result()

    def test_rejects_unsupported_link(self):
        for changes in ({'ratio': -1}, {'offset': 1}, {'ia': 1}, {'a': True}, {'type': 'cam'}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp:
                link = {'a': 1, 'b': 2, 'ia': 0, 'ib': 0, 'ratio': 1, 'offset': 0} | changes
                with self.assertRaises(ValueError): SimulationInput(self.fixture(Path(temp), link), assembly='assembly.solidcraft', supports_couplings=True)

    def test_ordinary_urdf_consumers_still_reject_coupling(self):
        with tempfile.TemporaryDirectory() as temp:
            source = self.fixture(Path(temp), {'a': 1, 'b': 2, 'ia': 0, 'ib': 0, 'ratio': 1, 'offset': 0})
            with self.assertRaises(ValueError): SimulationInput(source, assembly='assembly.solidcraft')

    def check_engine(self, backend):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.fixture(root, {'a': 1, 'b': 2, 'ia': 0, 'ib': 0, 'ratio': 1, 'offset': 0})
            source = SimulationInput(result, assembly='assembly.solidcraft', supports_couplings=True)
            engine = Engine(backend, result.urdf_path, source.couplings)
            try:
                engine.set_joint('left_finger', .1)
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertAlmostEqual(positions['right_finger'], .1, places=5)
                with self.assertRaises(ValueError): engine.set_position_control('right_finger', .2, {'kp': 10, 'kd': 1, 'max_force': 5})
                engine.set_position_control('left_finger', .2, {'kp': 10, 'kd': 1, 'max_force': 5})
                for _ in range(240): engine.step()
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertGreater(positions['left_finger'], .11)
                self.assertAlmostEqual(positions['left_finger'], positions['right_finger'], delta=.01)
                engine.reset()
                self.assertFalse(engine.actuators)
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertAlmostEqual(positions['left_finger'], positions['right_finger'], delta=.001)
                engine.set_position_control('left_finger', .1, {'kp': 10, 'kd': 1, 'max_force': 5})
                for _ in range(120): engine.step()
                positions = {j['id']: j['position'] for j in engine.snapshot()['joints']}
                self.assertGreater(positions['left_finger'], .01)
                self.assertAlmostEqual(positions['left_finger'], positions['right_finger'], delta=.01)
            finally: engine.close()

    @unittest.skipUnless(importlib.util.find_spec('mujoco'), 'MuJoCo optional')
    def test_mujoco_constraint(self): self.check_engine('mujoco')

    @unittest.skipUnless(importlib.util.find_spec('pybullet'), 'PyBullet optional')
    def test_pybullet_constraint(self): self.check_engine('pybullet')
