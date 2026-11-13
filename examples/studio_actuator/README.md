# Rotary actuator arm for Studio

Open this directory as the Studio project and select `assembly.solidcraft`.
The linked `mount.solidcraft` and `arm.solidcraft` must remain alongside it.
Under Simulation, start a PyBullet or MuJoCo session, select the `Output`
revolute joint, pause, and use **Set pose** with a position such as 0.5 rad.
Return to zero before trying position control. For an illustrative conservative
profile inspired by the ROBOTIS DYNAMIXEL XM430-W350-T at 12 V, enter Kp 1,
Kd 0.2 and maximum torque 0.82 N·m. The gains are chosen for this example,
not identified hardware properties. The saved joint limits are ±90 degrees,
also chosen for this example.

ROBOTIS lists 4.1 N·m stall torque, 46 rpm no-load speed (4.82 rad/s),
82 g mass, and 28.5 × 46.5 × 34 mm dimensions at 12 V in its
[XM430-W350-T product specifications](https://robotis.us/products/dynamixel-xm430-w350-t).
The manufacturer labels 0.82 N·m an **estimated** continuous torque, calculated
as 20% of stall torque; it is used here as a constant cap, not a measured
continuous rating. The Studio PD controller clamps torque in both engines but
does not enforce the 46 rpm no-load speed or a torque–speed curve. It does not
model current, thermal behavior, backlash, gearing losses, or the servo's own
controller. Do not infer hardware performance from this simulation.

The CAD remains a conceptual stand-in, not an XM430 dimensional model: a
90 × 70 × 8 mm mounting plate with four 6 mm through holes on a 70 × 50 mm
pattern, a 42 × 38 × 32 mm housing, a 24 mm diameter output boss, and a
100 × 18 × 6 mm arm. The hole pattern, housing, boss and plate are design
estimates, not manufacturer specifications. The boss represents an output
interface; the gearbox, shaft details and fasteners are not modeled. The
manufacturer's 82 g mass is not assigned to the exported inertials; review
inertials and collision behavior before physics or hardware use.

For a headless PyBullet run from the repository root:

```sh
python -m pip install ./parameter_studio pybullet
cargo build --locked --manifest-path rust/Cargo.toml --bin studio-urdf-preflight
PATH="$PWD/rust/target/debug:$PATH" python examples/pybullet_sim/demo.py --project examples/studio_actuator --assembly assembly.solidcraft
```

The standalone demo uses its own 20 N·m controller, not the Studio profile above.
