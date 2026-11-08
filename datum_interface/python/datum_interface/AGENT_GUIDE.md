# DParams agent integration guide

This guide is for a coding agent adding CAD-derived parameters to a user's
robot project. It matches DParams 0.1.0. If the code and this guide disagree,
the code is authoritative; report the mismatch instead of inventing behavior.

DParams reads **saved** SolidCraft `.solidcraft` files and extracts **explicit**
dimensions into named values in metres. It does not infer dimensions from
rendered geometry, does not edit CAD, and does not run inside the CAD
application. A local Studio is available for visual picking, but the code-first
workflow below is complete without it.

## 1. Pick the shortest supported path

| Need | Use | Requires |
|---|---|---|
| Python values now, no generated files | `datum_interface.load_runtime(PROJECT)` | Python package, `datum/spec.json`, saved CAD |
| Python with a reviewed/committed artifact | `datum_interface.load_generated(PROJECT/datum/parameters.json)` | Python package, generator, spec, saved CAD |
| C++17 generated constants | generated `parameters.hpp` | generator |
| C++17 values read at startup with no generated files | `dparams_runtime.h` plus the static library | Rust toolchain to build the library |
| ROS 2 parameters | Python loader plus `ros_parameters()` / `ros_yaml()` | Python package |
| URDF export | Studio or `datum_parameter_studio.runtime_urdf` | SolidCraft CLI; Docker only for Studio |

Start with `load_runtime` unless the user explicitly wants generated artifacts
checked into the project or has a build step that needs generated constants.
Do **not** start Studio just to do a code integration. Studio is for the user to
pick dimensions visually; the same spec can be written directly.

## 2. Inspect the project before writing anything

Resolve these facts first:

1. **Project root** — the directory that will contain `datum/`.
2. **Saved sources** — paths to `.solidcraft` files, relative to the project
   root. They must already be saved; DParams does not read unsaved editor state.
3. **Runtime values** — the exact names and units the application needs.
4. **Worktree key** — a spec key such as `main`. This is **not** a Git worktree.
5. **Units** — the document unit recorded in `document.json` and the canonical
   output unit. Output units are currently always metres (`m`).

Inspect a saved source read-only:

```sh
python -c "import json,zipfile; z=zipfile.ZipFile('PROJECT/cad/arm.solidcraft'); print(json.dumps(json.load(z.open('document.json')), indent=2))"
```

The file is a ZIP archive with a `document.json` entry. Use a JSON Pointer
(RFC 6901) to name one dimension, for example `/features/0/length`. Verify that
the pointer resolves against the actual saved file before putting it in a spec.
If a feature array is edited, its indexes can change; re-check the pointer and
regenerate. Choosing from Studio avoids most pointer mistakes, but is optional.

## 3. Write `PROJECT/datum/spec.json`

This is the fastest code-first path. A complete spec needs only a schema, the
canonical unit, and one worktree:

