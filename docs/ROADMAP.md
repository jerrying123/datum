# Immediate roadmap: CAD to simulation workspace

This is the current priority queue for Studio. Work through the milestones in
order; check off a task only when its acceptance condition is met. Later items
are directions to validate, not promises of a particular implementation. All
work must remain usable locally and preserve source and spec freshness checks.

## 1. CAD configurations and simulation inputs

Goal: derive configurations from a CAD document's labeled feature-history
states and, where supported, automatically offer branch tips. Selecting a
configuration must produce the corresponding geometry and parameters for
simulation without changing the user's saved CAD.

- [x] Audit the existing handoff and identify boundaries (see below).
- [ ] Investigate SolidCraft's representation of feature-history branches,
  labels and branch tips, including how to evaluate and export each state.
  Its current command catalog exposes a linear history marker and named
  configuration rows; it does not expose branch commands. Do not infer branches
  from a dependency graph or treat feature folders as branches.
- [x] Replace the experimental assembly-path JSON selector with discovery of
  native configuration rows and explicit linear history points. These are
  distinct from labeled branching states, which remain unsupported.
- [ ] Activate the selected state in an isolated captured copy and export its
  geometry; extract parameters from the same state. Reject unsupported or
  stale selections explicitly, without modifying saved source files.
- [ ] Show available states and their source in Studio and expose the same
  workflow to agents. Selection changes affect the next session, not a running
  captured simulation.
- [ ] Test distinct states, linked parts, missing labels, stale sources and
  configuration activation with synthetic CAD; validate real exporter behavior.

The first slice activates native rows or linear history points for URDF export
and simulation. It does not extract parameters from the chosen state, provide
branch tips. The CAD viewport evaluates supported selections in a temporary capture.

First audit: `simulation_input` requires a project and project-relative assembly;
it rejects retained bundles; `bring_up_urdf` captures saved dependencies in a temporary project,
exports a URDF and meshes, and records source hashes, exporter version and
freshness. The bundle can be retained, but exporter fidelity and physics
readiness are not established. Parameter spec worktrees are named spec entries,
not Git operations. A configuration must explicitly bind these separate inputs;
path names alone cannot prove that a retained export matches its sources.

## 2. Agent and project editing workflow

- [ ] Inventory scriptable parameter, export and simulation operations and fill
  gaps so an agent can complete a workflow without starting the Studio browser.
- [ ] Design a Studio project editor for relevant files, showing unsaved changes,
  validation errors and external edits; prototype a narrow, useful editing flow.
- [ ] Evaluate IDE extensions, a desktop shell and integration with T3 Code,
  Codex and Cursor against the local API and security model before selecting a
  platform. Avoid making any particular agent or cloud service mandatory.
- [ ] Document and test a complete agent-to-simulation workflow on synthetic CAD.

## 3. Environments beyond robot CAD

- [ ] Define a portable scene referencing a robot and independent environment
  assets, transforms, initial poses and engine-specific limitations.
- [ ] Import or author a minimal environment and load it in a supported engine;
  keep environment assets and robot export provenance independently visible.
- [ ] Test missing assets, coordinate frames, reload and reproducible scene setup;
  extend engine coverage based on actual capabilities.

## 4. Telemetry and sensor workspace

- [ ] Define data sources, timestamps, frames and recording/playback semantics
  for live simulation and external telemetry, including disconnected sources.
- [ ] Build useful first views for time plots and spatial data beside simulation;
  make supported message and sensor types explicit.
- [ ] Save, version and share portable display templates with missing-source
  handling; validate with representative recorded data.

## 5. ROS 2 integration

- [ ] Inventory supported ROS 2 distributions, discovery, launch and lifecycle
  capabilities; define local process ownership and failure reporting.
- [ ] Inspect nodes, topics and status in Studio, then add explicit controls for
  managed processes and lifecycle nodes where supported. Arbitrary nodes cannot
  necessarily be paused; report capabilities and actual outcomes.
- [ ] Design launch-file import and editing with preview, validation and
  preservation of user files; support starting and stopping selected components.
- [ ] Connect ROS telemetry and recording to the workspace and test recovery,
  time/frame handling and teardown with a small ROS 2 example.

## 6. CAD versions and reproducible exports

- [ ] Investigate the local version-control prototype read-only, including its
  provenance and migration boundaries, before choosing an integration.
- [ ] Define version identity and dirty/uncommitted behavior, and record source
  hashes, exporter identity and settings alongside retained exports and sessions.
- [ ] Provide explicit export/re-export and version selection, with clear stale,
  missing and unavailable-version errors. Never silently reuse an old bundle.
- [ ] Test switching versions and restoring a recorded session's inputs without
  modifying user CAD; document any limits to reproducibility.

Each milestone should deliver a working vertical slice with deterministic tests
and documentation before expanding scope. Validate real engine and ROS behavior
where dependencies are available, and record any unverified integrations.
