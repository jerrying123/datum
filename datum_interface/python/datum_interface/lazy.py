"""Deprecated compatibility alias for :mod:`datum_interface.runtime`.

Early 0.1.0 snapshots called this eager startup evaluation "lazy". The public
names now describe the runtime/generated distinction; use
:func:`datum_interface.load_runtime` or
:func:`datum_interface.runtime.evaluate_runtime` in new code.
"""
from .runtime import evaluate_runtime, write_evidence

# Deprecated: evaluation happens eagerly at startup, not on first access.
evaluate_lazy = evaluate_runtime

__all__ = ["evaluate_lazy", "evaluate_runtime", "write_evidence"]
