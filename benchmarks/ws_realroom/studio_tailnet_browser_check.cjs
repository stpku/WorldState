// Non-mutating HTTPS smoke check. Windows user agent; browser runs on the server.
const {chromium}=require('playwright');
const crypto=require('crypto');const fs=require('fs');const path=require('path');
async function main(){
  const [url,output]=process.argv.slice(2),target=new URL(url);
  if(target.protocol!=='https:'||target.username||target.password||target.pathname!=='/'||target.search||target.hash||!output||fs.existsSync(output))
    throw Error('expected an HTTPS origin and a new output directory');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--no-proxy-server']});
  const context=await browser.newContext({viewport:{width:1500,height:1000},userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  try{
    const response=await page.goto(target.origin+'/modeler',{waitUntil:'domcontentloaded',timeout:60000});
    if(response.status()!==200)throw Error('modeler HTTP '+response.status());
    await page.waitForFunction(()=>document.querySelector('#view-a').options.length>=2&&document.querySelector('#view-b').options.length>=2,null,{timeout:60000});
    await page.waitForFunction(()=>['canvas-a','canvas-b'].every(id=>document.getElementById(id).toDataURL('image/jpeg').length>12000),null,{timeout:60000});
    const result=await page.evaluate(async()=>{
      const before=await(await fetch('/api/modeler/state')).json();
      const projectBefore=await(await fetch('/api/project')).json();
      const camera=before.state.cameras.find(c=>String(c.image_id)===document.querySelector('#view-a').value);
      const photo=before.uploads.find(u=>u.sha256===camera.sha256);
      const preview=await fetch('/api/photo-preview/'+encodeURIComponent(photo.id));
      const previewBytes=(await preview.arrayBuffer()).byteLength;
      const solved=await fetch('/api/modeler/preview-solve',{method:'POST',headers:{'Content-Type':'application/json','X-WorldState-Token':token},body:JSON.stringify({state_revision:before.state.revision})});
      const solution=await solved.json();
      const after=await(await fetch('/api/modeler/state')).json();
      const projectAfter=await(await fetch('/api/project')).json();
      const ifc=await fetch('/api/export/model.ifc');const ifcData=Array.from(new Uint8Array(await ifc.arrayBuffer()));
      return {photos:before.uploads.length,cameras:before.state.cameras.length,has_model:before.has_model,
        photo_status:preview.status,photo_type:preview.headers.get('content-type'),photo_bytes:previewBytes,
        solve_status:solved.status,solution_status:solution.solution?.status,objects:solution.solution?.objects?.length,
        solve_persisted:solution.persisted,solve_rms_px:solution.solution?.optimization?.point_rms_px,
        state_revision_before:before.state.revision,state_revision_after:after.state.revision,
        events_before:projectBefore.project.events.length,events_after:projectAfter.project.events.length,
        ifc_status:ifc.status,ifcData};
    });
    if(result.photo_status!==200||!result.photo_type.startsWith('image/')||result.photo_bytes<1000||result.solve_status!==200||
       result.solve_persisted!==false||result.objects<1||result.state_revision_before!==result.state_revision_after||
       result.events_before!==result.events_after||result.ifc_status!==200||errors.length)throw Error('unexpected result '+JSON.stringify({...result,ifcData:undefined,errors}));
    const bytes=Buffer.from(result.ifcData);delete result.ifcData;
    if(!bytes.subarray(0,12).toString().startsWith('ISO-10303-21'))throw Error('IFC header mismatch');
    fs.writeFileSync(path.join(output,'download.ifc'),bytes);result.ifc_bytes=bytes.length;result.ifc_sha256=crypto.createHash('sha256').update(bytes).digest('hex');
    await page.locator('.views').screenshot({path:path.join(output,'views.png')});
    result.status='PASS_SERVER_SIDE_WINDOWS_UA';result.browser_os='Linux; Windows user agent only';result.tls='verified by Chromium';result.errors=errors;
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
