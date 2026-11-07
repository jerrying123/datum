//! C ABI over lazy evaluation so C++ (and other FFI languages) can load CAD
//! parameter values at startup without pre-generated artifacts. The same shared
//! core backs compiled artifact generation, so compiled and lazy modes agree by
//! construction whenever the spec and CAD sources are unchanged.
//!
//! Conventions: functions return 0 (or a positive byte count including NUL for
//! string buffers) on success and -1 on error. Errors are message-formatted by
//! `dparams_lazy_error`. One lazy session is active at a time; release it
//! before the next evaluation.
use crate::Evaluation;
use std::{
    collections::BTreeMap,
    ffi::{c_char, CStr},
    fs,
    path::Path,
    ptr,
    sync::Mutex,
};

struct Session {
    evaluation: Evaluation,
    order: Vec<String>,
    hashes: BTreeMap<String, String>,
}

static SESSION: Mutex<Option<Session>> = Mutex::new(None);
static LAST_ERROR: Mutex<Option<String>> = Mutex::new(None);

fn fail(message: String) {
    *LAST_ERROR.lock().unwrap() = Some(message);
}

fn clear_error() {
    *LAST_ERROR.lock().unwrap() = None;
}

fn cstr(pointer: *const c_char) -> Result<String, String> {
    if pointer.is_null() {
        return Err("required string argument is null".into());
    }
    unsafe { CStr::from_ptr(pointer) }
        .to_str()
        .map(str::to_owned)
        .map_err(|_| "argument is not valid UTF-8".into())
}

/// Writes `text` NUL-terminated into `buffer`. Returns the needed byte length
/// (including NUL) when the buffer is too small or null, so callers can retry;
/// returns the written length including NUL on success.
fn write_string(buffer: *mut c_char, len: usize, text: &str) -> i32 {
    let needed = text.as_bytes().len() as i32 + 1;
    if buffer.is_null() || (len as i32) < needed {
        return needed;
    }
    unsafe {
        ptr::copy_nonoverlapping(text.as_ptr() as *const c_char, buffer, text.as_bytes().len());
        *buffer.add(text.as_bytes().len()) = 0;
    }
    needed
}

fn with_session<T>(body: impl FnOnce(&Session) -> Result<T, String>, on_error: impl FnOnce() -> T) -> T {
    let guard = SESSION.lock().unwrap();
    match guard.as_ref() {
        Some(session) => match body(session) {
            Ok(value) => {
                clear_error();
                value
            }
            Err(message) => {
                fail(message);
                on_error()
            }
        },
        None => {
            fail("no lazy evaluation is active; call dparams_lazy_eval first".into());
            on_error()
        }
    }
}

/// Evaluates the spec against the saved CAD sources and installs the result as
/// the active lazy session. Returns 0 on success, -1 on error. Any previous
/// session (even a failed evaluation) must be released, so check the result.
#[no_mangle]
pub extern "C" fn dparams_lazy_eval(project: *const c_char, spec: *const c_char, worktree: *const c_char) -> i32 {
    match (|| -> Result<Evaluation, String> {
        let project = cstr(project)?;
        let spec = cstr(spec)?;
        let worktree = cstr(worktree)?;
        crate::evaluate(Path::new(&project), Path::new(&spec), &worktree)
            .map_err(|error| format!("{error:#}"))
    })() {
        Ok(evaluation) => {
            let mut order: Vec<String> = evaluation.parameters.keys().cloned().collect();
            order.sort();
            let hashes = evaluation.sources_sha256.clone();
            *SESSION.lock().unwrap() = Some(Session { evaluation, order, hashes });
            clear_error();
            0
        }
        Err(message) => {
            *SESSION.lock().unwrap() = None;
            fail(message);
            -1
        }
    }
}

/// Count of parameters in the active session. -1 when no session is active.
#[no_mangle]
pub extern "C" fn dparams_lazy_count() -> i32 {
    with_session(|session| Ok(session.order.len() as i32), || -1)
}

/// Parameter name for an ordinal position in the active session.
#[no_mangle]
pub extern "C" fn dparams_lazy_name(index: i32, buffer: *mut c_char, len: usize) -> i32 {
    with_session(
        |session| {
            let name = session
                .order
                .get(index as usize)
                .ok_or("lazy session parameter index out of range")?;
            Ok(write_string(buffer, len, name))
        },
        || -1,
    )
}

/// Parameter value by name into `*out`. 0 on success, -1 on error.
#[no_mangle]
pub extern "C" fn dparams_lazy_get(name: *const c_char, out: *mut f64) -> i32 {
    if out.is_null() {
        fail("output pointer is null".into());
        return -1;
    }
    with_session(
        |session| {
            let name = cstr(name).map_err(|_| "parameter name is not valid UTF-8".to_string())?;
            match session.evaluation.parameters.get(&name) {
                Some(value) => {
                    unsafe { *out = *value };
                    Ok(0)
                }
                None => Err(format!("unknown lazy parameter {name}")),
            }
        },
        || -1,
    )
}

/// SHA-256 of a recorded source (CAD or utility source) by its spec-relative name.
#[no_mangle]
pub extern "C" fn dparams_lazy_source_hash(name: *const c_char, buffer: *mut c_char, len: usize) -> i32 {
    with_session(
        |session| {
            let name = cstr(name).map_err(|_| "source name is not valid UTF-8".to_string())?;
            match session.hashes.get(&name) {
                Some(hash) => Ok(write_string(buffer, len, hash)),
                None => Err(format!("unknown lazy source {name}")),
            }
        },
        || -1,
    )
}

/// Selected worktree of the active session.
#[no_mangle]
pub extern "C" fn dparams_lazy_worktree(buffer: *mut c_char, len: usize) -> i32 {
    with_session(|session| Ok(write_string(buffer, len, &session.evaluation.worktree)), || -1)
}

/// Writes the machine-readable lazy-evidence record (mode, values, bounds,
/// source and spec hashes) to `path`. 0 on success, -1 on error.
#[no_mangle]
pub extern "C" fn dparams_lazy_evidence(path: *const c_char) -> i32 {
    with_session(
        |session| {
            let path = cstr(path)?;
            let document = session.evaluation.evidence();
            let text = serde_json::to_string_pretty(&document).map_err(|error| error.to_string())?;
            if let Some(parent) = Path::new(&path).parent() {
                let _ = fs::create_dir_all(parent);
            }
            fs::write(&path, format!("{text}\n")).map_err(|error| error.to_string()).map(|_| 0)
        },
        || -1,
    )
}

/// Last error message, or an empty string when there is no recorded error.
/// Reading the error does not clear it; `dparams_lazy_release` does.
#[no_mangle]
pub extern "C" fn dparams_lazy_error(buffer: *mut c_char, len: usize) -> i32 {
    let message = LAST_ERROR.lock().unwrap().clone().unwrap_or_default();
    write_string(buffer, len, &message)
}

/// Releases the active session and the recorded error. Pointers and values
/// obtained through this module become invalid.
#[no_mangle]
pub extern "C" fn dparams_lazy_release() {
    *SESSION.lock().unwrap() = None;
    *LAST_ERROR.lock().unwrap() = None;
}
