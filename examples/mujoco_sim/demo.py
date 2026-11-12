"""Load an exported SolidCraft URDF directly in MuJoCo 4 and step it."""
import argparse
from contextlib import nullcontext
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project')
    parser.add_argument('--assembly')
    args = parser.parse_args()
    if bool(args.project) != bool(args.assembly):
        parser.error('--project and --assembly must be supplied together')
    try:
        import mujoco
    except ImportError as exc:
        raise SystemExit('Install MuJoCo 4: python -m pip install "mujoco>=4,<5"') from exc
    if int(mujoco.__version__.split('.')[0]) != 4:
        raise SystemExit('This example requires MuJoCo 4')
    if args.project:
        from datum_parameter_studio.simulation import simulation_input
        context = simulation_input(args.project, args.assembly)
    else:
        context = nullcontext(Path(__file__).parents[1] / 'pybullet_sim/assets/simple_arm.urdf')
    with context as source:
        path = source.urdf_path if hasattr(source, 'urdf_path') else source
        model = mujoco.MjModel.from_xml_path(str(path))
        data = mujoco.MjData(model)
        initial = data.qpos.copy()
        if model.nv:
            data.qfrc_applied[0] = 0.01
        for _ in range(250):
            mujoco.mj_step(model, data)
        print(f'joints={model.njnt} geometries={model.ngeom} initial={initial.tolist()} qpos={data.qpos.tolist()} steps=250')


if __name__ == '__main__':
    main()
