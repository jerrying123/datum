# Datum project context

The intended direction is a single Datum repository for the local, open-source
product, including Datum Parameters, Parameter Studio and local version control.
Cloud-facing managed services and infrastructure belong in the separate private
cloud repository. This document records the direction; the version-control
implementation has not yet been migrated into this repository.

## Local reference checkout

This machine has the earlier combined prototype at `.datum-context/`. It is an
ignored local symlink, not a submodule or a portable dependency. Start with
`.datum-context/AGENTS.md`, `.datum-context/docs/ROADMAP_RUNBOOK.md` and
`.datum-context/local/README.md` for the version-control implementation. The
checkout also contains unrelated changes and private working material: inspect it
read-only and preserve its state. Cloud/service and deployment files there are
historical context, not a decision to copy them into this public repository.

On another machine, create an equivalent link to a checkout you already have:

```sh
ln -s /absolute/path/to/cad-code-vc .datum-context
```

The link itself is local and ignored by Git. Nothing in this repository's build
requires it. Do not copy credentials, private infrastructure, machine-specific
CAD, unreviewed history or untracked assets into the public repository. Any
future migration needs an explicit scope, provenance/license review, and its own
implementation and checks.
