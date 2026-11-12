"""Process one saved-file URDF job in isolated scratch.

Protocol: JOBDIR/request.json contains {assembly: project-relative path};
JOBDIR/cancel requests cancellation. status.json and report.json are atomic.
Run with --project ROOT --job JOBDIR --preflight BIN --exporter BIN.
"""
import argparse
import re
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import threading
import zipfile

from datum_parameter_studio.urdf_check import check_urdf
from datum_parameter_studio.fidelity_check import check_fidelity
from datum_parameter_studio.physics_check import check_physics


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(tmp, path)
    if path.name == 'status.json':
        versioned = path.parent / f'status-{time.time_ns():020d}.json'
        staged = versioned.with_suffix('.tmp')
        staged.write_text(json.dumps(value, indent=2) + '\n')
        os.replace(staged, versioned)


def run(project, job, preflight, exporter, timeout=120):
    project, job = Path(project).resolve(strict=True), Path(job).resolve(strict=True)
    request = json.loads((job / 'request.json').read_text())
    assembly = request['assembly']
    if not isinstance(assembly, str) or not assembly or assembly.startswith('/') or '\\' in assembly or any(p in ('', '.', '..') for p in assembly.split('/')):
        raise ValueError('Invalid assembly path')
    def status(state, **kwargs):
        atomic(job / 'status.json', {'state': state, **kwargs})
    def cancelled():
        return (job / 'cancel').exists()
    def check_cancel():
        if cancelled(): raise InterruptedError('Cancelled')
    def scan(root):
        result = subprocess.run([str(preflight), str(root), assembly], capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        if data.get('source_checks') != 'pass': raise ValueError(data.get('evidence', 'Source preflight failed'))
        return data
    status('capturing')
    try:
        with tempfile.TemporaryDirectory(prefix='datum-urdf-') as temp:
            scratch = Path(temp) / 'project'; scratch.mkdir()
            source = scan(project); check_cancel()
            for name in source['sources']:
                rel = Path(name)
                if rel.is_absolute() or any(p in ('', '.', '..') for p in rel.parts): raise ValueError('Invalid dependency path')
                src = (project / rel).resolve(strict=True)
                if not src.is_relative_to(project) or not src.is_file(): raise ValueError('Dependency escapes project')
                dst = scratch / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst)
            captured = scan(scratch)
            if source['sources'] != captured['sources'] or source['sources'] != scan(project)['sources']:
                raise ValueError('Source changed during capture')
            check_cancel(); status('exporting')
            bundle = Path(temp) / 'bundle'; bundle.mkdir(); urdf = bundle / 'robot.urdf'
            with tempfile.TemporaryFile() as log:
                child = subprocess.Popen([str(exporter), 'run', '--quiet', '--in', str(scratch / assembly), '--out', str(urdf)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + timeout
                while child.poll() is None:
                    if cancelled() or time.monotonic() > deadline:
                        os.killpg(child.pid, signal.SIGTERM)
                        try: child.wait(timeout=3)
                        except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
                        if cancelled(): raise InterruptedError('Cancelled')
                        raise TimeoutError('Export timed out')
                    time.sleep(.1)
                log.seek(0); output = log.read(65536).decode(errors='replace')
            if child.returncode or not urdf.is_file(): raise RuntimeError(f'Export failed ({child.returncode}): {output}')
            check_cancel(); status('checking')
            result = check_urdf(urdf, bundle, synthetic_base='base_link')
            try: fresh = scan(project)['sources'] == source['sources']
            except Exception: fresh = False
            outputs = [p for p in bundle.rglob('*') if p.is_file()]
            if len(outputs)>4096 or sum(p.stat().st_size for p in outputs)>256*1024*1024: raise ValueError('Output quota exceeded')
            if any(p.is_symlink() or not p.resolve().is_relative_to(bundle.resolve()) for p in outputs): raise ValueError('Unsafe output')
            version = subprocess.run([str(exporter), '--version'], capture_output=True, text=True, timeout=10)
            report = {'schema':'datum.studio-urdf-worker-report/1', 'execution':'complete',
                      'capture':{'mode':'saved-files','assembly':assembly,'hash_algorithm':'blake3'},
                      'exporter':{'version':version.stdout.strip() if version.returncode==0 else None},
                      'outputs_sha256':{p.relative_to(bundle).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs},
                      'source_preflight':source, 'structural_checks':result,
                      'cad_urdf_fidelity_checks':check_fidelity(scratch / assembly, urdf),
                      'physics_checks':check_physics(urdf, bundle),
                      'assembly_fidelity':source['source_fidelity'],
                      'freshness':'current' if fresh else 'stale',
                      'physics_readiness':'unknown', 'note':'Saved-file capture; freshness was checked at export completion. Physics and source-to-URDF equivalence are not verified.'}
            (bundle / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            outputs.append(bundle / 'report.json')
            archive = job / 'bundle.zip.tmp'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                for path in outputs: z.write(path, path.relative_to(bundle))
            check_cancel(); os.replace(archive, job / 'bundle.zip'); atomic(job / 'report.json', report)
            status('succeeded', freshness=report['freshness'], structural_checks=result['status'], assembly_fidelity=report['assembly_fidelity'])
            return report
    except InterruptedError as exc:
        status('cancelled', error=str(exc))
    except Exception as exc:
        status('failed', error=str(exc))
    finally:
        (job / 'bundle.zip.tmp').unlink(missing_ok=True)
    return None


def serve(project, spool, preflight, exporter, timeout=120):
    spool = Path(spool)
    if spool.is_symlink(): raise ValueError('Symlink spool refused')
    spool.mkdir(parents=True, exist_ok=True)
    with open(spool / 'worker.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopping = False
        def stop(signum, frame):
            nonlocal stopping
            stopping = True
            for job in spool.iterdir():
                if re.fullmatch('[0-9a-f]{32}', job.name) and not job.is_symlink() and job.is_dir():
                    if (job / 'status.json').exists():
                        try: state = json.loads((job / 'status.json').read_text()).get('state')
                        except (ValueError, OSError): continue
                        if state in ('capturing', 'exporting', 'checking'): (job / 'cancel').touch()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        marker = spool / 'worker.ready'
        marker.write_text(str(os.getpid()))
        heartbeat_stop = threading.Event()
        def heartbeat():
            while not heartbeat_stop.wait(2):
                marker.touch()
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        first = True
        while not stopping:
            marker.touch()
            for job in sorted(spool.iterdir()):
                if stopping: break
                if not re.fullmatch('[0-9a-f]{32}', job.name) or job.is_symlink() or not job.is_dir(): continue
                if any(p.is_symlink() for p in job.iterdir()): continue
                status = job / 'status.json'
                try: state = json.loads(status.read_text()).get('state') if status.exists() else 'queued'
                except (ValueError, OSError): state = 'invalid'
                if first and state in ('capturing', 'exporting', 'checking'):
                    atomic(status, {'state':'failed', 'error':'Worker interrupted'})
                elif state == 'queued' and (job / 'request.json').is_file():
                    try: run(project, job, preflight, exporter, timeout)
                    except Exception as exc: atomic(status, {'state':'failed', 'error':str(exc)})
            first = False
            time.sleep(.2)
        heartbeat_stop.set()
        heartbeat_thread.join()
        marker.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True);parser.add_argument('--job')
    parser.add_argument('--serve',action='store_true');parser.add_argument('--spool')
    parser.add_argument('--preflight',required=True);parser.add_argument('--exporter',required=True)
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args()
    if args.serve:
        if not args.spool: parser.error('--serve requires --spool')
        serve(args.project,args.spool,args.preflight,args.exporter,args.timeout)
    else:
        if not args.job: parser.error('--job is required')
        run(args.project,args.job,args.preflight,args.exporter,args.timeout)

if __name__=='__main__': main()
