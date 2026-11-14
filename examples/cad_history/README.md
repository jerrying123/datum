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
export diagnostics. Parameter generation uses the saved state and is unavailable
while an alternate state is selected. SolidCraft does not expose branch tips.
