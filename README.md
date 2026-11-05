# Datum Parameters

DParams extracts explicit SolidCraft dimensions into a hash-checked JSON manifest and C++ header. The local Studio provides a mobile-friendly CAD viewer, parameter picker, and experimental URDF export/checking. It works on saved files without a Datum repository, account or cloud service.

## Install

Requires Python 3.10+, Rust/Cargo, Docker Compose and a host installation of `solidcraft-cli` for CAD rendering and URDF export. From a clone:

```sh
git clone https://github.com/marker-labs/datum-params.git
cd datum-params
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./datum_interface ./parameter_studio
cargo build --manifest-path rust/Cargo.toml --bins
cargo install --path rust --bin datum-params --locked
dparam-std up --source-repo "$PWD" --project /path/to/your/cad/project
```

Open http://localhost:8000. For a phone on your Tailscale network add `--tailscale` and use the URL printed by the launcher. Studio runs in the foreground; use another terminal for other commands. See [Studio instructions](parameter_studio/README.md).

The runtime API loads a generated file at `PROJECT/datum/parameters.json`, alongside `PROJECT/datum/spec.json`:

```python
from datum_interface import load
params = load('PROJECT/datum/parameters.json', worktree='main')
print(params['forearm_length_m'])
```

It verifies the spec and saved CAD hashes. Keep the exact downloaded spec beside the manifest. Snapshot-based generation belongs to the optional Datum integration and is not implemented in this standalone package.

## C++ example

The [C++ pick-and-place example](examples/cpp-pick-place/README.md) generates headers from baseline and changed CAD, then compares the same changed arm with stale and current controller dimensions. It is a kinematic demonstration and requires no ROS.

## Scope

The URDF preview/export requires a separately installed SolidCraft CLI. The initial validator accepts a limited SolidCraft/34 assembly profile; coupling, transform equivalence, physical mass properties, and simulation or hardware readiness are not certified. A structural pass is not a fidelity or safety guarantee. Consult the Studio guide before using a generated file.

Licensed under Apache-2.0. The SolidCraft executable is a separate dependency and is not included.
