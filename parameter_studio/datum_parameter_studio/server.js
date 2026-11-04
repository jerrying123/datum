import express from 'express';
import AdmZip from 'adm-zip';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { constants } from 'node:fs';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const app = express();
const here = path.dirname(fileURLToPath(import.meta.url));
app.use(express.json({limit:'2mb'}));
app.use(express.static(path.join(here,'public')));
app.use('/vendor/three',express.static(path.join(here,'node_modules/three')));
const numeric = v => typeof v === 'number' && Number.isFinite(v) || typeof v === 'string' && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*(?:mm|cm|m|in|ft))?$/.test(v.trim());
function flatten(value, pointer='', paramNames=new Set()) {
  if (Array.isArray(value)) return value.flatMap((v,i)=>flatten(v,`${pointer}/${i}`,paramNames));
  if (value && typeof value==='object') return Object.entries(value).flatMap(([k,v])=>flatten(v,`${pointer}/${k.replaceAll('~','~0').replaceAll('/','~1')}`,paramNames));
  return numeric(value)||(typeof value==='string'&&paramNames.has(value)) ? [{pointer,value}] : [];
}
app.post('/api/inspect',(req,res)=>{
  try {
    const {name,base64}=req.body||{};
    if(typeof name!=='string'||typeof base64!=='string'||base64.length>100*1024*1024) return res.status(400).json({error:'Provide a CAD filename and archive under 100 MiB.'});
    const zip=new AdmZip(Buffer.from(base64,'base64'));
    const entry=zip.getEntry('document.json');
    if(!entry) return res.status(400).json({error:'Archive has no document.json.'});
    const doc=JSON.parse(entry.getData().toString('utf8'));
    if(!Array.isArray(doc.features)) return res.status(400).json({error:'document.json has no features array.'});
    const paramNames=new Set((doc.params||[]).map(p=>p.name));
    res.json({name:name.replaceAll('\\','/').split('/').pop(),units:doc.units||'mm',fields:flatten(doc.features,'/features',paramNames),features:doc.features,components:doc.components||[],occurrences:doc.occurrences||[],links:doc.links||{},params:doc.params||[],sketches:doc.sketches||[]});
  } catch(e) { res.status(400).json({error:`Could not read SolidCraft archive: ${e.message}`}); }
});
const projectRoot=path.resolve(process.env.DATUM_PROJECT_ROOT||'/workspace');
async function cadFiles(dir=projectRoot,relative='') {
  let entries; try { entries=await fs.readdir(dir,{withFileTypes:true}); } catch { return []; }
  const found=[];
  for(const ent of entries){if(ent.name.startsWith('.')||ent.name==='node_modules'||ent.name==='target')continue;const rel=path.posix.join(relative,ent.name),full=path.join(dir,ent.name);
    if(ent.isDirectory()){found.push(...await cadFiles(full,rel));continue;}
    if(!/\.(solidcraft|sc)$/i.test(ent.name))continue;
    try{const st=await fs.stat(full);if(st.size>100*1024*1024)continue;const bytes=await fs.readFile(full);const zip=new AdmZip(bytes),entry=zip.getEntry('document.json');if(!entry)continue;const doc=JSON.parse(entry.getData().toString('utf8'));if(!Array.isArray(doc.features))continue;const previewId=createHash('sha256').update(rel).digest('hex'),fingerprint=createHash('sha256').update(bytes).digest('hex'),root=path.join('/previews',previewId);let evaluation=null;try{if(await fs.readFile(root+'.rev','utf8')===fingerprint){const data=await fs.readFile(root+'.json','utf8');if(await fs.readFile(root+'.rev','utf8')===fingerprint)evaluation=JSON.parse(data);}}catch{}const paramNames=new Set((doc.params||[]).map(p=>p.name));found.push({path:rel,units:doc.units||'mm',fingerprint,previewId,fields:flatten(doc.features,'/features',paramNames),features:doc.features,components:doc.components||[],occurrences:doc.occurrences||[],links:doc.links||{},params:doc.params||[],sketches:evaluation?.sketches||doc.sketches||[],evaluation});}catch{ /* incomplete CAD save; retry on next poll */}
  }
  return found.sort((a,b)=>a.path.localeCompare(b.path));
}
app.get('/api/cad',async(_,res)=>{try{res.json({project_id:process.env.DATUM_PROJECT_ID||projectRoot,files:await cadFiles()});}catch(e){res.status(500).json({error:e.message});}});
const runFile=promisify(execFile);
async function validateSource(name,base) {
  if(typeof name!=='string'||!name||name.includes('\\')||name.includes('\0')||path.posix.isAbsolute(name)||/^[A-Za-z]:/.test(name)||name.split('/').some(part=>!part||part==='.'||part==='..')) throw new Error('Invalid project-relative source path.');
  const resolved=await fs.realpath(path.join(base,name));
  if(!resolved.startsWith(base+path.sep)) throw new Error('Source path escapes the project.');
  const stat=await fs.stat(resolved);
  if(!stat.isFile()||stat.size>100*1024*1024) throw new Error('Source must be a file under 100 MiB.');
}
app.post('/api/generate',async(req,res)=>{
  let scratch;
  try {
    const {spec,worktree}=req.body||{};
    if(!spec||typeof spec!=='object'||Array.isArray(spec)||spec.schema!=='datum.robot.parameter-spec/2'||spec.units!=='m'||typeof worktree!=='string'||!/^[a-z_][a-z0-9_]*$/.test(worktree)||!spec.worktrees||typeof spec.worktrees!=='object'||!Object.hasOwn(spec.worktrees,worktree)) throw new Error('Provide a parameter spec and valid worktree.');
    const tree=spec.worktrees[worktree];
    if(!tree||typeof tree!=='object'||Array.isArray(tree)||!Array.isArray(spec.sources||[])||!Array.isArray(tree.sources||[])||!tree.parameters||typeof tree.parameters!=='object'||Array.isArray(tree.parameters)) throw new Error('Invalid parameter specification.');
    const base=await fs.realpath(projectRoot);
    const sources=[...(spec.sources||[]),...(tree.sources||[]),...Object.values(tree.parameters).map(mapping=>mapping?.path)];
    for(const source of sources) await validateSource(source,base);
    scratch=await fs.mkdtemp(path.join(os.tmpdir(),'datum-studio-'));
    const specFile=path.join(scratch,'spec.json'),manifestFile=path.join(scratch,'manifest.json'),headerFile=path.join(scratch,'parameters.hpp');
    await fs.writeFile(specFile,JSON.stringify(spec,null,2)+'\n');
    await runFile(process.env.DATUM_PARAMS_BIN||'datum-params',['generate',base,specFile,worktree,manifestFile,headerFile],{timeout:30000,maxBuffer:1024*1024});
    const [manifest,header]=await Promise.all([fs.readFile(manifestFile,'utf8'),fs.readFile(headerFile,'utf8')]);
    res.json({manifest,header});
  } catch(e) { res.status(400).json({error:e.stderr?.trim()||e.message}); }
  finally { if(scratch) await fs.rm(scratch,{recursive:true,force:true}); }
});
app.get('/api/preview/:id',async(req,res)=>{if(!/^[a-f0-9]{64}$/.test(req.params.id)||!/^[a-f0-9]{64}$/.test(req.query.v||''))return res.sendStatus(400);const root=path.join('/previews',req.params.id),file=root+'.png';try{if((await fs.readFile(root+'.rev','utf8'))!==req.query.v)return res.sendStatus(409);res.set('Cache-Control','no-store').sendFile(file);}catch{res.sendStatus(404);}});
app.get('/api/model/:id',async(req,res)=>{if(!/^[a-f0-9]{64}$/.test(req.params.id)||!/^[a-f0-9]{64}$/.test(req.query.v||''))return res.sendStatus(400);const root=path.join('/previews',req.params.id),file=root+'.3mf';try{if((await fs.readFile(root+'.rev','utf8'))!==req.query.v)return res.sendStatus(409);res.set('Content-Type','model/3mf').set('Cache-Control','no-store').sendFile(file);}catch{res.sendStatus(404);}});

