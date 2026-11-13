"""Local Gazebo Sim (Harmonic) transport adapter; no synthetic telemetry."""
import importlib
import ctypes.util
import math
import re
import json
import select
import sys
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid
from xml.sax.saxutils import escape


def bindings():
    # Explicit ABI pairs; do not mix protobuf and transport installations.
    for transport, msgs in ((15, 12), (14, 11), (13, 10)):
        try:
            return (importlib.import_module(f'gz.transport{transport}'),
                    {n: importlib.import_module(f'gz.msgs{msgs}.{n}_pb2')
                     for n in ('world_control', 'boolean', 'pose_v', 'model', 'double')})
        except ImportError:
            continue
    raise RuntimeError('Gazebo requires matching Python gz transport/messages bindings (13/10, 14/11, or 15/12)')


def capability():
    result = {'supported': False, 'dependency': 'modern gz sim and matching Python transport/messages bindings',
              'executable': shutil.which('gz')}
    try:
        if not result['executable']:
            raise RuntimeError('gz executable not found')
        bindings()
        probe = subprocess.run(['gz', 'sim', '--versions'], capture_output=True, timeout=5, text=True)
        if probe.returncode or not probe.stdout.strip():
            raise RuntimeError('gz sim version probe failed')
        result.update(supported=True, version=probe.stdout.strip(),
                      reason='Prerequisites detected; physics plugin and URDF loading validated at startup')
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        result['reason'] = str(exc)
    return result


def mimic_physics_engine():
    """Find the active Gazebo release's physics plugin with mimic support."""
    try:
        versions = subprocess.run(['gz', 'sim', '--versions'], capture_output=True, text=True, timeout=5)
        majors = {int(m) for m in re.findall(r'(?<![0-9])([0-9]+)\.[0-9]+\.[0-9]+', versions.stdout)}
        # Harmonic/Ionic/Jetty use matching Gazebo Physics 7/8/9 respectively.
        if versions.returncode or len(majors) != 1 or not majors.issubset({8, 9, 10}):
            raise RuntimeError('unsupported or ambiguous Gazebo Sim version')
        major = next(iter(majors)) - 1
        library = ctypes.util.find_library(f'gz-physics{major}-bullet-featherstone-plugin')
        if library:
            probe = subprocess.run(['gz', 'plugin', '-i', '-p', library], capture_output=True, text=True, timeout=5)
            if probe.returncode == 0 and 'SetMimicConstraintFeature' in probe.stdout:
                return 'gz-physics-bullet-featherstone-plugin'
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise RuntimeError('Gazebo needs the matching Bullet Featherstone physics plugin with mimic support for coupled joints')


def parse_pose(message):
    stamp = message.header.stamp
    links = []
    for pose in message.pose:
        # SceneBroadcaster publishes world-space link poses as well as models.
        name = pose.name.split('::')[-1]
        links.append({'id': name, 'position': [pose.position.x, pose.position.y, pose.position.z],
                      'quaternion': [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]})
    return {'time': stamp.sec + stamp.nsec * 1e-9, 'links': links, 'joints': []}


