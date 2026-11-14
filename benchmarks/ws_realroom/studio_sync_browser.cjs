/* Synchronize one already-created external IFC through the Studio UI.
 * Intended for explicit local test workspaces, not automatic authoring approval.
 */
const {chromium}=require('playwright');
const fs=require('fs');
async function main(){
  const [base,ifcPath,elementId,attribute,revisionText,output]=process.argv.slice(2);
  const revision=Number(revisionText);
  if(!base||!ifcPath||!elementId||!attribute||!Number.isInteger(revision)||!output||fs.existsSync(output))
    throw Error('usage: BASE EXTERNAL_IFC ELEMENT_ID ATTRIBUTE CURRENT_REVISION NEW_REPORT_JSON');
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']}),page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(base+'/',{waitUntil:'networkidle'});
  await page.waitForFunction(n=>document.querySelector('#summary')?.textContent.includes('版本 '+n),revision);
  const buttons=await page.locator('#tree button').all();let found=false;
  for(const button of buttons){if((await button.textContent()).endsWith(elementId)){await button.click();found=true;break}}
  if(!found)throw Error('element not found');
  await page.selectOption('#attribute',attribute);await page.fill('#reason','自动化 Bonsai 编辑验证，不是现场测量');
  await page.locator('details summary').click();await page.locator('#external-ifc').setInputFiles(ifcPath);await page.click('#sync-ifc');
  await page.waitForFunction(n=>document.querySelector('#summary')?.textContent.includes('版本 '+(n+1)),revision,{timeout:30000});
  const model=await(await page.request.get(base+'/api/model')).json();
  const result={type:'SCRIPTED_EXTERNAL_IFC_READBACK',revision:model.revision,diff:model.history.at(-1),errors};
  if(errors.length)throw Error(errors.join('; '));
  fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log('External IFC synchronized through Studio.');await browser.close();
}
main().catch(error=>{console.error(error);process.exit(1)});
