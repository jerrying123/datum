# CAD feature history and gripper configurations

Run Studio with this example:

```sh
dparam-std up --source-repo /path/to/datum --project /path/to/datum/examples/cad_history
```

Studio opens the assembly. In **CAD feature state**, select **Parallel gripper**
or **Rotary gripper** to swap the end effector, **No gripper** to remove it, or
**Mount only** to see the mount. The feature-history entries show earlier points
on the linear timeline. The selected state is evaluated in a temporary capture;
the saved CAD is unchanged. Simulation and URDF export use the same selection.

The grippers are illustrative static parts, not articulated or physically
validated mechanisms. Suppressed parts can leave empty links in URDF; inspect
export diagnostics. The Studio parameter generator reads Saved state; while an
alternate state is selected it fails closed instead of returning dimensions
from the wrong state. To make a configuration available as a parameter source,
materialize it to a new file from the host, then map that file in Studio:

```sh
dparam-std materialize --project /path/to/datum/examples/cad_history \
  --assembly assembly.solidcraft --configuration "Parallel gripper" \
  --output /path/to/datum/examples/cad_history/derived/parallel.solidcraft
```

The command activates the selection in a temporary copy and leaves the saved
assembly untouched. `solidcraft-cli` must be installed on the host. SolidCraft
does not expose branch tips.
