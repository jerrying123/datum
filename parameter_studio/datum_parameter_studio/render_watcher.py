"""Render changed SolidCraft documents with the host SolidCraft CLI."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


def main():
    root, cache, executable = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
    cache.mkdir(parents=True, exist_ok=True)
    state = {}
    while True:
        for cad in list(root.rglob("*.solidcraft")) + list(root.rglob("*.sc")):
            if any(part.startswith(".") or part in {"target", "node_modules"} for part in cad.relative_to(root).parts):
                continue
            try:
                digest = hashlib.sha256(cad.read_bytes()).hexdigest()
                if state.get(cad) == digest:
                    continue
                rel = cad.relative_to(root).as_posix()
                preview_id = hashlib.sha256(rel.encode()).hexdigest()
                rev_file = cache / f"{preview_id}.rev"
                rev_file.unlink(missing_ok=True)
                out = cache / f"{preview_id}.png"
                with tempfile.NamedTemporaryFile(dir=cache, suffix=".png", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    env = dict(os.environ, SOLIDCRAFT_GPU="cpu")
                    result = subprocess.run([executable, "snapshot", str(cad), "--out", str(tmp_path), "--width", "1000", "--height", "620", "--view", "iso"], env=env, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    image_ok = result.returncode == 0 and tmp_path.stat().st_size > 0
                    if image_ok:
                        tmp_path.replace(out)
                    meta_tmp = cache / f"{preview_id}.json.tmp"
                    meta_out = cache / f"{preview_id}.json"
                    meta_result = subprocess.run([executable, "eval", str(cad), "--json-out", str(meta_tmp)], env=env, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if meta_result.returncode == 0 and meta_tmp.exists():
                        meta_tmp.replace(meta_out)
                        mesh_tmp = cache / f"{preview_id}.3mf.tmp"
                        mesh_out = cache / f"{preview_id}.3mf"
                        script = cache / f"{preview_id}-export.json"
                        script.write_text(json.dumps({"commands": [{"command": "file.export", "params": {"path": str(mesh_tmp), "format": "3mf-tagged"}}]}))
                        mesh_result = subprocess.run([executable, "run", str(script), "--in", str(cad), "--quiet"], env=env, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        script.unlink(missing_ok=True)
                        if mesh_result.returncode == 0 and mesh_tmp.exists() and mesh_tmp.stat().st_size > 100:
                            mesh_tmp.replace(mesh_out)
                            if image_ok:
                                rev_tmp = cache / f"{preview_id}.rev.tmp"
                                rev_tmp.write_text(digest)
                                rev_tmp.replace(rev_file)
                                state[cad] = digest
                        else:
                            mesh_tmp.unlink(missing_ok=True)
                    else:
                        meta_tmp.unlink(missing_ok=True)
                finally:
                    tmp_path.unlink(missing_ok=True)
            except (OSError, subprocess.TimeoutExpired, zipfile.BadZipFile):
                continue
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C is a normal way to stop a manually launched watcher. The
        # launcher normally manages it with SIGTERM; suppress the traceback
        # when a developer runs this module directly in a terminal.
        pass
