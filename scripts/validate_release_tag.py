#!/usr/bin/env python3
"""Validate that the git release tag matches the version in datum_interface/pyproject.toml."""
import pathlib
import sys

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: validate_release_tag.py <tag>")
    tag = sys.argv[1].strip()
    root = pathlib.Path(__file__).resolve().parents[1]
    toml_path = root / "datum_interface/pyproject.toml"
    if not toml_path.is_file():
        sys.exit(f"Error: {toml_path} not found")

    version = None
    try:
        import tomllib
        with open(toml_path, "rb") as f:
            version = tomllib.load(f).get("project", {}).get("version")
    except Exception:
        pass

    if not version:
        for line in toml_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("version"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    version = parts[1].strip().strip('"').strip("'")
                    break

    if not version:
        sys.exit("Error: Could not determine version from datum_interface/pyproject.toml")

    expected_tag = f"v{version}"
    if tag != expected_tag and tag != version:
        sys.exit(
            f"Release tag mismatch: got tag {tag!r}, but datum_interface/pyproject.toml specifies version {version!r} "
            f"(expected {expected_tag!r}). Tag must match the package version before any publishing."
        )

    print(f"Validated release tag {tag!r} matches datum_interface/pyproject.toml version {version!r}")

if __name__ == "__main__":
    main()
