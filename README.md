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

The runtime API has two modes. Compiled mode loads a generated file at `PROJECT/datum/parameters.json`, alongside `PROJECT/datum/spec.json`:

```python
from datum_interface import load
params = load('PROJECT/datum/parameters.json', worktree='main')
print(params['forearm_length_m'])
```

It verifies the spec and saved CAD hashes: keep the exact downloaded spec beside the manifest. Lazy mode gives the same Parameters object without any generated artifacts by evaluating the spec against the saved CAD at startup, so values cannot silently drift from the CAD; any missing field, unit mismatch or out-of-bounds dimension fails fast instead:

```python
from datum_interface import load_lazy
params = load_lazy('PROJECT', worktree='main')            # no parameters.json needed
params = load_lazy('PROJECT', evidence='evidence/lazy.json')  # machine-readable record
```

The C++ side has the same choice: link the compiled constants from a generated `parameters.hpp`, or link `rust/include/dparams_lazy.h` (the shared Rust evaluation core as a static library) and read the values at startup. Snapshot-based generation belongs to the optional Datum integration and is not implemented in this standalone package.

## URDF export modes

The URDF exists only because most robotics and simulation systems cannot load the saved CAD natively. Studio exports it on demand from the saved sources (**Generate and check**); the result is written to a scratch directory you download, never to the project. For a runtime bring-up without the checked-in file, `datum_parameter_studio.lazy_urdf` runs the same capture, export and structural check in-process and hands back the URDF text:

```python
from datum_parameter_studio.lazy_urdf import bring_up_urdf
result = bring_up_urdf('PROJECT', 'cad/arm_concept.solidcraft')
robot_description = result.text          # URDF text exported from the live sources
```

Or stream it to stdout for a launch pipeline:

```sh
python -m datum_parameter_studio.lazy_urdf --project PROJECT --assembly cad/arm_concept.solidcraft
```

Export runs against the saved CAD at evaluation time and is stamped with the source hashes and a freshness result; there is no committed URDF file to go stale, and neither is there for geometry. The bundle also gets every URDF-referenced STL exported from the captured sources at the same moment (the structural check requires those meshes to resolve inside the bundle), a whole-assembly STEP on request from the exporter, and the content-addressed per-part STEP blobs embedded in the saved files, extracted with a SHA-256 name verification before each write. The report's `geometry` section records all of it with hashes. Export still requires the installed SolidCraft CLI, accepts the same limited SolidCraft/34 profile as the Studio spool, and does not verify physics readiness or source-to-URDF fidelity; per-part STEP blobs are not mapped to URDF links, a correspondence that is not established here.

## C++ example

The [ROS 2 C++ pick-and-place example](examples/ros2_cpp_pick_place/README.md) uses generated dimensions with an `rclcpp` controller and action-based motor simulator. The companion [standalone C++ comparison](examples/cpp-pick-place/README.md) contrasts stale and current dimensions against the same kinematic arm, in a compiled-header mode and a lazy mode that reads the CAD at startup with no generated files.

## Scope

The URDF preview/export requires a separately installed SolidCraft CLI. The initial validator accepts a limited SolidCraft/34 assembly profile; coupling, transform equivalence, physical mass properties, and simulation or hardware readiness are not certified. A structural pass is not a fidelity or safety guarantee. Consult the Studio guide before using a generated file.

Licensed under Apache-2.0. The SolidCraft executable is a separate dependency and is not included.
