# Datum Studio

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
start a session. Studio transitions the main viewport to engine-reported link
poses. Use the viewport layout controls to return to the CAD inspection view or
show CAD and simulation side by side. Pause, single-step, resume, reset and stop
are available in the panel. Playback speed targets any value from 0.25× to 4×
real time; the displayed actual rate can be lower if the engine or machine cannot
keep up. The viewport frame-rate setting independently targets 1–60 pose updates
per second and displays the received rate. It does not precompute or buffer
frames, so the target is not guaranteed and background browser throttling can
reduce it. MuJoCo and PyBullet keep a bounded in-memory history of up to 2,501
physics checkpoints per session. Pause to seek backward or forward through that
history; resuming or editing from the past discards the later branch. History is
lost when the session ends and is not a recording or exact cross-engine replay.
Gazebo currently supports playback speed but cannot rewind. Applying position
control while paused configures the controller; press Resume or Step to advance it. The joint panel shows the measured
position and velocity and reports whether the command was accepted. For MuJoCo and PyBullet, pause and set a named joint position in radians or metres; this teleports the joint and clears its velocity. Recording writes local JSONL
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
two-link assembly. Direct joint positioning is not yet supported for Gazebo; force-limited position control is available. Availability appears inline; dependencies are not downloaded by
the application. Simulations use captured saved inputs and do not update if the
CAD changes. Reset restores the captured model; start a new session to load edits.
Physics fidelity and suitability are not established by visualization.

Studio checks its host simulation and URDF workers through authenticated, read-only
health APIs on ephemeral host ports. Docker connects via `host.docker.internal`;
each endpoint descriptor and bearer token are stored in its project worker
spool with owner-only permissions. Session commands and telemetry continue to use
the local spool. The service and its container must run on the same machine.
By default each health API binds host network interfaces to accommodate Docker
bridge networking; `DATUM_WORKER_HEALTH_BIND` can restrict its bind address when
the container can reach that address. The endpoint exposes only health and
capabilities, requires its private bearer token, and never accepts commands.

For MuJoCo, PyBullet, and Gazebo sessions, Studio supports one SolidCraft motion link
between two named slider joints with identical limits, a 1:1 ratio, and zero
offset. It creates a simulator constraint for that pair and records the mapping
in recording metadata. Command the driver joint for position control. Other
links and nested couplings are rejected. Gazebo coupled sessions require a matching
Bullet Featherstone physics plugin that advertises mimic-constraint support. The exported URDF
itself still lacks the link: direct `simulation_input` consumers reject it by
default unless they explicitly opt in and implement the supplied coupling.
The simulator constraint is an approximation and does not prove source frame,
geometry, inertia, or contact fidelity.


## Frontend development and distribution

Use Node.js 22 and npm from the repository root:

```sh
cd parameter_studio/datum_parameter_studio
npm ci
npm run typecheck
npm run build
npm run check:bundle
```

Author the browser entry at `frontend/src/app.ts`. The strict TypeScript check
covers `frontend/src/**/*.ts`; esbuild bundles dependencies into the local ESM
asset `public/app.js`. Keep `public/index.html` and `public/style.css` alongside
it. Run the build after source changes and include the resulting `public/app.js`
in the distribution. No CDN or build service is required at runtime.

The Docker frontend builder runs `npm ci` and `npm run build` from source,
then copies its bundle into the runtime image. Building the image requires the
TypeScript entry and all imported modules to exist. Docker builds therefore
also enforce the frontend typecheck. Python installation never invokes npm;
maintainers must build the frontend before producing Python distributions:

```sh
# From the repository root, after the frontend commands above:
python -m build parameter_studio
```

The sdist and wheel carry the public assets, TypeScript sources, tsconfig and
npm manifests so an installed Studio can still supply a Docker build context.
Dependency installation and image construction need dependencies available at
build time; the running Studio uses local bundled assets and remains offline.
When coordinating a conversion, land the TypeScript entry, its imports, the
rebuilt public bundle and this tooling together. A missing entry fails the
build explicitly.

The source checkout also provides `npm run test:browser`, an offline browser
smoke test. It requires a local Chromium executable; set `CHROMIUM_PATH` if the
browser is not installed in Playwright's usual cache. It exercises the CAD
catalog and simulation controls against local synthetic API responses.
