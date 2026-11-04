import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datum_parameter_studio.urdf_check import check_urdf

INERTIA = '<inertial><mass value="1"/><inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/></inertial>'
STL = '''solid test
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 1 0 1
vertex 0 1 0
endloop
endfacet
endsolid test
'''

class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name); (self.dir / 'part.stl').write_text(STL)
        self.xml = '<robot name="r"><link name="base">' + INERTIA + '<visual><geometry><mesh filename="part.stl"/></geometry></visual></link></robot>'
    def check(self, xml):
        path = self.dir / 'robot.urdf'; path.write_text(xml)
        return check_urdf(path, self.dir)
    def test_valid_and_cli(self):
        self.assertEqual(self.check(self.xml)['status'], 'pass')
        result = subprocess.run([sys.executable, '-m', 'datum_parameter_studio.urdf_check', str(self.dir / 'robot.urdf'), str(self.dir)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0); self.assertTrue(json.loads(result.stdout)['unknowns'])
    def test_exporter_prolog_and_comment(self):
        self.assertEqual(self.check('<?xml version="1.0"?>\n<!-- Exported by SolidCraft -->\n' + self.xml)['status'], 'pass')

    def test_bad_inputs(self):
        for xml in (self.xml.replace('part.stl', '../part.stl'), self.xml.replace('part.stl', 'http://host/a.stl'), self.xml.replace('value="1"', 'value="NaN"', 1), self.xml.replace('izz="1"', 'izz="0"'), self.xml.replace('</robot>', '<link name="base"/></robot>'), '<!DOCTYPE robot [<!ENTITY x "x">]><robot/>'):
            with self.subTest(xml=xml): self.assertEqual(self.check(xml)['status'], 'fail')
    def test_symlink_escape(self):
        (self.dir / 'escape.stl').symlink_to('/etc/passwd')
        self.assertEqual(self.check(self.xml.replace('part.stl', 'escape.stl'))['status'], 'fail')
    def test_synthetic_base(self):
        path = self.dir / 'robot.urdf'; path.write_text('<robot><link name="base"/></robot>')
        self.assertEqual(check_urdf(path, self.dir, 'base')['status'], 'pass')
        self.assertEqual(check_urdf(path, self.dir)['status'], 'fail')

if __name__ == '__main__': unittest.main()
