// C ABI for runtime Datum parameter evaluation. A runtime counterpart to the
// generated C++ header: values are extracted from the spec and saved CAD
// sources at startup by the same shared Rust core that produces the generated
// artifacts, so those two modes agree by construction for an unchanged spec and
// CAD. The executable cannot fall back to an earlier evaluation: a
// failed dparams_runtime_eval clears the session and reports the error.
//
// Return conventions:
//   - Status functions return 0 on success and -1 on error.
//   - String functions return 0 after writing NUL-terminated text. A positive
//     return is the required buffer size in bytes including the NUL; nothing
//     was written, so retry with a buffer of at least that size. Pass a null
//     buffer and length 0 to query the required size.
//   - Errors are reported as text by dparams_runtime_error.
// The session and error slots are process-global. Call these functions from one
// thread at a time. Exactly one runtime session is active at a time; call
// dparams_runtime_release before the next evaluation.
#ifndef DPARAMS_RUNTIME_H
#define DPARAMS_RUNTIME_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

// Evaluates PROJECT/datum/spec.json for WORKTREE against the saved CAD sources
// and installs the result as the active session. Returns 0 on success, -1 on
// error. A failed evaluation clears any active session.
int dparams_runtime_eval(const char* project, const char* spec, const char* worktree);

// Active session introspection. dparams_runtime_name enumerates parameters by
// ordinal position; dparams_runtime_get reads a named value in metres; hashes use
// the spec-relative source name and compare against parameters.json in
// generated mode.
int dparams_runtime_count(void);
int dparams_runtime_name(int index, char* buffer, size_t length);
int dparams_runtime_get(const char* name, double* out_value);
int dparams_runtime_source_hash(const char* name, char* buffer, size_t length);
int dparams_runtime_worktree(char* buffer, size_t length);

// Atomically writes a machine-readable evidence record (evidence schema, mode,
// values, bounds, source and spec SHA-256 hashes) to PATH.
int dparams_runtime_evidence(const char* path);

// Last error text, or an empty string with no recorded error. Reading does not
// clear the error; a successful session call or dparams_runtime_release does.
int dparams_runtime_error(char* buffer, size_t length);

// Releases the active session and the recorded error. Values already copied out
// stay valid; session-based calls fail until the next dparams_runtime_eval.
void dparams_runtime_release(void);

#ifdef __cplusplus
}
#endif
#endif // DPARAMS_RUNTIME_H