<!-- quickstart-spec -->
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
          "unit": "m",
          "min": 100,
          "max": 200
        }
      },
      "constants": {
        "shoulder_height_m": {
          "value": 0.11,
          "unit": "m",
          "min": 0.05,
          "max": 0.2
        }
      },
      "derived": {
        "reach_m": {
          "operation": "sum",
          "inputs": ["forearm_length_m", "shoulder_height_m"],
          "unit": "m"
        }
      },
      "groups": {
        "arm": ["forearm_length_m", "reach_m"]
      }
    }
  }
}
```
<!-- /quickstart-spec -->

For the example above, `cad/arm.solidcraft` contains a document with
`"units": "mm"` and a length of `160` at `/features/0/length`, so
`forearm_length_m` is `0.16`, `reach_m` is `0.27`, and `params.group("arm")`
returns both values.

### Parameter mappings

Each entry in `parameters` names one runtime value:

| Field | Meaning |
|---|---|
| `path` | Source path relative to the project root; must stay inside the project |
| `pointer` | JSON Pointer into the source `document.json` |
| `source_units` | Unit recorded by the source document: `mm`, `cm`, `m`, `in` or `ft` |
| `unit` | Output unit; currently `m` |
| `min`, `max` | Optional bounds in **source units**; checked after conversion |

A pointed-to value may be:

- a JSON number;
- a string containing a number with an optional unit, such as `"160 mm"` or
  `"0.16 m"`;
- the name of a parameter in the document's `params` array, provided that
  parameter's `expr` is itself a number with an optional unit.

General CAD expressions, formulas and chained references such as `160 * 2` are
not supported. A named `params` entry is usable only when its `expr` is a
numeric literal with an optional unit. Put arithmetic in a DParams `derived`
value instead.

### Constants, derived values and groups

- `constants` are named values defined in the spec. `value` and any `min`/`max`
  are in metres.
- `derived` values combine existing names with exactly one operation:
  `sum`, `product`, `min`, `max`, `difference` (two inputs) or `ratio` (two
  inputs). `unit` must be `m`. Definitions are evaluated in **sorted name
  order**, so an input must be a parameter, constant or earlier derived name.
- `groups` are named lists of existing parameter names. They are useful for
  `params.group("arm")` and ROS organisation; they do not affect evaluation.
- Optional `sources` at the spec or worktree level list extra paths to hash even
  when no parameter points at them. Their bytes are hashed, but they are not
  parsed for dimensions.

Metadata keys outside the reserved fields are copied into the manifest
`metadata` object.

### Rules that commonly break generation

- `schema` must be `datum.robot.parameter-spec/2`; `units` must be `m`.
- Names must not start with a digit and may contain only `a-z`, `0-9` and `_`.
  Use lowercase snake_case; Studio enforces a leading lowercase letter.
- Every parameter, constant and derived value must be greater than zero unless
  its `min` is `0` or less. A negative `difference` therefore needs an explicit
  non-positive `min`.
- `source_units` must equal the document's own `units`, or evaluation stops with
  `units mismatch`.
- A source path must be relative, must not contain `.` or `..`, and must resolve
  inside the project root.
- Values and bounds must be finite.

## 4. Generated mode: write and consume artifacts

Create this layout, keeping the spec and the manifest together:

```text
PROJECT/
  cad/
    arm.solidcraft
  datum/
    spec.json
    parameters.json      # generated
    parameters.hpp       # generated
```

Generate from a clone of this repository:

```sh
cargo build --manifest-path rust/Cargo.toml --bins
rust/target/debug/datum-params generate \
  PROJECT PROJECT/datum/spec.json main \
  PROJECT/datum/parameters.json PROJECT/datum/parameters.hpp
```

Or install the CLI once and use it directly:

```sh
cargo install --path rust --bin datum-params --locked
datum-params generate PROJECT PROJECT/datum/spec.json main \
  PROJECT/datum/parameters.json PROJECT/datum/parameters.hpp
```

The command reads the spec and CAD, then writes the checked JSON manifest and a
C++ header. If evaluation fails it exits non-zero and writes no new artifacts;
an older manifest may still be present, so treat a non-zero exit as a build
failure rather than consuming the previous file. The command does **not** watch
for later changes. Add it to the project's build or regeneration step and
rebuild C++ consumers whenever it runs.

### Python: checked manifest

```python
from datum_interface import load_generated

params = load_generated("PROJECT/datum/parameters.json", worktree="main")
print(params["forearm_length_m"])   # 0.16
print(params["reach_m"])            # 0.27
print(params.group("arm"))
```

`load_generated()` resolves the project root as the parent of `datum/`, so the manifest
must be at `PROJECT/datum/parameters.json`. It checks:

- the schema and canonical units;
- that `spec.json` beside the manifest still has the recorded SHA-256;
- that every referenced CAD source still has the recorded SHA-256;
- that every value is finite, positive where required, and within bounds;
- that the requested worktree matches the manifest.

A failure raises `ValueError`; do not catch it and continue with old values.

### C++: generated header

The header defines one namespace per worktree:

```cpp
#include "parameters.hpp"

double reach() {
    return datum::robot::main::reach_m;
}
```

Compile with the directory that contains the header on the include path:

```sh
c++ -std=c++17 -I PROJECT/datum controller.cpp -o controller
```

The header contains `inline constexpr double` values. It performs **no** runtime
CAD or spec hash checks; it is a build artifact. Regenerate it and rebuild after
CAD or spec changes. Values are copied at process start and do not update while
the process runs.

## 5. Runtime mode: read spec and CAD at startup

Runtime mode removes the need for generated artifacts. The trade-off is startup
parsing of the spec and CAD; the benefit is that a changed CAD file is either
read fresh or rejected by validation, never served from an old manifest.

### Python

```python
from datum_interface import load_runtime

params = load_runtime("PROJECT", worktree="main")
print(params["forearm_length_m"])

