// Real Agent, registered ETH3D photos and a controlled perturbation, in an automation copy.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
 const [url,out]=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)||!out||fs.existsSync(out))throw Error('use a local test server and new output');
 fs.mkdirSync(out,{recursive:true});const b=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']}),p=await b.newPage({viewport:{width:1600,height:1000}}),errors=[],dialogs=[];
 p.on('pageerror',e=>errors.push(String(e)));p.on('dialog',async d=>{dialogs.push(d.message());await d.accept()});
 try{
  await p.goto(url,{waitUntil:'networkidle'});const project=await p.evaluate(async()=>await(await fetch('/api/project')).json());
  if(project.project?.operator_kind!=='automation'||!project.project.name.includes('controlled height perturbation'))throw Error('not the controlled automation project');
  const initial=await p.evaluate(async()=>await(await fetch('/api/model/projections')).json());
  fs.writeFileSync(path.join(out,'before.ifc'),Buffer.from(await p.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())))));
  await p.selectOption('#assistant-mode','agent');await p.selectOption('#agent-evidence-mode','photos');
  await p.selectOption('#view-a','9');await p.selectOption('#view-b','19');
  await p.fill('#command','这是受控扰动实验，并非现场变化。请查看已配准原照片与模型顶边投影，调用确定性多视图拟合工具预览高度修复，报告前后残差与尺度假设。');
  await p.click('#send');let status;const deadline=Date.now()+300000;
  do{await p.waitForTimeout(1500);status=await p.evaluate(async()=>await(await fetch('/api/agent/status')).json())}while(status.job?.status==='RUNNING'&&Date.now()<deadline);
  if(!['COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'].includes(status.job?.status))throw Error('Agent failed: '+JSON.stringify(status.job));
  const proposal=(status.job.revision_proposals||[]).find(x=>x.projection_evidence&&x.projection_evidence.after_max_line_px<=3);
  if(!proposal)throw Error('Agent did not produce a bounded photo-fit proposal');
  await p.selectOption('#agent-revisions',proposal.id);await p.locator('#agent-apply-revision').waitFor({state:'visible'});
  await p.screenshot({path:path.join(out,'preview.png'),fullPage:true});await p.click('#agent-apply-revision');
  await p.waitForFunction(rev=>document.querySelector('#status-version')?.textContent.includes('版本 '+rev),initial.revision+1,{timeout:30000});
  const after=await p.evaluate(async()=>await(await fetch('/api/model/projections')).json());
  const updatedModel=await p.evaluate(async()=>await(await fetch('/api/model')).json());
  const savedEvidence=updatedModel.evidence[updatedModel.evidence.length-1]?.projection_evidence;
  if(!savedEvidence||savedEvidence.views.length!==2||savedEvidence.after_max_line_px>3)throw Error('photo-fit evidence was not persisted in the new IR');
  fs.writeFileSync(path.join(out,'after.ifc'),Buffer.from(await p.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())))));
  if(after.revision!==initial.revision+1||errors.length||dialogs.length<2)throw Error('unexpected revision or browser errors');
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',operator:'automation',experiment:'CONTROLLED_PERTURBATION_NOT_SITE_CHANGE',
   before_revision:initial.revision,after_revision:after.revision,proposal,savedEvidence,dialogs,errors,
   caveats:['The line observations were used to fit; residual is not independent accuracy.','No human labor measured.','Scale and wall identity are unverified.']},null,2)+'\n');
  console.log(JSON.stringify({status:'PASS',before:initial.revision,after:after.revision,fit:proposal.projection_evidence}));
 }finally{await b.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
