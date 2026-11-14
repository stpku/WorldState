/* Resume a real development project, reject stale scale and rebind it.
 * Scripted confirmation is NOT human measurement or acceptance.
 * Usage: BASE NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,out]=process.argv.slice(2);if(!out||fs.existsSync(out))throw Error('BASE NEW_OUTPUT_DIR required');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']}),page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.waitForFunction(()=>fusionData?.wall_surfaces?.length&&project?.fusion_scale,null,{timeout:30000});
 const old=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ids=old.evidence.filter(e=>e.kind==='multiview_semantic_surface').map(e=>e.surface_id);
 for(const id of ids)await page.locator('#fusion-surfaces input[value="'+id+'"]').check();
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');await page.click('#fusion-generate');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('重新求解'),null,{timeout:30000});
 const rejected=await page.locator('#status').textContent();await page.check('#confirm-fusion-scale');await page.click('#fusion-solve-scale');await page.waitForFunction(()=>document.querySelector('#fusion-scale-status').textContent.includes('已求解'));
 await page.click('#fusion-generate');await page.waitForURL(base+'/',{timeout:30000});await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),old.revision+1);
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 let camera=model.evidence.find(e=>e.kind==='multiview_camera_reconstruction');if(!camera?.calibration?.source_sha256)throw Error('camera calibration provenance missing');
 fs.writeFileSync(path.join(out,'rebound.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'rebound.ifc'),ifc);await page.screenshot({path:path.join(out,'rebound.png'),fullPage:true});
 if(errors.length)throw Error(errors.join('; '));let result={operator:'automation',old_revision:old.revision,new_revision:model.revision,stale_binding_rejected:rejected,camera_calibration_sha256:camera.calibration.source_sha256,scale:model.scale.independence,independent_accuracy:'NOT_MEASURED',human_time:'NOT_MEASURED'};
 fs.writeFileSync(path.join(out,'rebind-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
