// Scripted browser run using prior development observations. It does not
// represent a human annotation, independent wall or a measured scale.
const {chromium}=require('playwright');
const fs=require('fs');const path=require('path');

async function main(){
  const [url,images,manifestPath,inputPath,output]=process.argv.slice(2);
  if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url||'')||!images||!manifestPath||!inputPath||!output||fs.existsSync(output))
    throw Error('expected local URL, images, camera manifest, general modeler input and new output');
  fs.mkdirSync(output,{recursive:true});const input=JSON.parse(fs.readFileSync(inputPath,'utf8'));
  const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const getState=()=>page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
  const saveIfc=async filename=>{let buffer=await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())));fs.writeFileSync(path.join(output,filename),Buffer.from(buffer))};
  async function clickPixel(cam,pixel){
    if(await page.locator('#view-a').inputValue()!==String(cam.image_id))await page.locator('#view-a').selectOption(String(cam.image_id));
    await page.waitForTimeout(150);
    const canvas=page.locator('#canvas-a');await canvas.scrollIntoViewIfNeeded();let box=await canvas.boundingBox();
    await canvas.dispatchEvent('click',{clientX:box.x+pixel[0]*box.width/cam.width_px,clientY:box.y+pixel[1]*box.height/cam.height_px});
    await page.locator('#zoom-panel').waitFor({state:'visible',timeout:30000});
    let z=await page.evaluate(()=>pendingZoom);const zoom=page.locator('#zoom');await zoom.scrollIntoViewIfNeeded();box=await zoom.boundingBox();
    await zoom.dispatchEvent('click',{clientX:box.x+(pixel[0]-z.x)*box.width/z.w,clientY:box.y+(pixel[1]-z.y)*box.height/z.h});
    await page.waitForFunction(()=>document.querySelector('#zoom-panel').hidden,{timeout:30000});
  }
  try{
    await page.goto(url+'modeler',{waitUntil:'networkidle'});
    let existing=await getState(),seen=new Set(existing.uploads.map(x=>x.sha256)),n=seen.size;
    for(const cam of input.cameras){if(seen.has(cam.sha256))continue;await page.locator('#upload').setInputFiles(path.join(images,cam.photo),{timeout:120000});n++;
      await page.waitForFunction(k=>document.querySelector('#project-status').textContent.includes('已上传 '+k+' 张'),n,{timeout:120000})}
    await page.locator('#camera-file').setInputFiles(manifestPath,{timeout:120000});
    await page.waitForFunction(k=>document.querySelector('#view-a').options.length===k,input.cameras.length,{timeout:60000});
    await page.locator('#object-id').fill('generic-wall-patch');await page.locator('#construction').selectOption('edge_to_line');
    await page.locator('#vertex-count').fill('4');await page.locator('#create-object').click();
    await page.waitForFunction(()=>document.querySelector('#object').options.length===1);
    let expected=0;
    for(const obs of input.observations.filter(o=>o.kind==='point')){
      await page.locator('#mark-mode').selectOption('point');await page.locator('#feature').selectOption(obs.feature_id);
      const cam=input.cameras.find(c=>c.image_id===obs.image_id);await clickPixel(cam,obs.pixel_xy);expected++;
      await page.waitForFunction(async n=>{let d=await(await fetch('/api/modeler/state')).json();return d.state.observations.length===n},expected,{timeout:30000});
    }
    for(const obs of input.observations.filter(o=>o.kind==='line')){
      await page.locator('#mark-mode').selectOption('line');await page.locator('#feature').selectOption('p3');await page.locator('#line-end').selectOption('p4');
      const cam=input.cameras.find(c=>c.image_id===obs.image_id);await clickPixel(cam,obs.points_px[0]);
      await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('线段终点'),null,{timeout:30000});
      await clickPixel(cam,obs.points_px[1]);expected++;
      await page.waitForFunction(async n=>{let d=await(await fetch('/api/modeler/state')).json();return d.state.observations.length===n},expected,{timeout:30000});
    }
    await page.locator('#solve').click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('候选已求解'),null,{timeout:90000});
    let first=(await getState()).state;
    if(first.solution.objects[0].vertices.filter(v=>v.status==='inferred_line_intersection').length!==2)throw Error('inferred vertices not marked');
    await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('已生成 IFC'),null,{timeout:30000});
    await saveIfc('first.ifc');
    const original=input.observations.find(o=>o.kind==='point'&&o.feature_id==='p1');
    await page.locator('#mark-mode').selectOption('point');await page.locator('#feature').selectOption('p1');
    await clickPixel(input.cameras.find(c=>c.image_id===original.image_id),[original.pixel_xy[0]+.5,original.pixel_xy[1]]);
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('观察已记录'),null,{timeout:30000});
    await page.locator('#solve').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('候选已求解'),null,{timeout:90000});
    await page.locator('#commit').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('已生成 IFC'),null,{timeout:30000});
    await saveIfc('revised.ifc');let end=await getState();
    if(end.state.solution.objects.length!==1||end.state.observations.some(o=>o.origin!=='automation'))throw Error('automation source or candidate lost');
    if(errors.length)throw Error('browser errors: '+errors.join(';'));
    await page.locator('.views').screenshot({path:path.join(output,'views.png')});
    let report={status:'PASS',operator:'automation',scene:'same Round 9 development patch; not a new independent wall',
      observations:end.state.observations.length,inferred_vertices:2,first_rms_px:first.solution.optimization.point_rms_px,
      final_rms_px:end.state.solution.optimization.point_rms_px,revision:2,errors,
      caveats:['No human annotation or labor time.','Wall coplanarity, scale, up direction and thickness remain unverified.']};
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
