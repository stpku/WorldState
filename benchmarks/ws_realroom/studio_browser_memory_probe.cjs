// Read-only controlled browser load. Measurements are diagnostics, not proof of a crash cause.
const {chromium}=require('playwright');const fs=require('fs'),cp=require('child_process');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function snapshot(serverPid,modelPid){
 const mem=Object.fromEntries(fs.readFileSync('/proc/meminfo','utf8').split('\n').map(x=>x.match(/^(MemAvailable|SwapFree):\s+(\d+)/)).filter(Boolean).map(x=>[x[1],Number(x[2])]));
 const rows=cp.execFileSync('ps',['-eo','pid=,ppid=,rss=,comm='],{encoding:'utf8'}).trim().split('\n').map(line=>{const m=line.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(\S+)/);return m?{pid:+m[1],ppid:+m[2],rss_kib:+m[3],comm:m[4]}:null}).filter(Boolean);
 const pids=new Set([process.pid]);let changed=true;while(changed){changed=false;for(const r of rows)if(pids.has(r.ppid)&&!pids.has(r.pid)){pids.add(r.pid);changed=true}}
 const children=rows.filter(r=>pids.has(r.pid)&&/chrom(e|ium)/i.test(r.comm));const server=rows.find(r=>r.pid===serverPid),model=rows.find(r=>r.pid===modelPid);
 const tmp=process.env.TMPDIR||'/tmp',stat=fs.statfsSync(tmp),tmpFree=Number(stat.bavail)*Number(stat.bsize)/1024/1024;
 let cgroup=null;try{const rel=fs.readFileSync('/proc/self/cgroup','utf8').trim().split('::')[1],base='/sys/fs/cgroup'+rel;cgroup={memory_current_mib:Number(fs.readFileSync(base+'/memory.current','utf8'))/1024/1024,events:fs.readFileSync(base+'/memory.events','utf8').trim()}}catch(_){}
 return {at:new Date().toISOString(),mem_available_mib:mem.MemAvailable/1024,swap_free_mib:mem.SwapFree/1024,tmp_free_mib:tmpFree,cgroup,
  browser_processes:children.length,browser_rss_sum_mib:children.reduce((n,r)=>n+r.rss_kib,0)/1024,
  server_rss_mib:server?server.rss_kib/1024:null,model_client_rss_mib:model?model.rss_kib/1024:null,warning:'Summed process RSS double-counts shared pages; remote model server is not measured.'};
}
async function main(){
 const [url,out,countText,serverText,modelText]=process.argv.slice(2),count=Number(countText),serverPid=Number(serverText),modelPid=Number(modelText);
 if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)||!out||fs.existsSync(out)||![1,2].includes(count))throw Error('local URL, new output and 1 or 2 browsers required');
 fs.mkdirSync(out,{recursive:true});const errors=[],failures=[],crashes=[],samples=[],decoded=[],browsers=[];let timer;
 try{
  samples.push(snapshot(serverPid,modelPid));timer=setInterval(()=>samples.push(snapshot(serverPid,modelPid)),500);
  for(let i=0;i<count;i++){
   const browser=await chromium.launch({headless:true,executablePath:process.env.WS_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});browsers.push(browser);
  }
  await Promise.all(browsers.map(async(browser,index)=>{
   const p=await browser.newPage({viewport:{width:1440,height:900}});p.on('pageerror',e=>errors.push({index,error:String(e)}));p.on('crash',()=>crashes.push(index));p.on('requestfailed',r=>failures.push({index,url:new URL(r.url()).pathname,error:r.failure()?.errorText}));
   await p.goto(url,{waitUntil:'networkidle'});const project=await p.evaluate(async()=>await(await fetch('/api/project')).json());
   if(project.project?.operator_kind!=='automation')throw Error('not an isolated automation project');
   const ids=project.uploads.slice(0,6).map(u=>u.id);
   const result=await p.evaluate(async ids=>{const output=[];for(const id of ids){const t=performance.now(),response=await fetch('/api/photo-preview/'+id);if(!response.ok)throw Error('image request '+response.status);const bitmap=await createImageBitmap(await response.blob());output.push({id,width:bitmap.width,height:bitmap.height,elapsed_ms:performance.now()-t});bitmap.close()}return output},ids);
   decoded.push({index,images:result});await sleep(1000);await p.screenshot({path:out+'/browser-'+index+'.png'});await p.close();
  }));
 }catch(e){errors.push({error:String(e)})}finally{
  if(timer)clearInterval(timer);samples.push(snapshot(serverPid,modelPid));for(const browser of browsers)await browser.close().catch(e=>errors.push({error:String(e)}));
  const result={status:errors.length||crashes.length||failures.length?'FAILED':'PASS',browsers:count,decoded,errors,failures,crashes,samples,
   model_process:modelPid?'LOCAL_CLIENT_ONLY_REMOTE_SERVER_NOT_MEASURED':'NOT_REQUESTED',note:'Controlled light load only. System and server resource contention may differ from the earlier crash.'};
  fs.writeFileSync(out+'/report.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({status:result.status,browsers:count,decoded:decoded.length,errors:errors.length,failures:failures.length,crashes:crashes.length}));
  if(result.status!=='PASS')process.exitCode=1;
 }
}
main().catch(e=>{console.error(e);process.exitCode=1});
