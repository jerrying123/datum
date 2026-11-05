# C++ pick-and-place parameter example

This example uses generated C++ constants in a small pick-and-place **kinematic** controller. It needs neither ROS nor `rclpy`. It compares a deliberately stale forearm dimension with parameters generated from changed SolidCraft files, while both runs evaluate the same changed physical dimensions.

The model evaluates grasp, lift and place target positions using the arm's two-link inverse and forward kinematics. It does not simulate contact, a gripper, dynamics, collisions or an object being knocked over. Its 15 mm position tolerance is illustrative, not a hardware or safety limit.

## Run

Install Rust/Cargo, a C++17 compiler, `sha256sum` and SolidCraft with `solidcraft-cli` on PATH. From a checkout of this repository:

```sh
examples/cpp-pick-place/run.sh /tmp/dparams-cpp-pick-place
```

The destination must not exist. The script creates new native SolidCraft box files for baseline and changed dimensions, writes a parameter spec for each, invokes the real `datum-params` generator and compiles both C++ controllers. It compiles `physical.cpp` once against the changed header and links that **same object** into both cases. The controller source is the same for both executables; its include path selects the baseline or changed generated header. It does not edit source CAD or override hashes.

| Parameter | Baseline controller | Changed CAD/controller |
|---|---:|---:|
| Upper arm | 0.180 m | 0.180 m |
| Forearm | 0.100 m | 0.160 m |
| Palm | 0.050 m | 0.050 m |
| Finger | 0.055 m | 0.055 m |
| Effective tool: forearm + palm + finger / 2 | 0.1775 m | 0.2375 m |

The stale controller misses the fixed grasp target by 0.0600 m and stops. The generated controller reaches the grasp, lift and place positions within tolerance. Both use the same target coordinates and changed arm. Each program takes an expected result (`fail` or `pass`) and returns nonzero if the observed result differs, so the script is suitable for a reproducibility check.

The output directory retains each saved CAD file, spec, source-hashed JSON manifest, generated C++ header, SHA-256 inventory, compiled executable and result text. This is a self-contained synthetic arm example; it does not claim equivalence to the exported URDF or the Bullet contact demonstration.

## Code boundary and freshness

`controller.cpp` includes the generated header and uses the named dimensions at the IK boundary. `physical.cpp` includes the changed header in a separate namespace and derives the physical tool length. If you change CAD or the spec, rerun the generator and rebuild before running the controller.

The generated C++ header contains constants; it **does not perform runtime CAD or spec hash checks**. The JSON manifest records those hashes, and the separate Python `datum_interface` loader can validate them, but this example does not use that loader. This workflow generates both headers immediately before compiling; it is not runtime stale-data protection.
