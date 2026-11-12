import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datum_parameter_studio.simulation import SimulationInput, simulation_input
from test_runtime_urdf import MINIMAL_URDF, STL


class Result:
    def __init__(self, freshness='current', fidelity='unknown'):
        self.holder = tempfile.TemporaryDirectory()
        self.bundle = Path(self.holder.name)
        self.urdf_path = self.bundle / 'robot.urdf'
        self.urdf_path.write_text(MINIMAL_URDF)
        (self.bundle / 'robot-arm.stl').write_text(STL)
        self.report = {'freshness': freshness, 'assembly_fidelity': fidelity}

    def close(self):
        self.holder.cleanup()


class SimulationInputTest(unittest.TestCase):
    def test_live_bundle_and_synthetic_base(self):
        result = Result()
        bundle = result.bundle
        with patch('datum_parameter_studio.simulation.bring_up_urdf', return_value=result):
            with simulation_input('/project', 'robot.solidcraft') as source:
                self.assertTrue(source.urdf_path.is_file())
                self.assertTrue((source.bundle / 'robot-arm.stl').is_file())
            self.assertFalse(bundle.exists())

    def test_rejected_report_cleans_bundle(self):
        for freshness, fidelity in [('stale', 'unknown'), ('current', 'fail'), ('current', None)]:
            with self.subTest(freshness=freshness, fidelity=fidelity):
                result = Result(freshness, fidelity)
                bundle = result.bundle
                with self.assertRaises(ValueError):
                    SimulationInput(result)
                self.assertFalse(bundle.exists())

    def test_validation_exception_cleans_bundle(self):
        result = Result()
        bundle = result.bundle
        with patch('datum_parameter_studio.simulation.check_urdf', side_effect=RuntimeError('bad XML')):
            with self.assertRaises(RuntimeError):
                SimulationInput(result)
        self.assertFalse(bundle.exists())

    def test_missing_mesh_rejected_and_cleaned(self):
        result = Result()
        bundle = result.bundle
        (bundle / 'robot-arm.stl').unlink()
        with self.assertRaises(ValueError):
            SimulationInput(result)
        self.assertFalse(bundle.exists())
