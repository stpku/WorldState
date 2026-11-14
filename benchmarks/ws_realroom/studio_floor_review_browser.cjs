/* Exercise a seeded real fusion in a browser. Never a human-cost study.
 * BASE TRACK_ID PHOTO_NAME NEW_OUTPUT_DIR; workspace operator must be automation.
 */
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
const [base,id,photoName,out]=process.argv.slice(2);if(!out)throw Error('BASE TRACK_ID PHOTO_NAME NEW_OUTPUT_DIR required');
if(fs.existsSync(out))throw Error('choose a new external output directory');
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 try{
  const page=await b.newPage({viewport:{width:1500,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept('脚本检查：像素需人工核验'));
  await page.goto(base+'/builder');await page.waitForFunction(()=>project!==null&&fusionData!==null);
  if(await page.evaluate(()=>project.operator_kind)!=='automation')throw Error('requires an automation-only fixture');
  await page.locator('details').filter({hasText:'地面支持与语义复核'}).locator('summary').click();
  const row=page.locator('#floor-review .ann-row').filter({hasText:`轨迹 ${id} ·`});
  await row.getByRole('button',{name:'查看 '+photoName}).click();
  await page.waitForFunction(()=>reviewPoint!==null&&photo?.id===reviewPoint.photoId&&photoImage!==null);
  const canvas=page.locator('#photo-canvas'),box=await canvas.boundingBox();
  await page.evaluate(()=>$('photo-canvas').addEventListener('click',e=>{let r=e.currentTarget.getBoundingClientRect();
    window.expectedPhotoPixel=[Math.round((e.clientX-r.left)*photo.width/r.width),Math.round((e.clientY-r.top)*photo.height/r.height)]},{once:true,capture:true}));
  await canvas.click({position:{x:box.width/2,y:box.height/2}});
  const mapping=await page.evaluate(()=>({image:[photo.width,photo.height],canvas:[$('photo-canvas').width,$('photo-canvas').height],point:photoPoints[0],expected:window.expectedPhotoPixel}));
  if(mapping.point.some((v,i)=>v!==mapping.expected[i])||mapping.canvas[0]>1600)throw Error('original photo pixel mapping failed');
  await row.getByRole('button',{name:'标记疑点'}).click();await page.waitForFunction(()=>project?.floor_reviews?.at(-1)?.decision==='suspect');
  const blocked=await page.evaluate(async()=>{let r=await fetch('/api/fusion/scale',{method:'POST',headers:{'Content-Type':'application/json','X-WorldState-Token':token},body:JSON.stringify({fusion_id:fusionData.id,confirmed_endpoints:true})});return {status:r.status,body:await r.json()}});
  if(blocked.status!==400||!blocked.body.error.includes('人工疑点')||errors.length)throw Error('review was not safely blocked: '+JSON.stringify({blocked,errors}));
  const result=await page.evaluate(()=>({review:project.floor_reviews.at(-1),operator:project.operator_kind}));
  result.mapping=mapping;result.blocked=blocked;result.scope='automation-only seeded prior fusion; not new reconstruction or human labor';
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
  await page.screenshot({path:path.join(out,'review.png')});console.log(JSON.stringify(result,null,2));
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});
