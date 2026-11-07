import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'datum_interface/python'))
from datum_interface import load, load_lazy

class StandaloneTest(unittest.TestCase):
    def test_generation_and_stale_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'cad').mkdir(); (root / 'datum').mkdir()
            cad = root / 'cad/part.solidcraft'
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':160}]}))
            spec = {'schema':'datum.robot.parameter-spec/2','units':'m','worktrees':{'main':{'parameters':{'length_m':{'path':'cad/part.solidcraft','pointer':'/features/0/length','source_units':'mm','unit':'m'}}}}}
            spec_path = root / 'datum/spec.json'; spec_path.write_text(json.dumps(spec))
            manifest = root / 'datum/parameters.json'; header = root / 'datum/parameters.hpp'
            subprocess.run(['cargo','run','--quiet','--offline','--manifest-path',str(ROOT/'rust/Cargo.toml'),'--bin','datum-params','--','generate',str(root),str(spec_path),'main',str(manifest),str(header)],check=True)
            self.assertAlmostEqual(load(manifest, worktree='main')['length_m'], .16)
            cad.write_bytes(cad.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError, 'CAD source changed'): load(manifest, worktree='main')

    def test_lazy_evaluation_agrees_with_compiled_artifacts(self):
        """Compiled and lazy modes must evaluate one spec to identical values."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'cad').mkdir(); (root / 'datum').mkdir()
            cad = root / 'cad/part.solidcraft'
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','params':[{'name':'arm_length','expr':'160 mm','unit':'mm'}],'features':[{'type':'box','length':'arm_length'}]}))
            spec = {'schema':'datum.robot.parameter-spec/2','units':'m','worktrees':{'main':{
                'parameters':{'length_m':{'path':'cad/part.solidcraft','pointer':'/features/0/length','source_units':'mm','unit':'m'}},
                'constants':{'shoulder_height_m':{'value':.11,'unit':'m'}},
                'derived':{'reach_m':{'operation':'sum','inputs':['length_m','shoulder_height_m'],'unit':'m'}},
                'groups':{'arm':['length_m','reach_m']}}}}
            spec_path = root / 'datum/spec.json'; spec_path.write_text(json.dumps(spec))
            manifest_path = root / 'datum/parameters.json'
            subprocess.run(['cargo','run','--quiet','--offline','--manifest-path',str(ROOT/'rust/Cargo.toml'),'--bin','datum-params','--','generate',str(root),str(spec_path),'main',str(manifest_path),str(root/'datum/parameters.hpp')],check=True)
            compiled = json.loads(manifest_path.read_text())
            params, evidence = None, None
            lazy = load_lazy(root, worktree='main', evidence=root/'evidence/lazy.json')
            self.assertEqual(compiled['parameters'], lazy.values)
            self.assertEqual(compiled['sources_sha256'], lazy.manifest['sources_sha256'])
            self.assertEqual(compiled['spec_sha256'], lazy.manifest['spec_sha256'])
            self.assertEqual(compiled['groups'], lazy.manifest['groups'])
            evidence = (root/'evidence/lazy.json').read_text()
            self.assertIn('"mode": "lazy"', evidence)
            self.assertIn('"spec_sha256"', evidence)
            self.assertAlmostEqual(lazy['reach_m'], .16 + .11)
            self.assertEqual(lazy.group('arm'), {'length_m':0.16,'reach_m':0.27})
            # The named SolidCraft parameter resolves identically in both modes.
            self.assertAlmostEqual(lazy['length_m'], .16)

    def test_lazy_requires_only_spec_and_cad(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'cad').mkdir(); (root / 'datum').mkdir()
            cad = root / 'cad/part.solidcraft'
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':160}]}))
            spec_path = root / 'datum/spec.json'
            spec_path.write_text(json.dumps(
                {'schema':'datum.robot.parameter-spec/2','units':'m','worktrees':{'main':{'parameters':{'length_m':{'path':'cad/part.solidcraft','pointer':'/features/0/length','source_units':'mm','unit':'m','min':100,'max':200}}}}}))
            params = load_lazy(root, evidence=root/'datum/lazy-evidence.json')
            self.assertAlmostEqual(params['length_m'], .16)
            self.assertEqual(params.manifest['bounds']['length_m'], {'min':0.1,'max':0.2,'allow_nonpositive':False})
            # Bounds and structure are enforced at runtime, not baked in: changing
            # the CAD yields the new value rather than serving a stale artifact,
            # and an out-of-bounds CAD change is rejected at startup.
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':180}]}))
            self.assertAlmostEqual(load_lazy(root)['length_m'], .18)
            # An out-of-bounds CAD change is rejected at startup.
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':40}]}))
            with self.assertRaisesRegex(ValueError, 'outside allowed bounds'):
                load_lazy(root)
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'inch','features':[{'type':'box','length':6}]}))
            with self.assertRaisesRegex(ValueError, 'units mismatch'):
                load_lazy(root)
            with zipfile.ZipFile(cad, 'w') as archive:
                archive.writestr('document.json', json.dumps({'units':'mm','features':[{'type':'box','length':250}]}))
            with self.assertRaisesRegex(ValueError, 'outside allowed bounds'):
                load_lazy(root)
