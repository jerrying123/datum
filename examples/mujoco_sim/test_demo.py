import ast
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


@unittest.skipUnless(importlib.util.find_spec('mujoco'), 'MuJoCo is optional')
class DemoTest(unittest.TestCase):
    def test_free_fall_matches_gravity(self):
        import mujoco
        model = mujoco.MjModel.from_xml_string('''<mujoco><option timestep="0.001" gravity="0 0 -9.81"/>
          <worldbody><body pos="0 0 10"><freejoint/><geom type="sphere" size="0.05" mass="1"/></body></worldbody></mujoco>''')
        data = mujoco.MjData(model)
        for _ in range(100):
            mujoco.mj_step(model, data)
        self.assertAlmostEqual(data.qvel[2], -0.981, delta=1e-5)
        self.assertAlmostEqual(data.qpos[2], 10 - 0.5 * 9.81 * 0.1**2, delta=0.001)

    def run_demo(self, args=()):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(REPO / 'parameter_studio')
        result = subprocess.run([sys.executable, str(ROOT / 'demo.py'), *args], env=env,
                                capture_output=True, text=True, check=True)
        match = re.search(r'joints=(\d+) geometries=(\d+) initial=(\[[^]]*\]) qpos=(\[[^]]*\])', result.stdout)
        self.assertIsNotNone(match, result.stdout)
        self.assertEqual(int(match[1]), 1)
        self.assertGreater(int(match[2]), 0)
        self.assertGreater(abs(ast.literal_eval(match[4])[0] - ast.literal_eval(match[3])[0]), 1e-6)

    def test_headless_joint_and_drive(self):
        self.run_demo()

    @unittest.skipUnless(shutil.which('solidcraft-cli') and shutil.which('studio-urdf-preflight'), 'native tools optional')
    def test_native_cad_export(self):
        self.run_demo(['--project', str(REPO / 'examples/pybullet_sim/cad'), '--assembly', 'assembly.solidcraft'])


if __name__ == '__main__':
    unittest.main()
