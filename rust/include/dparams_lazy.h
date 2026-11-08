// Deprecated compatibility header. New code should include dparams_runtime.h
// and call the dparams_runtime_* functions. These declarations keep old source
// compiling against the dparams_lazy_* wrapper symbols exported by the library
// for already-compiled callers.
#ifndef DPARAMS_LAZY_H
#define DPARAMS_LAZY_H
#include "dparams_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

int dparams_lazy_eval(const char* project, const char* spec, const char* worktree);
int dparams_lazy_count(void);
int dparams_lazy_name(int index, char* buffer, size_t length);
int dparams_lazy_get(const char* name, double* out_value);
int dparams_lazy_source_hash(const char* name, char* buffer, size_t length);
int dparams_lazy_worktree(char* buffer, size_t length);
int dparams_lazy_evidence(const char* path);
int dparams_lazy_error(char* buffer, size_t length);
void dparams_lazy_release(void);

#ifdef __cplusplus
}
#endif
#endif // DPARAMS_LAZY_H
