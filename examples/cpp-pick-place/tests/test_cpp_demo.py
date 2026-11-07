"""Exercise generated C++ headers and lazy C++ evaluation without SolidCraft."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / 'examples/cpp-pick-place'

def write_cad_project(root, variant, forearm_length):
    (root / 'cad').mkdir(parents=True)
    (root / 'datum').mkdir()
    parameters = {}
    for name, value in [('upper_arm', 180), ('forearm', forearm_length), ('gripper_palm', 50), ('finger', 55)]:
        with zipfile.ZipFile(root / f'cad/{name}.solidcraft', 'w') as z:
            z.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':value}]}))
        parameters[name + '_length_m'] = {'path':f'cad/{name}.solidcraft','pointer':'/features/0/length','source_units':'mm','unit':'m'}
    spec = {'schema':'datum.robot.parameter-spec/2','units':'m','worktrees':{'main':{'parameters':parameters,'constants':{'shoulder_height_m':{'value':.11,'unit':'m'}}}}}
    spec_path = root / 'datum/spec.json'
    spec_path.write_text(json.dumps(spec))
    return spec_path

class CppPickPlaceTest(unittest.TestCase):
    def test_generated_headers_drive_same_changed_plant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant, length in [('baseline', 100), ('changed', 160)]:
                project = root / variant
                spec_path = write_cad_project(project, variant, length)
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

    def test_lazy_evaluation_matches_compiled_values_without_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant, length in [('baseline', 100), ('changed', 160)]:
                project = root / variant
                spec_path = write_cad_project(project, variant, length)
                subprocess.run(['cargo','run','--quiet','--locked','--manifest-path',str(ROOT/'rust/Cargo.toml'),'--bin','datum-params','--','generate',str(project),str(spec_path),'main',str(project/'datum/parameters.json'),str(project/'datum/parameters.hpp')],check=True)
            subprocess.run(['cargo','build','--quiet','--locked','--manifest-path',str(ROOT/'rust/Cargo.toml'),'--lib'],check=True)
            executable=root/'pick_place_lazy'
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'rust/include'),'-I',str(EXAMPLE),str(EXAMPLE/'controller_lazy.cpp'),'-o',str(executable),'-L',str(ROOT/'rust/target/debug'),'-ldatum_params_tools','-lpthread','-ldl'],check=True)
            env = dict(os.environ)
            existing = env.get('LD_LIBRARY_PATH')
            env['LD_LIBRARY_PATH'] = str(ROOT/'rust/target/debug') + (os.pathsep + existing if existing else '')
            # The lazy consumer needs no generated artifacts: remove both.
            generated = root/'changed/datum/parameters.json', root/'changed/datum/parameters.hpp'
            for path in generated: path.unlink()
            for projects, expected in [((root/'changed',root/'changed'),'pass'), ((root/'baseline',root/'changed'),'fail')]:
                evidence = root/f'{projects[0].name}-lazy-evidence.json'
                result=subprocess.run([str(executable),str(projects[0]),str(projects[1]),expected,str(evidence)],check=True,capture_output=True,text=True,env=env).stdout
                self.assertIn(f'controller tool={0.1775 if expected=="fail" else 0.2375} m',result)
                self.assertIn('physical tool=0.2375 m',result)
                if expected=='fail':
                    self.assertIn('error=0.0600 m',result)
                else:
                    self.assertIn('PASS:',result)
                record=json.loads(evidence.read_text())
                self.assertEqual(record['mode'],'lazy')
                self.assertEqual(record['sources_sha256']['cad/forearm.solidcraft'],hashlib.sha256((projects[0]/'cad/forearm.solidcraft').read_bytes()).hexdigest())
                self.assertEqual(record['spec_sha256'],hashlib.sha256((projects[0]/'datum/spec.json').read_bytes()).hexdigest())
            # Mismatching CAD directories must return the failing exit code.
            self.assertEqual(subprocess.run([str(executable),str(root/'baseline'),str(root/'changed'),'pass'],capture_output=True,text=True,env=env).returncode,1)

if __name__=='__main__': unittest.main()
