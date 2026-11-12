"""Local Gazebo Sim (Harmonic) transport adapter; no synthetic telemetry."""
import importlib
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
                     for n in ('world_control', 'boolean', 'pose_v', 'model')})
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
    def __init__(self, path):
        self.process = None
        self.node = None
        self.condition = threading.Condition()
        self.sample = None
        self.joints = []
        self.generation = 0
        self.links = set()
        import xml.etree.ElementTree as ET
        path = Path(path).resolve()
        self.original_path = path
        tree = ET.parse(path)
        self.links = {link.get('name') for link in tree.getroot().findall('link')}
        self.expected_links = {link.get('name') for link in tree.getroot().findall('link') if link.find('visual') is not None}
        # SolidCraft exports an empty synthetic base. Gazebo cannot preserve a
        # fixed joint whose parent has no inertial, so anchor the real root to
        # world directly when the synthetic joint has an identity transform.
        root = tree.getroot()
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
        path = path.with_name('datum-gazebo.urdf')
        tree.write(path, encoding='utf-8', xml_declaration=True)
        transport, self.messages = bindings()
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
            self.process = subprocess.Popen(['gz', 'sim', '-s', str(world)], env=self.env,
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

    def control(self, **fields):
        request = self.messages['world_control'].WorldControl(**fields)
        attempts = 1 if fields.get('multi_step') else 3
        for attempt in range(attempts):
            ok, reply = self.node.request('/world/datum/control', request,
                                          self.messages['world_control'].WorldControl,
                                          self.messages['boolean'].Boolean, 1000)
            if ok and reply.data:
                return
            if attempt + 1 < attempts: time.sleep(.1)
        raise RuntimeError('Gazebo world control failed')

    def step(self):
        with self.condition:
            generation = self.generation
            self.control(pause=True, multi_step=1)
            if not self.condition.wait_for(lambda: self.generation > generation, timeout=3):
                raise RuntimeError('Gazebo link telemetry timed out')

    def reset(self):
        path = self.original_path
        self.close()
        self.__init__(path)

    def snapshot(self):
        if self.process.poll() is not None:
            raise RuntimeError('Gazebo server exited')
        with self.condition:
            if self.sample is None:
                raise RuntimeError('Gazebo has no live link telemetry')
            return {**self.sample, 'joints': list(self.joints)}

    def close(self):
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
