"""Validate that Studio distributions include the exact reviewed browser bundle."""
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

root = Path(__file__).resolve().parents[1]
expected = (root / 'parameter_studio/datum_parameter_studio/public/app.js').read_bytes()
directory = Path(sys.argv[1])
wheels = list(directory.glob('datum_parameter_studio-*.whl'))
sdists = list(directory.glob('datum_parameter_studio-*.tar.gz'))
if len(wheels) != 1 or len(sdists) != 1:
    raise SystemExit('Expected exactly one Studio wheel and sdist')
required = ('public/app.js', 'frontend/src/app.ts', 'frontend/src/models.ts', 'frontend/src/contracts.ts', 'frontend/src/validation.ts', 'frontend/src/dom.ts', 'frontend/scripts/check-bundle.cjs', 'tsconfig.json', 'package-lock.json')

def verify(names, read):
    for suffix in required:
        matches = [n for n in names if n.endswith('/datum_parameter_studio/' + suffix) or n == 'datum_parameter_studio/' + suffix]
        if len(matches) != 1:
            raise SystemExit(f'Missing or ambiguous distribution file: {suffix}')
        if suffix == 'public/app.js' and read(matches[0]) != expected:
            raise SystemExit('Distribution contains a different browser bundle')
    if any('/node_modules/' in n for n in names):
        raise SystemExit('Distribution includes node_modules')

with ZipFile(wheels[0]) as archive:
    verify(archive.namelist(), archive.read)
with tarfile.open(sdists[0]) as archive:
    def read_tar(name):
        stream = archive.extractfile(name)
        if stream is None:
            raise ValueError(name)
        return stream.read()
    verify(archive.getnames(), read_tar)
print('Studio sdist and wheel contain the reviewed bundle and sources.')
