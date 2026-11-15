// Disposable, automated browser check against real preloaded ETH3D images.
// This does not represent human annotation, accepted walls, or labor time.
const {chromium}=require('playwright');
const fs=require('fs');const path=require('path');
async function main(){
  const [url,inputFile,output]=process.argv.slice(2);
  if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url||'')||!inputFile||!output||fs.existsSync(output))throw Error('expected local URL, input and new output');
  fs.mkdirSync(output,{recursive:true});const input=JSON.parse(fs.readFileSync(inputFile));
  const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const getState=()=>page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
  const message=async text=>page.waitForFunction(s=>document.querySelector('#message').textContent.includes(s),text,{timeout:90000});
  async function pixel(cam,p){
    if(await page.locator('#view-a').inputValue()!==String(cam.image_id))await page.locator('#view-a').selectOption(String(cam.image_id));
    let revision=(await getState()).state.revision;
    const canvas=page.locator('#canvas-a');await canvas.scrollIntoViewIfNeeded();let box=await canvas.boundingBox();
    await canvas.dispatchEvent('click',{clientX:box.x+p[0]*box.width/cam.width_px,clientY:box.y+p[1]*box.height/cam.height_px});
    try{await page.locator('#zoom-panel').waitFor({state:'visible',timeout:30000})}
    catch(e){throw Error('zoom did not open for image '+cam.image_id+': '+await page.locator('#message').textContent())}
    let z=await page.evaluate(()=>pendingZoom);
    const zoom=page.locator('#zoom');await zoom.scrollIntoViewIfNeeded();box=await zoom.boundingBox();
    await zoom.dispatchEvent('click',{clientX:box.x+(p[0]-z.x)*box.width/z.w,clientY:box.y+(p[1]-z.y)*box.height/z.h});
    await page.waitForFunction(async n=>(await(await fetch('/api/modeler/state')).json()).state.revision>n,revision,{timeout:30000});
    await message('观察已记录');
  }
  async function download(name){const bytes=await page.evaluate(async()=>{let r=await fetch('/api/export/model.ifc');if(!r.ok)throw Error('IFC export '+r.status);return Array.from(new Uint8Array(await r.arrayBuffer()))});fs.writeFileSync(path.join(output,name),Buffer.from(bytes))}
  try{
    await page.goto(url+'modeler',{waitUntil:'networkidle'});let initial=await getState();
    const project=await page.evaluate(async()=>await(await fetch('/api/project')).json());
    if(project.project?.operator_kind!=='automation')throw Error('refusing to write scripted clicks to a human trial workspace');
    if(initial.uploads.length!==29||initial.state.cameras.length!==29||!initial.has_model)throw Error('preload incomplete');
    const a=await page.locator('#view-a').inputValue(),b=await page.locator('#view-b').inputValue();
    if(!a||!b||a===b)throw Error('need two initial source views');
    await download('preexisting.ifc');const old=initial.state.observations.find(o=>o.kind==='point'&&o.feature_id==='p1');
    await page.locator('#feature').selectOption('p1');await pixel(initial.state.cameras.find(c=>c.image_id===old.image_id),[old.pixel_xy[0]+.5,old.pixel_xy[1]]);
    await page.locator('#solve').click();await message('候选已求解');let first=(await getState()).state.solution;
    await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();await message('已生成 IFC');
    await download('existing-revised.ifc');
    await page.locator('#object-id').fill('new-unreviewed-hull');await page.locator('#vertex-count').fill('4');await page.locator('#create-object').click();await message('已创建并选中新墙面候选');
    if(await page.locator('#object').inputValue()!=='new-unreviewed-hull')throw Error('new object was not selected');
    for(const obs of input.observations.filter(o=>o.object_id===input.objects[0].id&&o.kind==='point')){
      await page.locator('#feature').selectOption(obs.feature_id);await pixel(input.cameras.find(c=>c.image_id===obs.image_id),obs.pixel_xy);
    }
    await page.locator('#solve').click();await message('候选已求解');let solved=(await getState()).state.solution;
    if(solved.objects.length!==2)throw Error('both visible patches must remain in same scene');
    await page.locator('.views').screenshot({path:path.join(output,'multiview.png')});
    let source=input.observations.find(o=>o.object_id===input.objects[0].id&&o.kind==='point');
    await page.locator('#feature').selectOption(source.feature_id);await pixel(input.cameras.find(c=>c.image_id===source.image_id),[source.pixel_xy[0]+.2,source.pixel_xy[1]]);
    await page.locator('#solve').click();await message('候选已求解');let modified=(await getState()).state.solution;
    await page.locator('#commit').click();await message('未生成 IFC');const rejection=await page.locator('#message').textContent();
    if(!rejection.includes('nonrectangular')&&!rejection.includes('nonvertical'))throw Error('unexpected result: '+rejection);
    if(errors.length)throw Error(errors.join(';'));
    const report={status:'PASS_WITH_EXPECTED_NEW_IFC_REJECTION',operator:'automation',initial_photos:29,initial_cameras:29,
      initial_selected_views:[a,b],existing_ifc_edited_and_exported:true,first_existing_rms_px:first.optimization.point_rms_px,
      new_surface_solved_with_existing:solved.objects.length,modified_and_resolved:true,new_ifc_gate:rejection,
      source_kind:'unreviewed real-image semantic feature hull; may include furniture; NOT a confirmed wall',
      observation_rms_px:modified.optimization.point_rms_px,errors,
      caveats:['All clicks were automated and do not count as a human trial or labor time.',
        'The new candidate fails the IFC geometry gate and must not be called a wall.',
        'The exported IFC is the previous real partial patch with assumed scale and thickness.']};
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
