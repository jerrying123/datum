// Deprecated compatibility header. New code should include dparams_runtime.h
// and call the dparams_runtime_* functions. These macros forward source-level
// calls; the library also exports dparams_lazy_* wrappers for already-compiled
// binaries.
#ifndef DPARAMS_LAZY_H
#define DPARAMS_LAZY_H
#include "dparams_runtime.h"

#define dparams_lazy_eval dparams_runtime_eval
#define dparams_lazy_count dparams_runtime_count
#define dparams_lazy_name dparams_runtime_name
#define dparams_lazy_get dparams_runtime_get
#define dparams_lazy_source_hash dparams_runtime_source_hash
#define dparams_lazy_worktree dparams_runtime_worktree
#define dparams_lazy_evidence dparams_runtime_evidence
#define dparams_lazy_error dparams_runtime_error
#define dparams_lazy_release dparams_runtime_release

#endif // DPARAMS_LAZY_H
