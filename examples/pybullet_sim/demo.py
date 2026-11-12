"""Run a small self-contained PyBullet arm, or load a SolidCraft assembly."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='project containing saved SolidCraft files')
    parser.add_argument('--assembly', help='project-relative .solidcraft assembly path')
    parser.add_argument('--gui', action='store_true', help='show the PyBullet GUI')
    args = parser.parse_args()
    if bool(args.project) != bool(args.assembly):
        parser.error('--project and --assembly must be supplied together')
    try:
        import pybullet as bullet
    except ImportError as exc:
        raise SystemExit('Install optional dependency with: python -m pip install pybullet') from exc
    if args.project:
        from datum_parameter_studio.simulation import simulation_input
        source_context = simulation_input(args.project, args.assembly)
    else:
        from contextlib import nullcontext
        source_context = nullcontext(Path(__file__).parent / 'assets' / 'simple_arm.urdf')
    with source_context as source:
        urdf = source.urdf_path if hasattr(source, 'urdf_path') else source
        client = bullet.connect(bullet.GUI if args.gui else bullet.DIRECT)
        try:
            bullet.setGravity(0, 0, -9.81, physicsClientId=client)
            body = bullet.loadURDF(str(urdf), useFixedBase=True, physicsClientId=client)
            count = bullet.getNumJoints(body, physicsClientId=client)
            movable = [j for j in range(count) if bullet.getJointInfo(body, j, physicsClientId=client)[2] in (bullet.JOINT_REVOLUTE, bullet.JOINT_PRISMATIC)]
            if movable:
                bullet.setJointMotorControl2(body, movable[0], bullet.POSITION_CONTROL, targetPosition=0.5, force=20, physicsClientId=client)
            for _ in range(240):
                bullet.stepSimulation(physicsClientId=client)
            positions = [bullet.getJointState(body, j, physicsClientId=client)[0] for j in range(count)]
            print(f'Loaded body {body}: {count} joints; joint positions {positions}')
        finally:
            bullet.disconnect(physicsClientId=client)


if __name__ == '__main__':
    main()
