/* Real AI inference and scripted selection of three separated image lines.
 * This is NOT human annotation, a physical measurement or room acceptance.
 * Usage: node studio_ai_three_segments.cjs BASE PHOTO COLMAP_RESULT NEW_DIR
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,photo,sfmPath,out]=process.argv.slice(2);if(!out)throw Error('BASE PHOTO COLMAP_RESULT NEW_DIR required');
if(fs.existsSync(out))throw Error('use a new output directory');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.fill('#project-name','Eyeful real-photo three separated candidates');await page.selectOption('#operator-kind','automation');await page.click('#create');await page.waitForFunction(()=>document.querySelector('#project-status').textContent.includes('项目：'));
 await page.setInputFiles('#photo-upload',photo);await page.waitForFunction(()=>document.querySelector('#photo-select').options.length>0);
 await page.click('#ai-analyze');await page.waitForFunction(()=>document.querySelector('#vision-status').textContent.includes('个图像候选'),null,{timeout:60000});
 const state=await page.evaluate(()=>fetch('/api/project').then(r=>r.json())),run=state.project.vision_runs.at(-1);
 await page.click('#accept-segments');await page.waitForFunction(()=>project?.annotations?.length===9,null,{timeout:30000});
 const acceptedState=await page.evaluate(()=>fetch('/api/project').then(r=>r.json()));
 const selected=acceptedState.project.annotations.filter(x=>x.kind==='wall_boundary');
 const endpoints=acceptedState.project.annotations.filter(x=>x.kind==='corner');
 if(selected.length!==3||endpoints.length!==6)throw Error('batch did not produce three separated candidate walls');
 await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
 const sfm=JSON.parse(fs.readFileSync(sfmPath)),prefix=path.basename(photo).split('_')[0];if(!sfm.inputs.every(x=>x.file.split('_')[0]===prefix))throw Error('SfM camera-name prefix differs');
 const [f,cx,cy]=sfm.camera_parameters[0].params;
 await page.selectOption('#geometry-mode','photo_floor_segments');for(const [id,value] of Object.entries({'camera-fx':f,'camera-fy':f,'camera-cx':cx,'camera-cy':cy,'camera-pitch':0,'camera-description':'Focal estimate from separate SfM run on same named camera; pitch 0 and roll 0 assumed; calibration unverified','anchor-length':1,'anchor-description':'EXPLICIT PLACEHOLDER 1 m, not a physical measurement; scale UNKNOWN','wall-height':2.5,'wall-thickness':0.12}))await page.fill('#'+id,String(value));
 await page.selectOption('#anchor-basis','assumed');await page.selectOption('#height-basis','assumed');await page.check('#confirm-camera');await page.check('#confirm-scale');await page.click('#bind-scale');await page.waitForFunction(()=>document.querySelector('#scale-status').textContent.includes('已绑定'));
 await page.check('#confirm-candidate');await page.click('#generate');await page.waitForURL(base+'/',{timeout:30000});await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 1'));
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 const walls=model.elements.filter(e=>e.ifc_type==='IfcWall'),accepted=model.evidence.filter(e=>e.kind==='vision_candidate_accepted');
 if(walls.length!==3||accepted.length!==9||model.elements.some(e=>e.ifc_type==='IfcSpace'))throw Error('unexpected model or provenance');
 fs.writeFileSync(path.join(out,'original.ifc'),ifc);fs.writeFileSync(path.join(out,'original.json'),JSON.stringify(model,null,2));
 await page.selectOption('#attribute','height');await page.fill('#value','2.6');await page.fill('#reason','Scripted preview; height is an assumption');await page.click('#save');await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 2'));
 const revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text())));
 await page.screenshot({path:path.join(out,'model.png'),fullPage:true});if(errors.length)throw Error(errors.join(';'));
 const result={operator:'automation',input:'real photograph and real CPU inference',line_selection:'product-selected non-maximum suppression; scripted user confirmation; no manual coordinates',wall_segments:3,connections:'UNKNOWN; no room closure',ai_evidence_count:accepted.length,selected_line_ids:selected.map(c=>c.vision_candidate_id),selected_endpoint_ids:endpoints.map(c=>c.vision_candidate_id),metric_scale:'ASSUMED 1m; no measured anchor',height:'ASSUMED',camera_attitude:'ASSUMED',focal:'self-calibrated estimate from different photos with same camera-name prefix; unverified',photo_registered_in_sfm:sfm.registered_cameras.some(c=>c.name===path.basename(photo)),actual_human_time:'NOT_MEASURED',independent_accuracy:'NOT_MEASURED',revision_after_edit:revised.revision};
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
