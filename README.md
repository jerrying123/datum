# Datum Parameters

DParams extracts explicit SolidCraft dimensions into a hash-checked JSON manifest and C++ header. The local Studio provides a mobile-friendly CAD viewer, parameter picker, and experimental URDF export/checking. It works on saved files without a Datum repository, account or cloud service.

## Install

You can install the Python runtime library via `pip`, download precompiled native CLI and C++ static library archives from GitHub Releases without cloning the repository, or build everything from a source checkout.

### Python runtime package (pip)

The Python runtime loader (`datum_interface`) is published on PyPI as `datum-cad-parameters` (requires Python 3.10+):

```sh
pip install datum-cad-parameters
```

This provides the `datum_interface` package (`load_generated` and `load_runtime`) for consuming generated manifests or evaluating saved CAD at runtime in Python without compiling Rust or cloning the repository. The early `load` and `load_lazy` names remain as deprecated aliases.

### Native CLI & C++ static library (GitHub Release archive)

Precompiled native bundles are published on [GitHub Releases](https://github.com/marker-labs/datum-params/releases) for Linux x86-64 (`datum-params-linux-x86_64.zip`), macOS Apple Silicon (`datum-params-macos-aarch64.zip`), macOS Intel (`datum-params-macos-x86_64.zip`), and Windows x86-64 (`datum-params-windows-x86_64.zip`).

Download and unzip the archive for your platform without cloning the repository:

```sh
unzip datum-params-linux-x86_64.zip
cd dparams
```

The self-contained archive includes:
- `datum-params` (or `datum-params.exe` on Windows): standalone CLI executable to extract JSON manifests and C++ headers. You can move it to `/usr/local/bin` or place it on your `PATH`.
- `include/dparams_runtime.h`: C ABI / C++ header for runtime CAD evaluation. The legacy `include/dparams_lazy.h` compatibility header is also included.
- `libdatum_params_tools.a` (or `datum_params_tools.lib` on Windows): precompiled static library.
- `example/`: bundled C++ kinematic pick-and-place comparison example that runs directly from the archive without Rust or Cargo.

To compile your own C++ code against the bundled library and header without Rust:

```sh
c++ -std=c++17 -I include my_app.cpp libdatum_params_tools.a -lpthread -ldl -o my_app
```

To run the bundled C++ example from the extracted archive (requires a C++17 compiler, `sha256sum`, and `solidcraft-cli` on `PATH`):

```sh
example/run.sh /tmp/dparams-cpp-pick-place
```

### Developer install from clone (including Parameter Studio)

Developing the Rust generator, modifying Parameter Studio, or running from source requires Python 3.10+, Rust/Cargo, Docker Compose, and a host installation of `solidcraft-cli` for CAD rendering and URDF export:

```sh
git clone https://github.com/marker-labs/datum-params.git
cd datum-params
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./datum_interface ./parameter_studio
cargo build --manifest-path rust/Cargo.toml --bins
cargo install --path rust --bin datum-params --locked  # alternative developer install
dparam-std up --source-repo "$PWD" --project /path/to/your/cad/project
```

Open http://localhost:8000. For a phone on your Tailscale network add `--tailscale` and use the URL printed by the launcher. Studio runs in the foreground; use another terminal for other commands. See [Studio instructions](parameter_studio/README.md).

## Agent integration

Coding agents integrating DParams into another project should start with the
short [package usage guide](docs/AGENT_USAGE.md) and the detailed, packaged
[agent integration guide](datum_interface/python/datum_interface/AGENT_GUIDE.md).
The guide covers the direct `datum/spec.json` path, both Python modes, generated
and runtime C++, and the optional Studio workflow. After installation the same
guide is available from the package:

```sh
python -c "from datum_interface import agent_guide; print(agent_guide())"
```

Studio is optional for these integrations; the spec can be authored directly.

The API has two modes. Generated mode reads `PROJECT/datum/parameters.json`, which sits beside `PROJECT/datum/spec.json`:

```python
from datum_interface import load_generated
params = load_generated('PROJECT/datum/parameters.json', worktree='main')
print(params['forearm_length_m'])
```

It verifies the spec and saved CAD hashes: keep the exact downloaded spec beside the manifest. Runtime mode gives the same Parameters object without any generated artifacts by evaluating the spec and saved CAD eagerly at startup. A failed evaluation raises instead of returning values, so a run cannot fall back to an earlier evaluation; concurrent edits during evaluation are detected by the source-hash check, not blocked, and a process keeps the values it read at startup:

```python
from datum_interface import load_runtime
params = load_runtime('PROJECT', worktree='main')              # no parameters.json needed
params = load_runtime('PROJECT', evidence='evidence/runtime.json')  # machine-readable record
```

The C++ side has the same choice: include a generated `parameters.hpp`, or include `rust/include/dparams_runtime.h` (or `include/dparams_runtime.h` in the release archive) and link the `libdatum_params_tools` static library and read the values at startup. The Rust generator and C ABI share one evaluation core; the Python loader is a separate implementation kept in step by cross-mode conformance tests. Snapshot-based generation belongs to the optional Datum integration and is not implemented in this standalone package.

Early 0.1.0 `load_lazy` and `dparams_lazy_*` names remain as deprecated compatibility aliases; new code should use the runtime names.

## URDF export modes

The URDF exists only because most robotics and simulation systems cannot load the saved CAD natively. Studio exports it on demand from the saved sources (**Generate and check**); the result is written to a scratch directory you download, never to the project. For a runtime bring-up without the checked-in file, `datum_parameter_studio.runtime_urdf` runs the same capture preflight and structural checker in-process, validates the output bundle for symlinks, containment and size, and hands back the URDF text plus its export bundle:

```python
from datum_parameter_studio.runtime_urdf import bring_up_urdf
with bring_up_urdf('PROJECT', 'cad/arm_concept.solidcraft') as result:
    robot_description = result.text      # URDF text exported from the live sources
    result.write_bundle('runtime/robot') # URDF + meshes + STEP files, self-contained
```

Or stream it to stdout for a launch pipeline (add `--bundle-out DIR` for the geometry):

```sh
python -m datum_parameter_studio.runtime_urdf --project PROJECT --assembly cad/arm_concept.solidcraft
```

Export runs against the saved CAD at evaluation time and is stamped with the source hashes and a freshness result; there is no committed URDF file to go stale. The bundle holds the exporter's current output for the captured inputs: every URDF-referenced STL (the structural check requires those meshes to resolve inside the bundle), a whole-assembly STEP on request from the exporter, and the content-addressed per-part STEP blobs embedded in the saved files, extracted with a SHA-256 name verification before each write. The report's `geometry` section records all of it with hashes. Exporter provenance and fidelity to native CAD geometry are not verified, per-part STEP blobs are not mapped to URDF links, and this path has no cancellation channel or worker heartbeat. Export still requires the installed SolidCraft CLI and accepts the same limited SolidCraft/34 profile as the Studio spool; physics readiness and source-to-URDF equivalence are not verified.

## C++ example

The [ROS 2 C++ pick-and-place example](examples/ros2_cpp_pick_place/README.md) uses generated dimensions with an `rclcpp` controller and action-based motor simulator. The companion [standalone C++ comparison](examples/cpp-pick-place/README.md) contrasts stale and current dimensions against the same kinematic arm, in a generated-header mode and a runtime mode that reads the CAD at startup with no generated files. It is bundled in the native release archive as `example/` and runs with the precompiled CLI and static library without Rust or Cargo.

## Performance

See [BENCHMARKS.md](BENCHMARKS.md) for startup measurements, their scope, and reproduction commands.

## Contributing

Agents modifying this repository should start with [AGENTS.md](AGENTS.md). It
covers the repository layout, required checks, and contribution rules. If you
are integrating DParams into another project, use the
[package usage guide](docs/AGENT_USAGE.md) instead.

## Scope

The URDF preview/export requires a separately installed SolidCraft CLI. The initial validator accepts a limited SolidCraft/34 assembly profile; coupling, transform equivalence, physical mass properties, and simulation or hardware readiness are not certified. A structural pass is not a fidelity or safety guarantee. Consult the Studio guide before using a generated file.

Licensed under Apache-2.0. The SolidCraft executable is a separate dependency and is not included.
