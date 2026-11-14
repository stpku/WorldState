/* Recheck an existing real-photo Studio project after floor support safeguards.
 * BASE OUTPUT_DIR; all clicks are automation, not human labor or accuracy.
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,out]=process.argv.slice(2);
if(!base||!out||fs.existsSync(out))throw Error('BASE and a new OUTPUT_DIR are required');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');
 await page.waitForFunction(()=>fusionData?.cameras?.length&&project?.fusion_scale,null,{timeout:30000});
 const source=await page.evaluate(()=>({photos:fusionData.cameras.length,tracks:fusionData.tracks.length}));
 const before=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 const old=await page.evaluate(()=>structureData?.id||null);
 await page.click('#structure-reconstruct');
 await page.waitForFunction(id=>structureData?.id&&structureData.id!==id&&structureData.groups?.length,old,{timeout:60000});
 const structure=await page.evaluate(()=>structureData);
 const good=structure.groups.filter(g=>g.floor_consistency==='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'&&g.floor_joint_holdout_status==='CONSISTENT_UNVERIFIED'&&g.visible_support_intervals.length);
 if(!good.length)throw Error('no eligible real line candidate');
 for(const g of good)await page.locator('#structure-candidates input[value="'+g.id+'"]').check();
 await page.fill('#wall-height','2.3');await page.selectOption('#height-basis','assumed');
 await page.fill('#height-description','Scripted development assumption; no physical measurement');
 await page.fill('#wall-thickness','0.12');await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');
 await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
 await page.click('#structure-generate');await page.waitForURL(base+'/',{timeout:30000});
 await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),before.revision+1);
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 const ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 if(model.scale.independence!=='assumed'||model.elements.filter(e=>e.ifc_type==='IfcWall').length!==good.length)throw Error('unexpected model provenance or wall count');
 fs.writeFileSync(path.join(out,'initial.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'initial.ifc'),ifc);
 const wall=model.elements.find(e=>e.ifc_type==='IfcWall');
 await page.selectOption('#attribute','height');await page.fill('#value',String(wall.parameters.height.value+.1));
 await page.fill('#reason','Scripted development edit; not a physical measurement');await page.click('#save');
 await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),model.revision+1);
 const revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 const revisedIfc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),revisedIfc);
 await page.screenshot({path:path.join(out,'model.png'),fullPage:true});
 if(errors.length)throw Error(errors.join('; '));
 const result={operator:'automation',source:'previous real Eyeful development workspace',registered_photos:source.photos,
  input_track_count:source.tracks,eligible_candidates:good.length,revision_before:before.revision,revision_after:revised.revision,
  scale:'assumed and correlated, not a physical measurement',human_time:'NOT_MEASURED',accuracy:'NOT_MEASURED'};
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