# Optional machine-readable record of the exact evaluation.
params = load_runtime("PROJECT", evidence="evidence/runtime.json")
```

`load_runtime()` needs only `PROJECT/datum/spec.json` and the saved CAD. It uses the
same value contract as `load_generated()` and raises `ValueError` on any failure. It reads
the sources again after evaluation to detect a file that changed mid-read. The
`evidence` path is resolved from the process working directory, not from the
project root.

`load_lazy` and the `dparams_lazy_*` C symbols remain as deprecated
aliases for early 0.1.0 callers; new code should use the runtime names.

### C++ and other FFI consumers

Build the static library and use the C ABI header:

```sh
cargo build --release --manifest-path rust/Cargo.toml --lib
```

Header: `rust/include/dparams_runtime.h`.
Library: `rust/target/release/libdatum_params_tools.a`.

```cpp
#include "dparams_runtime.h"
#include <cstdio>

int main(int argc, char** argv) {
    if (argc != 3) return 2;

    if (dparams_runtime_eval(argv[1], argv[2], "main") != 0) {
        char error[512] = {0};
        if (dparams_runtime_error(error, sizeof error) != 0) {
            std::snprintf(error, sizeof error, "Datum evaluation failed");
        }
        std::fprintf(stderr, "%s\n", error);
        return 1;
    }

    double reach = 0.0;
    if (dparams_runtime_get("reach_m", &reach) != 0) return 3;
    std::printf("%.6f\n", reach);

    dparams_runtime_release();
    return 0;
}
```

```sh
c++ -std=c++17 -I rust/include runtime.cpp -o runtime \
  -L rust/target/release -ldatum_params_tools -lpthread -ldl
./runtime PROJECT PROJECT/datum/spec.json
```

The spec path is read exactly as passed, relative to the process working
directory (or absolute), not relative to the project argument. The session and
error slots are process-global; call the C ABI from one thread at a time and
use one active session. A failed evaluation clears the session, so a caller
cannot fall back to earlier values. Call `dparams_runtime_evidence(PATH)` after a
successful evaluation to write the same record as the Python `evidence` option.

### Runtime behavior to tell the user

- This is a **startup snapshot**, not continuous tracking. Once evaluation
  returns, the process keeps the doubles it read.
- A failed evaluation raises (Python) or clears the session and records an error
  (C ABI); it never silently returns stale values.
- Changing a file during evaluation is detected by the source-hash check.
- Concurrent edits are not blocked; they are detected.

## 6. ROS 2

The Python object exposes the two shapes `rclpy` commonly needs:

```python
from datum_interface import load_runtime

params = load_runtime("PROJECT", worktree="main")

