"""Optional integration test: executes the actual demo against PyBullet."""
import importlib.util
import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(importlib.util.find_spec('pybullet'), 'PyBullet is optional')
class PyBulletDemoTest(unittest.TestCase):
    def test_headless_demo_loads_and_moves_joint(self):
        result = subprocess.run([sys.executable, str(ROOT / 'demo.py')], capture_output=True, text=True, check=True)
        self.assertIn('1 joints', result.stdout)
        positions = ast.literal_eval(result.stdout.split('joint positions ', 1)[1].strip())
        self.assertAlmostEqual(positions[0], 0.5, delta=0.05)

    @unittest.skipUnless(shutil.which('solidcraft-cli') and shutil.which('studio-urdf-preflight'), 'SolidCraft and preflight are optional')
    def test_native_cad_export_loads_and_moves(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT.parents[1] / 'parameter_studio')
        result = subprocess.run([sys.executable, str(ROOT / 'demo.py'), '--project', str(ROOT / 'cad'),
                                 '--assembly', 'assembly.solidcraft'], env=env, capture_output=True, text=True, check=True)
        positions = ast.literal_eval(result.stdout.split('joint positions ', 1)[1].strip())
        self.assertEqual(len(positions), 2)
        self.assertAlmostEqual(positions[1], 0.5, delta=0.05)


if __name__ == '__main__':
    unittest.main()
