"""Worktree-aware Datum CAD parameters, usable from Python with optional ROS helpers."""
import hashlib
import json
import math
from pathlib import Path


class Parameters:
    """Immutable-style named values loaded from a checked Datum manifest."""
    def __init__(self, manifest):
        self.manifest = manifest
        self.worktree = manifest["worktree"]
        self.values = manifest["parameters"]
        self.groups = manifest["groups"]

    def __getitem__(self, name):
        return self.values[name]

    def get(self, name, default=None):
        return self.values.get(name, default)

    def group(self, name):
        """Return named values for one mapped CAD feature group."""
        return {key: self.values[key] for key in self.groups[name]}

    def ros_parameters(self):
        """Return a flat dict accepted by rclpy Node(parameters=[...])."""
        return dict(self.values)

    def ros_yaml(self, node_name):
        """Return a node-scoped mapping suitable for ROS parameter YAML."""
        if not node_name or not isinstance(node_name, str):
            raise ValueError("node_name must be a non-empty string")
        return {node_name: {"ros__parameters": dict(self.values)}}


def load(manifest_path, *, worktree=None):
    """Load a generated manifest after checking the selected tree and CAD hashes."""
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "datum.robot.parameters/2" or manifest.get("units") != "m":
        raise ValueError("unsupported Datum parameter manifest")
    selected = worktree if worktree is not None else manifest.get("worktree")
    if selected != manifest.get("worktree"):
        raise ValueError(f"manifest is for worktree {manifest.get('worktree')!r}, not {selected!r}")
    spec = path.with_name("spec.json")
    if not spec.is_file() or hashlib.sha256(spec.read_bytes()).hexdigest() != manifest.get("spec_sha256"):
        raise ValueError("Datum parameter specification changed; regenerate parameters and rebuild")
    root = path.parent.parent.resolve()
    sources = manifest.get("sources_sha256")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Datum manifest has no CAD source hashes")
    for name, expected in sources.items():
        candidate = (root / name).resolve(strict=True)
        if not candidate.is_relative_to(root):
            raise ValueError(f"Datum CAD source escapes project: {name}")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Datum CAD source changed: {name}; regenerate parameters and rebuild")
    values = manifest.get("parameters")
    if not isinstance(values, dict) or not values:
        raise ValueError("Datum manifest has no parameters")
    bounds = manifest.get("bounds", {})
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"invalid Datum parameter {name}")
        limits = bounds.get(name, {})
        if value <= 0 and limits.get("allow_nonpositive") is not True:
            raise ValueError(f"invalid non-positive Datum parameter {name}")
        if value < (limits.get("min") if limits.get("min") is not None else -math.inf) or value > (limits.get("max") if limits.get("max") is not None else math.inf):
            raise ValueError(f"Datum parameter {name} is outside its allowed bounds")
    groups = manifest.get("groups")
    if not isinstance(groups, dict) or any(not isinstance(v, list) or any(n not in values for n in v) for v in groups.values()):
        raise ValueError("invalid Datum feature groups")
    return Parameters(manifest)
