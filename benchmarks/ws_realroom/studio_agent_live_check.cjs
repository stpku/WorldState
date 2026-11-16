// HTTPS read-only check: does not start an Agent or alter a user workspace.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
 const [url,out]=process.argv.slice(2),target=new URL(url);
 if(target.protocol!=='https:'||target.pathname!=='/'||target.search||target.hash||target.username||target.password||!out||fs.existsSync(out))throw Error('expected HTTPS origin and new output directory');
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--no-proxy-server','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900},userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))errors.push(new URL(r.url()).pathname+': '+r.failure()?.errorText)});
 try{
  const response=await page.goto(target.origin+'/',{waitUntil:'domcontentloaded'});if(response.status()!==200)throw Error('home HTTP '+response.status());
  await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#viewer canvas')&&!document.querySelector('#assistant-mode option[value="agent"]').disabled,null,{timeout:60000});
  const before=await page.evaluate(async()=>({state:await(await fetch('/api/modeler/state')).json(),project:await(await fetch('/api/project')).json(),agent:await(await fetch('/api/agent/status')).json()}));
  await page.locator('#assistant-mode').selectOption('agent');if(!(await page.locator('#assistant-provider').textContent()).includes(before.agent.provider))throw Error('agent mode not displayed');
  const after=await page.evaluate(async()=>({state:await(await fetch('/api/modeler/state')).json(),project:await(await fetch('/api/project')).json()}));
  if(!before.agent.enabled||!before.agent.image_transfer_requires_confirmation||before.state.state.revision!==after.state.state.revision||before.project.project.events.length!==after.project.project.events.length||errors.length)throw Error('read-only check failed '+JSON.stringify({errors}));
  await page.screenshot({path:path.join(out,'agent-enabled.png')});
  const report={status:'PASS_READ_ONLY_WINDOWS_UA',browser_os:'Linux; Windows user agent only',tls:'verified by Chromium',agent_enabled:true,provider:before.agent.provider,confirmation_required:true,photos:before.state.uploads.length,state_revision:before.state.state.revision,events:before.project.project.events.length,errors};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }finally{fs.writeFileSync(path.join(out,'request-failures.json'),JSON.stringify(errors,null,2)+'\n');await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
