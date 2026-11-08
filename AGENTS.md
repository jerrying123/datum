# DParams repository guide for coding agents

This file is for agents changing the DParams repository. If you are integrating
DParams into a user's robot project, use
[`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) and the packaged
[detailed guide](datum_interface/python/datum_interface/AGENT_GUIDE.md) instead.

DParams extracts explicit dimensions from saved SolidCraft files into named
values in metres, with generated manifests/headers and runtime evaluation. It
also includes an optional local Studio and URDF helpers.

## Read first

- [`README.md`](README.md) — install paths and user-visible workflows.
- [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) — short package-integration guide.
- [`datum_interface/python/datum_interface/AGENT_GUIDE.md`](datum_interface/python/datum_interface/AGENT_GUIDE.md)
  — detailed, packaged consumer guide. Keep it in sync with public behavior.
- [`docs/AGENT_INTEGRATION_PLAN.md`](docs/AGENT_INTEGRATION_PLAN.md) — design
  history for the agent documentation.

## Repository layout

- `datum_interface/` — Python package, `load_generated`/`load_runtime`, packaged
  agent guide.
- `rust/` — shared evaluation core, `datum-params` generator, C ABI and
  compatibility headers.
- `parameter_studio/` — optional local Studio and URDF helpers.
- `examples/` — C++ and ROS 2 consumers, including generated and runtime modes.
- `benchmarks/` — recorded startup measurements and result files.
- `scripts/` — release and validation helpers.
- `.github/workflows/` — CI, release packaging, and clean-room archive checks.

## Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./datum_interface ./parameter_studio
cargo build --manifest-path rust/Cargo.toml --bins
```

`solidcraft-cli` is required for real CAD rendering/export and the C++ example.
Tests use synthetic CAD or temporary projects; do not depend on a user's CAD.

## Checks before proposing a change

Run the relevant suites from the repository root:

```sh
cargo test --manifest-path rust/Cargo.toml --locked

PYTHONPATH=datum_interface/python python3 -m unittest discover -s datum_interface/tests -v

python3 -m unittest discover -s examples/cpp-pick-place/tests -v

PYTHONPATH=parameter_studio python3 -m unittest discover -s parameter_studio/tests -v
```

For release or version changes, also run:

```sh
python3 scripts/validate_release_tag.py vX.Y.Z
```

CI runs `cpp-demo` and `ros2-cpp-demo`. The C++ suite includes the clean-room
archive test; keep `example/run.sh` and `example/benchmark.py` working from an
extracted release archive without Rust source or Cargo.

## Contribution rules

- Keep Python loading logic under `datum_interface/`, the evaluation core and C
  ABI under `rust/`, Studio/URDF code under `parameter_studio/`, and consumers
  under `examples/`.
- Preserve offline behavior: parameter generation, runtime loading, Studio, and
  URDF export work from saved files and must not require a cloud account or
  network service.
- Use synthetic or temporary CAD in tests. Never edit a user's CAD or a checked
  fixture to make a test pass.
- Do not bypass spec or source hash checks. A stale or changed input must fail
  explicitly instead of returning old values.
- Keep the runtime/generated terminology precise: runtime evaluates the current
  spec and saved CAD; generated refers to manifest/header artifacts.
- When changing a public API or schema, update the packaged guide, README,
  examples, benchmarks, and compatibility aliases or shims together.
- Do not claim PyPI or native release artifacts are available unless the release
  actually exists.
- Add deterministic checks for recurring failure modes. Prefer tests over prose
  when a contract can be exercised.
- Keep `AGENTS.md` repository-focused and `docs/AGENT_USAGE.md` consumer-focused;
  do not merge the two again.

## Documentation map

- Contributors and coding agents changing this repository: this file.
- Agents integrating DParams into another project:
  [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md).
- Detailed package behavior and error handling: packaged
  [`AGENT_GUIDE.md`](datum_interface/python/datum_interface/AGENT_GUIDE.md).
- Install, release, and product overview: [`README.md`](README.md).
- Measured performance and reproduction: [`BENCHMARKS.md`](BENCHMARKS.md).
