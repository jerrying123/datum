"""Exercise generated C++ headers without requiring the SolidCraft application."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/cpp-pick-place'

class CppPickPlaceTest(unittest.TestCase):
    def test_generated_headers_drive_same_changed_plant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant, length in [('baseline', 100), ('changed', 160)]:
                project = root / variant
                (project / 'cad').mkdir(parents=True)
                (project / 'datum').mkdir()
                parameters = {}
                for name, value in [('upper_arm', 180), ('forearm', length), ('gripper_palm', 50), ('finger', 55)]:
                    with zipfile.ZipFile(project / f'cad/{name}.solidcraft', 'w') as z:
                        z.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':value}]}))
                    parameters[name + '_length_m'] = {'path':f'cad/{name}.solidcraft','pointer':'/features/0/length','source_units':'mm','unit':'m'}
                spec = {'schema':'datum.robot.parameter-spec/2','units':'m','worktrees':{'main':{'parameters':parameters,'constants':{'shoulder_height_m':{'value':.11,'unit':'m'}}}}}
                spec_path = project / 'datum/spec.json'
                spec_path.write_text(json.dumps(spec))
                subprocess.run(['cargo','run','--quiet','--locked','--manifest-path',str(ROOT/'rust/Cargo.toml'),'--bin','datum-params','--','generate',str(project),str(spec_path),'main',str(project/'datum/parameters.json'),str(project/'datum/parameters.hpp')],check=True)
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(root/'changed/datum'),'-c',str(EXAMPLE/'physical.cpp'),'-o',str(root/'physical.o')],check=True)
            for variant, expected in [('baseline','fail'),('changed','pass')]:
                executable=root/variant/'pick_place'
                subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(root/variant/'datum'),str(EXAMPLE/'controller.cpp'),str(root/'physical.o'),'-o',str(executable)],check=True)
                result=subprocess.run([str(executable),expected],check=True,capture_output=True,text=True).stdout
                self.assertIn('physical tool=0.2375 m',result)
                if variant=='baseline':
                    self.assertIn('error=0.0600 m',result)
                    self.assertIn('remaining stages skipped',result)
                else:
                    for stage in ('grasp:', 'lift:', 'place:', 'PASS:'):
                        self.assertIn(stage,result)
                wrong='pass' if expected=='fail' else 'fail'
                self.assertNotEqual(subprocess.run([str(executable),wrong],capture_output=True).returncode,0)

if __name__=='__main__': unittest.main()
