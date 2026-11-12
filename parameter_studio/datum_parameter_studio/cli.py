import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run the local Datum Studio with Docker Compose.")
    parser.add_argument("action", nargs="?", choices=["up", "down", "logs"], default="up")
    parser.add_argument("--port", default=os.environ.get("DATUM_STUDIO_PORT", "8000"))
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="CAD project folder to watch (default: current directory)")
    parser.add_argument("--source-repo", type=Path, help="datum-params checkout containing rust/Cargo.toml (required to build the generator)")
    parser.add_argument("--tailscale", action="store_true", help="Share Studio privately over Tailscale HTTPS on port 8443")
    args = parser.parse_args()
    docker = shutil.which("docker")
    if not docker:
        parser.error("Docker is required. Install Docker Desktop or Docker Engine with the Compose plugin.")
    package_dir = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["DATUM_STUDIO_PORT"] = args.port
    project = args.project.expanduser().resolve()
    if args.action == "up" and not project.is_dir():
        parser.error(f"CAD project folder does not exist: {project}")
    env["DATUM_PROJECT_DIR"] = str(project)
    candidates = ([args.source_repo.expanduser().resolve()] if args.source_repo else
                  [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]])
    source_repo = next((p for p in candidates if (p / "rust/Cargo.toml").is_file()
                        and (p / "parameter_studio/datum_parameter_studio/Dockerfile").is_file()), None)
    if args.action == "up" and source_repo is None:
        parser.error("Building Studio requires a datum-params checkout. Pass --source-repo /path/to/datum.")
    if source_repo:
        env["DATUM_SOURCE_REPO"] = str(source_repo)
    preview_dir = project / ".dparams-studio" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    env["DATUM_PREVIEW_DIR"] = str(preview_dir)
    spool = project / '.dparams-studio' / 'urdf-jobs'
    if spool.is_symlink(): parser.error('URDF spool must not be a symlink')
    spool.mkdir(parents=True, exist_ok=True)
    env['DATUM_URDF_SPOOL'] = str(spool)
    sim_spool = project / '.dparams-studio' / 'sim-jobs'
    if sim_spool.is_symlink(): parser.error('Simulation spool must not be a symlink')
    sim_spool.mkdir(parents=True, exist_ok=True)
    env['DATUM_SIM_SPOOL'] = str(sim_spool)
    sim_pid = sim_spool / 'worker.pid'
    def owned_sim_worker():
        try:
            record = json.loads(sim_pid.read_text())
            pid = record['pid']
            cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            start = Path(f'/proc/{pid}/stat').read_text().split()[21]
            return pid if start == record['start'] and b'datum_parameter_studio.simulations.worker' in cmd and str(sim_spool).encode() in cmd else None
        except (OSError, ValueError, KeyError, IndexError): return None
    worker_pid = spool / 'worker.pid'
    def owned_worker():
        try:
            record = json.loads(worker_pid.read_text())
            pid = record['pid']
            cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            stat = Path(f'/proc/{pid}/stat').read_text().split()[21]
            return pid if stat == record['start'] and b'datum_parameter_studio.urdf_worker' in cmd and str(spool).encode() in cmd else None
        except (OSError, ValueError, KeyError, IndexError): return None
    compose_file = Path(__file__).resolve().parent / "compose.yaml"
    command = [docker, "compose", "-f", str(compose_file), "--project-directory", str(compose_file.parent), args.action]
    sim_worker = None
    try:
        if args.action == "up":
            if not owned_sim_worker():
                (sim_spool / 'worker.ready').unlink(missing_ok=True)
                with open(sim_spool / 'worker.log', 'ab', buffering=0) as log:
                    sim_env = os.environ.copy()
                    if source_repo:
                        sim_env.setdefault('DATUM_URDF_PREFLIGHT', str(source_repo / 'rust/target/debug/studio-urdf-preflight'))
                    sim_worker = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.simulations.worker', '--serve', '--project', str(project), '--spool', str(sim_spool)], start_new_session=True, stdout=log, stderr=log, env=sim_env)
                try:
                    sim_pid.write_text(json.dumps({'pid': sim_worker.pid, 'start': Path(f'/proc/{sim_worker.pid}/stat').read_text().split()[21]}))
                except FileNotFoundError:
                    print('Simulation worker unavailable; see sim-jobs/worker.log.', file=sys.stderr)
            executable = shutil.which("solidcraft-cli")
            if executable and not owned_worker():
                subprocess.run(['cargo', 'build', '--manifest-path', str(source_repo / 'rust/Cargo.toml'), '--bin', 'studio-urdf-preflight'], check=True)
                preflight = source_repo / 'rust/target/debug/studio-urdf-preflight'
                with open(spool / 'worker.log', 'ab', buffering=0) as log:
                    worker = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.urdf_worker', '--serve', '--project', str(project), '--spool', str(spool), '--preflight', str(preflight), '--exporter', executable], start_new_session=True, stdout=log, stderr=log)
                worker_pid.write_text(json.dumps({'pid':worker.pid, 'start':Path(f'/proc/{worker.pid}/stat').read_text().split()[21]}))
            elif not executable:
                print('URDF generation unavailable: install solidcraft-cli on the host.', file=sys.stderr)
            pid_file = preview_dir / "watcher.pid"
            if executable and not pid_file.exists():
                log = open(preview_dir / "watcher.log", "ab", buffering=0)
                child = subprocess.Popen([sys.executable, "-m", "datum_parameter_studio.render_watcher", str(project), str(preview_dir), executable], start_new_session=True, stdout=log, stderr=log)
                pid_file.write_text(str(child.pid))
            command.extend(["--build", "--detach"])
            if args.tailscale:
                tailscale = shutil.which("tailscale")
                if not tailscale:
                    parser.error("Tailscale is not installed on this host.")
                status = json.loads(subprocess.check_output([tailscale, "status", "--json"], text=True))
                hostname = status["Self"]["DNSName"].rstrip(".")
                subprocess.run([tailscale, "serve", "--bg", "--https=8443", f"http://127.0.0.1:{args.port}"], check=True)
                print(f"Datum Studio: https://{hostname}:8443 (available when Compose finishes starting)", flush=True)
        subprocess.run(command, env=env, check=True)
    except BaseException:
        if sim_worker is not None and sim_worker.poll() is None:
            sim_worker.terminate()
            try:
                sim_worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sim_worker.kill()
                sim_worker.wait()
            sim_pid.unlink(missing_ok=True)
        raise
    if args.action == "up" and not args.tailscale:
        print(f"Datum Studio: http://localhost:{args.port}")
    elif args.action == "down":
        sim_owned = owned_sim_worker()
        if sim_owned:
            try: os.kill(sim_owned, signal.SIGTERM)
            except ProcessLookupError: pass
        sim_pid.unlink(missing_ok=True)
        (sim_spool / 'worker.ready').unlink(missing_ok=True)
        pid = owned_worker()
        if pid: os.kill(pid, signal.SIGTERM)
        worker_pid.unlink(missing_ok=True)
        pid_file = preview_dir / "watcher.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
            pid_file.unlink(missing_ok=True)
