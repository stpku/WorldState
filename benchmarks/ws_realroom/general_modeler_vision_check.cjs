// Exercise an actually configured local vision provider in Studio. The click is
// automation; acceptance remains unverified and is not a human annotation.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
async function main(){
  const [url,output]=process.argv.slice(2);
  if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url||'')||!output||fs.existsSync(output))throw Error('expected local URL and new output');
  fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  try{
    await page.goto(url+'modeler',{waitUntil:'networkidle'});
    if(!await page.locator('#object option').count())throw Error('load a modeler workspace with an object and a registered photo');
    await page.locator('#mark-mode').selectOption('line');await page.locator('#feature').selectOption('p1');await page.locator('#line-end').selectOption('p2');
    await page.locator('#ai-analyze').click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('视觉分析完成'),null,{timeout:180000});
    const first=page.locator('#vision-candidates div').filter({hasText:'wall_'}).first();
    if(!await first.count())throw Error('vision model produced no selectable line; preserve as failure');
    const candidate=await first.textContent();await first.getByRole('button',{name:'接受'}).click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('视觉候选处理已记录'),null,{timeout:30000});
    let current=await page.evaluate(async()=>await(await fetch('/api/modeler/state')).json());
    let recorded=current.state.observations.find(o=>o.origin==='ai_suggested'&&o.accepted_by==='automation');
    if(!recorded)throw Error('AI observation provenance missing');if(errors.length)throw Error(errors.join('; '));
    await page.locator('#vision-overlay').screenshot({path:path.join(output,'vision-overlay.png')});
    let result={status:'PASS',operator:'automation',candidate,recorded,errors,
      limitations:['Semantic and line proposals are not verified wall instances or dimensions.','Acceptance was scripted, not a human review.']};
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({status:result.status,candidate,kind:recorded.kind},null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
