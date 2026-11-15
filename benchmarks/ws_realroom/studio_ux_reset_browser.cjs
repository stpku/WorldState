// ETH3D development data and automated clicks, never a human acceptance run.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');const crypto=require('crypto');
async function main(){
 const [base,inputFile,out]=process.argv.slice(2);
 if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(base||'')||!inputFile||!out||fs.existsSync(out))throw Error('expected isolated local URL, real observations and new output');
 fs.mkdirSync(out,{recursive:true});const input=JSON.parse(fs.readFileSync(inputFile,'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--enable-unsafe-swiftshader']});
 const errors=[],failed=[];let page;
 const attach=p=>{p.on('pageerror',e=>errors.push(e.message));p.on('requestfailed',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))failed.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText})});p.on('crash',()=>errors.push('browser page crashed'))};
 const read=()=>page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
 const message=async t=>{try{await page.waitForFunction(x=>document.querySelector('#message').textContent.includes(x),t,{timeout:30000})}catch(error){throw Error('waiting for '+t+'; current message: '+await page.locator('#message').textContent())}};
 async function waitReady(id){await page.waitForFunction(x=>document.querySelector('#canvas-a').dataset.imageId===String(x),id,{timeout:30000})}
 async function choose(cam,feature){await page.locator('#feature').selectOption(feature);await page.locator('#view-a').selectOption(String(cam.image_id));await waitReady(cam.image_id)}
 async function clickPixel(cam,xy,{fine=true,wait=true}={}){
   const revision=(await read()).state.revision;await waitReady(cam.image_id);
   const canvas=page.locator('#canvas-a'),box=await canvas.boundingBox();
   await canvas.click({position:{x:xy[0]/cam.width_px*box.width,y:xy[1]/cam.height_px*box.height}});
   if(fine){try{await page.locator('#zoom-panel').waitFor({state:'visible',timeout:30000})}catch(e){throw Error('zoom image '+cam.image_id+' unavailable: '+await page.locator('#message').textContent())}const z=page.locator('#zoom'),r=await z.boundingBox(),crop=await z.evaluate(e=>({x:Number(e.dataset.cropX),y:Number(e.dataset.cropY),w:Number(e.dataset.cropWidth),h:Number(e.dataset.cropHeight)}));await z.click({position:{x:(xy[0]-crop.x)*r.width/crop.w,y:(xy[1]-crop.y)*r.height/crop.h}})}
   if(wait)await page.waitForFunction(async n=>(await(await fetch('/api/modeler/state')).json()).state.revision>n,revision,{timeout:60000});
 }
 async function saveIfc(name){const bytes=await page.evaluate(async()=>{const r=await fetch('/api/export/model.ifc');if(!r.ok)throw Error('IFC download '+r.status);return Array.from(new Uint8Array(await r.arrayBuffer()))});fs.writeFileSync(path.join(out,name),Buffer.from(bytes))}
 try{
  const layout=[];
  for(const [w,h] of [[1440,900],[1920,1080]]){
   page=await browser.newPage({viewport:{width:w,height:h}});attach(page);await page.goto(base+'modeler',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#canvas-b').dataset.imageId&&document.querySelector('#viewer canvas'),null,{timeout:60000});
   const project=await page.evaluate(async()=>await(await fetch('/api/project')).json());if(project.project?.operator_kind!=='automation')throw Error('refusing to modify a human trial workspace');
   const info=await page.evaluate(()=>({viewport:[innerWidth,innerHeight],page:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],buttons:['new-wall','mark-toggle','solve','open-delivery'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return {id,top:r.top,bottom:r.bottom,left:r.left,right:r.right}}),model:!!document.querySelector('#viewer canvas'),fallback:!document.querySelector('#viewer-fallback').hidden,photos:[...document.querySelectorAll('.photo-frame canvas')].map(c=>[Math.round(c.getBoundingClientRect().width),Math.round(c.getBoundingClientRect().height)])}));
   if(info.page[0]>w||info.page[1]>h||info.buttons.some(b=>b.top<0||b.bottom>h||b.left<0||b.right>w)||!info.model||info.fallback)throw Error('layout failure '+JSON.stringify(info));
   await page.screenshot({path:path.join(out,`modeler-${w}.png`)});await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#canvas-b').dataset.imageId&&document.querySelector('#viewer canvas'),null,{timeout:60000});await page.screenshot({path:path.join(out,`home-${w}.png`)});layout.push(info);await page.close();
  }
  page=await browser.newPage({viewport:{width:1440,height:900}});attach(page);await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#viewer canvas'),null,{timeout:60000});
  let initial=await read();if(!initial.has_model||initial.uploads.length!==29)throw Error('missing real preloaded model');await saveIfc('before.ifc');
  await page.locator('#view-top').click();await page.locator('#view-front').click();await page.locator('#view-iso').click();await page.locator('#zoom-in').click();await page.locator('#reset-view').click();
  await page.locator('#mark-toggle').click();const old=initial.state.observations.find(o=>o.kind==='point'&&o.feature_id==='p1'),oldCam=initial.state.cameras.find(c=>c.image_id===old.image_id);
  await choose(oldCam,'p1');await clickPixel(oldCam,[old.pixel_xy[0]+.5,old.pixel_xy[1]]);await page.locator('#solve').click();await message('候选已求解');
  await page.locator('#open-delivery').click();await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();await message('已生成 IFC 版本');await saveIfc('revised.ifc');
  await page.locator('#new-wall').click();await page.locator('#object-id').fill('ux-unreviewed-hull');await page.locator('#create-object').click();await message('已创建候选');
  if(await page.locator('#object').inputValue()!=='ux-unreviewed-hull')throw Error('new candidate not selected');
  let count=0;for(const obs of input.observations.filter(o=>o.object_id===input.objects[0].id&&o.kind==='point')){const cam=input.cameras.find(c=>c.image_id===obs.image_id);await choose(cam,obs.feature_id);await clickPixel(cam,obs.pixel_xy);count++}
  await page.locator('#solve').click();await message('候选已求解');let solved=(await read()).state;if(solved.solution.objects.length!==2)throw Error('expected existing plus new candidate');
  await page.screenshot({path:path.join(out,'candidate.png')});await page.locator('#open-delivery').click();await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();await page.waitForFunction(()=>document.querySelector('#delivery-message').textContent.includes('nonrectangular')||document.querySelector('#delivery-message').textContent.includes('nonvertical'),null,{timeout:30000});
  const rejection=await page.locator('#delivery-message').textContent();await page.locator('#delivery-dialog button[value="cancel"]').last().click();
  // Queue multiple genuine UI annotations with delayed network responses; they
  // remain automation and never count as independent observations or labor.
  const first=input.observations.find(o=>o.object_id===input.objects[0].id&&o.kind==='point'),cam=input.cameras.find(c=>c.image_id===first.image_id);
  await choose(cam,first.feature_id);await page.locator('#fine-mode').uncheck();await page.route('**/api/modeler/point',async route=>{await new Promise(r=>setTimeout(r,120));await route.continue()});
  const before=(await read()).state.revision;for(const dx of [.1,.3,.5,.7])await clickPixel(cam,[first.pixel_xy[0]+dx,first.pixel_xy[1]],{fine:false,wait:false});
  await page.waitForFunction(async n=>(await(await fetch('/api/modeler/state')).json()).state.revision>=n,before+4,{timeout:60000});
  await page.waitForFunction(()=>!document.querySelector('#solve').disabled,null,{timeout:60000});await page.unroute('**/api/modeler/point');
  let after=(await read()).state;if(after.revision!==before+4)throw Error('queued updates did not all persist');
  await page.locator('[data-right-tab="observations"]').click();await page.locator('#observations-tab details summary').click();page.once('dialog',d=>d.accept());await page.locator('#discard-object').click();await message('候选已放弃');
  await page.locator('#solve').click();await message('候选已求解');await page.locator('#open-delivery').click();await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();await message('已生成 IFC 版本');await saveIfc('after-discard.ifc');
  if(errors.length||failed.length)throw Error('browser issues '+JSON.stringify({errors,failed}));
  const result={status:'PASS_WITH_EXPECTED_CANDIDATE_REJECTION',operator:'automation',layout,real_photos:initial.uploads.length,registered_cameras:initial.state.cameras.length,photo_observations:count,queued_annotations:4,new_candidate_status:'UNREVIEWED_FEATURE_HULL_NOT_CONFIRMED_WALL',rejection,ifc_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(out,'revised.ifc'))).digest('hex'),errors,failed,caveats:['Automation is not a human trial or labor measurement.','The new feature hull was correctly rejected for IFC.']};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
