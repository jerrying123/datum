// C ABI for lazy Datum parameter evaluation. A runtime counterpart to the
// generated compile-time header: values are extracted from the spec and saved
// CAD sources at startup by the same shared core that produces the compiled
// artifacts, so the executable cannot drift from the CAD it is pointed at.
//
// Conventions: functions return 0 (or a needed/given string length including
// NUL) on success and -1 on error; format the last error with
// dparams_lazy_error. Exactly one lazy session is active at a time; call
// dparams_lazy_release before the next evaluation.
#ifndef DPARAMS_LAZY_H
#define DPARAMS_LAZY_H
#ifdef __cplusplus
extern "C" {
#endif

// Evaluates PROJECT_ROOT/datum SPEC_JSON for WORKTREE against the saved CAD
// sources and installs the result as the active session.
int dparams_lazy_eval(const char* project, const char* spec, const char* worktree);

// Active session introspection. dparams_lazy_name enumerates parameters by
// ordinal position; dparams_lazy_get reads a named value in metres; hashes use
// the spec-relative source name and compare against parameters.json in
// compiled mode.
int dparams_lazy_count(void);
int dparams_lazy_name(int index, char* buffer, int length);
int dparams_lazy_get(const char* name, double* out_value);
int dparams_lazy_source_hash(const char* name, char* buffer, int length);
int dparams_lazy_worktree(char* buffer, int length);

// Writes a machine-readable evidence record (mode lazily evaluated, values,
// bounds, source and spec SHA-256 hashes) to PATH.
int dparams_lazy_evidence(const char* path);

// Last error text, or an empty string with no recorded error. Reading does not
// clear the error; dparams_lazy_release does.
int dparams_lazy_error(char* buffer, int length);

// Releases the active session; subsequent reads fail until the next
// dparams_lazy_eval.
void dparams_lazy_release(void);

#ifdef __cplusplus
}
#endif
#endif // DPARAMS_LAZY_H
