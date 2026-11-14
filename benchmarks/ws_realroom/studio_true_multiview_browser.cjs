/* Real local end-to-end: photographs -> SfM -> semantic tracks -> 3D planes -> IFC.
 * The scripted operator selects tracked points and an assumed scale derived from
 * same-scene Metashape camera positions. This is NOT human work, a physical
 * ruler measurement, independent accuracy, or acceptance.
 * Usage: BASE IMAGE_DIR EYEFUL_MANIFEST REFERENCE_CAMERAS_JSON CALIBRATION_BIN NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{chromium}=require('playwright');
const [base,dir,manifestPath,refPath,calibrationPath,out]=process.argv.slice(2);if(!out)throw Error('BASE IMAGE_DIR MANIFEST REFERENCE_CAMERAS CALIBRATION_BIN NEW_DIR required');
if(fs.existsSync(out))throw Error('use a new output directory');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const files=fs.readdirSync(dir).filter(x=>/\.(jpg|png)$/i.test(x)).sort().map(x=>path.join(dir,x));
 if(files.length<4||files.length>32)throw Error('need 4–32 photos');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(base+'/builder');await page.fill('#project-name','Real multiview semantic surface development');await page.selectOption('#operator-kind','automation');await page.click('#create');await page.waitForFunction(()=>document.querySelector('#project-status').textContent.includes('项目：'));
 await page.setInputFiles('#photo-upload',files);await page.waitForFunction(n=>document.querySelector('#photo-select').options.length===n,files.length,{timeout:120000});
 // Same capture's documented camera calibration, not a guessed focal length.
 const referenceRaw=fs.readFileSync(refPath),referenceSha=crypto.createHash('sha256').update(referenceRaw).digest('hex');
 if(referenceSha!=='5b1628c1e72f64052a471c8bfd96f98d2cca78fdf6b2feef45a1ed991e4b1283')throw Error('reference camera JSON hash mismatch');
 const ref=JSON.parse(referenceRaw).KRT,sensor=ref.find(x=>x.cameraId.split('/').at(-1)===path.basename(files[0],path.extname(files[0])))?.sensorId;
 if(!Number.isInteger(sensor))throw Error('cannot associate source photo with its calibration sensor');
 const rawCal=fs.readFileSync(calibrationPath),calibrationSha=crypto.createHash('sha256').update(rawCal).digest('hex');
 if(calibrationSha!=='05e702e72fb9076d6fef2eb40e6dbd082ad7615dc381cb2709bace449fec74b7')throw Error('calibration file hash mismatch');let offset=8,cal=null;
 for(let i=0,n=Number(rawCal.readBigUInt64LE(0));i<n;i++){let id=rawCal.readInt32LE(offset),kind=rawCal.readInt32LE(offset+4),w=Number(rawCal.readBigUInt64LE(offset+8)),h=Number(rawCal.readBigUInt64LE(offset+16));offset+=24;if(kind!==1)throw Error('unexpected camera calibration model');let vals=[0,1,2,3].map(j=>rawCal.readDoubleLE(offset+j*8));offset+=32;if(id===sensor)cal={w,h,vals}}
 if(!cal)throw Error('calibration sensor absent');const uploaded=await page.evaluate(()=>uploads[0]),sx=uploaded.width/cal.w,sy=uploaded.height/cal.h;
 await page.selectOption('#geometry-mode','photo_floor');for(const [id,val] of Object.entries({'camera-fx':cal.vals[0]*sx,'camera-fy':cal.vals[1]*sy,'camera-cx':cal.vals[2]*sx,'camera-cy':cal.vals[3]*sy,'camera-description':`Eyeful Tower raf_emptyroom same camera sensor ${sensor}; COLMAP undistorted cameras.bin, resized to uploaded dimensions`,'camera-calibration-sha':calibrationSha}))await page.fill('#'+id,String(val));await page.check('#geometry-use-calibration');
 await page.click('#geometry-reconstruct');await page.waitForFunction(()=>project?.geometry_runs?.length===1,null,{timeout:180000});
 const geometryStatus=await page.evaluate(()=>project.geometry_runs[0].status);if(geometryStatus!=='UNVERIFIED_RESEARCH_CANDIDATE')throw Error('calibrated SfM failed: '+geometryStatus);
 await page.click('#fusion-reconstruct');await page.waitForFunction(()=>fusionData?.wall_surfaces?.length>0,null,{timeout:240000});
 const fusion=await page.evaluate(()=>fusionData);if(fusion.cameras.length<4||!fusion.floor_planes.length)throw Error('insufficient multiview geometry');
 const cams=Object.fromEntries(fusion.cameras.map(c=>[c.image_id,c])),distance=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i])),dot=(a,b)=>a.reduce((v,x,i)=>v+x*b[i],0),groups=new Map();
 for(const t of fusion.tracks){if(t.status!=='SUPPORTED'||t.semantic_class!==0)continue;const obs=t.observations.filter(o=>o.usable&&o.semantic_class===0&&o.reprojection_error_px<1.5);
  for(let i=0;i<obs.length;i++)for(let j=i+1;j<obs.length;j++){const a=obs[i],b=obs[j],v=t.xyz.map((x,k)=>x-cams[a.image_id].center_world[k]),w=t.xyz.map((x,k)=>x-cams[b.image_id].center_world[k]),angle=Math.acos(Math.max(-1,Math.min(1,dot(v,w)/(Math.hypot(...v)*Math.hypot(...w)))))*180/Math.PI;
   if(angle<2)continue;let ids=[a.image_id,b.image_id].sort((x,y)=>x-y),key=ids.join(',');if(!groups.has(key))groups.set(key,[]);groups.get(key).push({track:t,obs:[a,b]});}}
 let best=null;for(const [key,items] of groups)for(let i=0;i<items.length;i++)for(let j=i+1;j<items.length;j++){let d=distance(items[i].track.xyz,items[j].track.xyz);if(d>1&&d<5&&(!best||d>best.d))best={d,key,a:items[i],b:items[j]}}
 if(!best)throw Error('no two matching real feature tracks with useful baseline');const ids=best.key.split(',').map(Number);
 // Estimate scale from the same-scene Metashape camera baseline solely as a
 // labeled correlated assumption; this is not a physical ruler measurement.
 const manifest=JSON.parse(fs.readFileSync(manifestPath)),names=Object.fromEntries(manifest.input_photos.map(x=>[x.sha256,x.filename.replace(/\.jpg$/,'')]));
 function refCenter(camera){let name=names[camera.sha256],v=ref.find(x=>x.cameraId.split('/').at(-1)===name);if(!v)throw Error('camera missing in correlated reference');let T=v.T,t=T[3].slice(0,3);return [0,1,2].map(j=>-(T[j][0]*t[0]+T[j][1]*t[1]+T[j][2]*t[2]))}
 let factor=distance(refCenter(cams[ids[0]]),refCenter(cams[ids[1]]))/distance(cams[ids[0]].center_world,cams[ids[1]].center_world),assumedLength=best.d*factor;
 async function mark(imageId){let camera=cams[imageId],photoId='upload-'+camera.sha256.slice(0,16);await page.selectOption('#photo-select',photoId);await page.waitForFunction(id=>photo?.id===id&&photoImage?.complete&&photoImage?.src.includes(id),photoId);await page.selectOption('#annotation-kind','scale');await page.fill('#wall-id','wall-1');
  const a=best.a.obs.find(x=>x.image_id===imageId),b=best.b.obs.find(x=>x.image_id===imageId),canvas=page.locator('#photo-canvas'),box=await canvas.boundingBox(),size=await canvas.evaluate(c=>({width:c.width,height:c.height}));
  for(const [x,y] of [a.pixel_xy,b.pixel_xy])await canvas.click({position:{x:(x+.5)*box.width/size.width,y:(y+.5)*box.height/size.height}});await page.click('#save-annotation');}
 await mark(ids[0]);await mark(ids[1]);await page.waitForFunction(()=>project.annotations.filter(a=>a.kind==='scale').length===2);
 const ordered=[...fusion.wall_surfaces].sort((a,b)=>b.support_count-a.support_count),chosen=[];
 for(const s of ordered){if(!chosen.length||chosen.every(x=>Math.abs(dot(x.normal,s.normal))<Math.cos(35*Math.PI/180)))chosen.push(s);if(chosen.length===2)break}
 if(chosen.length<2)throw Error('no two sufficiently distinct surface hypotheses');
 for(const s of chosen)await page.locator('#fusion-surfaces input[value="'+s.id+'"]').check();
 await page.fill('#anchor-length',String(assumedLength));await page.selectOption('#anchor-basis','assumed');await page.fill('#anchor-description','SCRIPTED DEBUG: assumed from correlated same-scene Metashape camera baseline; selected feature points are not independently measured ruler endpoints');await page.fill('#wall-thickness','0.12');
 await page.check('#confirm-fusion-scale');await page.click('#fusion-solve-scale');await page.waitForFunction(()=>document.querySelector('#fusion-scale-status').textContent.includes('已求解'),null,{timeout:30000});
 await page.check('#allow-fusion-assumed');await page.check('#confirm-candidate');await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});await page.click('#fusion-generate');await page.waitForURL(base+'/',{timeout:30000});await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 1'));
 const model=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),ifc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));
 if(model.mode!=='assisted'||model.elements.filter(e=>e.ifc_type==='IfcWall').length!==2||!model.evidence.some(e=>e.kind==='multiview_semantic_surface'))throw Error('assisted IFC IR not backed by 3D surface evidence');
 fs.writeFileSync(path.join(out,'original.json'),JSON.stringify(model,null,2));fs.writeFileSync(path.join(out,'original.ifc'),ifc);fs.writeFileSync(path.join(out,'fusion.json'),JSON.stringify(fusion,null,2));
 const originalHeight=model.elements.find(e=>e.ifc_type==='IfcWall').parameters.height.value;
 await page.selectOption('#attribute','height');await page.fill('#value',String(originalHeight+.1));await page.fill('#reason','Scripted dimension edit, not a field measurement');await page.click('#save');await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 2'));
 const revised=await page.evaluate(()=>fetch('/api/model').then(r=>r.json())),revisedIfc=await page.evaluate(()=>fetch('/api/export/model.ifc').then(r=>r.text()));fs.writeFileSync(path.join(out,'revised.json'),JSON.stringify(revised,null,2));fs.writeFileSync(path.join(out,'revised.ifc'),revisedIfc);
 await page.screenshot({path:path.join(out,'model.png'),fullPage:true});if(errors.length)throw Error(errors.join(';'));
 const result={operator:'automation',source_photos:files.length,registered:fusion.cameras.length,tracks:fusion.tracks.length,surface_hypotheses:fusion.wall_surfaces.length,selected_surface_ids:chosen.map(x=>x.id),wall_candidates:2,calibration_source_sha256:calibrationSha,calibration_sensor:sensor,anchor_basis:'assumed from correlated same-scene camera baseline; not a ruler measurement',assumed_anchor_m:assumedLength,anchor_track_ids:[best.a.track.id,best.b.track.id],metric_accuracy:'NOT_MEASURED',human_time:'NOT_MEASURED',scope:'PARTIAL_OPEN',studio_edit_revision:revised.revision};
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
