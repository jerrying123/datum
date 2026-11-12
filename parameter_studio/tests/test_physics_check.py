import sys
import tempfile
import unittest
import struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datum_parameter_studio.physics_check import check_physics

class PhysicsCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.urdf=self.root/'r.urdf'
    def run_xml(self, body):
        self.urdf.write_text('<robot>'+body+'</robot>')
        return check_physics(self.urdf)
    def test_analytical_valid_tensor(self):
        r=self.run_xml('<link name="a"><inertial><mass value="2"/><inertia ixx="2" iyy="3" izz="4" ixy="0" ixz="0" iyz="0"/></inertial><collision><geometry><box size="1 1 1"/></geometry></collision></link>')
        self.assertEqual(r['checks']['mass_inertia']['status'],'pass')
        self.assertEqual(r['checks']['inertia_triangle']['status'],'pass')
        self.assertEqual(r['physics_readiness']['status'],'unknown')
    def test_mutated_invalid_mass_and_triangle(self):
        for mass, izz in [('0','4'),('1','10')]:
            r=self.run_xml(f'<link name="a"><inertial><mass value="{mass}"/><inertia ixx="1" iyy="1" izz="{izz}" ixy="0" ixz="0" iyz="0"/></inertial><collision/></link>')
            if mass == '0': self.assertEqual(r['checks']['mass_inertia']['status'],'fail')
            if izz=='10': self.assertEqual(r['checks']['inertia_triangle']['status'],'fail')
    def test_missing_collision_fails(self):
        r=self.run_xml('<link name="a"/>')
        self.assertEqual(r['checks']['collision_geometry']['status'],'fail')

    def test_triangle_equality_and_roundoff(self):
        for value in ('2', '2.00000000001'):
            r = self.run_xml(f'<link name="a"><inertial><mass value="1"/><inertia ixx="1" iyy="1" izz="{value}" ixy="0" ixz="0" iyz="0"/></inertial><collision><geometry><box size="1 1 1"/></geometry></collision></link>')
            self.assertEqual(r['checks']['inertia_triangle']['status'], 'pass')

    def test_invalid_collision_geometry(self):
        for collision in ('<collision/>', '<collision><geometry><box size="1 0 1"/></geometry></collision>'):
            r = self.run_xml('<link name="a">' + collision + '</link>')
            self.assertEqual(r['checks']['collision_geometry']['status'], 'fail')

    def test_mesh_scale_and_small_triangle(self):
        path = self.root / 'small.stl'
        path.write_bytes(bytes(80) + struct.pack('<I', 1) + struct.pack('<12fH', 0,0,1, 0,0,0, 1e-6,0,0, 0,1e-6,0, 0))
        for scale, expected in [('1 1 1', 'pass'), ('0 1 1', 'fail'), ('nan 1 1', 'fail')]:
            r = self.run_xml(f'<link name="a"><collision><geometry><mesh filename="small.stl" scale="{scale}"/></geometry></collision></link>')
            self.assertEqual(r['checks']['collision_geometry']['status'], expected)
        path = self.root / 'bad.stl'
        for payload in (bytes(80) + struct.pack('<I', 0),
                        bytes(80) + struct.pack('<I', 1) + struct.pack('<12fH', 0,0,0, float('nan'),0,0, 1,0,0, 0,1,0, 0)):
            path.write_bytes(payload)
            r = self.run_xml('<link name="a"><collision><geometry><mesh filename="bad.stl"/></geometry></collision></link>')
            self.assertEqual(r['checks']['collision_geometry']['status'], 'fail')

if __name__=='__main__': unittest.main()
