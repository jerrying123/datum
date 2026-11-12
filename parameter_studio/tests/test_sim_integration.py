"""Exercise Studio API through the real host worker and synthetic CAD example."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / 'parameter_studio/datum_parameter_studio'
PREFLIGHT = ROOT / 'rust/target/debug/studio-urdf-preflight'


@unittest.skipUnless(shutil.which('node') and (STUDIO / 'node_modules/express').exists() and shutil.which('solidcraft-cli') and PREFLIGHT.exists() and importlib.util.find_spec('mujoco') and importlib.util.find_spec('pybullet'), 'requires Node, native CAD tools, MuJoCo and PyBullet')
class IntegrationTest(unittest.TestCase):
    def test_api_worker_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = root / 'project'; spool = root / 'spool'; spool.mkdir()
            shutil.copytree(ROOT / 'examples/pybullet_sim/cad', project)
            env = os.environ.copy(); env.update(DATUM_PROJECT_ROOT=str(project), DATUM_SIM_SPOOL=str(spool),
                DATUM_URDF_PREFLIGHT=str(PREFLIGHT), PYTHONPATH=str(ROOT / 'parameter_studio'))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
            env['DATUM_STUDIO_PORT'] = str(port); base = f'http://127.0.0.1:{port}'
            worker = subprocess.Popen([sys.executable,'-m','datum_parameter_studio.simulations.worker','--serve','--project',str(project),'--spool',str(spool)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            server = subprocess.Popen(['node',str(STUDIO / 'server.js')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.addCleanup(lambda: (worker.poll() is None and worker.terminate(), server.poll() is None and server.terminate()))
            def req(path, data=None, token=None):
                headers = {'Origin':base, 'X-Dparams-Capability':token or ''}
                if data is not None: headers['Content-Type']='application/json'
                request = Request(base+path, data=None if data is None else json.dumps(data).encode(),headers=headers)
                with urlopen(request,timeout=2) as response: return json.load(response)
            def until(fn, predicate, timeout=15):
                end = time.monotonic()+timeout; last = None
                while time.monotonic()<end:
                    try:
                        last=fn()
                        if predicate(last): return last
                    except HTTPError as exc: exc.close()
                    except (URLError, OSError, ValueError): pass
                    time.sleep(.05)
                self.fail(f'timed out: {last}')
            try:
                cap=until(lambda:req('/api/simulation/capabilities'),lambda x:x.get('available'))
                token=cap['capability']
                with self.assertRaises(HTTPError) as denied:
                    req('/api/simulation/sessions', {'backend':'mujoco','assembly':'assembly.solidcraft'})
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()
                for backend in ('mujoco','pybullet'):
                    self.assertTrue(cap['backends'][backend]['supported'])
                    start=req('/api/simulation/sessions',{'backend':backend,'assembly':'assembly.solidcraft'},token)
                    uri='/api/simulation/sessions/'+start['id']
                    state=until(lambda:req(uri),lambda x:x.get('state') in ('paused','failed'))
                    self.assertEqual(state['state'],'paused',state)
                    scene=req(uri+'/scene'); sample=req(uri+'/state')
                    self.assertTrue(scene['links']); self.assertTrue(sample['links'])
                    visual_links={link['id'] for link in scene['links'] if link['geometry']}
                    self.assertTrue(visual_links.issubset({link['id'] for link in sample['links']}), (scene, sample))
                    with urlopen(base+uri+'/mesh?name=robot-arm.stl',timeout=2) as response:
                        self.assertGreater(len(response.read()), 84)
                    req(uri+'/commands',{'command':'record_start'},token)
                    until(lambda:req(uri),lambda x:x.get('recording'))
                    command=req(uri+'/commands',{'command':'set_joint','joint':'hinge','position':0.4},token)
                    ack=until(lambda:req(uri+'/commands/'+command['id']),lambda x:x.get('status') in ('applied','rejected','unknown'))
                    self.assertEqual(ack['status'], 'applied', ack)
                    positioned = until(lambda:req(uri+'/state'),lambda x:any(j.get('id')=='hinge' and abs(j['position']-0.4)<1e-5 for j in x.get('joints',[])))
                    self.assertTrue(positioned['joints'])
                    drive = {'command':'set_position_control', 'joint':'hinge', 'position':0.2,
                             'profile':{'kp':12, 'kd':2, 'max_force':5}}
                    with self.assertRaises(HTTPError) as invalid:
                        req(uri+'/commands', {**drive, 'profile':{**drive['profile'], 'max_force':0}}, token)
                    self.assertEqual(invalid.exception.code, 400)
                    invalid.exception.close()
                    command = req(uri+'/commands', drive, token)
                    ack = until(lambda:req(uri+'/commands/'+command['id']), lambda x:x.get('status') in ('applied','rejected','unknown'))
                    self.assertEqual(ack['status'], 'applied', ack)
                    req(uri+'/commands',{'command':'step'},token)
                    stepped=until(lambda:req(uri),lambda x:x.get('time',0)>0 or x.get('error'))
                    self.assertFalse(stepped.get('error'), stepped)
                    self.assertGreater(stepped['time'],0)
                    req(uri+'/commands',{'command':'reset'},token)
                    until(lambda:req(uri+'/state'),lambda x:x.get('epoch')==1)
                    req(uri+'/commands',{'command':'record_stop'},token)
                    until(lambda:req(uri),lambda x:not x.get('recording',True))
                    recordings = req(uri+'/recordings')['recordings']
                    self.assertTrue(recordings)
                    with urlopen(base+uri+'/recordings/'+recordings[0],timeout=2) as response:
                        entries = [json.loads(line) for line in response.read().splitlines()]
                    self.assertEqual(entries[0]['type'], 'metadata')
                    self.assertTrue(any(x.get('command') == 'step' for x in entries))
                    self.assertTrue(any(x.get('command') == 'record_stop' for x in entries))
                    self.assertTrue(any(x.get('type') == 'state' and x.get('time', 0) > 0 for x in entries))
                    req(uri+'/commands',{'command':'stop'},token)
                    until(lambda:req(uri),lambda x:x.get('state')=='stopped')
                    with self.assertRaises(HTTPError) as denied:
                        req(uri+'/commands', {'command':'step'}, token)
                    self.assertEqual(denied.exception.code, 409)
                    denied.exception.close()
                start=req('/api/simulation/sessions',{'backend':'mujoco','assembly':'assembly.solidcraft'},token)
                uri='/api/simulation/sessions/'+start['id']
                until(lambda:req(uri),lambda x:x.get('state')=='paused')
                worker.kill(); worker.wait(timeout=5)
                worker = subprocess.Popen([sys.executable,'-m','datum_parameter_studio.simulations.worker','--serve','--project',str(project),'--spool',str(spool)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                until(lambda:req(uri),lambda x:x.get('state') in ('failed', 'stopped'))
                until(lambda:req('/api/simulation/capabilities'),lambda x:x.get('available'))
                new = req('/api/simulation/sessions',{'backend':'mujoco','assembly':'assembly.solidcraft'},token)
                self.assertNotEqual(new['id'], start['id'])
            finally:
                worker.terminate(); server.terminate()
                for p in (worker,server):
                    try: p.wait(timeout=5)
                    except subprocess.TimeoutExpired: p.kill(); p.wait()
