// Real local browser exercise on development photo tracks. All interaction is
// automation; this is not a human annotation or productivity measurement.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');

async function main(){
  const [url,images,manifestPath,inputPath,output]=process.argv.slice(2);
  if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url||'')||!images||!manifestPath||!inputPath||!output||fs.existsSync(output))
    throw Error('expected local URL, images, camera manifest, candidate input and new output');
  fs.mkdirSync(output,{recursive:true});const input=JSON.parse(fs.readFileSync(inputPath,'utf8'));
  const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const state=()=>page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
  try{
    await page.goto(url+'modeler',{waitUntil:'networkidle'});
    let existing=await state(),seen=new Set(existing.uploads.map(x=>x.sha256)),k=seen.size;
    for(const cam of input.cameras){
      if(seen.has(cam.sha256))continue;
      await page.locator('#upload').setInputFiles(path.join(images,cam.photo),{timeout:120000});k++;
      await page.waitForFunction(n=>document.querySelector('#project-status').textContent.includes('已上传 '+n+' 张'),k,{timeout:120000});
    }
    await page.locator('#camera-file').setInputFiles(manifestPath,{timeout:120000});
    await page.waitForFunction(n=>document.querySelector('#view-a').options.length===n,input.cameras.length,{timeout:60000});
    await page.locator('#fine-mode').uncheck(); // scripted approximate click; accepted track provides exact observed pixels
    await page.locator('#object-id').fill('unreviewed-feature-hull');await page.locator('#vertex-count').fill('4');
    await page.locator('#create-object').click();await page.waitForFunction(()=>document.querySelector('#object').options.length===1);
    const mapping=[];
    for(const feature of input.objects[0].vertices){
      await page.locator('#feature').selectOption(feature);
      const source=input.observations.find(o=>o.feature_id===feature);
      await page.locator('#view-a').selectOption(String(source.image_id));
      const camera=input.cameras.find(c=>c.image_id===source.image_id);
      await page.waitForTimeout(400);
      const canvas=page.locator('#canvas-a');await canvas.scrollIntoViewIfNeeded();const box=await canvas.boundingBox();
      await canvas.dispatchEvent('click',{clientX:box.x+source.pixel_xy[0]*box.width/camera.width_px,
                                          clientY:box.y+source.pixel_xy[1]*box.height/camera.height_px});
      await page.waitForFunction(f=>document.querySelector('#message').textContent.includes('观察已记录'),feature,{timeout:30000});
      await page.locator('#suggest').click();
      await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('特征建议'),null,{timeout:30000});
      let current=(await state()).state;const suggestions=current.suggestions.filter(x=>x.track_id===source.source_track_id&&x.status==='proposed');
      if(!suggestions.length)throw Error('nearest track differs from fixture for '+feature+': '+JSON.stringify(current.suggestions));
      const needed=new Set(input.observations.filter(o=>o.feature_id===feature).map(o=>o.image_id));
      for(const item of suggestions.filter(x=>needed.has(x.target_image_id))){
        const row=page.locator('#suggestions div').filter({hasText:'照片 '+item.target_image_id+' ·'}).first();
        await row.getByRole('button',{name:'接受'}).click();
        await page.waitForFunction(id=>document.querySelector('#suggestions').textContent.includes('照片 '+id+' ·')&&
          [...document.querySelectorAll('#suggestions div')].some(x=>x.textContent.includes('照片 '+id+' ·')&&x.textContent.includes('accepted')),item.target_image_id,{timeout:30000});
      }
      current=(await state()).state;
      const selected=current.observations.filter(o=>o.object_id==='unreviewed-feature-hull'&&o.feature_id===feature);
      if(selected.length<2||selected.some(o=>o.accepted_by!=='automation'))throw Error('unverified track provenance missing');
      mapping.push({feature,track:source.source_track_id,views:selected.map(o=>o.image_id)});
    }
    await page.locator('#solve').click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('候选已求解'),null,{timeout:90000});
    let solved=(await state()).state;
    if(solved.solution.objects.length!==1)throw Error('expected a new surface candidate');
    await page.locator('#confirm-up').check();await page.locator('#confirm-rectangle').check();await page.locator('#commit').click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('未生成 IFC'),null,{timeout:30000});
    const gate=await page.locator('#message').textContent();
    if(!gate.includes('nonrectangular')&&!gate.includes('nonvertical'))throw Error('unexpected gate: '+gate);
    if(errors.length)throw Error('browser errors '+errors.join(';'));
    await page.locator('.views').screenshot({path:path.join(output,'views.png')});
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({status:'PASS_EXPECTED_IFC_REJECTION',operator:'automation',
      input_kind:'unreviewed semantic feature hull; includes furniture; not a wall',mapping,
      point_rms_px:solved.solution.optimization.point_rms_px,gate,errors,
      warning:'No human annotation, valid wall result or labor cost is claimed.'},null,2)+'\n');
    console.log(JSON.stringify({status:'PASS_EXPECTED_IFC_REJECTION',gate,mapping},null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