// The host launcher owns worker.ready and the worker lifecycle.
const urdfSpool=process.env.DATUM_URDF_SPOOL;
const urdfCapability=randomBytes(32).toString('hex');
const jobIdPattern=/^[0-9a-f]{32}$/;
const activeStates=new Set(['queued','capturing','exporting','checking']);
let queueLock=Promise.resolve();
async function spoolReady() {
  if(!urdfSpool) return false;
  try { const root=await fs.lstat(urdfSpool), marker=await fs.lstat(path.join(urdfSpool,'worker.ready')); return root.isDirectory()&&!root.isSymbolicLink()&&marker.isFile()&&!marker.isSymbolicLink()&&(Date.now()-marker.mtimeMs<10000); } catch { return false; }
}
function authorized(req) {
  const token=req.get('X-Dparams-Capability')||'';
  const a=Buffer.from(token), b=Buffer.from(urdfCapability);
  if(a.length!==b.length||!timingSafeEqual(a,b)) return false;
  try { const origin=new URL(req.get('Origin')); const proto=(req.get('X-Forwarded-Proto')||req.protocol).split(',')[0].trim(); return ['http','https'].includes(proto)&&origin.origin===`${proto}://${req.get('Host')}`; } catch { return false; }
}
async function jobDirectory(id) {
  if(!jobIdPattern.test(id)) throw Object.assign(new Error('Invalid job ID.'),{status:400});
  const dir=path.join(urdfSpool||'',id), st=await fs.lstat(dir);
  if(!st.isDirectory()||st.isSymbolicLink()) throw Object.assign(new Error('Job not found.'),{status:404});
  return dir;
}
async function openJobFile(dir,name) {
  const handle=await fs.open(path.join(dir,name),constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
  try { if(!(await handle.stat()).isFile()) throw new Error('Not a regular file'); return handle; } catch(e) { await handle.close(); throw e; }
}
async function readJobJson(dir,name) {
  const h=await openJobFile(dir,name);
  try { const st=await h.stat(); if(st.size>2*1024*1024) throw new Error('File too large'); return JSON.parse(await h.readFile('utf8')); } finally { await h.close(); }
}
async function readJobStatus(dir) { const versions=(await fs.readdir(dir)).filter(name=>/^status-[0-9]{20}\.json$/.test(name)).sort(); return readJobJson(dir,versions.at(-1)||'status.json'); }
function jobError(res,e) { res.status(e.status|| (e.code==='ENOENT'?404:500)).json({error:e.status||e.code==='ENOENT'?e.message:'Job unavailable.'}); }
app.get('/api/urdf/capabilities',async(req,res)=>{res.set('Cache-Control','no-store').json({available:await spoolReady(),capability:urdfCapability});});
app.post('/api/urdf/jobs',async(req,res)=>{
  if(!authorized(req)) return res.status(403).json({error:'Invalid origin or capability.'});
  if(!await spoolReady()) return res.status(503).json({error:'URDF worker unavailable.'});
  const body=req.body;
  if(!body||typeof body!=='object'||Array.isArray(body)||Object.keys(body).length!==1||typeof body.assembly!=='string'||!/\.(solidcraft|sc)$/i.test(body.assembly)) return res.status(400).json({error:'Provide an assembly path.'});
  try { await validateSource(body.assembly,await fs.realpath(projectRoot)); } catch { return res.status(400).json({error:'Invalid assembly path.'}); }
  const previous=queueLock; let release; queueLock=new Promise(resolve=>{release=resolve;}); await previous;
  try {
    if(!await spoolReady()) return res.status(503).json({error:'URDF worker unavailable.'});
    let count=0;
    for(const ent of await fs.readdir(urdfSpool,{withFileTypes:true})) {
      if(!jobIdPattern.test(ent.name)||!ent.isDirectory()) continue;
      try { const dir=await jobDirectory(ent.name); const status=await readJobStatus(dir); if(activeStates.has(status.state)) count++; }
      catch { count++; }
    }
    if(count>=4) return res.status(429).json({error:'URDF queue is full.'});
    const id=randomBytes(16).toString('hex'), dir=path.join(urdfSpool,id);
    await fs.mkdir(dir,{mode:0o700});
    try {
      await fs.writeFile(path.join(dir,'status.json.tmp'),JSON.stringify({state:'queued',freshness:null,structural_checks:null,assembly_fidelity:null,error:null}),{flag:'wx'});
      await fs.rename(path.join(dir,'status.json.tmp'),path.join(dir,'status.json'));
      await fs.writeFile(path.join(dir,'request.json.tmp'),JSON.stringify({assembly:body.assembly}),{flag:'wx'});
      await fs.rename(path.join(dir,'request.json.tmp'),path.join(dir,'request.json'));
    } catch(e) { await fs.rm(dir,{recursive:true,force:true}); throw e; }
    res.status(202).json({id});
  } catch(e) { jobError(res,e); } finally { release(); }
});
app.get('/api/urdf/jobs/:id',async(req,res)=>{
  try { const dir=await jobDirectory(req.params.id), status=await readJobStatus(dir); let report; try { report=await readJobJson(dir,'report.json'); } catch(e) { if(e.code!=='ENOENT') throw e; } res.set('Cache-Control','no-store').json({...status,...(report===undefined?{}:{report})}); } catch(e) { jobError(res,e); }
});
app.post('/api/urdf/jobs/:id/cancel',async(req,res)=>{
  if(!authorized(req)) return res.status(403).json({error:'Invalid origin or capability.'});
  try { const dir=await jobDirectory(req.params.id); await fs.writeFile(path.join(dir,'cancel'),'',{flag:'wx'}).catch(e=>{if(e.code!=='EEXIST') throw e;}); res.status(202).json({cancelled:true}); } catch(e) { jobError(res,e); }
});
app.get('/api/urdf/jobs/:id/:artifact',async(req,res)=>{
  if(!['report','bundle'].includes(req.params.artifact)) return res.sendStatus(404);
  let h;
  try { const dir=await jobDirectory(req.params.id), status=await readJobStatus(dir); if(status.state!=='succeeded') return res.status(409).json({error:'Job output is not complete.'}); const name=req.params.artifact==='report'?'report.json':'bundle.zip'; h=await openJobFile(dir,name); res.set('Cache-Control','no-store').type(name.endsWith('.zip')?'application/zip':'application/json'); res.set('Content-Disposition',`attachment; filename="${name}"`); const stream=h.createReadStream(); h=null; stream.on('error',()=>res.destroy()); stream.pipe(res); } catch(e) { if(h) await h.close(); jobError(res,e); }
});

app.get('/healthz',(_,res)=>res.json({ok:true}));
app.listen(Number(process.env.DATUM_STUDIO_PORT||8080),'0.0.0.0',()=>console.log('Datum Parameter Studio listening'));
