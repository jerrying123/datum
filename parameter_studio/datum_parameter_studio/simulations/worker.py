"""Atomic JSON spool. Poses use metres and quaternion xyzw; time uses seconds."""
import argparse
import ctypes
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from ..simulation import simulation_input
from ..worker_health import WorkerHealth
from .gazebo import GazeboEngine, capability as gazebo_capability


def atomic(path, value):
    path = Path(path)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with tmp.open('x') as out:
            json.dump(value, out, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)



def publish_versioned(directory, name, value):
    """Publish unique immutable snapshots so shared mounts do not cache old inodes."""
    directory = Path(directory)
    atomic(directory / (name + '.json'), value)  # compatibility with host recovery/readers
    atomic(directory / ('%s-%020d.json' % (name, time.time_ns())), value)


def capabilities():
    return {name: {'supported': importlib.util.find_spec(module) is not None,
                   'dependency': module, 'commands': list(Session.commands)}
            for name, module in [('mujoco', 'mujoco'), ('pybullet', 'pybullet')]} | {
        'gazebo': {**gazebo_capability(), 'commands': [c for c in Session.commands if c not in ('set_joint', 'seek')]}}


class Engine:
    def __init__(self, backend, path, couplings=None):
        self.couplings = couplings or []
        self.backend = backend
        self.client = None
        self.actuators = {}
        if backend == 'mujoco':
            import mujoco
            self.api = mujoco
            # Preserve link identities and visual geometry for live telemetry.
            # Keep the original exported URDF intact as provenance evidence.
            tree = ET.parse(path)
            extension = tree.getroot().find('mujoco')
            if extension is None:
                extension = ET.SubElement(tree.getroot(), 'mujoco')
            compiler = extension.find('compiler')
            if compiler is None:
                compiler = ET.SubElement(extension, 'compiler')
            compiler.set('fusestatic', 'false')
            compiler.set('discardvisual', 'false')
            compiled_path = Path(path).with_name('datum-mujoco.urdf')
            tree.write(compiled_path, encoding='utf-8', xml_declaration=True)
            spec = mujoco.MjSpec.from_file(str(compiled_path))
            for coupling in self.couplings:
                spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1=coupling['driven'],
                                  name2=coupling['driver'], data=[0, 1] + [0] * 10)
            self.model = spec.compile()
            self.data = mujoco.MjData(self.model)
            mujoco.mj_forward(self.model, self.data)
        elif backend == 'pybullet':
            import pybullet
            self.api = pybullet
            self.client = pybullet.connect(pybullet.DIRECT)
            try:
                pybullet.setGravity(0, 0, -9.81, physicsClientId=self.client)
                pybullet.setTimeStep(1 / 240, physicsClientId=self.client)
                self.body = pybullet.loadURDF(str(path), useFixedBase=True, physicsClientId=self.client)
                for i in range(pybullet.getNumJoints(self.body, physicsClientId=self.client)):
                    if pybullet.getJointInfo(self.body, i, physicsClientId=self.client)[2] in (pybullet.JOINT_REVOLUTE, pybullet.JOINT_PRISMATIC):
                        pybullet.setJointMotorControl2(self.body, i, pybullet.VELOCITY_CONTROL, force=0, physicsClientId=self.client)
                for coupling in self.couplings:
                    driver = self._joint(coupling['driver'], 0)
                    driven = self._joint(coupling['driven'], 0)
                    constraint = pybullet.createConstraint(self.body, driver, self.body, driven,
                        pybullet.JOINT_GEAR, [1, 0, 0], [0, 0, 0], [0, 0, 0], physicsClientId=self.client)
                    pybullet.changeConstraint(constraint, gearRatio=-1, maxForce=1000, erp=0.8, physicsClientId=self.client)
                self.saved = pybullet.saveState(physicsClientId=self.client)
                self.t = 0.
            except Exception:
                self.close()
                raise
        else:
            raise ValueError('Unsupported backend: ' + str(backend))

    @property
    def timestep(self):
        return float(self.model.opt.timestep) if self.backend == 'mujoco' else 1 / 240

    def checkpoint(self):
        if self.backend == 'mujoco':
            import numpy as np
            flags = self.api.mjtState.mjSTATE_INTEGRATION
            state = np.empty(self.api.mj_stateSize(self.model, flags), dtype=np.float64)
            self.api.mj_getState(self.model, self.data, state, flags)
            return (state, dict(self.actuators))
        return (self.api.saveState(physicsClientId=self.client), self.t, dict(self.actuators))

    def restore_checkpoint(self, checkpoint):
        if self.backend == 'mujoco':
            state, actuators = checkpoint
            self.api.mj_setState(self.model, self.data, state, self.api.mjtState.mjSTATE_INTEGRATION)
            self.api.mj_forward(self.model, self.data)
        else:
            state, self.t, actuators = checkpoint
            self.api.restoreState(state, physicsClientId=self.client)
            for i in range(self.api.getNumJoints(self.body, physicsClientId=self.client)):
                self.api.setJointMotorControl2(self.body, i, self.api.VELOCITY_CONTROL, force=0, physicsClientId=self.client)
        self.actuators = dict(actuators)

    def release_checkpoint(self, checkpoint):
        if self.backend == 'pybullet' and self.client is not None:
            self.api.removeState(checkpoint[0], physicsClientId=self.client)

    def step(self):
        # PD gains use SI joint units; effort is N for slides and N m for hinges.
        for i, (target, kp, kd, limit) in self.actuators.items():
            if self.backend == 'mujoco':
                dof = self.model.jnt_dofadr[i]
                q, v = self.data.qpos[self.model.jnt_qposadr[i]], self.data.qvel[dof]
                self.data.qfrc_applied[dof] = max(-limit, min(limit, kp * (target - q) - kd * v))
            else:
                q, v = self.api.getJointState(self.body, i, physicsClientId=self.client)[:2]
                effort = max(-limit, min(limit, kp * (target - q) - kd * v))
                self.api.setJointMotorControl2(self.body, i, self.api.TORQUE_CONTROL, force=effort, physicsClientId=self.client)
        if self.backend == 'mujoco':
            self.api.mj_step(self.model, self.data)
        else:
            self.api.stepSimulation(physicsClientId=self.client)
            self.t += 1 / 240

    def reset(self):
        self.actuators.clear()
        if self.backend == 'mujoco':
            self.api.mj_resetData(self.model, self.data)
            self.api.mj_forward(self.model, self.data)
        else:
            self.api.restoreState(self.saved, physicsClientId=self.client)
            for i in range(self.api.getNumJoints(self.body, physicsClientId=self.client)):
                self.api.setJointMotorControl2(self.body, i, self.api.VELOCITY_CONTROL, force=0, physicsClientId=self.client)
            self.t = 0.

    def _joint(self, name, value):
        if not isinstance(name, str) or not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError('Joint and finite position are required')
        if self.backend == 'mujoco':
            a, m = self.api, self.model
            index = a.mj_name2id(m, a.mjtObj.mjOBJ_JOINT, name)
            if index < 0 or int(m.jnt_type[index]) not in (int(a.mjtJoint.mjJNT_HINGE), int(a.mjtJoint.mjJNT_SLIDE)):
                raise ValueError('Unknown or unsupported joint')
            if m.jnt_limited[index] and not m.jnt_range[index, 0] <= value <= m.jnt_range[index, 1]:
                raise ValueError('Position outside joint limits')
            return index
        else:
            a, c, b = self.api, self.client, self.body
            for i in range(a.getNumJoints(b, physicsClientId=c)):
                info = a.getJointInfo(b, i, physicsClientId=c)
                if info[1].decode() == name and info[2] in (a.JOINT_REVOLUTE, a.JOINT_PRISMATIC):
                    if info[8] <= info[9] and not info[8] <= value <= info[9]:
                        raise ValueError('Position outside joint limits')
                    return i
            raise ValueError('Unknown or unsupported joint')

    def set_joint(self, name, value):
        i = self._joint(name, value)
        paired = None
        for coupling in self.couplings:
            if name in (coupling['driver'], coupling['driven']):
                paired = self._joint(coupling['driven'] if name == coupling['driver'] else coupling['driver'], value)
        if self.backend == 'mujoco':
            self.data.qpos[self.model.jnt_qposadr[i]] = value
            self.data.qvel[self.model.jnt_dofadr[i]] = 0
            if paired is not None:
                self.data.qpos[self.model.jnt_qposadr[paired]] = value
                self.data.qvel[self.model.jnt_dofadr[paired]] = 0
            self.api.mj_forward(self.model, self.data)
        else:
            self.api.resetJointState(self.body, i, value, targetVelocity=0, physicsClientId=self.client)
            if paired is not None:
                self.api.resetJointState(self.body, paired, value, targetVelocity=0, physicsClientId=self.client)

    def set_position_control(self, name, target, profile):
        if not isinstance(profile, dict) or set(profile) != {'kp', 'kd', 'max_force'}:
            raise ValueError('Profile requires kp, kd and max_force')
        for key in ('kp', 'kd', 'max_force'):
            x = profile[key]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or (key == 'max_force' and x == 0):
                raise ValueError('Invalid actuator profile')
        if any(name == coupling['driven'] for coupling in self.couplings):
            raise ValueError('Command the driver joint for this coupled pair')
        i = self._joint(name, target)
        self.actuators[i] = (target, profile['kp'], profile['kd'], profile['max_force'])

    def snapshot(self):
        if self.backend == 'mujoco':
            a, m, d = self.api, self.model, self.data
            links = [{'id': a.mj_id2name(m, a.mjtObj.mjOBJ_BODY, i) or str(i),
                      'position': d.xpos[i].tolist(),
                      'quaternion': d.xquat[i][[1, 2, 3, 0]].tolist()} for i in range(1, m.nbody)]
            joints = [{'id': a.mj_id2name(m, a.mjtObj.mjOBJ_JOINT, i),
                       'position': float(d.qpos[m.jnt_qposadr[i]]), 'velocity': float(d.qvel[m.jnt_dofadr[i]])}
                      for i in range(m.njnt) if int(m.jnt_type[i]) in (int(a.mjtJoint.mjJNT_HINGE), int(a.mjtJoint.mjJNT_SLIDE))]
            return {'time': float(d.time), 'links': links, 'joints': joints}
        a, c, b = self.api, self.client, self.body
        p, q = a.getBasePositionAndOrientation(b, physicsClientId=c)
        dynamics = a.getDynamicsInfo(b, -1, physicsClientId=c)
        inv_p, inv_q = a.invertTransform(dynamics[3], dynamics[4])
        p, q = a.multiplyTransforms(p, q, inv_p, inv_q)
        links = [{'id': a.getBodyInfo(b, physicsClientId=c)[0].decode(), 'position': list(p), 'quaternion': list(q)}]
        joints = []
        for i in range(a.getNumJoints(b, physicsClientId=c)):
            info = a.getJointInfo(b, i, physicsClientId=c)
            pose = a.getLinkState(b, i, physicsClientId=c)
            links.append({'id': info[12].decode(), 'position': list(pose[4]), 'quaternion': list(pose[5])})
            state = a.getJointState(b, i, physicsClientId=c)
            if info[2] in (a.JOINT_REVOLUTE, a.JOINT_PRISMATIC):
                joints.append({'id': info[1].decode(), 'position': state[0], 'velocity': state[1]})
        return {'time': self.t, 'links': links, 'joints': joints}

    def close(self):
        if self.client is not None:
            self.api.disconnect(self.client)
            self.client = None


