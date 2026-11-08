# DParams package usage for coding agents

This guide is for a coding agent adding DParams to a user's robot project. It is
intentionally short: the detailed, version-matched guide is
[`datum_interface/python/datum_interface/AGENT_GUIDE.md`](../datum_interface/python/datum_interface/AGENT_GUIDE.md),
and it also ships with the Python package:

```sh
python -c "from datum_interface import agent_guide; print(agent_guide())"
```

If you are changing DParams itself, use the repository
[`AGENTS.md`](../AGENTS.md) instead.

DParams reads **saved** SolidCraft `.solidcraft` files and extracts **explicit**
dimensions into named values in metres. It does not infer dimensions from
rendered geometry, edit CAD, or run inside the CAD application. A local Studio
is available for visual picking, but the code-first workflow below is complete
without it.

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
from datum_interface import load_runtime

params = load_runtime("PROJECT", worktree="main")
print(params["forearm_length_m"])
```

This path needs only the Python package, the spec and the saved CAD. It needs no
generated artifact, Rust build, Docker, cloud account or Studio.

5. For C++, either generate a C++ header:

```sh
cargo build --manifest-path rust/Cargo.toml --bins
rust/target/debug/datum-params generate \
  PROJECT PROJECT/datum/spec.json main \
  PROJECT/datum/parameters.json PROJECT/datum/parameters.hpp
```

and include `PROJECT/datum/parameters.hpp`. For runtime evaluation, build the
static library with
`cargo build --release --manifest-path rust/Cargo.toml --lib`, then link
`rust/include/dparams_runtime.h` plus
`rust/target/release/libdatum_params_tools.a` and evaluate at startup. The
detailed guide has complete snippets for both.

## Choose the mode deliberately

| Need | Mode | Runtime check |
|---|---|---|
| Python iteration, no generated files | `load_runtime(PROJECT)` | Spec and CAD read at startup |
| Reviewed generated artifact | `load_generated(PROJECT/datum/parameters.json)` | Spec and CAD SHA-256 checked |
| C++ generated constants | generated `parameters.hpp` | None; rebuild after changes |
| C++ startup evaluation | C ABI static library | Spec and CAD read at startup |

Generated headers are copied into the binary and are not runtime-checked.
Runtime values are startup snapshots; generated constants are baked into the
binary at build time. Neither tracks CAD or spec changes continuously.

## Studio is optional

Studio (`dparam-std up --source-repo "$PWD" --project PROJECT`) is a local
browser UI for picking dimensions, naming parameters, reviewing CAD changes and
downloading generated files. It is useful when a human wants to choose
dimensions visually. It is not required for integration, and its spec editor
only emits `parameters` mappings. Constants, derived values, bounds, groups and
extra hashed sources must be added by editing `spec.json`.

## Failure behavior to preserve

The loaders raise or report errors instead of returning stale values:

- changed `spec.json` after generation: regenerate and rebuild;
- changed saved CAD: regenerate and rebuild, or use runtime mode;
- stale pointer: re-inspect `document.json`;
- unit mismatch: correct `source_units`;
- out-of-bounds or non-positive value: fix the CAD or the intended bounds;
- missing worktree or invalid name: correct the spec.

The full error table is in the
[detailed guide](../datum_interface/python/datum_interface/AGENT_GUIDE.md#9-failure-handling).

When handing work back, record the integration mode, the exact values and units,
the consumed spec/source hashes, the validation command, and whether Studio was
used. Do not edit user CAD or bypass spec/source hash checks to make a run pass.
