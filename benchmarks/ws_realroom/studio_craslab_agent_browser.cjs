// Real model-only Agent run in an isolated automation project; never human acceptance.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
  const [url,out]=process.argv.slice(2);
  const selected=process.env.WS_ELEMENT||'wall-a29ee94ac6f2dc67',target=process.env.WS_PROPOSAL_ELEMENT||selected;
  const attribute=process.env.WS_ATTRIBUTE||'height',delta=Number(process.env.WS_DELTA||.1);
  const command=process.env.WS_COMMAND||'将选中墙体的高度增加10厘米，检查宿主窗开口及相邻构件，先预览，不要直接修改。';
  if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)||!out||fs.existsSync(out))throw Error('use a local server and a new output directory');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],dialogs=[];
  page.on('pageerror',e=>errors.push(String(e)));page.on('dialog',async d=>{dialogs.push(d.message());await d.accept()});
  try{
    await page.goto(url,{waitUntil:'networkidle'});
    const project=await page.evaluate(async()=>await(await fetch('/api/project')).json());
    if(project.project?.operator_kind!=='automation'||project.project.id!=='craslab-room-development')throw Error('not the isolated CRASLAB automation project');
    const before=await page.evaluate(async()=>await(await fetch('/api/model')).json());
    fs.writeFileSync(path.join(out,'before.ifc'),Buffer.from(await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())))));
    await page.selectOption('#assistant-mode','agent');await page.selectOption('#agent-evidence-mode','model');
    await page.locator('[data-element-id="'+selected+'"]').click();
    await page.fill('#command',command);
    await page.click('#send');
    let status;
    const deadline=Date.now()+300000;
    do {await page.waitForTimeout(1500);status=await page.evaluate(async()=>await(await fetch('/api/agent/status')).json())} while(status.job?.status==='RUNNING'&&Date.now()<deadline);
    if(!['COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'].includes(status.job?.status))throw Error('Agent failed: '+JSON.stringify(status.job));
    const proposal=(status.job.revision_proposals||[]).find(x=>x.attribute===attribute&&x.element_id===target&&Math.abs(x.diff.after-x.diff.before-delta)<1e-8);
    if(!proposal)throw Error('no matching requested proposal: '+JSON.stringify(status.job.revision_proposals));
    await page.selectOption('#agent-revisions',proposal.id);
    await page.locator('#agent-apply-revision').waitFor({state:'visible'});
    await page.screenshot({path:path.join(out,'preview.png'),fullPage:true});
    await page.click('#agent-apply-revision');
    await page.waitForFunction(rev=>document.querySelector('#status-version')?.textContent.includes('版本 '+rev),before.revision+1,{timeout:30000});
    const after=await page.evaluate(async()=>await(await fetch('/api/model')).json());
    fs.writeFileSync(path.join(out,'after.ifc'),Buffer.from(await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer())))));
    if(after.revision!==before.revision+1||errors.length||dialogs.length<2||!dialogs[0].includes('不发送照片'))throw Error('unexpected revision, consent, or browser error');
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',operator:'automation',source:'CRASLAB scan-derived unverified model',
      before_revision:before.revision,after_revision:after.revision,proposal,dialogs,errors,
      caveats:['No real human confirmation or efficiency measurement.','No registered site photos.']},null,2)+'\n');
    console.log(JSON.stringify({status:'PASS',before:before.revision,after:after.revision,proposal:proposal.id,dialogs:dialogs.length}));
  } finally {await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