class Session:
    commands = ('pause', 'resume', 'step', 'reset', 'stop', 'record_start', 'record_stop', 'set_joint', 'set_position_control', 'set_speed', 'seek')

    def __init__(self, project, directory):
        self.project, self.directory = project, Path(directory)
        self.engine = self.source = self.record = None
        self.state, self.error, self.backend = 'starting', None, None
        self.epoch = self.seq = 0
        self.next_snapshot_cleanup = 0.0
        self.seen = set()
        self.speed, self.accumulator, self.last_tick = 1.0, 0.0, time.monotonic()
        self.history, self.history_cursor, self.history_next, self.history_generation = [], -1, 0, 0
        self.rate_wall, self.rate_sim, self.actual_speed = time.monotonic(), 0.0, 0.0

    def clear_history(self):
        if self.engine and hasattr(self.engine, 'release_checkpoint'):
            for entry in self.history:
                self.engine.release_checkpoint(entry[1])
        self.history, self.history_cursor = [], -1
        self.history_generation += 1

    def capture_checkpoint(self):
        if not self.engine or not hasattr(self.engine, 'checkpoint'):
            return
        if self.history_cursor + 1 < len(self.history):
            self.history_generation += 1
        for entry in self.history[self.history_cursor + 1:]:
            self.engine.release_checkpoint(entry[1])
        del self.history[self.history_cursor + 1:]
        self.history.append((self.history_next, self.engine.checkpoint()))
        self.history_next += 1
        self.history_cursor = len(self.history) - 1
        # Roughly five seconds at 500 Hz; memory is bounded per session.
        if len(self.history) > 2501:
            self.engine.release_checkpoint(self.history.pop(0)[1])
            self.history_cursor -= 1
            self.history_generation += 1

    def seek(self, frame, generation):
        if self.state != 'paused':
            raise ValueError('Pause before seeking')
        if isinstance(frame, bool) or not isinstance(frame, int) or isinstance(generation, bool) or not isinstance(generation, int):
            raise ValueError('Invalid timeline position')
        if generation != self.history_generation:
            raise ValueError('Timeline changed; refresh before seeking')
        if frame < 0 or frame >= len(self.history):
            raise ValueError('Timeline position is no longer available')
        index = frame
        self.engine.restore_checkpoint(self.history[index][1])
        self.history_cursor = index
        self.epoch += 1
        self.accumulator = 0.0

    def publish(self):
        try:
            sample = self.engine.snapshot() if self.engine else {'time': 0, 'links': [], 'joints': []}
        except Exception:
            if self.state != 'failed': raise
            sample = {'time': 0, 'links': [], 'joints': []}
        sample.update(epoch=self.epoch, seq=self.seq)
        now = time.monotonic()
        if now - self.rate_wall >= .5:
            self.actual_speed = max(0.0, (sample['time'] - self.rate_sim) / (now - self.rate_wall)) if self.state == 'running' else 0.0
            self.rate_wall, self.rate_sim = now, sample['time']
        publish_versioned(self.directory, 'state', sample)
        publish_versioned(self.directory, 'status', dict(state=self.state, backend=self.backend,
               error=self.error, time=sample['time'], epoch=self.epoch, seq=self.seq,
               recording=self.record is not None, speed=self.speed, actual_speed=self.actual_speed,
               timeline={'min': 0, 'max': len(self.history)-1, 'current': self.history_cursor,
                         'generation': self.history_generation} if self.history else None))
        if time.monotonic() >= self.next_snapshot_cleanup:
            self.next_snapshot_cleanup = time.monotonic() + 2
            for kind in ('state', 'status'):
                for old in sorted(self.directory.glob(kind + '-*.json'))[:-150]:
                    old.unlink(missing_ok=True)
        if self.record:
            if self.record.tell() >= 64 * 1024 * 1024:
                self.record.close(); self.record = None
                self.error = 'Recording stopped: 64 MiB limit reached'
            else:
                self.record.write(json.dumps({'type': 'state', **sample}, allow_nan=False) + '\n')
                self.record.flush()

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'commands').mkdir(exist_ok=True)
        (self.directory / 'acks').mkdir(exist_ok=True)
        atomic(self.directory / 'capabilities.json', capabilities())
        request = json.loads((self.directory / 'request.json').read_text())
        self.backend = request['backend']
        if not capabilities().get(self.backend, {}).get('supported'):
            raise ValueError('Backend unavailable: ' + str(self.backend))
        self.source = simulation_input(self.project, request['assembly'], supports_couplings=self.backend in ('mujoco', 'pybullet', 'gazebo'))
        target = self.directory / 'bundle'
        shutil.copytree(self.source.bundle, target)
        path = target / Path(self.source.urdf_path).relative_to(self.source.bundle)
        root = ET.parse(path).getroot()
        couplings = getattr(self.source, 'couplings', [])
        atomic(self.directory / 'scene.json', {'links': [dict(id=l.get('name'), name=l.get('name'),
               geometry=[ET.tostring(v, encoding='unicode') for v in l.findall('visual')]) for l in root.findall('link')], 'couplings': couplings})
        self.engine = GazeboEngine(path, couplings) if self.backend == 'gazebo' else Engine(self.backend, path, couplings)
        self.state = 'paused'
        self.capture_checkpoint()
        self.last_tick = time.monotonic()
        self.publish()

    def tick(self):
        for path in sorted((self.directory / 'commands').glob('*.json'), key=lambda p: (p.stat().st_mtime_ns, p.name)):
            if path.name in self.seen:
                continue
            self.seen.add(path.name)
            ack = self.directory / 'acks' / path.name
            atomic(ack, {'id':path.stem, 'status':'processing'})
            outcome = {'id':path.stem, 'status':'applied'}
            try:
                item = json.loads(path.read_text())
                if item['id'] != path.stem or item['command'] not in self.commands:
                    raise ValueError('Invalid command or ID')
                command = item['command']
                if command == 'stop': self.state = 'stopped'
                elif command == 'pause': self.state = 'paused'
                elif command == 'resume':
                    self.state = 'running'
                    self.accumulator = 0.0
                    self.last_tick = time.monotonic()
                elif command == 'step':
                    if self.state != 'paused': raise ValueError('Pause before stepping')
                    self.engine.step()
                    self.capture_checkpoint()
                elif command == 'reset':
                    self.engine.reset(); self.epoch += 1
                    self.clear_history(); self.capture_checkpoint()
                    self.accumulator = 0.0; self.last_tick = time.monotonic()
                elif command == 'seek': self.seek(item.get('frame'), item.get('generation'))
                elif command == 'set_speed':
                    speed = item.get('speed')
                    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or not 0.25 <= speed <= 4:
                        raise ValueError('Unsupported playback speed')
                    self.speed = float(speed)
                    self.accumulator = 0.0; self.last_tick = time.monotonic()
                elif command == 'set_joint':
                    if self.state != 'paused': raise ValueError('Pause before setting joint positions')
                    if not hasattr(self.engine, 'set_joint'): raise ValueError('Joint positioning unavailable for this backend')
                    self.engine.set_joint(item.get('joint'), item.get('position'))
                    self.capture_checkpoint()
                elif command == 'set_position_control':
                    if not hasattr(self.engine, 'set_position_control'): raise ValueError('Position control unavailable for this backend')
                    self.engine.set_position_control(item.get('joint'), item.get('position'), item.get('profile'))
                    self.capture_checkpoint()
                elif command == 'record_start' and self.record is None:
                    folder = self.directory / 'recordings'
                    folder.mkdir(exist_ok=True)
                    existing = list(folder.glob('*.jsonl'))
                    if len(existing) >= 10 or sum(p.stat().st_size for p in existing) >= 128 * 1024 * 1024:
                        raise ValueError('Recording storage limit reached for this session')
                    self.record = (folder / (uuid.uuid4().hex + '.jsonl')).open('x')
                    self.record.write(json.dumps({'type': 'metadata', 'schema': 'datum.simulation-recording/1',
                        'backend': self.backend, 'source_report': self.source.result.report,
                        'simulation_couplings': getattr(self.source, 'couplings', []),
                        'backend_version': getattr(getattr(self.engine, 'api', None), '__version__', None),
                        'started_at_unix': time.time()}, allow_nan=False) + '\n')
                elif command == 'record_stop' and self.record:
                    self.record.write(json.dumps({'type':'command','command':command,'joint':item.get('joint'),'position':item.get('position'),'profile':item.get('profile'),'frame':item.get('frame'),'generation':item.get('generation'),'speed':item.get('speed'),'epoch':self.epoch,'seq':self.seq}) + '\n')
                    self.seq += 1
                    self.publish()
                    self.record.close(); self.record = None
                if self.record:
                    self.record.write(json.dumps({'type':'command','command':command,'joint':item.get('joint'),'position':item.get('position'),'profile':item.get('profile'),'frame':item.get('frame'),'generation':item.get('generation'),'speed':item.get('speed'),'epoch':self.epoch,'seq':self.seq}) + '\n')
                self.error = None
            except (ValueError, KeyError, OSError) as exc:
                self.error = str(exc)
                outcome = {'id':path.stem, 'status':'rejected', 'error':str(exc)}
            except Exception as exc:
                atomic(ack.with_suffix('.done.json'), {'id':path.stem, 'status':'unknown', 'error':str(exc)})
                atomic(ack, {'id':path.stem, 'status':'unknown', 'error':str(exc)})
                raise
            atomic(ack.with_suffix('.done.json'), outcome)
            atomic(ack, outcome)
            path.unlink(missing_ok=True)
            self.seq += 1
            self.publish()
            if self.state == 'stopped': break
        now = time.monotonic()
        if self.state == 'running':
            dt = getattr(self.engine, 'timestep', 1 / 240)
            self.accumulator = min(self.accumulator + max(0.0, now - self.last_tick) * self.speed, .25)
            steps = min(int(self.accumulator / dt), 64)
            if steps and hasattr(self.engine, 'step_many') and not hasattr(self.engine, 'checkpoint'):
                before = self.engine.snapshot()['time']
                self.engine.step_many(steps)
                advanced = self.engine.snapshot()['time'] - before
                # Gazebo can report a later request before every requested step
                # is visible; pace against its observed simulation clock.
                self.accumulator = max(0.0, self.accumulator - max(0.0, advanced))
            else:
                for _ in range(steps):
                    self.engine.step()
                    self.capture_checkpoint()
                    self.accumulator -= dt
        else:
            self.accumulator = 0.0
        self.last_tick = now
        self.seq += 1
        self.publish()

    def close(self):
        if self.record: self.record.close(); self.record = None
        self.clear_history()
        if self.engine: self.engine.close()
        if self.source: self.source.close()

    def run(self):
        def stop(_signum, _frame):
            self.state = 'stopped'
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            self.start()
            while self.state != 'stopped':
                self.tick()
                time.sleep(.01)
        except Exception as exc:
            self.state, self.error = 'failed', str(exc)
        finally:
            try: self.publish()
            finally: self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', nargs='?')
    parser.add_argument('session', nargs='?')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--project', dest='serve_project')
    parser.add_argument('--spool')
    args = parser.parse_args()
    if args.serve:
        if not args.serve_project or not args.spool:
            parser.error('--serve requires --project and --spool')
        serve(args.serve_project, args.spool)
    elif args.project and args.session:
        expected_parent = os.environ.get('DATUM_SIM_SUPERVISOR_PID')
        if expected_parent:
            ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)
            if os.getppid() != int(expected_parent):
                raise SystemExit('Simulation supervisor exited')
        Session(args.project, args.session).run()
    else:
        parser.error('provide project and session')


