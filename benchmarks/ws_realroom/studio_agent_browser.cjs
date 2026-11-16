// Real model call via Studio on an isolated automation project, not a human trial.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
 const [base,out,mode='model']=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(base||'')||!out||fs.existsSync(out)||!['model','edit'].includes(mode))throw Error('expected isolated local URL, new output, and model/edit mode');
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];let confirmation='';
 page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))errors.push(new URL(r.url()).pathname+': '+r.failure()?.errorText)});
 try{
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&!document.querySelector('#assistant-mode option[value="agent"]').disabled,null,{timeout:60000});
  const project=await page.evaluate(async()=>await(await fetch('/api/project')).json());if(project.project?.operator_kind!=='automation')throw Error('refusing to modify a human workspace');
  const before=await page.evaluate(async()=>await(await fetch('/api/model')).json());
  if(mode==='edit'){const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())));fs.writeFileSync(path.join(out,'before.ifc'),Buffer.from(bytes))}
  await page.locator('#view-a').selectOption('3');await page.locator('#view-b').selectOption('13');
  await page.locator('#assistant-mode').selectOption('agent');await page.locator('#command').fill(mode==='edit'?'将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效，并提出修改建议。':'根据这些照片，尝试建立这个房间的可编辑模型。');
  page.once('dialog',async dialog=>{confirmation=dialog.message();await dialog.accept()});await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#activity').textContent.includes('AI 正在'),null,{timeout:30000});
  await page.waitForFunction(()=>{const s=document.querySelector('#activity').textContent;return s.includes('没有可靠')||s.includes('Agent 已完成')||s.includes('运行失败')||s.includes('未获授权')},null,{timeout:360000});
  const status=await page.evaluate(async()=>await(await fetch('/api/agent/status')).json());
  if(!confirmation.includes('DSC_6490.JPG')||!confirmation.includes('DSC_6502.JPG')||!confirmation.includes('发送'))throw Error('photo transfer confirmation missing');
  if(!status.job||JSON.stringify(status.job.image_ids)!=='[3,13]'||status.job.status==='FAILED'||status.job.status==='APPROVAL_BLOCKED'||status.job.status==='TIMEOUT')throw Error('agent did not complete: '+JSON.stringify(status.job));
  const tools=status.job.events.filter(x=>x.status==='ok').map(x=>x.tool);if(!tools.includes('inspect_scene')||!tools.includes('view_photo'))throw Error('actual model tool calls absent');
  if(status.job.hypotheses?.length){await page.locator('#agent-hypotheses').selectOption(status.job.hypotheses[0].id);await page.waitForTimeout(500)}
  let revision=null;if(mode==='edit'){
   if(!tools.includes('inspect_element')||!tools.includes('preview_revision')||!status.job.revision_proposals?.length)throw Error('real edit proposal missing');
   const chosen=status.job.revision_proposals.find(r=>Math.abs((r.diff?.after-r.diff?.before)-.2)<1e-7);if(!chosen)throw Error('no proposal actually increases length by 0.2 m');
   if(!(await page.locator('#agent-apply-revision').isHidden()))throw Error('revision must require an explicit choice');await page.locator('#agent-revisions').selectOption(chosen.id);
   page.once('dialog',d=>d.accept());await page.locator('#agent-apply-revision').click();await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('AI 修改建议已应用'),null,{timeout:30000});
   const after=await page.evaluate(async()=>await(await fetch('/api/model')).json());if(after.revision!==before.revision+1)throw Error('revision missing');
   const wall=m=>{const e=m.elements.find(x=>x.ifc_type==='IfcWall'),a=m.nodes.find(n=>n.id===e.start),b=m.nodes.find(n=>n.id===e.end);return Math.hypot(b.x-a.x,b.y-a.y)};
   if(Math.abs(wall(after)-wall(before)-.2)>1e-7)throw Error('wall length did not increase by 0.2 m');
   const bytes=await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())));fs.writeFileSync(path.join(out,'after.ifc'),Buffer.from(bytes));revision={before:before.revision,after:after.revision,length_change_m:wall(after)-wall(before)};
  }
  if(errors.length)throw Error('browser failures: '+JSON.stringify(errors));
  await page.screenshot({path:path.join(out,'agent-studio.png')});
  const result={status:'PASS_REAL_AGENT_UI',operator:'automation',image_ids:status.job.image_ids,transfer_confirmation:true,
                agent_status:status.job.status,successful_tools:tools,candidate_count:status.job.candidates.length,hypothesis_count:status.job.hypotheses?.length||0,revision,
                model_report:status.job.result,errors,warning:'No human confirmation, independent precision, or labor measurement.'};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 }finally{fs.writeFileSync(path.join(out,'request-failures.json'),JSON.stringify(errors,null,2)+'\n');await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
