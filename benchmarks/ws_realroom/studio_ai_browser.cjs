/* Real-model, headless browser smoke test. The scripted operator is NOT a human
 * time study; its assumed scale and room height are NOT physical measurements.
 * Usage: node studio_ai_browser.cjs URL PHOTO COLMAP_RESULT NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [url,imagePath,sfmPath,out]=process.argv.slice(2);if(!out)throw Error('URL PHOTO COLMAP_RESULT NEW_OUTPUT_DIR required');
if(fs.existsSync(out))throw Error('use a new output directory');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}});let errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/builder');await page.fill('#project-name','Eyeful real-photo scripted preview');await page.selectOption('#operator-kind','automation');await page.click('#create');
 await page.setInputFiles('#photo-upload',imagePath);await page.waitForFunction(()=>document.querySelector('#photo-select').options.length>0);
 await page.click('#ai-analyze');await page.waitForFunction(()=>document.querySelector('#vision-status').textContent.includes('个图像候选'),{timeout:60000});
 let state=await page.evaluate(()=>fetch('/api/project').then(r=>r.json()));const run=state.project.vision_runs.at(-1),lines=run.candidates.filter(c=>c.kind==='wall_floor_line');
 if(lines.length<2)throw Error('model did not propose two floor lines');
 const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);let selected=null;
 for(const a of lines){for(const b of lines){if(a===b)continue;let va=[a.points_px[1][0]-a.points_px[0][0],a.points_px[1][1]-a.points_px[0][1]],vb=[b.points_px[1][0]-b.points_px[0][0],b.points_px[1][1]-b.points_px[0][1]];
 let angle=Math.abs(Math.atan2(va[0]*vb[1]-va[1]*vb[0],va[0]*vb[0]+va[1]*vb[1]));angle=Math.min(angle,Math.PI-angle);if(angle<.22)continue;
 for(let i=0;i<2;i++)for(let j=0;j<2;j++)if(dist(a.points_px[i],b.points_px[j])<15&&!selected)selected={a,b,first:a.points_px[1-i],shared:a.points_px[i],last:b.points_px[1-j]};}}
 if(!selected)throw Error('model produced no approximately connected differently oriented floor lines');
 const endpoint=p=>run.candidates.find(c=>c.kind==='line_endpoint'&&JSON.stringify(c.points_px[0])===JSON.stringify(p));
 let points=[selected.first,selected.shared,selected.last],corners=points.map(endpoint);if(corners.some(x=>!x))throw Error('missing model-proposed endpoints');
 async function accept(candidate,wall,node){await page.fill('#wall-id',wall);if(node)await page.fill('#vision-node-id',node);let index=run.candidates.findIndex(c=>c.id===candidate.id);let row=page.locator('#vision-candidates .ann-row').nth(index);await row.getByRole('button',{name:'接受'}).click();await page.waitForFunction(({id,runId})=>{let r=project?.vision_runs?.find(x=>x.id===runId);return r?.candidates?.find(x=>x.id===id)?.status==='accepted'},{id:candidate.id,runId:run.id});}
 await accept(selected.a,'wall-1');await accept(selected.b,'wall-2');for(let i=0;i<3;i++)await accept(corners[i],i===2?'wall-2':'wall-1',`node-${i+1}`);
 await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
 const sfm=JSON.parse(fs.readFileSync(sfmPath));if(!sfm.registered_cameras.some(c=>c.name===path.basename(imagePath)))throw Error('photo not registered by SfM');const [f,cx,cy]=sfm.camera_parameters[0].params;
 await page.selectOption('#geometry-mode','photo_floor');for(const [id,value] of Object.entries({'camera-fx':f,'camera-fy':f,'camera-cx':cx,'camera-cy':cy,'camera-pitch':0,'camera-description':'SfM self-calibrated focal length; pitch zero and roll zero assumed, not independently verified','anchor-length':1,'anchor-description':'EXPLICIT PLACEHOLDER 1 m, not a physical measurement; unknown metric scale','wall-height':2.5,'wall-thickness':0.12}))await page.fill('#'+id,String(value));
 await page.selectOption('#anchor-basis','assumed');await page.selectOption('#height-basis','assumed');await page.check('#confirm-camera');await page.check('#confirm-scale');await page.click('#bind-scale');await page.waitForFunction(()=>document.querySelector('#scale-status').textContent.includes('已绑定'));
 await page.check('#confirm-candidate');await page.click('#generate');await page.waitForURL(url+'/',{timeout:60000});await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 1'));
 let original=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));let ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 fs.writeFileSync(path.join(out,'original.json'),JSON.stringify(original,null,2));fs.writeFileSync(path.join(out,'original.ifc'),ifc);
 let accepted=original.evidence.filter(e=>e.kind==='vision_candidate_accepted');if(accepted.length<5)throw Error('AI candidates missing from IR evidence');
 await page.selectOption('#attribute','height');await page.fill('#value','2.6');await page.fill('#reason','Scripted preview; assumed height edit, not a measurement');await page.click('#save');await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 2'));
 let revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));let revisedIfc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),revisedIfc);
 await page.screenshot({path:path.join(out,'model.png'),fullPage:true});if(errors.length)throw Error('browser errors: '+errors.join('; '));
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({operator:'automation',model:'real CPU inference on real photo',walls:original.elements.filter(e=>e.ifc_type==='IfcWall').length,ai_evidence_count:accepted.length,selected_candidate_ids:[selected.a.id,selected.b.id,...corners.map(c=>c.id)],metric_scale:'ASSUMED 1m; not measurement',height:'ASSUMED',pitch_and_roll:'ASSUMED',registered_sfm_input:true,revision_after_edit:revised.revision,actual_human_time:'NOT_MEASURED',independent_accuracy:'NOT_MEASURED'},null,2));
 console.log(fs.readFileSync(path.join(out,'browser-result.json'),'utf8'));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