def mark_unfinished_commands(directory):
    commands, acks = directory / 'commands', directory / 'acks'
    if not commands.is_dir() or commands.is_symlink() or not acks.is_dir() or acks.is_symlink():
        return
    for path in commands.glob('*.json'):
        try:
            ack = acks / path.name
            completed = ack.with_suffix('.done.json')
            previous = json.loads(completed.read_text()) if completed.exists() else (json.loads(ack.read_text()) if ack.exists() else {})
            if previous.get('status') not in ('applied', 'rejected'):
                outcome = {'id':path.stem, 'status':'unknown', 'error':'Session stopped before command outcome was confirmed'}
                atomic(completed, outcome)
                atomic(ack, outcome)
        except (OSError, ValueError):
            continue


def serve(project, spool):
    root = Path(spool)
    root.mkdir(parents=True, exist_ok=True)
    stopping = False
    child = None
    active = None
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    available = capabilities()
    # Recover sessions whose owning supervisor died. Only signal a process when
    # both its PID start time and command line still identify our worker.
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or len(directory.name) != 32 or any(c not in '0123456789abcdef' for c in directory.name):
            continue
        try:
            status = json.loads((directory / 'status.json').read_text())
            if status.get('state') in ('stopped', 'failed'):
                mark_unfinished_commands(directory)
                continue
            if status.get('state') == 'queued':
                continue
            identity = json.loads((directory / 'worker.pid').read_text())
            pid = identity['pid']
            start = Path(f'/proc/{pid}/stat').read_text().split()[21]
            cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if start == identity['start'] and b'datum_parameter_studio.simulations.worker' in cmd and str(directory).encode() in cmd:
                os.killpg(pid, signal.SIGTERM)
        except (OSError, ValueError, KeyError, IndexError):
            pass
        mark_unfinished_commands(directory)
        publish_versioned(directory, 'status', {'state': 'failed', 'error': 'Simulation supervisor restarted'})

    heartbeat = [time.monotonic()]
    health = WorkerHealth(root, lambda: {
        'available': not stopping and time.monotonic() - heartbeat[0] < 5,
        'capabilities': available,
    })
    try:
        while not stopping:
            heartbeat[0] = time.monotonic()
            if child is not None and child.poll() is not None:
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try:
                    status = json.loads((active / 'status.json').read_text())
                    mark_unfinished_commands(active)
                    if status.get('state') not in ('stopped', 'failed'):
                        publish_versioned(active, 'status', {'state': 'failed', 'error': 'Simulation worker exited unexpectedly'})
                except (OSError, ValueError):
                    pass
                child = None
                active = None
            if child is None:
                for directory in sorted(root.iterdir()):
                    if not directory.is_dir() or directory.is_symlink() or len(directory.name) != 32 or any(c not in '0123456789abcdef' for c in directory.name):
                        continue
                    try:
                        status = json.loads((directory / 'status.json').read_text())
                        if status.get('state') != 'queued' or not (directory / 'request.json').is_file():
                            continue
                    except (OSError, ValueError):
                        continue
                    publish_versioned(directory, 'status', {'state': 'starting'})
                    child_env = os.environ.copy()
                    child_env['DATUM_SIM_SUPERVISOR_PID'] = str(os.getpid())
                    child = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.simulations.worker', str(project), str(directory)], start_new_session=True, env=child_env)
                    try:
                        atomic(directory / 'worker.pid', {'pid': child.pid, 'start': Path(f'/proc/{child.pid}/stat').read_text().split()[21]})
                    except (OSError, IndexError):
                        pass
                    active = directory
                    break
            time.sleep(0.2)
    finally:
        health.close()
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__': main()
