# Agent guide for Datum Parameters

DParams turns explicit dimensions from saved SolidCraft files into named values
in metres. This file is the entry point for agents. The detailed version-matched
guide is
[`datum_interface/python/datum_interface/AGENT_GUIDE.md`](datum_interface/python/datum_interface/AGENT_GUIDE.md).
It also ships with the Python package:

```sh
python -c "from datum_interface import agent_guide; print(agent_guide())"
```

## Fastest integration path

1. Find the project root and the saved `.solidcraft` sources.
2. Inspect each source's `document.json` read-only and pick an explicit
   dimension, for example `/features/0/length`.
3. Write `PROJECT/datum/spec.json` directly. A complete minimal spec:

```json
{
  "schema": "datum.robot.parameter-spec/2",
  "units": "m",
  "worktrees": {
    "main": {
      "parameters": {
        "forearm_length_m": {
          "path": "cad/arm.solidcraft",
          "pointer": "/features/0/length",
          "source_units": "mm",
          "unit": "m"
        }
      }
    }
  }
}
```

4. For Python, read the spec and saved CAD at startup:

```python
from datum_interface import load_lazy

params = load_lazy("PROJECT", worktree="main")
print(params["forearm_length_m"])
```

This path needs only the Python package, the spec and the saved CAD. It needs no
generated artifact, Rust build, Docker, cloud account or Studio.

5. For C++, either generate a compile-time header:

```sh
cargo build --manifest-path rust/Cargo.toml --bins
rust/target/debug/datum-params generate \
  PROJECT PROJECT/datum/spec.json main \
  PROJECT/datum/parameters.json PROJECT/datum/parameters.hpp
```

and include `PROJECT/datum/parameters.hpp`, or link the lazy static library
(`rust/include/dparams_lazy.h` plus `rust/target/release/libdatum_params_tools.a`)
and evaluate at startup. The guide has complete snippets for both.

## Choose the mode deliberately

| Need | Mode | Runtime check |
|---|---|---|
| Python iteration, no generated files | `load_lazy(PROJECT)` | Spec and CAD read at startup |
| Reviewed generated artifact | `load(PROJECT/datum/parameters.json)` | Spec and CAD SHA-256 checked |
| C++ compile-time constants | generated `parameters.hpp` | None; rebuild after changes |
| C++ startup evaluation | C ABI static library | Spec and CAD read at startup |

Compiled headers are copied into the binary and are not runtime-checked.
Lazy and generated values are startup snapshots, not continuous tracking.

## Studio is optional

Studio (`dparam-std up --source-repo "$PWD" --project PROJECT`) is a local
browser UI for picking dimensions, naming parameters, reviewing CAD changes and
downloading generated files. It is useful when a human wants to choose
dimensions visually. It is not required for integration, and its spec editor
only emits `parameters` mappings. Constants, derived values, bounds, groups and
extra hashed sources must be added by editing `spec.json`.

## Repository layout

- `datum_interface/` — Python runtime package, `load`, `load_lazy`, packaged guide
- `rust/` — shared evaluation core, `datum-params` generator, C ABI
- `parameter_studio/` — optional local Studio and URDF helpers
- `examples/` — C++ and ROS 2 consumers, including compiled versus lazy modes
- `benchmarks/` — recorded startup measurements

## Checks before proposing a change

```sh
cargo test --manifest-path rust/Cargo.toml --locked
PYTHONPATH=datum_interface/python python3 -m unittest discover -s datum_interface/tests -v
python3 -m unittest discover -s examples/cpp-pick-place/tests -v
PYTHONPATH=parameter_studio python3 -m unittest discover -s parameter_studio/tests -v
```

Use synthetic or temporary CAD in tests. Do not edit a user's CAD or bypass
spec/source hash checks to make a test pass. Do not claim PyPI or native release
artifacts are available unless they are actually published.

## Failure behavior to preserve

The loaders raise or report errors instead of returning stale values:

- changed `spec.json` after generation: regenerate and rebuild;
- changed saved CAD: regenerate and rebuild, or use lazy mode;
- stale pointer: re-inspect `document.json`;
- unit mismatch: correct `source_units`;
- out-of-bounds or non-positive value: fix the CAD or the intended bounds;
- missing worktree or invalid name: correct the spec.

The full error table is in the
[detailed guide](datum_interface/python/datum_interface/AGENT_GUIDE.md#9-failure-handling).
