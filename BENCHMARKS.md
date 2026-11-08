# Benchmarks

This page collects the startup measurements currently available for Datum
Parameters. These are measurements on one machine, not performance guarantees.
A dash means no measurement has been recorded; it does not mean zero overhead.

| Example or component | C++ | Python | Coverage |
|---|---|---|---|
| Standalone pick-and-place kinematics | Measured below | No equivalent example in this repository | Process launch through a kinematic plan |
| ROS 2 Jazzy pick-and-place | Not measured | No equivalent example in this repository | No ROS startup or task timing recorded |
| Datum parameter loader | Used by the lazy C++ example below | Measured below | Python interpreter startup plus one parameter load; no simulation |
| External pick-and-place, rover and other demos | Not measured here | Not measured here | No comparable results retained in this repository |

## November 7, 2026: Linux x86-64

Both measurements use the same changed synthetic SolidCraft arm, on a Manjaro
x86-64 machine running Linux 6.18.55. Each has 2 warmup iterations and 30
measured iterations per mode. Runs alternate mode order. Percentiles are
linearly interpolated between sorted samples; 30 observations do not establish
a reliable tail latency. Filesystem cache, other processes and hardware affect
the numbers.

| Measurement | Median | p90 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| C++ generated constants | 1.195 ms | 1.300 ms | 1.324 ms | 1.361 ms | 1.374 ms |
| C++ lazy CAD evaluation | 4.045 ms | 4.200 ms | 4.219 ms | 4.373 ms | 4.431 ms |
| Python checked manifest | 63.384 ms | 66.229 ms | 66.665 ms | 66.877 ms | 66.888 ms |
| Python lazy CAD evaluation | 64.350 ms | 68.610 ms | 69.129 ms | 71.683 ms | 72.704 ms |

The C++ processes execute the complete small kinematic plan. Lazy C++ evaluates
the saved CAD twice, for the controller and physical model. Generated C++
uses compiled constants and does not check their freshness at runtime. In this
run, their p99 estimates differed by 3.011 ms. A separate single timing for
artifact generation was 2.676 ms; C++ compilation took 492.592 ms for the
generated example and 871.858 ms for the lazy example, excluding the Rust
build.

The Python processes use Python 3.14.7. Each starts a fresh interpreter,
imports the package, loads parameters once, and prints the values. The checked
manifest verifies the CAD and spec hashes; lazy mode parses and evaluates CAD.
These numbers include interpreter startup and JSON output. They do not run a
Python robot or simulation and cannot be compared directly to the C++ rows,
which perform a different workload. Neither benchmark includes ROS, URDF export,
physics, Gazebo or Docker startup.

Raw samples and input hashes: [C++ run](benchmarks/results/cpp-pick-place-2026-11-07-linux-x86_64.json)
and [Python run](benchmarks/results/python-loader-2026-11-07-linux-x86_64.json).
The JSON files retain the original temporary project path; the generated CAD
files themselves are not included.

## Reproduce

Install the prerequisites in [the C++ example](examples/cpp-pick-place/README.md),
then run from the repository root with a new output directory:

```sh
examples/cpp-pick-place/run.sh /tmp/dparams-benchmark-project
python3 examples/cpp-pick-place/benchmark.py /tmp/dparams-benchmark-project/changed \
  --warmup 2 --runs 30 --output /tmp/dparams-cpp-benchmark.json
python3 benchmarks/python_startup.py /tmp/dparams-benchmark-project/changed \
  --warmup 2 --runs 30 --output /tmp/dparams-python-benchmark.json
```

The C++ benchmark requires the Rust debug build made by `run.sh`. Both scripts
check that the two modes produce matching output and that the recorded CAD and
spec hashes still match. Re-run measurements for each additional example and
record its workload and conditions before adding a comparison here.
