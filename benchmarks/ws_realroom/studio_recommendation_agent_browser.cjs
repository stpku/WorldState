// Real multi-photo Agent run on an isolated ETH3D automation copy; not human review.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
async function main(){
 const [url,out,mode]=process.argv.slice(2),verifyExisting=mode==='verify-existing';if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)||!out||fs.existsSync(out))throw Error('use local server and new output');fs.mkdirSync(out,{recursive:true});
 const b=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']}),p=await b.newPage({viewport:{width:1600,height:1000}}),errors=[],dialogs=[];
 p.on('pageerror',e=>errors.push(String(e)));p.on('dialog',async d=>{dialogs.push(d.message());if(verifyExisting)await d.dismiss();else await d.accept()});
 try{
  await p.goto(url,{waitUntil:'networkidle'});const project=await p.evaluate(async()=>await(await fetch('/api/project')).json());
  if(project.project?.operator_kind!=='automation')throw Error('not an automation project');
  await p.selectOption('#assistant-mode','agent');await p.locator('[data-element-id="generic-wall-patch"]').click();
  await p.click('#recommend-views');await p.locator('#agent-photo-choices').waitFor({state:'visible',timeout:30000});
  const options=await p.locator('#agent-photo-choices option').evaluateAll(xs=>xs.map(x=>({id:Number(x.value),selected:x.selected,text:x.textContent})));
  const requested=[9,19,26];if(!requested.every(id=>options.some(x=>x.id===id)))throw Error('expected three visible source candidates');
  await p.selectOption('#agent-photo-choices',requested.map(String));await p.screenshot({path:path.join(out,'recommendation.png'),fullPage:true});
  const previous=await p.evaluate(async()=>await(await fetch('/api/agent/status')).json());
  await p.fill('#command','查看授权的三张照片，排除家具和遮挡，寻找可以跨图确认的其他建筑墙面；若不可靠请说明，不要强行生成。');await p.click('#send');
  let status;const deadline=Date.now()+300000;do{await p.waitForTimeout(1500);status=await p.evaluate(async()=>await(await fetch('/api/agent/status')).json())}while(status.job?.status==='RUNNING'&&Date.now()<deadline);
  if(!['COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'].includes(status.job?.status))throw Error('Agent failed '+JSON.stringify(status.job));
  if(verifyExisting&&(!(status.job.observations||[]).length||status.job.observations.some(x=>x.stale||x.confirmation!=='proposed')))throw Error('expected original unconfirmed AI observations');
  if(verifyExisting)await p.waitForFunction(()=>document.querySelector('#agent-observations').textContent.includes('未自动加入构件'),null,{timeout:10000});
  if(JSON.stringify([...status.job.image_ids].sort((a,b)=>a-b))!==JSON.stringify([...requested].sort((a,b)=>a-b))||!dialogs[0]?.includes('DSC_6497')||errors.length||(verifyExisting&&status.job.id!==previous.job?.id))throw Error('photo consent, scope, or browser error');
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',operator:'automation',requested,options,dialogs,job:status.job,errors,verify_existing_job:verifyExisting,
    caveats:['No real human confirmation or productivity data.','Photo and semantic hypotheses remain unverified.']},null,2)+'\n');
  console.log(JSON.stringify({status:'PASS',authorized:requested,job_status:status.job.status,candidates:status.job.candidates,events:status.job.events.length}));
 }finally{await b.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
