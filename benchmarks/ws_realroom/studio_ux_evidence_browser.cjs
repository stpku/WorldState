// Real CPU vision and editing on an isolated project. All actions are automation.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
 const [base,out,photoFile]=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(base||'')||!out||fs.existsSync(out))throw Error('expected local server and new output');
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--enable-unsafe-swiftshader']}),page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];let thumbnailActive=0,thumbnailPeak=0;
 const thumbnail=r=>new URL(r.url()).pathname.startsWith('/api/photo-thumbnail/');
 page.on('request',r=>{if(thumbnail(r)){thumbnailActive++;thumbnailPeak=Math.max(thumbnailPeak,thumbnailActive)}});
 page.on('requestfinished',r=>{if(thumbnail(r))thumbnailActive--});
 page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>{if(thumbnail(r))thumbnailActive--;if(new URL(r.url()).pathname.startsWith('/api/'))errors.push(new URL(r.url()).pathname+': '+r.failure()?.errorText)});
 try{
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#attribute').options.length);
  const project=await page.evaluate(async()=>await(await fetch('/api/project')).json());if(project.project.operator_kind!=='automation')throw Error('refusing to modify a human trial workspace');
  let uploadStatus='NOT_TESTED';if(photoFile){await page.locator('#upload').setInputFiles(photoFile);await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('照片已上传'),null,{timeout:60000});uploadStatus='PASS'}
  const before=await page.evaluate(async()=>await(await fetch('/api/model')).json()),wall=before.elements.find(e=>e.ifc_type==='IfcWall');
  await page.locator('#attribute').selectOption('height');await page.locator('#value').fill(String(wall.parameters.height.value+.01));await page.locator('#reason').fill('自动化交互测试，非实测');await page.locator('#save').click();
  await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('参数修改已保存'),null,{timeout:30000});const after=await page.evaluate(async()=>await(await fetch('/api/model')).json());if(after.revision!==before.revision+1)throw Error('parameter revision missing');
  await page.locator('#command').fill('将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效');await page.locator('#send').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('规则命令已执行'),null,{timeout:30000});
  const commanded=await page.evaluate(async()=>await(await fetch('/api/model')).json());if(commanded.revision!==after.revision+1)throw Error('rule revision missing');
  await page.locator('#ai-analyze').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('视觉分析完成'),null,{timeout:180000});
  const result=await page.evaluate(async()=>await(await fetch('/api/project')).json()),run=result.project.vision_runs.at(-1);if(run.provider!=='upernet-convnext-tiny-ade20k-onnx'||run.device!=='CPU')throw Error('real CPU vision provider missing');
  const rows=await page.locator('#vision-candidates .candidate-row').count();if(rows){await page.locator('#vision-candidates .candidate-row').first().getByRole('button',{name:'拒绝'}).click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('视觉建议已记录'),null,{timeout:30000})}
  await page.locator('[data-left-tab="evidence"]').click();const photos=await page.locator('#photos .photo-item').count();await page.waitForFunction(()=>[...document.querySelectorAll('#photos img')].some(i=>i.complete&&i.naturalWidth>0),null,{timeout:30000});if(photos!==29||errors.length)throw Error(JSON.stringify({photos,errors}));
  await page.screenshot({path:path.join(out,'vision-and-evidence.png')});
  const ifc=await page.evaluate(async()=>{const r=await fetch('/api/export/model.ifc');if(!r.ok)throw Error('IFC export '+r.status);return Array.from(new Uint8Array(await r.arrayBuffer()))});fs.writeFileSync(path.join(out,'property-command.ifc'),Buffer.from(ifc));
  await page.locator('#new-wall').click();await page.locator('#object-id').fill('ux-selection-probe');await page.locator('#create-object').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('已创建候选'));
  const scene=page.locator('#scene'),box=await scene.boundingBox();let picked=false;
  for(const [x,y] of [[.5,.5],[.48,.5],[.52,.5],[.5,.45],[.5,.55]]){await scene.click({position:{x:box.width*x,y:box.height*y}});if((await page.locator('#detail').textContent()).includes(wall.id)){picked=true;break}}
  if(!picked)throw Error('cannot select the real IFC wall in the 3D view');
  if(!(await page.locator('#dimension-overlay').textContent()).includes('长'))throw Error('selected dimensions missing');
  if(errors.length||thumbnailPeak<1||thumbnailPeak>2)throw Error(JSON.stringify({errors,thumbnailPeak}));
  const report={status:'PASS',operator:'automation',real_photo_upload:uploadStatus,parameter_revision:after.revision,rule_revision:commanded.revision,real_vision:run.provider,vision_seconds:run.runtime_seconds,vision_candidates:rows,photos,thumbnail_peak_requests:thumbnailPeak,ifc_3d_selection:picked,dimensions_visible:true,errors,scope:'Development data; not human annotation or independent accuracy.'};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