node = Node("arm_controller", parameters=[params.ros_parameters()])
yaml_mapping = params.ros_yaml("arm_controller")
```

`ros_parameters()` returns a flat `dict[str, float]`. `ros_yaml()` returns
`{"arm_controller": {"ros__parameters": {...}}}` for a ROS parameter file; the
node name must be a non-empty string.

See `examples/ros2_cpp_pick_place/README.md` for a C++ ROS 2 consumer.

## 7. Optional Studio workflow

Studio is a local browser interface for choosing dimensions and generating the
same files. It is optional and does not replace the spec rules above.

From a clone:

```sh
python -m pip install ./datum_interface ./parameter_studio
cargo install --path rust --bin datum-params --locked
dparam-std up --source-repo "$PWD" --project /path/to/your/cad/project
```

Open <http://localhost:8000>. The project folder is mounted read-only. The host
preview and URDF workers need `solidcraft-cli`; the first container build also
compiles the Rust generator.

Workflow:

1. **Parts** — choose a SolidCraft document and select a part or assembly.
2. **Dimensions** — choose a feature or sketch and select a supported input.
   Viewport body selection identifies a part, not the dimension that controls it.
3. **Code parameters** — name the parameter, choose the worktree and canonical
   output unit, and remove mappings that are not needed. The spec preview updates
   live.
4. **Generate** — **Download spec.json**, or **Generate manifest & header** and
   download `parameters.json` and `parameters.hpp`.

If linked CAD changes while Studio is open, **Live change review** shows the
before/after fields; acknowledge the change and regenerate. The downloads are
written to the browser's device, not the project folder. Place `spec.json` and
`parameters.json` together under `PROJECT/datum/`, and place `parameters.hpp`
where the C++ build expects it.

### What Studio can and cannot customise

Studio can choose the mapped dimensions, parameter names, worktree key, output
unit (currently `m`), and which mappings to keep. It generates only
`parameters` mappings.

Studio does **not** expose constants, derived values, bounds, groups, extra
hashed sources, or more than one worktree at a time in the spec editor. Add
those by editing `spec.json` directly, or start from a hand-written spec. Do not
claim that a Studio download contains features it does not emit.

## 8. Optional URDF export

URDF export is separate from parameter extraction and is not required to
integrate parameters. It requires a separately installed `solidcraft-cli` and
accepts a limited SolidCraft/34 assembly profile. Use the Studio **Export URDF**
panel or the scriptable `datum_parameter_studio.runtime_urdf` path documented in
the repository README and `parameter_studio/README.md`. A structural pass is not
a fidelity, physics-readiness or safety guarantee. Export does not make URDF
generation a prerequisite for `load_generated()` or `load_runtime()`.

## 9. Failure handling

| Error text (abridged) | Likely cause | Correct action |
|---|---|---|
| `Datum parameter specification changed; regenerate parameters and rebuild` | `spec.json` changed after generation | Regenerate the manifest/header, rebuild C++ |
| `Datum CAD source changed: ...; regenerate parameters and rebuild` | Saved CAD changed after generation | Regenerate the manifest/header, rebuild C++ |
| `... has no feature/dimension at /...` | Pointer stale or wrong | Re-inspect `document.json` and correct the pointer |
| `units mismatch: ...` | `source_units` does not match the document | Correct `source_units` |
| `... is outside allowed bounds [...]` | CAD value outside `min`/`max` | Fix the CAD or the intended bounds; do not widen bounds just to hide a mistake |
| `invalid non-positive Datum parameter ...` | Value is `<= 0` without a non-positive `min` | Fix the value, or set a deliberate non-positive bound if negative is valid |
| `worktree '...' is not defined in the spec` | Wrong worktree key | Use a key that exists in `worktrees` |
| `invalid parameter name ...` | Uppercase, leading digit or unsupported character | Rename to lowercase snake_case |
| `unsupported SolidCraft expression ...` | Expression is not a numeric literal | Put arithmetic in a `derived` value |
| `source escapes project` / `invalid source path` | Absolute path, `..`, or a symlink leaving the project | Use a relative path inside the project |
| `source changed during evaluation` | CAD changed while it was being read | Retry once the file is stable |

Never silence these errors by editing `parameters.json`, deleting hash checks,
or editing the user's CAD. Regenerate from the spec and saved sources.

## 10. Verify before handing back

Run the check that matches the chosen mode, on synthetic or temporary data when
possible:

```sh
# Runtime Python path
python -c "from datum_interface import load_runtime; p=load_runtime('PROJECT'); print(p.manifest['worktree'], p['forearm_length_m'], p['reach_m'])"

# Generated Python path
python -c "from datum_interface import load_generated; p=load_generated('PROJECT/datum/parameters.json', worktree='main'); print(p['forearm_length_m'])"

# C++ generated header
c++ -std=c++17 -I PROJECT/datum controller.cpp -o controller && ./controller
```

To check stale-input rejection without touching the user's real files, copy the
project to a temporary directory, change the copy's CAD, and confirm the
generated loader raises `Datum CAD source changed` while the runtime loader either
picks up the new valid value or rejects it.

Record in the handback:

- integration mode (`load_generated`, `load_runtime`, generated C++ header or C ABI);
- project root and worktree key;
- parameter names and values in metres;
- path and SHA-256 of the consumed spec and sources (the manifest or evidence
  record contains them);
- the validation command and its result;
- whether Studio was used and whether generated artifacts were committed;
- known limits, especially that generated headers are not runtime-checked and
  runtime values are a startup snapshot.

## 11. Read the installed guide

The same file ships inside the Python package:

```sh
python -c "from datum_interface import agent_guide; print(agent_guide())"
```

Or, without the helper:

```sh
python -c "from importlib.resources import files; print(files('datum_interface').joinpath('AGENT_GUIDE.md').read_text())"
```

## 12. Source material

- Repository README: install, runtime modes, URDF modes
- `parameter_studio/README.md`: Studio controls and URDF export
- `examples/cpp-pick-place/README.md`: generated and runtime C++ comparison
- `examples/ros2_cpp_pick_place/README.md`: ROS 2 consumer
- `BENCHMARKS.md`: startup measurements and reproduction
