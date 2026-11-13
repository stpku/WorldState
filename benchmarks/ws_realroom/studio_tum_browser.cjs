/* Development smoke run against the TUM RGB-D room, not acceptance or a human-cost measurement.
 * Start a new Studio photo workspace first; pass URL, two RGB paths, and a new report directory.
 * NODE_PATH must provide Playwright. See the Round 4 status for the same-sensor anchor derivation.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {chromium} = require('playwright');

async function main() {
  const [base, photo1, photo2, output] = process.argv.slice(2);
  if (!base || !photo1 || !photo2 || !output) throw Error('usage: node studio_tum_browser.cjs BASE PHOTO1 PHOTO2 NEW_REPORT_DIR');
  fs.mkdirSync(output);
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1500,height:1100}}), errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('dialog',dialog=>dialog.accept());
  async function clickPhoto(x,y) {
    const canvas=page.locator('#photo-canvas'), box=await canvas.boundingBox();
    const size=await canvas.evaluate(c=>({width:c.width,height:c.height}));
    await canvas.click({position:{x:(x+.5)*box.width/size.width,y:(y+.5)*box.height/size.height}});
  }
  async function mark(kind, points, corner, expected) {
    await page.selectOption('#annotation-kind',kind);
    await page.fill('#wall-id','wall-1');
    if(corner) await page.fill('#corner-id',corner);
    for(const [x,y] of points) await clickPhoto(x,y);
    await page.click('#save-annotation');
    await page.waitForFunction(n=>document.querySelectorAll('#annotation-list .ann-row').length===n,expected);
  }
  async function getModel(){return (await page.request.get(base+'/api/model')).json()}
  await page.goto(base+'/',{waitUntil:'networkidle'});
  await page.fill('#project-name','TUM 开发样例：可见墙面片段');
  await page.selectOption('#operator-kind','automation');
  await page.click('#create');
  await page.waitForFunction(()=>document.querySelector('#project-status').textContent.includes('项目：'));
  await page.locator('#photo-upload').setInputFiles([photo1,photo2]);
  await page.waitForFunction(()=>document.querySelector('#photo-select').options.length===2);
  await page.waitForFunction(()=>document.querySelector('#photo-canvas').width===640);
  await mark('wall_boundary',[[255,170],[415,155]],null,1);
  await mark('corner',[[255,170]],'node-1',2);
  await mark('corner',[[415,155]],'node-2',3);
  const project=(await (await page.request.get(base+'/api/project')).json()).project;
  const cameraCorners=project.annotations.filter(a=>a.kind==='corner').map(a=>a.points[0]);
  if(JSON.stringify(cameraCorners)!==JSON.stringify([[255,170],[415,155]]))throw Error('browser corner pixels do not match the depth-derived anchor');
  await page.selectOption('#geometry-mode','photo_floor');
  for(const [id,value] of Object.entries({'camera-fx':'525','camera-fy':'525','camera-cx':'319.5','camera-cy':'239.5',
      'camera-pitch':'30','camera-description':'近似内参；俯角 30° 和零横滚均为未核实假设',
      'anchor-length':'0.6038487127014679','anchor-description':'同传感器深度帧 deprojection，非独立测量',
      'wall-height':'0.45','wall-thickness':'0.12'})) await page.fill('#'+id,value);
  await page.check('#confirm-camera');await page.selectOption('#anchor-basis','same_sensor');await page.selectOption('#height-basis','assumed');
  await page.screenshot({path:path.join(output,'builder.png'),fullPage:true});
  await page.click('#generate');
  await page.waitForFunction(()=>document.querySelector('#summary')?.textContent.includes('版本 1'),null,{timeout:30000});
  const original=await getModel();
  if(original.scale.method!=='photo_floor'||original.validation.scope!=='PARTIAL_OPEN')throw Error('wrong reconstruction method or scope');
  if(original.elements[0].classification.status!=='simulated')throw Error('automated annotation must not be marked human confirmed');
  await page.goto(base+'/builder',{waitUntil:'networkidle'});
  await page.locator('#annotation-list .ann-row').nth(2).locator('button').click();
  await page.waitForFunction(()=>document.querySelectorAll('#annotation-list .ann-row').length===2);
  await mark('corner',[[400,155]],'node-2',3);
  await page.click('#generate');
  await page.waitForFunction(()=>document.querySelector('#summary')?.textContent.includes('版本 2'),null,{timeout:30000});
  const corrected=await getModel();
  if(Math.abs(corrected.nodes[1].y-original.nodes[1].y)<1e-5)throw Error('photo annotation did not affect geometry');
  await page.fill('#command','将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效');
  await page.click('#send');
  await page.waitForFunction(()=>document.querySelector('#summary')?.textContent.includes('版本 3'),null,{timeout:30000});
  const revised=await getModel();
  await page.screenshot({path:path.join(output,'model.png'),fullPage:true});
  const report=await page.request.get(base+'/api/report'), exported=await page.request.get(base+'/api/export/model.ifc');
  if(report.status()!==200||exported.status()!==200||errors.length)throw Error('browser or export failed: '+errors.join('; '));
  fs.writeFileSync(path.join(output,'browser-revision-3.ifc'),await exported.body(),{flag:'wx'});
  const hash=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
  fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify({
    kind:'SCRIPTED_BROWSER_DEVELOPMENT_RUN',photo1_sha256:hash(photo1),photo2_sha256:hash(photo2),
    real_photo:true,automatic_clicks_not_human_labor:true,annotation_classification:original.elements[0].classification.status,
    scope:original.validation.scope,method:original.scale.method,
    anchor_basis:original.scale.independence,anchor_m:0.6038487127014679,
    assumptions:'floor level; pitch 30°, roll zero and approximate intrinsics are unverified; wall height 0.45 m and thickness 0.12 m assumed',
    original_node_2:original.nodes[1],corrected_node_2:corrected.nodes[1],
    revised_length_m:revised.history.at(-1).after,ifc_status:exported.status(),report_status:report.status(),errors
  },null,2)+'\n',{flag:'wx'});
  console.log('TUM development browser flow completed; recorded as partial and unverified.');
  await browser.close();
}
main().catch(e=>{console.error(e);process.exit(1)});
