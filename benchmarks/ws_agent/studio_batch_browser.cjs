// Isolated synthetic automation only. Replays genuine pre-existing Agent proposals.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
async function main(){
 const [url,out]=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)||!out||fs.existsSync(out))throw Error('use local Studio and new output');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],dialogs=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('dialog',async d=>{dialogs.push(d.message());await d.accept()});
 try{
  await page.goto(url,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>!document.querySelector('#assistant-mode option[value="agent"]').disabled,null,{timeout:30000});
  const before=await page.evaluate(async()=>({project:await(await fetch('/api/project')).json(),model:await(await fetch('/api/model')).json(),agent:await(await fetch('/api/agent/status')).json()}));
  if(before.project.project?.operator_kind!=='automation'||before.model.revision!==1||before.agent.job?.revision_proposals?.length!==2)throw Error('expected isolated synthetic project and two genuine proposals');
  await page.selectOption('#assistant-mode','agent');await page.selectOption('#agent-evidence-mode','model');
  const ids=await page.locator('#agent-revisions option').evaluateAll(xs=>xs.map(x=>x.value));await page.selectOption('#agent-revisions',ids);
  await page.locator('#agent-apply-batch').waitFor({state:'visible'});await page.screenshot({path:path.join(out,'before.png')});await page.click('#agent-apply-batch');
  await page.waitForFunction(async()=>{const r=await fetch('/api/model');return (await r.json()).revision===3},null,{timeout:60000});
  const after=await page.evaluate(async()=>({model:await(await fetch('/api/model')).json(),project:await(await fetch('/api/project')).json(),ifc:Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer()))}));
  const wall=after.model.elements.find(x=>x.id==='wall-2'),opening=after.model.elements.find(x=>x.id==='opening-door');
  if(wall.parameters.height.value!==2.9||opening.parameters.offset.value!==1.2||dialogs.length!==1||!dialogs[0].includes('wall-2')||!dialogs[0].includes('opening-door')||errors.length)throw Error('incorrect batch result '+JSON.stringify({dialogs,errors}));
  fs.writeFileSync(path.join(out,'after.ifc'),Buffer.from(after.ifc));delete after.ifc;await page.screenshot({path:path.join(out,'after.png')});
  const report={status:'PASS',operator:'automation',source:'real WS-Agent A20 proposal artifacts',human_confirmation:false,dialogs,revision_before:before.model.revision,revision_after:after.model.revision,
    wall_height:wall.parameters.height.value,door_offset:opening.parameters.offset.value,project_event:after.project.project.events.at(-1),errors};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
