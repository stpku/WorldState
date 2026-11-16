// Fault injection against an isolated automation project; never a human trial.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
 const [base,out]=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(base||'')||!out||fs.existsSync(out))throw Error('expected isolated local URL and new output');
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),failures=[],warnings=[];let stateReads=0,writes=0;
 page.on('requestfailed',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))failures.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText})});
 page.on('console',m=>{if(m.type()==='warning')warnings.push(m.text())});
 try{
  const project=await page.request.get(base+'api/project');const data=await project.json();if(data.project?.operator_kind!=='automation')throw Error('refusing to modify a human trial workspace');
  await page.route('**/api/modeler/state',async route=>{stateReads++;if(stateReads<=2)await route.fulfill({status:503,contentType:'application/json',body:'{"error":"injected transient failure"}'});else await route.continue()});
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#viewer canvas'),null,{timeout:60000});
  if(stateReads!==3||warnings.filter(x=>x.includes('status read failed')).length!==2)throw Error('state retry did not preserve two transient failures');
  await page.unroute('**/api/modeler/state');const before=await page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
  await page.route('**/api/modeler/object',async route=>{writes++;const response=await route.fetch();if(response.status()!==201)throw Error('injected write did not commit');await response.body();await route.abort('failed')});
  await page.locator('#new-wall').click();await page.locator('#object-id').fill('retry-ambiguity-check');await page.locator('#create-object').click();
  await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('写入状态不明'),null,{timeout:30000});await page.unroute('**/api/modeler/object');
  const after=await page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
  if(writes!==1||after.state.revision!==before.state.revision+1||after.state.objects.filter(o=>o.id==='retry-ambiguity-check').length!==1)throw Error('ambiguous write was repeated or not committed');
  await page.reload();await page.waitForFunction(()=>[...document.querySelectorAll('#tree .object-row')].some(x=>x.dataset.elementId==='retry-ambiguity-check'),null,{timeout:30000});
  const result={status:'PASS',state_read_attempts:stateReads,injected_503:2,ambiguous_write_requests:writes,committed_once:true,recovery:'manual reload',failures,warnings};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 }finally{fs.writeFileSync(path.join(out,'request-failures.json'),JSON.stringify({failures,warnings},null,2)+'\n');await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
