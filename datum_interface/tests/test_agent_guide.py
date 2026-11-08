"""Check that the documented agent quickstart works and the guide ships in a wheel."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / 'datum_interface/python/datum_interface/AGENT_GUIDE.md'
sys.path.insert(0, str(ROOT / 'datum_interface/python'))
from datum_interface import agent_guide, load, load_lazy


def write_cad(path, length_mm, units='mm'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('document.json', json.dumps({'units': units, 'features': [{'type': 'box', 'length': length_mm}]}))


def quickstart_spec():
    """Load the minimal spec straight from the guide so the example cannot drift."""
    text = GUIDE.read_text(encoding='utf-8')
    start = text.index('<!-- quickstart-spec -->')
    end = text.index('<!-- /quickstart-spec -->')
    block = text[start:end]
    match = re.search(r'```json\n(.*?)\n```', block, re.DOTALL)
    if not match:
        raise AssertionError('quickstart spec block is missing from the agent guide')
    return json.loads(match.group(1))


def write_project(root, length_mm=160):
    write_cad(root / 'cad/arm.solidcraft', length_mm)
    (root / 'datum').mkdir(parents=True, exist_ok=True)
    spec_path = root / 'datum/spec.json'
    spec_path.write_text(json.dumps(quickstart_spec(), indent=2) + '\n', encoding='utf-8')
    return spec_path


def generate(root, spec_path):
    manifest = root / 'datum/parameters.json'
    subprocess.run([
        'cargo', 'run', '--quiet', '--offline',
        '--manifest-path', str(ROOT / 'rust/Cargo.toml'),
        '--bin', 'datum-params', '--',
        'generate', str(root), str(spec_path), 'main',
        str(manifest), str(root / 'datum/parameters.hpp'),
    ], check=True)
    return manifest


class AgentGuideTest(unittest.TestCase):
    def test_quickstart_spec_works_in_both_python_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = write_project(root)
            manifest_path = generate(root, spec_path)

            compiled = load(manifest_path, worktree='main')
            lazy = load_lazy(root, worktree='main', evidence=root / 'evidence/lazy.json')

            self.assertAlmostEqual(compiled['forearm_length_m'], 0.16)
            self.assertAlmostEqual(compiled['reach_m'], 0.27)
            self.assertEqual(compiled.group('arm'), {'forearm_length_m': 0.16, 'reach_m': 0.27})
            self.assertEqual(compiled.manifest['parameters'], lazy.manifest['parameters'])
            self.assertEqual(compiled.manifest['sources_sha256'], lazy.manifest['sources_sha256'])
            evidence = json.loads((root / 'evidence/lazy.json').read_text())
            self.assertEqual(evidence['mode'], 'lazy')
            self.assertEqual(evidence['evidence_schema'], 'datum.robot.lazy-evidence/1')

    def test_compiled_artifact_rejects_stale_spec_and_cad(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = write_project(root)
            manifest_path = generate(root, spec_path)
            original_spec = spec_path.read_text(encoding='utf-8')

            changed = json.loads(original_spec)
            changed['worktrees']['main']['groups']['all'] = ['forearm_length_m']
            spec_path.write_text(json.dumps(changed) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'specification changed'):
                load(manifest_path, worktree='main')
            spec_path.write_text(original_spec, encoding='utf-8')

            write_cad(root / 'cad/arm.solidcraft', 170)
            with self.assertRaisesRegex(ValueError, 'CAD source changed'):
                load(manifest_path, worktree='main')
            # Lazy mode has no stale artifact: it reads the current valid CAD.
            self.assertAlmostEqual(load_lazy(root)['forearm_length_m'], 0.17)

            generate(root, spec_path)
            self.assertAlmostEqual(load(manifest_path, worktree='main')['forearm_length_m'], 0.17)

    def test_generated_cpp_header_exposes_the_documented_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = write_project(root)
            generate(root, spec_path)
            source = root / 'consumer.cpp'
            source.write_text(
                '#include "parameters.hpp"\n'
                '#include <cstdio>\n'
                'int main() {\n'
                '    std::printf("%.12f %.12f\\n", '
                'datum::robot::main::forearm_length_m, datum::robot::main::reach_m);\n'
                '    return 0;\n'
                '}\n',
                encoding='utf-8',
            )
            executable = root / 'consumer'
            subprocess.run([
                'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I', str(root / 'datum'), str(source), '-o', str(executable),
            ], check=True)
            values = [float(part) for part in subprocess.run(
                [str(executable)], check=True, capture_output=True, text=True,
            ).stdout.split()]
            self.assertAlmostEqual(values[0], 0.16)
            self.assertAlmostEqual(values[1], 0.27)

    def test_lazy_cpp_abi_needs_no_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root)
            # Deliberately do not generate parameters.json or parameters.hpp.
            subprocess.run([
                'cargo', 'build', '--quiet', '--locked',
                '--manifest-path', str(ROOT / 'rust/Cargo.toml'), '--lib',
            ], check=True)
            source = root / 'lazy.cpp'
            source.write_text(
                '#include "dparams_lazy.h"\n'
                '#include <cstdio>\n'
                'int main(int argc, char** argv) {\n'
                '    if (argc != 3) return 2;\n'
                '    if (dparams_lazy_eval(argv[1], argv[2], "main") != 0) {\n'
                '        char error[512] = {0};\n'
                '        if (dparams_lazy_error(error, sizeof error) != 0) {\n'
                '            std::snprintf(error, sizeof error, "Datum evaluation failed");\n'
                '        }\n'
                '        std::fprintf(stderr, "%s\\n", error);\n'
                '        return 1;\n'
                '    }\n'
                '    double reach = 0.0;\n'
                '    if (dparams_lazy_get("reach_m", &reach) != 0) return 3;\n'
                '    std::printf("%.6f\\n", reach);\n'
                '    dparams_lazy_release();\n'
                '    return 0;\n'
                '}\n',
                encoding='utf-8',
            )
            executable = root / 'lazy'
            subprocess.run([
                'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'rust/include'), str(source), '-o', str(executable),
                '-L', str(ROOT / 'rust/target/debug'), '-ldatum_params_tools',
                '-lpthread', '-ldl',
            ], check=True)
            result = subprocess.run(
                [str(executable), str(root), str(root / 'datum/spec.json')],
                check=True, capture_output=True, text=True,
            )
            self.assertAlmostEqual(float(result.stdout), 0.27)

    def test_agent_guide_ships_in_built_wheel_and_runs_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Build from a clean copy so stale build/ or egg-info directories in
            # the checkout cannot make the guide appear in the wheel by accident.
            source = root / 'source'
            shutil.copytree(
                ROOT / 'datum_interface', source,
                ignore=shutil.ignore_patterns('build', '*.egg-info', '__pycache__'),
            )
            wheel_dir = root / 'wheel'
            subprocess.run([
                sys.executable, '-m', 'build', '--wheel', '--no-isolation',
                '--outdir', str(wheel_dir), str(source),
            ], check=True, capture_output=True, text=True)
            wheels = list(wheel_dir.glob('*.whl'))
            self.assertEqual(len(wheels), 1)
            unpacked = root / 'unpacked'
            with zipfile.ZipFile(wheels[0]) as archive:
                names = archive.namelist()
                self.assertIn('datum_interface/AGENT_GUIDE.md', names)
                archive.extractall(unpacked)

            project = root / 'project'
            write_project(project)
            probe = (
                'import pathlib, sys\n'
                'import datum_interface\n'
                'from datum_interface import agent_guide, load_lazy\n'
                'params = load_lazy(sys.argv[1])\n'
                'print(pathlib.Path(datum_interface.__file__).resolve())\n'
                'print(params["forearm_length_m"])\n'
                'print(agent_guide().splitlines()[0])\n'
            )
            env = dict(os.environ)
            env['PYTHONPATH'] = str(unpacked)
            result = subprocess.run(
                [sys.executable, '-c', probe, str(project)],
                check=True, capture_output=True, text=True, cwd=root, env=env,
            )
            module_path, value, title = result.stdout.splitlines()
            self.assertTrue(Path(module_path).is_relative_to(unpacked))
            self.assertAlmostEqual(float(value), 0.16)
            self.assertEqual(title, '# DParams agent integration guide')


if __name__ == '__main__':
    unittest.main()
