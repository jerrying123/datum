#!/usr/bin/env bash
set -euo pipefail
example_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ $# != 1 || -e "$1" ]]; then echo 'Usage: run.sh NEW_OUTPUT_DIRECTORY' >&2; exit 2; fi

dparams_dir=$(cd "$example_dir/.." && pwd)
repo_dir=$(cd "$example_dir/../.." && pwd)

if [[ -f "$dparams_dir/include/dparams_runtime.h" && ( -f "$dparams_dir/libdatum_params_tools.a" || -f "$dparams_dir/datum_params_tools.lib" ) ]]; then
  # Running from downloaded/bundled release archive (Rust source absent)
  for tool in solidcraft-cli c++ sha256sum; do
    command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 2; }
  done
  generator="$dparams_dir/datum-params"
  if [[ ! -x "$generator" && -x "$dparams_dir/datum-params.exe" ]]; then
    generator="$dparams_dir/datum-params.exe"
  fi
  if [[ ! -x "$generator" ]]; then
    if command -v datum-params >/dev/null; then
      generator="datum-params"
    else
      echo "Missing executable datum-params CLI at $generator or in PATH" >&2
      exit 2
    fi
  fi
  include_dir="$dparams_dir/include"
  lib_file="$dparams_dir/libdatum_params_tools.a"
  if [[ ! -f "$lib_file" && -f "$dparams_dir/datum_params_tools.lib" ]]; then
    lib_file="$dparams_dir/datum_params_tools.lib"
  fi
elif [[ -f "$repo_dir/rust/Cargo.toml" ]]; then
  # Running from repository checkout (Rust source present)
  for tool in cargo solidcraft-cli c++ sha256sum; do
    command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 2; }
  done
  cargo build --locked --manifest-path "$repo_dir/rust/Cargo.toml" --bins --lib
  generator="$repo_dir/rust/target/debug/datum-params"
  include_dir="$repo_dir/rust/include"
  lib_file="$repo_dir/rust/target/debug/libdatum_params_tools.a"
else
  echo "Unable to locate datum-params CLI, C++ headers, or Rust source tree" >&2
  exit 2
fi

mkdir -p "$1"
out=$(cd "$1" && pwd)
for variant in baseline changed; do
  project="$out/$variant"
  mkdir -p "$project/cad" "$project/datum"
  for entry in upper_arm:180 forearm:100 gripper_palm:50 finger:55; do
    name=${entry%:*}; length=${entry#*:}
    if [[ $variant == changed && $name == forearm ]]; then length=160; fi
    printf '{"commands":[{"command":"solid.box","params":{"length":%s,"width":30,"height":30,"body_name":"%s"}}]}\n' "$length" "$name" > "$out/feature.json"
    solidcraft-cli run "$out/feature.json" --save "$project/cad/$name.solidcraft" --quiet
  done
  cat > "$project/datum/spec.json" <<'JSON'
{"schema":"datum.robot.parameter-spec/2","units":"m","worktrees":{"main":{"parameters":{
"upper_arm_length_m":{"path":"cad/upper_arm.solidcraft","pointer":"/features/0/length","source_units":"mm","unit":"m"},
"forearm_length_m":{"path":"cad/forearm.solidcraft","pointer":"/features/0/length","source_units":"mm","unit":"m"},
"gripper_palm_length_m":{"path":"cad/gripper_palm.solidcraft","pointer":"/features/0/length","source_units":"mm","unit":"m"},
"finger_length_m":{"path":"cad/finger.solidcraft","pointer":"/features/0/length","source_units":"mm","unit":"m"}},
"constants":{"shoulder_height_m":{"value":0.11,"unit":"m"}}}}}
JSON
  sha256sum "$project"/cad/*.solidcraft > "$project/datum/cad-sha256.txt"
  "$generator" generate "$project" "$project/datum/spec.json" main "$project/datum/parameters.json" "$project/datum/parameters.hpp"
done

# The physical object file is compiled once from changed CAD and linked into both cases.
c++ -std=c++17 -Wall -Wextra -Werror -I "$out/changed/datum" -c "$example_dir/physical.cpp" -o "$out/physical.o"
for variant in baseline changed; do
  c++ -std=c++17 -Wall -Wextra -Werror -I "$out/$variant/datum" "$example_dir/controller.cpp" "$out/physical.o" -o "$out/$variant/pick_place"
done
# The runtime controller needs no generated artifacts at all; it links the shared
# evaluation core and reads the spec and saved CAD at startup.
c++ -std=c++17 -Wall -Wextra -Werror -I "$include_dir" -I "$example_dir" \
  "$example_dir/controller_runtime.cpp" -o "$out/pick_place_runtime" \
  "$lib_file" -lpthread -ldl

printf '\nStale controller, changed physical arm:\n'
"$out/baseline/pick_place" fail | tee "$out/baseline/result.txt"
printf '\nGenerated controller, same changed physical arm:\n'
"$out/changed/pick_place" pass | tee "$out/changed/result.txt"
printf '\nRuntime controller (no generated artifacts), current CAD directory on both sides:\n'
"$out/pick_place_runtime" "$out/changed" "$out/changed" pass "$out/changed/runtime-evidence.json" | tee "$out/changed/runtime-result.txt"
printf '\nSame runtime executable pointed at the stale baseline CAD directory:\n'
"$out/pick_place_runtime" "$out/baseline" "$out/changed" fail "$out/baseline/runtime-evidence.json" | tee "$out/baseline/runtime-result.txt"
printf '\nCAD, source-hashed manifests, generated headers, runtime evidence and results: %s\n' "$out"
