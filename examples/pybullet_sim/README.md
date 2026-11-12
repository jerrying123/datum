# PyBullet simulation example

From the repository root, install PyBullet and run a headless joint-motion demo:

```sh
python -m pip install pybullet
python examples/pybullet_sim/demo.py
```

Add `--gui` to display the simulation. The default uses a small included URDF
with primitive geometry. To run the included SolidCraft assembly through the
runtime adapter, install `solidcraft-cli`, Rust and the Studio package, then:

```sh
python -m pip install ./parameter_studio
cargo build --locked --manifest-path rust/Cargo.toml --bin studio-urdf-preflight
PATH="$PWD/rust/target/debug:$PATH" python examples/pybullet_sim/demo.py --project examples/pybullet_sim/cad --assembly assembly.solidcraft
```

Supply another saved assembly with the same options. The first supported CAD
profile is described in the [Studio guide](../../parameter_studio/README.md#experimental-assembly-to-urdf).
The adapter checks export freshness and rejects known fidelity failures, but
cannot prove CAD transforms or physics readiness. The generated meshes remain
available until the simulation closes the input context. `cad/part.solidcraft`
and `cad/assembly.solidcraft` were authored for this example with SolidCraft:
two occurrences of a 100 × 50 × 40 mm box, connected by a revolute joint.
No user CAD is included.
