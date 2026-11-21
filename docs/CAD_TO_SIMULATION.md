# CAD change to the next simulation run

This walkthrough demonstrates a saved SolidCraft dimension changing the input used by a simulation process on its next run. It uses the standalone C++ runtime controller and a disposable project. It does not require ROS 2.

The standalone [C++ example](../examples/cpp-pick-place/README.md) builds a
kinematic pick-and-place simulator and a runtime controller. From the repository
root, with the quick-install environment active, a C++17 compiler, `sha256sum`,
and SolidCraft's `solidcraft-cli` on `PATH`, run the following. The destination
must not exist; it is a disposable project created by the script.

```sh
examples/cpp-pick-place/run.sh /tmp/dparams-walkthrough
/tmp/dparams-walkthrough/pick_place_runtime /tmp/dparams-walkthrough/baseline /tmp/dparams-walkthrough/baseline pass /tmp/dparams-walkthrough/before.json
python -c "from datum_interface import load_runtime; print(load_runtime('/tmp/dparams-walkthrough/baseline')['forearm_length_m'], 'm')"
```

The baseline forearm is 100 mm, so the printed controller input is `0.1 m`.
Now change and save the disposable CAD: this command creates a new native box
with a 160 mm length at the same mapped feature and saves it over the example's
forearm. In your own project, edit and save the mapped dimension in SolidCraft
instead. Do not overwrite your own CAD with this command.

```sh
cat > /tmp/dparams-walkthrough/edited-forearm.json <<'JSON'
{"commands":[{"command":"solid.box","params":{"length":160,"width":30,"height":30,"body_name":"forearm"}}]}
JSON
rm /tmp/dparams-walkthrough/baseline/cad/forearm.solidcraft
solidcraft-cli run /tmp/dparams-walkthrough/edited-forearm.json --save /tmp/dparams-walkthrough/baseline/cad/forearm.solidcraft --quiet
/tmp/dparams-walkthrough/pick_place_runtime /tmp/dparams-walkthrough/baseline /tmp/dparams-walkthrough/baseline pass /tmp/dparams-walkthrough/after.json
python -c "from datum_interface import load_runtime; print(load_runtime('/tmp/dparams-walkthrough/baseline')['forearm_length_m'], 'm')"
```

The next run reads `0.16 m`; the runtime evidence files record the values and
source hashes actually consumed. Both project arguments above point to the same
saved CAD: the first supplies controller dimensions and the second supplies the
simulated arm dimensions. The simulation reports its grasp, lift and place
stages. It is a kinematic model, not a CAD geometry or contact simulation;
changing a controller parameter alone does not update a simulator's geometry.
The stale/current comparison printed by `run.sh` uses two separately created
projects and is not itself an edit-and-rerun demonstration.

Runtime loading takes a fresh snapshot at process startup; restart after saving.
For generated artifacts, regenerate after the save: checked Python manifests
reject changed sources, and C++ headers require regeneration **and a rebuild**.
For a ROS 2 generated-header consumer, see the
[ROS 2 example](../examples/ros2_cpp_pick_place/README.md): regenerate its header
and rebuild the node before restarting it. For actual exported CAD geometry, see
the separate [PyBullet example](../examples/pybullet_sim/README.md).


