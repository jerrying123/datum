#!/usr/bin/env python3
"""Measure Python interpreter startup and a generated or runtime parameter load."""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'datum_interface/python'))
from datum_interface import load_generated, load_runtime


def execute(project, mode):
    params = load_generated(project / 'datum/parameters.json', worktree='main') if mode == 'generated' else load_runtime(project)
    print(json.dumps(params.values, sort_keys=True, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--runs', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', choices=['generated', 'runtime'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    if args.child:
        execute(project, args.child)
        return
    if args.runs < 1 or args.warmup < 0:
        parser.error('--runs must be positive and --warmup non-negative')
    spec = project / 'datum/spec.json'
    manifest = json.loads((project / 'datum/parameters.json').read_text())
    samples = {'generated': [], 'runtime': []}
    expected = None
    for iteration in range(args.warmup + args.runs):
        modes = ['generated', 'runtime'] if iteration % 2 == 0 else ['runtime', 'generated']
        for mode in modes:
            start = time.perf_counter_ns()
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(project), '--child', mode], check=True, capture_output=True, text=True)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if expected is None:
                expected = json.loads(result.stdout)
            if json.loads(result.stdout) != expected:
                raise RuntimeError('parameter values changed or differ between modes')
            if iteration >= args.warmup:
                samples[mode].append(elapsed)
    for name, digest in manifest['sources_sha256'].items():
        if hashlib.sha256((project / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'CAD source changed: {name}')
    if hashlib.sha256(spec.read_bytes()).hexdigest() != manifest['spec_sha256']:
        raise RuntimeError('spec changed')
    report = {'schema':'datum.python-loader.startup-benchmark/1', 'platform':platform.platform(),
              'python':sys.version, 'project':str(project), 'runs':args.runs, 'warmup':args.warmup,
              'spec_sha256':manifest['spec_sha256'], 'sources_sha256':manifest['sources_sha256'],
              'scope':'Python process start through one load and JSON output; no simulation.',
              'end_to_end_process_ms': {k:{'samples_ms':v, 'median_ms':statistics.median(v), 'min_ms':min(v), 'max_ms':max(v)} for k,v in samples.items()}}
    output = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')

if __name__ == '__main__':
    main()
