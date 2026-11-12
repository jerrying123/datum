/* Offline browser workflow smoke. Requires playwright-core and a Chromium executable. */
const {spawn} = require('node:child_process');
const path = require('node:path');
const {createRequire} = require('node:module');
const studioRequire = createRequire(path.resolve(__dirname,'../datum_parameter_studio/package.json'));
const {chromium} = studioRequire('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');

(async()=>{
 const root=path.resolve(__dirname,'../datum_parameter_studio');
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'dparams-browser-'));
 fs.cpSync(path.resolve(__dirname,'../../examples/pybullet_sim/cad'),tmp,{recursive:true});
 const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
 const url=`http://127.0.0.1:${port}`;
 const server=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,DATUM_PROJECT_ROOT:tmp,DATUM_STUDIO_PORT:String(port)},stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(url+'/healthz')).ok)break}catch{}await new Promise(r=>setTimeout(r,50));if(i===99)throw Error('server did not start')}
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext();const page=await context.newPage();const errors=[],external=[];page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',request=>{if(new URL(request.url()).origin!==url)external.push(request.url())});
  let state='paused',recording=false,epoch=0,simtime=0,session=false,invalidStatus=false,invalidJson=false;const requests=[];
  const cad={project_id:'test-project',files:[{path:'robot.solidcraft',units:'mm',fingerprint:'a'.repeat(64),previewId:'b'.repeat(64),features:[],components:[],occurrences:[],links:{},params:[],sketches:[],fields:[]}]};
  await page.route('**/api/**',async route=>{
   const request=route.request(),u=new URL(request.url()),p=u.pathname;requests.push([request.method(),p]);let body={};
   if(invalidJson && p===`/api/simulation/sessions/${'a'.repeat(32)}`)return route.fulfill({status:200,contentType:'application/json',body:'{' });
   if(p==='/api/cad')body=cad;
   else if(p==='/api/urdf/capabilities')body={available:true,capability:'test-token'};
   else if(p==='/api/urdf/jobs'&&request.method()==='POST')body={id:'d'.repeat(32)};
   else if(p===`/api/urdf/jobs/${'d'.repeat(32)}`)body={state:'succeeded',report:{source_preflight:{issues:null}}};
   else if(p==='/api/simulation/capabilities')body={available:true,capability:'test-token',backends:{mujoco:{supported:true,commands:['set_joint']},pybullet:{supported:true,commands:['set_joint']},gazebo:{supported:false,reason:'not installed'}}};
   else if(p==='/api/simulation/sessions'&&request.method()==='POST'){session=true;body={id:'a'.repeat(32)}}
   else if(p==='/api/simulation/sessions')body={sessions:session?[{id:'a'.repeat(32),backend:'mujoco',assembly:'robot.solidcraft',state}]:[]};
   else if(p.endsWith('/commands')&&request.method()==='POST'){const command=request.postDataJSON().command;if(command==='resume')state='running';if(command==='pause')state='paused';if(command==='step')simtime+=.01;if(command==='reset'){simtime=0;epoch++}if(command==='record_start')recording=true;if(command==='record_stop')recording=false;if(command==='stop')state='stopped';body={id:'b'.repeat(32)}}
   else if(p.includes('/commands/'))body={status:'applied'};
   else if(p.endsWith('/scene'))body={links:[]};
   else if(p.endsWith('/state'))body={time:simtime,epoch,seq:1,links:[],joints:[{id:'hinge',position:0,velocity:0}]};
   else if(p.endsWith('/recordings'))body={recordings:[]};
   else if(p.startsWith('/api/simulation/sessions/'))body={state:invalidStatus?'not-a-state':state,backend:'mujoco',recording};
   else return route.fulfill({status:404,body:'{}',contentType:'application/json'});
   return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto(url,{waitUntil:'domcontentloaded'});
  await page.locator('#cad-list').getByText('robot.solidcraft').waitFor();
  cad.files[0].fields=[{pointer:'<img src=x onerror="window.injected=1">',value:'<svg onload="window.injected=2">'}];
  cad.files[0].fingerprint='c'.repeat(64);
  await page.waitForFunction(()=>!document.querySelector('#changes').hidden);
  assert.equal(await page.locator('#after code').textContent(),cad.files[0].fields[0].pointer);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  cad.files[0].params=[null];
  await page.getByText(/Could not refresh CAD files: Unexpected response from Studio API/).waitFor({state:'attached'});
  cad.files[0].params=[];
  cad.files[0].features=[{type:'sketch',sketch:{constraints:{invalid:true}}}];
  await page.waitForTimeout(2100);
  assert.match(await page.locator('#message').textContent(),/Unexpected response from Studio API/);
  cad.files[0].features=[];
  await page.locator('.urdf-panel > summary').click();
  await page.locator('#urdf-start:not([disabled])').click();
  await page.getByText(/Connection interrupted: Unexpected response from Studio API/).waitFor();
  await page.locator('.simulation-panel > summary').click();
  await page.locator('#sim-start:not([disabled])').waitFor();
  await page.locator('#sim-start').click();
  await page.getByText('paused · mujoco').waitFor();
  await page.locator('#sim-step:not([disabled])').click();
  await page.getByText(/Time: 0\.010/).waitFor();
  await page.locator('#sim-record').click();await page.getByRole('button',{name:'Stop recording'}).waitFor();
  await page.locator('#sim-reset').click();await page.getByText(/reset 1/).waitFor();
  invalidStatus=true;await page.locator('#sim-status').filter({hasText:/Unexpected response from Studio API/}).waitFor();
  invalidStatus=false;await page.locator('#sim-reconnect').click();await page.getByText('paused · mujoco').waitFor();
  invalidJson=true;await page.locator('#sim-status').filter({hasText:/Invalid JSON response/}).waitFor();
  invalidJson=false;await page.locator('#sim-reconnect').click();await page.getByText('paused · mujoco').waitFor();
  await page.locator('#sim-stop').click();await page.getByText('stopped · mujoco').waitFor();
  assert.equal(errors.length,0,errors.join('\n'));
  assert.deepEqual(external,[],`Unexpected external requests: ${external.join(', ')}`);
  assert(requests.some(([method,p])=>method==='POST'&&p.endsWith('/commands')));
  const real=await browser.newPage();const realErrors=[];real.on('pageerror',e=>realErrors.push(String(e)));
  await real.goto(url,{waitUntil:'domcontentloaded'});
  await real.locator('#cad-list').getByText('assembly.solidcraft').waitFor();
  assert.deepEqual(realErrors,[],realErrors.join('\n'));
  await real.close();
  console.log('Browser smoke passed: CAD catalog, session, step, recording, reset, stop.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(tmp,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
