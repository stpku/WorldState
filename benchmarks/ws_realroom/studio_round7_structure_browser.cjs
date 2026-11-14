/* Real local project: cached photos/cameras/masks -> line solve -> partial IFC.
 * The existing anchor and this scripted height are assumptions, not measured;
 * automated selections and elapsed time do not represent human labor.
 * Usage: BASE NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,out]=process.argv.slice(2);if(!out||fs.existsSync(out))throw Error('BASE NEW_OUTPUT_DIR required');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1600,height:1100},recordVideo:{dir:path.join(out,'video'),size:{width:1600,height:1100}}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.waitForFunction(()=>fusionData?.cameras?.length&&project?.fusion_scale,null,{timeout:30000});
 const source=await page.evaluate(()=>({registered_photos:fusionData.cameras.length,track_count:fusionData.tracks.length}));
 const previous=await page.evaluate(()=>fetch('/api/model').then(r=>r.json()));
 await page.click('#structure-reconstruct');await page.waitForFunction(()=>structureData?.groups?.length,null,{timeout:60000});
 let structure=await page.evaluate(()=>structureData),good=structure.groups.filter(g=>g.floor_consistency==='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'&&g.floor_joint_holdout_status==='CONSISTENT_UNVERIFIED'&&g.visible_support_intervals.length);
 if(!good.length)throw Error('no geometrically eligible line candidates');
 let refused=structure.groups.filter(g=>!good.includes(g));
 for(const g of refused)if(!await page.locator('#structure-candidates input[value="'+g.id+'"]').isDisabled())throw Error('conflicting candidate was not disabled');
 for(const g of good)await page.locator('#structure-candidates input[value="'+g.id+'"]').check();
 await page.fill('#wall-height','2.3');await page.selectOption('#height-basis','assumed');await page.fill('#height-description','Scripted development assumption, not a physical measurement');await page.fill('#wall-thickness','0.12');
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');
 // Reuse actual AI intersection observations to exercise the annotation UI.
 // The browser is the operator; these are not human-confirmed measurements.
 const candidate=structure.corner_candidates.find(c=>c.max_reprojection_error_px<2.5&&c.floor_consistency==='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY');
 if(!candidate)throw Error('no suitable real image corner candidate for the scripted UI check');
 let annotatedCount=await page.evaluate(()=>project.annotations.filter(a=>a.kind==='corner'&&a.object_id==='node-1').length);
 for(const obs of candidate.source_observations){
  const camera=await page.evaluate(id=>fusionData.cameras.find(c=>c.image_id===id),obs.image_id),photoId='upload-'+camera.sha256.slice(0,16);
  await page.selectOption('#photo-select',photoId);await page.waitForFunction(id=>photo?.id===id&&photoImage?.complete&&photoImage?.src.includes(id),photoId);
  await page.selectOption('#annotation-kind','corner');await page.fill('#corner-id','node-1');
  const canvas=page.locator('#photo-canvas'),box=await canvas.boundingBox(),size=await canvas.evaluate(c=>({width:c.width,height:c.height}));
  await canvas.click({position:{x:(obs.pixel_xy[0]+.5)*box.width/size.width,y:(obs.pixel_xy[1]+.5)*box.height/size.height}});await page.click('#save-annotation');
  annotatedCount++;await page.waitForFunction(n=>project.annotations.filter(a=>a.kind==='corner'&&a.object_id==='node-1').length>=n,annotatedCount);
 }
 await page.waitForFunction(()=>project.annotations.filter(a=>a.kind==='corner'&&a.object_id==='node-1').length>=2);
 await page.click('#structure-generate');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('角点标注已变化'));
 const staleMessage=await page.locator('#status').textContent();const oldStructure=structure.id;
 await page.click('#structure-reconstruct');await page.waitForFunction(id=>structureData?.id&&structureData.id!==id,oldStructure,{timeout:60000});
 structure=await page.evaluate(()=>structureData);good=structure.groups.filter(g=>g.floor_consistency==='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'&&g.floor_joint_holdout_status==='CONSISTENT_UNVERIFIED'&&g.visible_support_intervals.length);refused=structure.groups.filter(g=>!good.includes(g));
 if(!structure.annotated_corners.accepted.some(c=>c.status==='SCRIPTED_OR_MIXED_CORRESPONDENCE_NOT_HUMAN'))throw Error('scripted corner source was lost');
 for(const g of good)await page.locator('#structure-candidates input[value="'+g.id+'"]').check();
 await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
 await page.click('#structure-generate');await page.waitForURL(base+'/',{timeout:30000});
 await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),previous.revision+1);
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 if(model.mode!=='assisted'||model.scale.independence!=='assumed'||model.elements.filter(e=>e.ifc_type==='IfcWall').length!==good.length)throw Error('incorrect candidate provenance or model');
 fs.writeFileSync(path.join(out,'initial.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'initial.ifc'),ifc);fs.writeFileSync(path.join(out,'structure.json'),JSON.stringify(structure,null,2));
 const wall=model.elements.find(e=>e.ifc_type==='IfcWall');await page.selectOption('#attribute','height');await page.fill('#value',String(wall.parameters.height.value+.1));await page.fill('#reason','Scripted preview edit; not a physical measurement');await page.click('#save');
 await page.waitForFunction(n=>document.querySelector('#summary').textContent.includes('版本 '+n),model.revision+1);
 const revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),revisedIfc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),revisedIfc);await page.screenshot({path:path.join(out,'model.png'),fullPage:true});
 if(errors.length)throw Error(errors.join('; '));
 const result={operator:'automation',source:'previous real Eyeful development project, cached photos and registered cameras',registered_photos:source.registered_photos,
    input_track_count:source.track_count,
    groups:structure.groups.map(g=>({id:g.id,views:g.support_view_count,floor:g.floor_consistency,holdout:g.floor_joint_holdout_status,selected:good.includes(g)})),
    corner_candidates:structure.corner_candidates.length,scripted_annotated_corners:structure.annotated_corners.accepted.length,
    stale_corner_annotations_rejected:staleMessage,selected_walls:good.length,rejected_candidates:refused.length,
    scale:'assumed, correlated, not measured',height:'assumed, not measured',revision_before:previous.revision,revision_after:revised.revision,
    independent_accuracy:'NOT_MEASURED',human_labor:'NOT_MEASURED',status:'PARTIAL_OPEN_NOT_RELEASE_READY'};
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 await context.close();await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
