# Agent integration documentation plan

## Goal and size

Provide a portable entry point for coding agents integrating DParams into a user
project. Keep one detailed guide, a short repository AGENTS.md and a README link.
Do not require a provider-specific skill, MCP server, cloud account or Studio.
Ship the guide as a Python package resource so it remains available after pip
installation. Current main supports source installation; do not claim unpublished
PyPI or native release artifacts are available.

## Guide interactions

1. Identify project root, saved SolidCraft sources, language, selected spec worktree
   (a spec key, not a Git operation), and the exact runtime value needed. Inspect
   document.json read-only and validate the selected pointer against the actual file.
2. Choose the fastest supported integration: Python load_lazy for iteration;
   checked generated JSON for Python with reviewed artifacts; generated C++17
   header for minimal C++ integration; C ABI static library when startup evaluation
   is desired. Explain prerequisites per path; Docker and SolidCraft CLI are only
   needed for Studio rendering/export, not literal parameter extraction.
3. Author PROJECT/datum/spec.json directly. Include a minimal complete spec,
   canonical metre values, source-unit mapping bounds, constant/derived bounds,
   groups, explicit dependency sources and stable names. Explain supported literal
   and named-literal extraction, expression limits and sorted derived evaluation.
4. Generate and consume artifacts with exact commands and API calls. Keep downloaded
   spec and manifest together in PROJECT/datum; regenerate and rebuild C++ after
   changes. Cover error handling, copied startup values, optional evidence and
   checking output from the application's real consumer boundary.
5. Optional Studio: Parts → Dimensions → Code parameters → Generate; naming,
   worktree/unit, selecting features/sketch inputs, removing mappings, live change
   review and downloads. Explain supported UI controls without promising general
   CAD editing or feature-specific geometric selection.
6. Optional URDF: link existing export docs, retained mesh bundle and conservative
   readiness/fidelity limitations. Avoid turning URDF generation into a prerequisite.
7. Recovery and completion: stale source/spec, wrong root/worktree, unsupported
   expression, missing pointer and bounds errors; never bypass hashes or overwrite
   user CAD to force success. Record consumed value, units, hashes, validation and
   which integration mode was used.

## Implementation and checks

Luna implements the root entry point, packaged guide, README discovery, package-data
metadata, and a bounded deterministic check of documented quickstart behavior using
synthetic temporary CAD. Verify generation, both Python loading modes, compiled C++
consumption when applicable, stale-file rejection and guide inclusion in a built
wheel. Integrate the guide check into the existing PR CI rather than adding a new
release pipeline. No user CAD or broad dependency changes.

Terra independently reviews correctness, discoverability, shipped guide, executable
examples, supported customization, optional Studio and required failure behavior.
Resolve findings and publish a new PR for user review. Do not merge it automatically.