class GazeboEngine:
    timestep = 1 / 240

    def __init__(self, path, couplings=None):
        self.process = None
        self.node = None
        self.control_process = None
        self.condition = threading.Condition()
        self.sample = None
        self.joints = []
        self.generation = 0
        self.links = set()
        import xml.etree.ElementTree as ET
        path = Path(path).resolve()
        self.original_path = path
        self.couplings = couplings or []
        self.actuators = {}
        self.publishers = {}
        tree = ET.parse(path)
        self.links = {link.get('name') for link in tree.getroot().findall('link')}
        self.expected_links = {link.get('name') for link in tree.getroot().findall('link') if link.find('visual') is not None}
        # SolidCraft exports an empty synthetic base. Gazebo cannot preserve a
        # fixed joint whose parent has no inertial, so anchor the real root to
        # world directly when the synthetic joint has an identity transform.
        root = tree.getroot()
        physics_engine = mimic_physics_engine() if self.couplings else None
        for coupling in self.couplings:
            driven = next((j for j in root.findall('joint') if j.get('name') == coupling['driven']), None)
            if driven is None or driven.find('mimic') is not None:
                raise ValueError('Invalid Gazebo coupled joint')
            ET.SubElement(driven, 'mimic', joint=coupling['driver'], multiplier='1', offset='0')
        synthetic = next((link for link in root.findall('link') if link.get('name') == 'base_link' and link.find('inertial') is None and link.find('visual') is None and link.find('collision') is None), None)
        if synthetic is not None:
            attached = [j for j in root.findall('joint') if j.find('parent') is not None and j.find('parent').get('link') == 'base_link']
            if len(attached) == 1 and attached[0].get('type') == 'fixed':
                joint = attached[0]
                origin = joint.find('origin')
                xyz = origin.get('xyz', '0 0 0') if origin is not None else '0 0 0'
                rpy = origin.get('rpy', '0 0 0') if origin is not None else '0 0 0'
                if all(float(v) == 0 for v in (xyz + ' ' + rpy).split()):
                    joint.find('parent').set('link', 'world')
                    root.remove(synthetic)
                    ET.SubElement(root, 'link', name='world')
        for joint in tree.getroot().findall('joint'):
            if joint.get('type') == 'fixed' and joint.find('parent').get('link') != 'world':
                extension = ET.SubElement(tree.getroot(), 'gazebo', reference=joint.get('name'))
                ET.SubElement(extension, 'preserveFixedJoint').text = 'true'
        extension = ET.SubElement(tree.getroot(), 'gazebo')
        ET.SubElement(extension, 'plugin', filename='gz-sim-joint-state-publisher-system',
                      name='gz::sim::systems::JointStatePublisher')
        self.joint_limits = {}
        for joint in root.findall('joint'):
            name, kind, limit = joint.get('name'), joint.get('type'), joint.find('limit')
            if kind not in ('revolute', 'continuous', 'prismatic') or not name or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                continue
            self.joint_limits[name] = (float(limit.get('lower')), float(limit.get('upper'))) if limit is not None and limit.get('lower') is not None and limit.get('upper') is not None else None
            plugin = ET.SubElement(extension, 'plugin', filename='gz-sim-apply-joint-force-system', name='gz::sim::systems::ApplyJointForce')
            ET.SubElement(plugin, 'joint_name').text = name
        path = path.with_name('datum-gazebo.urdf')
        tree.write(path, encoding='utf-8', xml_declaration=True)
        transport, self.messages = bindings()
        (path.parent / '.fuel-disabled').mkdir(exist_ok=True)
        self.env = dict(os.environ, GZ_PARTITION='datum_' + uuid.uuid4().hex,
                        GZ_IP='127.0.0.1', GZ_SIM_RESOURCE_PATH=str(path.parent),
                        GZ_FUEL_CACHE_PATH=str(path.parent / '.fuel-disabled'))
        # Node reads the partition from the environment at construction.
        self.previous_partition = os.environ.get('GZ_PARTITION')
        os.environ['GZ_PARTITION'] = self.env['GZ_PARTITION']
        self.node = transport.Node()
        world = path.parent / ('datum-world-' + uuid.uuid4().hex + '.sdf')
        self.world = world
        world.write_text('''<sdf version="1.9"><world name="datum">
<physics name="physics" type="ignored"><max_step_size>0.004166666666666667</max_step_size></physics>
<plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
<plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
<include><uri>''' + escape(path.as_uri()) + '''</uri><name>robot</name></include>
</world></sdf>''')
        self.log = (path.parent / 'gazebo.log').open('w')
        try:
            control_env = dict(self.env, DATUM_GZ_PARENT_PID=str(os.getpid()))
            self.control_process = subprocess.Popen([sys.executable, '-m', 'datum_parameter_studio.simulations.gz_control'],
                env=control_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
            command = ['gz', 'sim', '-s', str(world)]
            if physics_engine: command.extend(['--physics-engine', physics_engine])
            self.process = subprocess.Popen(command, env=self.env,
                                             stdout=self.log, stderr=self.log)
            if not self.node.subscribe(self.messages['pose_v'].Pose_V, '/world/datum/pose/info', self._pose):
                raise RuntimeError('Gazebo pose subscription failed')
            if not self.node.subscribe(self.messages['model'].Model, '/world/datum/model/robot/joint_state', self._joints):
                raise RuntimeError('Gazebo joint subscription failed')
            deadline = time.monotonic() + 15
            while True:
                try:
                    self.control(pause=True)
                    break
                except RuntimeError:
                    if self.process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Gazebo startup failed; inspect ' + str(self.log.name))
            self.step()
            if self.couplings:
                with self.condition:
                    required = {c[k] for c in self.couplings for k in ('driver', 'driven')}
                    if not self.condition.wait_for(lambda: required.issubset({j['id'] for j in self.joints}), timeout=5):
                        raise RuntimeError('Gazebo did not publish all coupled joint states')
        except Exception:
            self.close()
            raise

    def _pose(self, message):
        sample = parse_pose(message)
        sample['links'] = [p for p in sample['links'] if p['id'] in self.links]
        if sample['links'] and self.expected_links.issubset({p['id'] for p in sample['links']}):
            with self.condition:
                self.sample = sample
                self.generation += 1
                self.condition.notify_all()

    def _joints(self, message):
        with self.condition:
            self.joints = [{'id': joint.name.split('::')[-1], 'position': joint.axis1.position,
                            'velocity': joint.axis1.velocity} for joint in message.joint if joint.HasField('axis1')]
            self.condition.notify_all()

    def control(self, **fields):
        attempts = 1 if fields.get('multi_step') else 3
        for attempt in range(attempts):
            try:
                if self.control_process is None or self.control_process.poll() is not None:
                    raise RuntimeError('Gazebo world control unavailable')
                self.control_process.stdin.write(json.dumps(fields) + '\n')
                self.control_process.stdin.flush()
                if not select.select([self.control_process.stdout], [], [], 2)[0]:
                    # The timed-out step may still execute. Discard the client
                    # so its late reply cannot acknowledge a later command.
                    self._stop_control()
                    raise RuntimeError('Gazebo world control outcome is unknown')
                if json.loads(self.control_process.stdout.readline()).get('ok'):
                    return
            except (BrokenPipeError, EOFError, OSError, ValueError) as exc:
                raise RuntimeError('Gazebo world control unavailable') from exc
            if attempt + 1 < attempts: time.sleep(.1)
        raise RuntimeError('Gazebo world control failed')

    def set_position_control(self, name, target, profile):
        if (not isinstance(name, str) or name not in self.joint_limits or
            isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target)):
            raise ValueError('Joint and finite position are required')
        limits = self.joint_limits[name]
        if limits and limits[0] <= limits[1] and not limits[0] <= target <= limits[1]:
            raise ValueError('Position outside joint limits')
        if any(name == c['driven'] for c in self.couplings):
            raise ValueError('Command the driver joint for this coupled pair')
        if not isinstance(profile, dict) or set(profile) != {'kp', 'kd', 'max_force'}:
            raise ValueError('Profile requires kp, kd and max_force')
        for key in ('kp', 'kd', 'max_force'):
            value = profile[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key == 'max_force' and value == 0):
                raise ValueError('Invalid actuator profile')
        if name not in self.publishers:
            self.publishers[name] = self.node.advertise('/model/robot/joint/' + name + '/cmd_force', self.messages['double'].Double)
        publisher = self.publishers[name]
        deadline = time.monotonic() + 3
        while not publisher.has_connections():
            if time.monotonic() >= deadline:
                raise RuntimeError('Gazebo joint force controller unavailable')
            time.sleep(.05)
        self.actuators[name] = (target, profile['kp'], profile['kd'], profile['max_force'])

    def step(self):
        self.step_many(1)

    def step_many(self, count):
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64:
            raise ValueError('Invalid physics step count')
        with self.condition:
            generation = self.generation
            start_time = self.sample['time'] if self.sample is not None else 0.0
            state = {joint['id']: joint for joint in self.joints}
        for name, (target, kp, kd, limit) in self.actuators.items():
            if name not in state:
                raise RuntimeError('Gazebo joint telemetry unavailable: ' + name)
            joint = state[name]
            force = max(-limit, min(limit, kp * (target - joint['position']) - kd * joint['velocity']))
            self.publishers[name].publish(self.messages['double'].Double(data=force))
        # Never hold the callback condition while making the control request.
        self.control(pause=True, multi_step=count)
        with self.condition:
            # The broadcaster can omit the final few physics frames while paused.
            target = start_time + max(1, count - 4) * self.timestep
            if not self.condition.wait_for(lambda: self.generation > generation and
                    self.sample is not None and self.sample['time'] >= target - 1e-8, timeout=3):
                raise RuntimeError('Gazebo link telemetry timed out')

    def reset(self):
        path, couplings = self.original_path, self.couplings
        self.close()
        self.__init__(path, couplings)

    def snapshot(self):
        if self.process.poll() is not None:
            raise RuntimeError('Gazebo server exited')
        with self.condition:
            if self.sample is None:
                raise RuntimeError('Gazebo has no live link telemetry')
            return {**self.sample, 'joints': list(self.joints)}

    def _stop_control(self):
        process, self.control_process = self.control_process, None
        if process is None:
            return
        if process.stdin:
            try: process.stdin.close()
            except (BrokenPipeError, OSError): pass
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        if process.stdout:
            process.stdout.close()

    def close(self):
        self._stop_control()
        if self.node:
            self.node.unsubscribe('/world/datum/pose/info')
            self.node.unsubscribe('/world/datum/model/robot/joint_state')
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if hasattr(self, 'log'): self.log.close()
        if hasattr(self, 'world'): self.world.unlink(missing_ok=True)
        if hasattr(self, 'previous_partition'):
            if self.previous_partition is None: os.environ.pop('GZ_PARTITION', None)
            else: os.environ['GZ_PARTITION'] = self.previous_partition
