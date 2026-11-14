/* Actual local COLMAP + vision + editable IFC browser run on development data.
 * Scripted confirmations are NOT human labor or independent scale evidence.
 * Usage: node studio_multiview_ai_browser.cjs BASE IMAGE_DIR SELECTED_NAME NEW_DIR
 */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{chromium}=require('playwright');
const [base,dir,selectedName,out]=process.argv.slice(2);if(!out)throw Error('BASE IMAGE_DIR SELECTED_NAME NEW_DIR required');
if(fs.existsSync(out))throw Error('use a new output directory');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const files=fs.readdirSync(dir).filter(x=>/\.(jpg|png)$/i.test(x)).sort().map(x=>path.join(dir,x));
 if(files.length<4||files.length>32)throw Error('need 4–32 photos');
 const target=path.join(dir,selectedName),sha=crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex'),photoId='upload-'+sha.slice(0,16);
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.fill('#project-name','Eyeful real multiview and AI candidate');await page.selectOption('#operator-kind','automation');await page.click('#create');await page.waitForFunction(()=>document.querySelector('#project-status').textContent.includes('项目：'));
 await page.setInputFiles('#photo-upload',files);await page.waitForFunction(n=>document.querySelector('#photo-select').options.length===n,files.length,{timeout:120000});
 await page.click('#geometry-reconstruct');await page.waitForFunction(()=>project?.geometry_runs?.length===1,null,{timeout:180000});
 let state=await page.evaluate(()=>fetch('/api/project').then(r=>r.json())),geometry=state.project.geometry_runs[0];
 if(geometry.status!=='UNVERIFIED_RESEARCH_CANDIDATE'||geometry.registered_cameras.length<3||!geometry.registered_cameras.some(x=>x.photo_id===photoId))throw Error('target photo was not registered in usable candidate');
 await page.selectOption('#photo-select',photoId);await page.click('#geometry-use-camera');const f=geometry.camera_parameters[0].params[0];
 if(Math.abs(Number(await page.inputValue('#camera-fx'))-f)>1e-8||await page.inputValue('#camera-pitch')!=='')throw Error('camera estimate not applied safely');
 await page.click('#ai-analyze');await page.waitForFunction(()=>project?.vision_runs?.length===1,null,{timeout:60000});await page.click('#accept-segments');
 await page.waitForFunction(()=>project?.annotations?.some(x=>x.kind==='wall_boundary'),null,{timeout:30000});
 state=await page.evaluate(()=>fetch('/api/project').then(r=>r.json()));const candidates=state.project.annotations.filter(x=>x.kind==='wall_boundary');if(candidates.length<2)throw Error('fewer than two AI segment candidates');
 await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
 for(const [id,value] of Object.entries({'camera-pitch':0,'anchor-length':1,'anchor-description':'1 m PLACEHOLDER; no independent measurement','wall-height':2.5,'wall-thickness':0.12}))await page.fill('#'+id,String(value));
 await page.selectOption('#anchor-basis','assumed');await page.selectOption('#height-basis','assumed');await page.check('#confirm-camera');await page.check('#confirm-scale');await page.click('#bind-scale');await page.waitForFunction(()=>document.querySelector('#scale-status').textContent.includes('已绑定'));
 await page.check('#confirm-candidate');await page.click('#generate');await page.waitForURL(base+'/',{timeout:30000});await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 1'));
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 const cameraEvidence=model.evidence.find(e=>e.id===geometry.id&&e.kind==='multiview_camera_estimate');
 if(!cameraEvidence||cameraEvidence.inputs.length!==files.length||!model.nodes[0].evidence_refs.includes(geometry.id))throw Error('multi-view camera provenance missing from IR');
 fs.writeFileSync(path.join(out,'original.ifc'),ifc);fs.writeFileSync(path.join(out,'original.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'geometry-candidate.json'),JSON.stringify(geometry,null,2));
 await page.selectOption('#attribute','height');await page.fill('#value','2.6');await page.fill('#reason','Scripted edit; height is an assumption');await page.click('#save');await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 2'));
 const revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text())));await page.screenshot({path:path.join(out,'model.png'),fullPage:true});
 if(errors.length)throw Error(errors.join(';'));
 const result={operator:'automation',photos:files.length,registered:geometry.registered_cameras.length,sparse_points:geometry.sparse_points,reprojection_px:geometry.mean_reprojection_error_px,geometry_status:geometry.status,photo_sha256:sha,target_photo_registered:true,camera_focal_px:f,ai_wall_segment_candidates:candidates.length,method:'COLMAP focal estimate and single-photo floor backprojection; wall corners not triangulated',scale:'ASSUMED 1 m, not independently measured',camera_pitch_roll_height:'ASSUMED',independent_accuracy:'NOT_MEASURED',human_labor:'NOT_MEASURED',revision_after_edit:revised.revision};
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
