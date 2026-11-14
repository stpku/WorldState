/* Re-solve a persisted multiview anchor and regenerate; scripted, not a human measurement. */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,out]=process.argv.slice(2);if(!out||fs.existsSync(out))throw Error('BASE NEW_OUTPUT_DIR required');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']}),page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.waitForFunction(()=>fusionData?.wall_surfaces?.length&&project?.fusion_scale,null,{timeout:30000});
 const old=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ids=old.evidence.filter(e=>e.kind==='multiview_semantic_surface').map(e=>e.surface_id);
 for(const id of ids)await page.locator('#fusion-surfaces input[value="'+id+'"]').check();await page.check('#confirm-fusion-scale');await page.click('#fusion-solve-scale');await page.waitForFunction(()=>document.querySelector('#fusion-scale-status').textContent.includes('已求解'));
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');await page.click('#fusion-generate');await page.waitForURL(base+'/',{timeout:30000});await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),old.revision+1);
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text())),anchor=model.evidence.find(e=>e.kind==='multiview_scale_anchor');
 if(model.mode!=='assisted')throw Error('scripted candidate confirmation must remain assisted mode');
 if(anchor.anchor.measurement_uncertainty_m!==null||!anchor.solution.uncertainty.includes('unknown'))throw Error('unknown measurement uncertainty was not preserved');
 fs.writeFileSync(path.join(out,'latest.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'latest.ifc'),ifc);await page.screenshot({path:path.join(out,'latest.png'),fullPage:true});if(errors.length)throw Error(errors.join('; '));
 let result={operator:'automation',revision:model.revision,anchor_basis:anchor.anchor.basis,measurement_uncertainty:'UNKNOWN',independent_accuracy:'NOT_MEASURED',human_time:'NOT_MEASURED'};fs.writeFileSync(path.join(out,'resolve-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
