"""Deprecated compatibility alias for :mod:`datum_parameter_studio.runtime_urdf`.

Early 0.1.0 snapshots called the on-demand export path "lazy". The public names
now describe the runtime/generated distinction; use ``runtime_urdf`` in new
code.
"""
from .runtime_urdf import RuntimeUrdf, bring_up_urdf, main

# Deprecated: the export happens eagerly when bring_up_urdf() is called.
LazyUrdf = RuntimeUrdf

__all__ = ["LazyUrdf", "RuntimeUrdf", "bring_up_urdf", "main"]

if __name__ == "__main__":
    main()
