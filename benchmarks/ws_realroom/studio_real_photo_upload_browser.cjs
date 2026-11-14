/* Upload a real photo to a new local Studio workspace. Not a human labor study.
 * BASE PHOTO NEW_OUTPUT_DIR
 */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{chromium}=require('playwright');
const [base,photo,out]=process.argv.slice(2);if(!out||fs.existsSync(out))throw Error('BASE PHOTO NEW_OUTPUT_DIR required');
(async()=>{
 const raw=fs.readFileSync(photo),sha=crypto.createHash('sha256').update(raw).digest('hex');
 const b=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 try{
  const page=await b.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/builder');await page.fill('#project-name','Automated real photo upload');await page.selectOption('#operator-kind','automation');await page.click('#create');
  await page.waitForFunction(()=>project?.operator_kind==='automation');await page.setInputFiles('#photo-upload',photo);
  await page.waitForFunction(()=>uploads.length===1&&photoImage!==null,null,{timeout:120000});
  const result=await page.evaluate(()=>({operator:project.operator_kind,upload:uploads[0],canvas:[$('photo-canvas').width,$('photo-canvas').height]}));
  if(result.upload.sha256!==sha||result.canvas[0]>1600||errors.length)throw Error('source hash or preview failed: '+JSON.stringify(errors));
  result.bytes=raw.length;result.scope='real photo upload and preview only; automation, not modeling or human labor';
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
  await page.screenshot({path:path.join(out,'upload.png')});console.log(JSON.stringify(result,null,2));
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});
