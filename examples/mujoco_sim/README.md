# MuJoCo 4 headless demo

Install MuJoCo 4 with `python -m pip install 'mujoco>=4,<5'`, then run
`python examples/mujoco_sim/demo.py`. The default loads the included simple URDF.

To export and simulate the included SolidCraft assembly, install the Studio
package and build preflight as described in [the PyBullet example](../pybullet_sim/README.md),
then run from the repository root:

```sh
PATH="$PWD/rust/target/debug:$PATH" python examples/mujoco_sim/demo.py --project examples/pybullet_sim/cad --assembly assembly.solidcraft
```

The demo loads the exported URDF directly in MuJoCo 4 and applies a small joint
force for 250 headless steps, keeping the exported mesh bundle alive throughout.
MuJoCo may compile URDF semantics differently from other engines. These steps
are an integration example, not a validation of CAD fidelity or physics.
