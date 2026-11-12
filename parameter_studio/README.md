# DParams Studio

Start from the [repository installation instructions](../README.md), providing a project folder containing saved `.solidcraft` files. Use `--tailscale` to expose the local service to your tailnet, or open http://localhost:8000 on the host. Compose keeps the CAD project read-only. The host preview and URDF workers need `solidcraft-cli`; the first container build compiles the Rust generator.

The viewport fills the workspace. Use the floating tools panel to choose an assembly, inspect a feature’s dimensions, and add a code parameter. Select **Hide tools** to use the full viewport; **Show tools** restores the panel. On mobile the panel sits at the bottom and scrolls independently. The generated `spec.json`, `parameters.json` and `parameters.hpp` are downloaded to your device. The Python loader expects the exact spec and manifest beside each other in the project's `datum/` directory. Changes to linked CAD invalidate a generated manifest.

## Experimental assembly to URDF

Choose a saved assembly, then open **Export URDF** in the tools panel and select **Export selected assembly**. Export runs on the host against a captured copy. Download the ZIP and report after completion. The first profile accepts `solidcraft/34`, millimetres, local linked rigid parts and a rooted occurrence tree with fixed, revolute or slider joints. Unsupported coupled joints are reported as a fidelity failure; export can succeed with a diagnostic bundle. The checker validates basic XML, graph structure, inertials and STL references, but does not establish geometry-cache freshness, source-to-URDF transform equivalence, material accuracy or physics readiness. Freshness is checked at export completion; regenerate after changing a source file. Host worker lifecycle currently requires Linux `/proc`.

The Studio spool is one way to export the URDF on demand. A second, scriptable path skips the spool and the checked-in file entirely: `datum_parameter_studio.runtime_urdf` captures the saved sources, exports into an isolated scratch directory, runs the same structural checker, validates the output bundle for symlinks, containment and size, and returns the URDF text plus a report with source hashes and a freshness result. The result's `bundle` holds the exporter's current output for the captured inputs; `write_bundle`/`--bundle-out` copy the URDF, per-link STLs, assembly STEP and verified part STEP blobs into a directory you keep, since the URDF's relative mesh references need those files beside it. Exporter provenance and fidelity to native CAD are not verified, and this path has no cancellation channel or worker heartbeat (see the [repository README](../README.md#urdf-export-modes) for `bring_up_urdf` and the streaming CLI).

The code is independent of Datum version control. Integrations with Datum snapshots must be supplied separately. Tailscale Serve uses a private tailnet HTTPS endpoint on port 8443; disable it with `tailscale serve --https=8443 off` when no longer needed.

Runtime and Studio export reports include `cad_urdf_fidelity_checks`, which
compare uniquely named joint types and limits against the captured saved CAD.
An ambiguous mapping is unknown. The overall result remains unknown unless a
mismatch is found, because geometry, frames, axes and occurrence mapping are
not established. `physics_checks` reports mass and inertia plausibility and
collision diagnostics; uninspectable mesh formats are unknown. These checks do
not verify material provenance, collision fidelity, or physics readiness.

## Experimental simulator input

`datum_parameter_studio.simulation.simulation_input(project, assembly)` is a
context manager for simulation consumers. It exports from saved CAD using
`bring_up_urdf`, requires a current freshness report and rejects known assembly
fidelity failures, validates the structural bundle, and keeps its meshes alive until the
context exits. It does not certify physics correctness or native CAD equivalence.
Existing arbitrary URDF bundles are currently refused because their freshness
and fidelity cannot be verified. The runnable example in
`examples/pybullet_sim/` includes a primitive one-joint arm URDF, so its default
mode needs no SolidCraft installation or project. Install PyBullet with
`python -m pip install pybullet`, then run headless from the repository root:
`python examples/pybullet_sim/demo.py`. It drives the arm joint and prints its
final position. Add `--gui` to view it. To simulate saved SolidCraft data,
install `parameter_studio` and pass `--project PROJECT --assembly PATH.solidcraft`;
the example uses `simulation_input` to validate and retain the exported meshes.
Run `python -m unittest examples/pybullet_sim/test_demo.py` to exercise the
actual PyBullet demo when that optional dependency is installed (otherwise the
test is skipped). The included native CAD demo and its prerequisites are described
in the [simulation example](../examples/pybullet_sim/README.md).

## Simulation sessions

Open **Simulation** in Studio, select an assembly and an available engine, and
start a session. The embedded simulation viewport uses engine-reported link
poses; the separate CAD preview remains an inspection view. Pause, single-step,
resume, reset and stop are available in the panel. For MuJoCo and PyBullet, pause and set a named joint position in radians or metres; this teleports the joint and clears its velocity. Recording writes local JSONL
samples and command events under `.dparams-studio/sim-jobs/<session>/recordings/`;
use the download links in the panel. Recordings include the captured export
report and source hashes. They are telemetry, not physics checkpoints or ROS bags.
Sessions persist while the host worker runs; closing a browser tab does not stop
them. Studio shutdown stops its worker and active session.

The host Python environment running `dparam-std` must have the desired optional
engine installed (`pip install 'mujoco>=4,<5'` or `pip install pybullet`), as
well as `solidcraft-cli` and the preflight tool used by URDF export. Gazebo is
experimental: its local `gz sim` executable and compatible Python transport
bindings are required. A headless Gazebo Harmonic run was tested with the included
two-link assembly. Direct joint positioning is not yet supported for Gazebo. Availability appears inline; dependencies are not downloaded by
the application. Simulations use captured saved inputs and do not update if the
CAD changes. Reset restores the captured model; start a new session to load edits.
Physics fidelity and suitability are not established by visualization.
