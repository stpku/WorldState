/* Browser integration test using real images with invented annotations and dimensions.
 * It tests product interactions only; it is not a real-room reconstruction evaluation.
 */
const {chromium}=require('playwright');
const fs=require('fs');

async function main(){
  const [base,photo1,photo2,output]=process.argv.slice(2);
  if(!base||!photo1||!photo2||!output||fs.existsSync(output))throw Error('usage: BASE PHOTO1 PHOTO2 NEW_REPORT_JSON');
  const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(base+'/',{waitUntil:'networkidle'});
  await page.fill('#project-name','模拟标注多墙浏览器测试 - 非真实语义');await page.selectOption('#operator-kind','automation');await page.click('#create');
  await page.waitForFunction(()=>document.querySelector('#project-status').textContent.includes('项目：'));
  await page.locator('#photo-upload').setInputFiles([photo1,photo2]);
  await page.waitForFunction(()=>document.querySelector('#photo-select').options.length===2);
  for(let i=1;i<=3;i++){
    await page.fill('#wall-id','wall-'+i);const box=await page.locator('#photo-canvas').boundingBox();
    await page.locator('#photo-canvas').click({position:{x:box.width*(.15+i*.05),y:box.height*.55}});
    await page.locator('#photo-canvas').click({position:{x:box.width*(.30+i*.05),y:box.height*.60}});
    await page.click('#save-annotation');await page.waitForFunction(n=>document.querySelectorAll('#annotation-list .ann-row').length===n,i);
  }
  await page.selectOption('#annotation-kind','window');await page.fill('#wall-id','wall-1');await page.fill('#opening-id','window-1');
  for(const [id,value] of Object.entries({'opening-offset':'1','opening-width':'1','opening-height':'1.2','opening-sill':'1'}))await page.fill('#'+id,value);
  const box=await page.locator('#photo-canvas').boundingBox();
  await page.locator('#photo-canvas').click({position:{x:box.width*.35,y:box.height*.35}});
  await page.locator('#photo-canvas').click({position:{x:box.width*.55,y:box.height*.50}});
  await page.click('#save-annotation');await page.waitForFunction(()=>document.querySelectorAll('#annotation-list .ann-row').length===4);
  const canvas=page.locator('#plan-canvas'),rect=await canvas.boundingBox();
  for(const [x,y] of [[.15,.25],[.70,.25],[.70,.70],[.20,.70]])await canvas.click({position:{x:rect.width*x,y:rect.height*y}});
  await page.check('#confirm-sketch');await page.fill('#anchor-length','4');await page.selectOption('#anchor-basis','assumed');
  await page.fill('#anchor-description','自动化测试的模拟尺度');await page.fill('#wall-height','2.8');
  await page.selectOption('#height-basis','assumed');await page.fill('#wall-thickness','.12');await page.check('#confirm-candidate');await page.click('#generate');
  await page.waitForFunction(()=>document.querySelector('#summary')?.textContent.includes('版本 1'),null,{timeout:30000});
  const original=await(await page.request.get(base+'/api/model')).json();
  if(original.elements.some(x=>x.classification.status!=='simulated'))throw Error('automated annotations must not be marked human confirmed');
  await page.fill('#command','将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效');await page.click('#send');
  await page.waitForFunction(()=>document.querySelector('#summary')?.textContent.includes('版本 2'),null,{timeout:30000});
  const changed=await(await page.request.get(base+'/api/model')).json(),ifc=await page.request.get(base+'/api/export/model.ifc');
  const result={test_type:'SCRIPTED_BROWSER_WITH_SYNTHETIC_ANNOTATIONS_AND_ASSUMED_DIMENSIONS',real_photo_inputs:true,
    does_not_prove_real_semantic_or_geometric_accuracy:true,walls:original.elements.filter(x=>x.ifc_type==='IfcWall').length,
    windows:original.elements.filter(x=>x.ifc_type==='IfcWindow').length,
    openings:original.elements.filter(x=>x.ifc_type==='IfcOpeningElement').length,open_room:original.validation.scope,
    ifc_status:ifc.status(),revision:changed.revision,affected:changed.history.at(-1).affected_elements,errors};
  if(errors.length||result.walls!==3||result.windows!==1||ifc.status()!==200)throw Error(JSON.stringify(result));
  fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  console.log('Synthetic-annotation multiwall browser flow passed.');await browser.close();
}
main().catch(error=>{console.error(error);process.exit(1)});
