"""Lazy parameter evaluation: value semantics shared with the compiled generator.

The Rust datum-params CLI bakes a manifest and C++ header before the build. This
module evaluates the same spec against the saved CAD files at runtime instead,
so no generated artifact is needed and the values cannot drift silently from
the CAD they came from. Any mismatch (missing field, units, bounds, positive-
dimension rule) stops evaluation with a ValueError instead of running stale.

Semantics deliberately mirror rust/src/lib.rs. The cross-mode unittest keeps
them from diverging: compiled artifacts and this loader must evaluate the same
spec to the same values.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import zipfile

_SPEC_SCHEMA = "datum.robot.parameter-spec/2"
_UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}


def _unit_scale(source, target):
    for unit in (source, target):
        if unit not in _UNIT_SCALE:
            raise ValueError("unsupported unit %r for CAD dimensions" % unit)
    return _UNIT_SCALE[source] / _UNIT_SCALE[target]


def _quantity(text, default_unit):
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        parts = text.split()
        if len(parts) == 2:
            try:
                float(parts[0])
            except ValueError:
                parts = None
            if parts is not None:
                return float(parts[0]) * _unit_scale(parts[1], default_unit)
        for unit in _UNIT_SCALE:
            if not text.endswith(unit):
                continue
            number = text[: -len(unit)].strip()
            try:
                return float(number) * _unit_scale(unit, default_unit)
            except ValueError:
                continue
        raise ValueError("unsupported SolidCraft expression %r; use a numeric literal with an optional unit" % text)


def _solidcraft_number(data, item, default_unit):
    if isinstance(item, bool) or not isinstance(item, (int, float, str)):
        raise ValueError("CAD dimension is not numeric")
    if not isinstance(item, str):
        return float(item)
    try:
        return _quantity(item, default_unit)
    except ValueError:
        pass
    params = data.get("params") if isinstance(data, dict) else None
    if isinstance(params, list):
        for parameter in params:
            if isinstance(parameter, dict) and parameter.get("name") == item:
                expression = parameter.get("expr")
                if not isinstance(expression, str):
                    raise ValueError("SolidCraft parameter %r has no expression" % item)
                unit = parameter.get("unit", default_unit)
                return _quantity(expression, default_unit) * _unit_scale(unit, default_unit)
    raise ValueError("%r is not a numeric literal or a named SolidCraft parameter" % item)


def _safe_relative(root, name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("invalid source path %s" % name)
    candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise ValueError("source escapes project: %s" % name)
    return candidate


def _cad_value(root, mapping, hashes):
    path = _safe_relative(root, mapping["path"])
    raw = path.read_bytes()
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            text = archive.read("document.json")
    except (zipfile.BadZipFile, KeyError) as error:
        raise ValueError("%s is not a SolidCraft archive" % mapping["path"]) from error
    if len(text) > 32 * 1024 * 1024:
        raise ValueError("SolidCraft document too large")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid document.json in %s" % mapping["path"]) from error
    if data.get("units") != mapping["source_units"]:
        raise ValueError("units mismatch: %s" % mapping["path"])
    item = data
    for raw_token in mapping["pointer"].split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(item, dict) and token in item:
            item = item[token]
        elif isinstance(item, list) and token.isdigit() and int(token) < len(item):
            item = item[int(token)]
        else:
            raise ValueError("%s has no feature/dimension at %s" % (mapping["path"], mapping["pointer"]))
    scale = _unit_scale(mapping["source_units"], mapping["unit"])
    value = _solidcraft_number(data, item, mapping["source_units"]) * scale
    minimum = mapping["min"] * scale if mapping.get("min") is not None else None
    maximum = mapping["max"] * scale if mapping.get("max") is not None else None
    _check_bounds("CAD dimension", value, minimum, maximum)
    hashes[mapping["path"]] = hashlib.sha256(raw).hexdigest()
    return value


def _ident(name):
    return bool(name) and all(("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_" for ch in name)


def _check_bounds(name, value, minimum, maximum):
    finite = lambda x: x is not None and math.isfinite(x)
    if not math.isfinite(value) or (minimum is not None and not math.isfinite(minimum)) or (maximum is not None and not math.isfinite(maximum)) or minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("invalid value or bounds for %s" % name)
    if minimum is not None and finite(minimum) and value < minimum:
        raise ValueError("%s=%s is outside allowed bounds [%s, %s]" % (name, value, minimum, "+inf" if maximum is None else maximum))
    if maximum is not None and finite(maximum) and value > maximum:
        raise ValueError("%s=%s is outside allowed bounds [%s, %s]" % (name, value, "-inf" if minimum is None else minimum, maximum))


def _bounds_doc(minimum, maximum, allow_nonpositive=False):
    return {"min": minimum, "max": maximum, "allow_nonpositive": allow_nonpositive}


def evaluate_lazy(project_root, *, worktree="main"):
    """Evaluate the parameter spec against the saved CAD files.

    Reads PROJECT/datum/spec.json from the resolved project root and extracts
    every mapped dimension fresh from the referenced SolidCraft sources.
    Returns (manifest, evidence); the manifest has the exact
    datum.robot.parameters/2 shape of the compiled generator, and the evidence
    record adds mode=lazy and the spec path.
    """
    project = Path(project_root).resolve(strict=True)
    spec_path = (project / "datum/spec.json").resolve(strict=True)
    spec_bytes = spec_path.read_bytes()
    try:
        spec = json.loads(spec_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("invalid parameter specification") from error
    if spec.get("schema") != _SPEC_SCHEMA or spec.get("units") != "m":
        raise ValueError("expected datum.robot.parameter-spec/2 with canonical units m")
    if not _ident(worktree):
        raise ValueError("invalid worktree name")
    tree = spec.get("worktrees", {}).get(worktree)
    if tree is None:
        raise ValueError("worktree %r is not defined in the spec" % worktree)
    values = {}
    bounds = {}
    hashes = {}
    for name, constant in (tree.get("constants") or {}).items():
        if not _ident(name) or constant.get("unit") != "m":
            raise ValueError("invalid constant %s" % name)
        value = constant.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("invalid value or bounds for %s" % name)
        _check_bounds(name, float(value), constant.get("min"), constant.get("max"))
        values[name] = float(value)
        bounds[name] = _bounds_doc(constant.get("min"), constant.get("max"), constant.get("min") is not None and constant["min"] <= 0.0)
    for name, mapping in (tree.get("parameters") or {}).items():
        if not _ident(name):
            raise ValueError("invalid parameter name %s" % name)
        value = _cad_value(project, mapping, hashes)
        if value <= 0.0:
            raise ValueError("CAD dimension %s must be positive" % name)
        scale = _unit_scale(mapping["source_units"], mapping["unit"])
        minimum = mapping["min"] * scale if mapping.get("min") is not None else None
        maximum = mapping["max"] * scale if mapping.get("max") is not None else None
        _check_bounds(name, value, minimum, maximum)
        values[name] = value
        bounds[name] = _bounds_doc(minimum, maximum)
    for name, derived in (tree.get("derived") or {}).items():
        if not _ident(name):
            raise ValueError("invalid parameter name %s" % name)
        inputs = derived.get("inputs") or []
        if not inputs or any(input_name not in values for input_name in inputs):
            raise ValueError("%s references a missing input" % name)
        arguments = [values[input_name] for input_name in inputs]
        operation = derived["operation"]
        if operation == "sum":
            value = sum(arguments)
        elif operation == "product":
            value = math.prod(arguments)
        elif operation == "min":
            value = min(arguments)
        elif operation == "max":
            value = max(arguments)
        elif operation == "difference" and len(arguments) == 2:
            value = arguments[0] - arguments[1]
        elif operation == "ratio" and len(arguments) == 2:
            value = arguments[0] / arguments[1]
        else:
            raise ValueError("unsupported operation or arity for %s" % name)
        if derived.get("unit") != "m":
            raise ValueError("derived parameter %s must use canonical unit m" % name)
        _check_bounds(name, value, derived.get("min"), derived.get("max"))
        values[name] = value
        bounds[name] = _bounds_doc(derived.get("min"), derived.get("max"), derived.get("min") is not None and derived["min"] <= 0.0)
    for source in list(tree.get("sources") or []) + list(spec.get("sources") or []):
        hashes[source] = hashlib.sha256(_safe_relative(project, source).read_bytes()).hexdigest()
    groups = tree.get("groups") or {}
    for group, names in groups.items():
        if not _ident(group) or not names or any(name not in values for name in names):
            raise ValueError("invalid group %s: every referenced parameter must exist" % group)
    manifest = {
        "schema": "datum.robot.parameters/2",
        "units": spec.get("units"),
        "worktree": worktree,
        "parameters": values,
        "groups": groups,
        "bounds": bounds,
        "metadata": {key: spec[key] for key in spec if key not in ("schema", "units", "worktrees", "sources")},
        "sources_sha256": hashes,
        "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
    }
    evidence = dict(manifest, mode="lazy", spec_path=str(spec_path))
    return manifest, evidence


def write_evidence(path, evidence):
    """Atomically persist a lazy-evaluation evidence record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(evidence, indent=2) + "\n")
    os.replace(tmp, target)
