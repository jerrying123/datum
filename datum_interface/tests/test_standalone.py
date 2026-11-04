import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'datum_interface/python'))
from datum_interface import load

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
