// Synthetic demo UI verification. Automated clicks are not human work.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
async function main(){const [base,out]=process.argv.slice(2);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(base)||!out||fs.existsSync(out))throw Error('use an isolated local server and new output');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--enable-unsafe-swiftshader']});const errors=[];
try{const page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));await page.goto(base,{waitUntil:'domcontentloaded'});
await page.waitForFunction(()=>document.querySelector('#canvas-a').dataset.imageId&&document.querySelector('#viewer canvas')&&document.querySelectorAll('#view-a option').length>=6,null,{timeout:60000});
const before=await page.evaluate(async()=>({p:await(await fetch('/api/project')).json(),m:await(await fetch('/api/model')).json(),state:await(await fetch('/api/modeler/state')).json()}));
if(before.p.project?.operator_kind!=='automation'||before.m.revision!==1||before.state.uploads.length!==6)throw Error('wrong isolated synthetic project');
await page.screenshot({path:path.join(out,'before-1440.png')});await page.setViewportSize({width:1920,height:1080});await page.screenshot({path:path.join(out,'before-1920.png')});
await page.locator('[data-element-id="wall-2"]').click();await page.selectOption('#attribute','height');await page.fill('#value','2.994');await page.fill('#reason','自动化合成演示，不是现场测量');await page.click('#save');
await page.waitForFunction(async()=>(await(await fetch('/api/model')).json()).revision===2,null,{timeout:30000});
let after=await page.evaluate(async()=>({model:await(await fetch('/api/model')).json(),ifc:Array.from(new Uint8Array(await(await fetch('/api/export/model.ifc')).arrayBuffer()))}));
if(after.model.elements.find(x=>x.id==='wall-2').parameters.height.value!==2.994)throw Error('synthetic wall edit failed');fs.writeFileSync(path.join(out,'edited.ifc'),Buffer.from(after.ifc));
await page.screenshot({path:path.join(out,'edited.png')});await page.waitForFunction(()=>Array.from(document.querySelector('#versions').options).some(x=>x.value==='1'),null,{timeout:30000});
await page.locator('#editor details summary').click();await page.selectOption('#versions','1');await page.click('#restore');await page.waitForFunction(async()=>(await(await fetch('/api/model')).json()).revision===3,null,{timeout:30000});
const restored=await page.evaluate(async()=>await(await fetch('/api/model')).json());if(restored.elements.find(x=>x.id==='wall-2').parameters.height.value!==2.894||errors.length)throw Error('version restore or browser error '+JSON.stringify(errors));
const report={status:'PASS',operator:'automation',scenario:'SYNTHETIC_NOT_RECONSTRUCTED',images:6,revision_before:1,revision_edited:2,revision_restored:3,edited_height:2.994,restored_height:2.894,errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}finally{await browser.close()}}
main().catch(e=>{console.error(e);process.exitCode=1});
