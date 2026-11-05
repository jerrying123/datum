#!/usr/bin/env bash
# Run inside an environment with ROS 2 Jazzy and control_msgs installed.
set -eo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ $# != 2 || ! -f "$1/parameters.hpp" || -e "$2" ]]; then
  echo 'Usage: smoke.sh GENERATED_HEADER_DIRECTORY NEW_WORKSPACE_DIRECTORY' >&2
  exit 2
fi
header=$(cd "$1" && pwd)
mkdir -p "$2/src"
work=$(cd "$2" && pwd)
cp -R "$repo/examples/ros2_cpp_pick_place" "$work/src/dparams_cpp_pick_place"
source /opt/ros/jazzy/setup.bash
cd "$work"
colcon build --event-handlers console_direct+ --cmake-args "-DDPARAMS_HEADER_DIR=$header"
source "$work/install/setup.bash"
ros2 run dparams_cpp_pick_place motor_sim > "$work/motor.log" 2>&1 & motor_pid=$!
ros2 run dparams_cpp_pick_place pick_place > "$work/controller.log" 2>&1 & controller_pid=$!
cleanup(){ kill "$motor_pid" "$controller_pid" 2>/dev/null || true; }
trap cleanup EXIT
if ! timeout 20s ros2 topic pub --once /pick_target geometry_msgs/msg/PoseStamped '{header: {frame_id: base_link}, pose: {position: {x: 0.25, y: 0.0, z: 0.2}, orientation: {w: 1.0}}}'; then
  cat "$work/controller.log" "$work/motor.log"; exit 1
fi
for _ in $(seq 1 30); do
  if grep -q 'Pick and place sequence complete' "$work/controller.log"; then
    cat "$work/controller.log"
    exit 0
  fi
  sleep 1
done
cat "$work/controller.log" "$work/motor.log"
exit 1
