/* Real persisted development project: changed scale must reject old binding.
 * The changed value is a scripted counterfactual, not a physical measurement.
 * Usage: BASE NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,out]=process.argv.slice(2);
if(!out||fs.existsSync(out))throw Error('BASE NEW_OUTPUT_DIR required');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');
 await page.waitForFunction(()=>fusionData?.wall_surfaces?.length&&project?.fusion_scale,null,{timeout:30000});
 const old=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 const ids=old.evidence.filter(e=>e.kind==='multiview_semantic_surface').map(e=>e.surface_id);
 for(const id of ids)await page.locator('#fusion-surfaces input[value="'+id+'"]').check();
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');
 const originalLength=Number(await page.inputValue('#anchor-length'));
 await page.fill('#anchor-length',String(originalLength*1.2));
 await page.click('#fusion-generate');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('重新求解'),null,{timeout:30000});
 const stale=await page.locator('#status').textContent();
 const afterReject=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 if(afterReject.revision!==old.revision)throw Error('stale scale unexpectedly generated a revision');
 await page.check('#confirm-fusion-scale');await page.click('#fusion-solve-scale');
 await page.waitForFunction(()=>document.querySelector('#fusion-scale-status').textContent.includes('已求解'));
 await page.click('#fusion-generate');await page.waitForURL(base+'/',{timeout:30000});
 await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),old.revision+1);
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 const ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 const ratio=model.scale.metres_per_relative_unit/old.scale.metres_per_relative_unit;
 if(Math.abs(ratio-1.2)>1e-8||model.mode!=='assisted')throw Error('scale or assisted mode incorrect');
 function lengths(m){const nodes=Object.fromEntries(m.nodes.map(n=>[n.id,n]));return Object.fromEntries(m.elements.filter(e=>e.ifc_type==='IfcWall').map(e=>[e.id,Math.hypot(nodes[e.start].x-nodes[e.end].x,nodes[e.start].y-nodes[e.end].y)]))}
 const a=lengths(old),b=lengths(model);
 if(Object.keys(a).some(id=>!b[id]||Math.abs(b[id]/a[id]-1.2)>1e-8))throw Error('wall identity or scaled lengths incorrect');
 fs.writeFileSync(path.join(out,'rescaled.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'rescaled.ifc'),ifc);
 await page.goto(base+'/builder');await page.waitForFunction(()=>fusionData?.wall_surfaces?.length&&project?.fusion_scale);
 for(const id of ids)await page.locator('#fusion-surfaces input[value="'+id+'"]').check();
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');
 const fx=Number(await page.inputValue('#camera-fx'));if(!(fx>0))throw Error('calibrated focal length missing');
 await page.fill('#camera-fx',String(fx+1));await page.click('#fusion-reconstruct');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('先重新恢复相机'));
 const cameraFusion=await page.locator('#status').textContent();await page.click('#fusion-generate');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('相机输入已改变'));
 const cameraGenerate=await page.locator('#status').textContent();
 const final=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 if(final.revision!==model.revision)throw Error('changed camera unexpectedly generated a revision');
 await page.reload();await page.waitForFunction(()=>fusionData?.wall_surfaces?.length&&project?.fusion_scale);
 await page.click('#fusion-reconstruct');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('先重新恢复相机'));
 const cameraPersisted=await page.locator('#status').textContent();
 if(errors.length)throw Error(errors.join('; '));
 const report={operator:'automation',basis:'assumed from correlated same-scene reconstruction',
   scenario:'scripted 20% reference change; not a physical measurement',stale_binding_rejected:stale,
   scale_ratio:ratio,wall_length_ratios:Object.fromEntries(Object.keys(a).map(id=>[id,b[id]/a[id]])),
   camera_change_fusion_rejected:cameraFusion,camera_change_generation_rejected:cameraGenerate,camera_change_after_reload_rejected:cameraPersisted,
   revision_before:old.revision,revision_after:model.revision,human_time:'NOT_MEASURED',independent_accuracy:'NOT_MEASURED'};
 fs.writeFileSync(path.join(out,'lifecycle-result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
