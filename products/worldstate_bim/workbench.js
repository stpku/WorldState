import {WorkbenchViewer} from './workbench_viewer.js';

const $=id=>document.getElementById(id);
const token=document.querySelector('meta[name="worldstate-token"]').content;
const labels={IfcWall:'墙面',IfcSlab:'楼板',IfcOpeningElement:'开口',IfcWindow:'窗',IfcDoor:'门',IfcSpace:'房间'};
const semanticLabels={wall:'墙面',floor:'地面',ceiling:'天花板',door:'门',window:'窗',furniture:'家具',unknown:'未知'};
const statuses={observed:'观测',inferred:'推断',human_confirmed:'人工确认',assumed:'假设',simulated:'模拟',unknown:'未知',conflict:'冲突'};
let state=null,uploads=[],project=null,model=null,mesh={objects:[],failures:[]},versions=[],selected=null,marking=false;
let pendingLine=null,pendingZoom=null,zoomSerial=0,viewSerial={a:0,b:0},mutationTail=Promise.resolve(),pendingMutations=0;
let viewer=null,viewerMode='ifc',viewerSignature='';
let agentInfo=null,agentTimer=null,agentPollFailures=0;
let recommendedObject=null;
const imageCache=new Map();
let thumbnailObserver=null,thumbnailGeneration=0,thumbnailActive=0,thumbnailQueue=[];

function element(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node}
function message(text,error=false){$('message').textContent=text;$('message').style.color=error?'#a45145':''}
function activity(text,error=false){$('activity').textContent=text;$('activity').style.color=error?'#a45145':''}
async function api(path,body){
  let response;const retryState=body===undefined&&path==='/api/modeler/state';
  for(let attempt=0;attempt<(retryState?3:1);attempt++){
    try{response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-WorldState-Token':token},body:JSON.stringify(body)})}
    catch(error){console.warn('[WorldState] request failed',path,'attempt',attempt+1,error.message);if(retryState&&attempt<2){await new Promise(resolve=>setTimeout(resolve,250*(attempt+1)));continue}throw new Error(body===undefined?'状态读取失败，请检查连接后重试。':'连接中断，本次写入状态不明，请刷新并核验；系统不会自动重发。')}
    if(retryState&&[502,503,504].includes(response.status)&&attempt<2){console.warn('[WorldState] status read failed',response.status,'attempt',attempt+1);await new Promise(resolve=>setTimeout(resolve,250*(attempt+1)));continue}
    break;
  }
  const data=response.headers.get('content-type')?.includes('application/json')?await response.json():await response.text();
  if(!response.ok){const error=new Error(typeof data==='object'?(data.error||'操作失败'):('请求失败（'+response.status+'）'));error.status=response.status;throw error}
  return data;
}
function queue(label,operation){
  pendingMutations++;$('solve').disabled=true;
  const run=mutationTail.then(async()=>{message(label);return operation()});
  mutationTail=run.catch(()=>{});
  return run.catch(async error=>{message(error.message,true);if(error.status===409){try{await loadState()}catch(_){}}throw error})
    .finally(()=>{pendingMutations--;$('solve').disabled=pendingMutations>0});
}
function silently(promise){promise.catch(()=>{})}
function activeObject(){return state?.objects?.find(o=>o.id===selected)||null}
function activeElement(){return model?.elements?.find(e=>e.id===selected)||null}
function camFor(side){return state?.cameras?.find(c=>String(c.image_id)===$('view-'+side).value)||null}
function uploadFor(cam){return uploads.find(u=>u.sha256===cam?.sha256)||null}
function switchLeft(name){document.querySelectorAll('[data-left-tab]').forEach(x=>x.classList.toggle('active',x.dataset.leftTab===name));$('objects-tab').hidden=name!=='objects';$('evidence-tab').hidden=name!=='evidence';if(name==='evidence')renderPhotos()}
function switchRight(name){document.querySelectorAll('[data-right-tab]').forEach(x=>x.classList.toggle('active',x.dataset.rightTab===name));$('properties-tab').hidden=name!=='properties';$('observations-tab').hidden=name!=='observations'}
function setMarking(value){marking=!!value;$('mark-toggle').classList.toggle('active',marking);$('mark-toggle').setAttribute('aria-pressed',String(marking));for(const side of ['a','b'])$('frame-'+side).classList.toggle('inactive',!marking);if(marking)switchRight('observations');else cancelZoom();$('observation-help').textContent=marking?'选择特征编号，再在照片中点击':'选择构件后可标注同一物理角点'}
function cancelZoom(){zoomSerial++;pendingZoom=null;$('zoom-panel').hidden=true}
function updateViewerLabels(){
  const candidate=viewerMode==='candidate';$('model-label').textContent=candidate?'多视图候选 · 源坐标':'已保存 IFC · 实际几何';
  $('viewer-source').textContent=candidate?'候选线框 · 未验证尺度':'IFC 实际几何';
  $('mesh-status').textContent=candidate?'候选几何 · '+(state?.solution?.objects?.length||0)+' 个构件':(mesh?.failures?.length?mesh.failures.length+' 项几何未显示':(mesh?.objects?.length?'IFC 几何 · '+mesh.objects.length+' 个构件':'尚无 IFC 几何'));
  $('model-draft').textContent=candidate?'候选未验证 · 尚未提交 IFC':(state?.model_dirty?'观察已修改 · 显示上次保存版本':'尺寸与尺度需核验');
}
function setViewerMode(mode){if(!viewer)return;if(!viewer.setMode(mode)){message('当前没有已求解的候选模型。',true);return}viewerMode=mode;$('mode-ifc').classList.toggle('active',mode==='ifc');$('mode-candidate').classList.toggle('active',mode==='candidate');updateViewerLabels();viewer.select(selected);renderDimensions()}
function getImage(id){
  if(imageCache.has(id)){const p=imageCache.get(id);imageCache.delete(id);imageCache.set(id,p);return p}
  const promise=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>{imageCache.delete(id);reject(new Error('照片预览加载失败，请检查照片是否可用。'))};image.src='/api/photo-preview/'+encodeURIComponent(id)});
  imageCache.set(id,promise);while(imageCache.size>6)imageCache.delete(imageCache.keys().next().value);return promise;
}
function renderTree(){
  const root=$('tree');root.replaceChildren();const all=new Map((model?.elements||[]).map(e=>[e.id,{id:e.id,type:e.ifc_type,saved:true}]));
  for(const o of state?.objects||[])if(!all.has(o.id))all.set(o.id,{id:o.id,type:o.ifc_type,saved:false});
  $('object-count').textContent=String(all.size);$('tree-empty').hidden=all.size>0;
  for(const item of all.values()){
    const b=element('button',undefined,'object-row'+(item.id===selected?' selected':'')+(!item.saved?' draft':''));b.type='button';b.dataset.elementId=item.id;
    b.append(element('span',undefined,'object-dot'),element('b',(labels[item.type]||item.type)+' · '+item.id),element('small',item.saved?'IFC':'候选'));b.onclick=()=>select(item.id);root.append(b);
  }
}
function refreshPhotoRelations(){const related=new Set((state?.observations||[]).filter(o=>o.object_id===selected).map(o=>o.photo_sha256));for(const row of $('photos').children)row.lastChild.textContent=row.dataset.title+(related.has(row.dataset.sha)?' · 已关联':'')}
function pumpThumbnails(){
  while(thumbnailActive<2&&thumbnailQueue.length){const item=thumbnailQueue.shift();if(item.generation!==thumbnailGeneration||!item.image.isConnected)continue;thumbnailActive++;const done=()=>{item.image.onload=item.image.onerror=null;thumbnailActive--;pumpThumbnails()};item.image.onload=done;item.image.onerror=done;item.image.src='/api/photo-thumbnail/'+encodeURIComponent(item.id)}
}
function renderPhotos(){
  const root=$('photos'),signature=uploads.map(u=>u.id).join('|')+';'+(state?.cameras||[]).map(c=>c.sha256+':'+c.image_id).join('|');
  if(root.dataset.signature===signature){refreshPhotoRelations();return}root.dataset.signature=signature;root.replaceChildren();thumbnailObserver?.disconnect();thumbnailQueue=[];const generation=++thumbnailGeneration;
  const enqueue=image=>{thumbnailQueue.push({image,id:image.dataset.id,generation});pumpThumbnails()};
  thumbnailObserver='IntersectionObserver' in window?new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){thumbnailObserver.unobserve(entry.target);enqueue(entry.target)}},{root:document.querySelector('.left-scroll'),rootMargin:'80px'}):null;
  for(const u of uploads){const cam=state?.cameras?.find(c=>c.sha256===u.sha256);const b=element('button',undefined,'photo-item');b.type='button';b.dataset.sha=u.sha256;b.dataset.title=cam?.photo||u.original_filename||u.id;const image=element('img');image.dataset.id=u.id;image.alt='照片预览';b.append(image,element('span',b.dataset.title));b.onclick=()=>{if(!cam){message('此照片尚未关联相机。',true);return}$('view-a').value=String(cam.image_id);cancelZoom();drawPhoto('a')};root.append(b);if(thumbnailObserver)thumbnailObserver.observe(image);else enqueue(image)}refreshPhotoRelations();
}
function renderProperties(){
  const root=$('detail'),editor=$('editor'),e=activeElement(),obj=activeObject();root.replaceChildren();
  if(!e&&!obj){editor.hidden=true;root.className='empty-state';root.textContent='选择一个构件，查看参数与证据。';return}
  root.className='';const title=element('div',e?.id||obj.id,'element-title');title.append(element('span',e?'已保存':'候选','type-pill'));root.append(title,element('div',(labels[e?.ifc_type||obj.ifc_type]||'构件')+' · '+(e?.ifc_type||obj.ifc_type),'element-subtitle'));
  if(!e){editor.hidden=true;root.append(element('p','此候选尚未生成 IFC；请先完成多视图标注并求解。','subtle'));return}
  let target=e;if(['IfcDoor','IfcWindow'].includes(e.ifc_type))target=model.elements.find(x=>x.id===e.opening)||e;
  const attributes=[];
  if(target.ifc_type==='IfcWall'){
    const a=model.nodes.find(n=>n.id===target.start),b=model.nodes.find(n=>n.id===target.end);
    if(a&&b&&[a.x,a.y,b.x,b.y].every(Number.isFinite)){attributes.push(['length','长度',Math.hypot(b.x-a.x,b.y-a.y),'inferred']);attributes.push(['position_x','起点 X',a.x,a.status],['position_y','起点 Y',a.y,a.status])}
  }
  const names={height:'高度',thickness:'厚度',base_elevation:'底部标高',offset:'位置',width:'宽度',sill:'底高',panel_thickness:'板厚',elevation:'标高'};
  for(const [key,value] of Object.entries(target.parameters||{}))attributes.push([key,names[key]||key,value.value,value.status]);
  const grid=element('div',undefined,'property-grid');for(const [,name,value,status] of attributes){const card=element('div',undefined,'property-card');card.append(element('small',name),element('b',value===null?'未知':Number(value).toFixed(3)+' m'),element('em',statuses[status]||status||'待确认'));grid.append(card)}root.append(grid);
  const refs=new Set(e.classification?.evidence_refs||[]);for(const v of Object.values(target.parameters||{}))for(const r of v.evidence_refs||[])refs.add(r);
  const related=new Set((state?.observations||[]).filter(o=>o.object_id===e.id).map(o=>o.photo_sha256));
  root.append(element('div',`证据关联：${related.size} 张照片 · ${refs.size} 项来源`,'element-subtitle'));
  if(refs.size){const details=element('details',undefined,'advanced');details.append(element('summary','查看证据来源'));const names={multiview_modeler_observations:'多视图照片观察',declared_source_up:'源坐标方向声明',scale_assumption:'尺度假设',multiview_metric_anchor:'多视图尺度参照',thickness_assumption:'墙厚假设',explicit_geometry_approximation:'几何近似'};for(const ref of refs){const evidence=model.evidence?.find(x=>x.id===ref);details.append(element('p',(names[evidence?.kind]||evidence?.kind||'来源')+' · '+ref,'subtle'))}root.append(details)}
  if(e.unknown?.length){const details=element('details',undefined,'unknown-note');details.append(element('summary',`${e.unknown.length} 项属性或边界待确认`));const list=element('ul');for(const item of e.unknown)list.append(element('li',item));details.append(list);root.append(details)}
  const option=$('attribute');const old=option.value;option.replaceChildren();for(const [key,name,value] of attributes){if(value===null||!Number.isFinite(Number(value)))continue;const item=new Option(name,key);item.dataset.value=String(value);option.add(item)}
  if([...option.options].some(o=>o.value===old))option.value=old;editor.hidden=option.options.length===0;editor.dataset.target=target.id;
  if(!editor.hidden)$('value').value=Number(option.selectedOptions[0].dataset.value).toFixed(3);
}
function renderDimensions(){const root=$('dimension-overlay');root.replaceChildren();const e=activeElement();if(viewerMode!=='ifc'||!e||e.ifc_type!=='IfcWall'){root.hidden=true;return}const a=model.nodes.find(n=>n.id===e.start),b=model.nodes.find(n=>n.id===e.end);if(a&&b&&[a.x,a.y,b.x,b.y].every(Number.isFinite))root.append(element('span','长 ≈ '+Math.hypot(b.x-a.x,b.y-a.y).toFixed(2)+' m'));if(Number.isFinite(e.parameters?.height?.value))root.append(element('span','高 ≈ '+e.parameters.height.value.toFixed(2)+' m'));root.hidden=!root.children.length}
function renderFeatures(){
  const obj=activeObject(),feature=$('feature'),end=$('line-end'),old=feature.value,previousEnd=end.value;feature.replaceChildren();end.replaceChildren();
  if(obj){const vertices=obj.vertices||[],items=obj.construction?.kind==='edge_to_line'&&$('mark-mode').value==='point'?[...vertices.slice(0,2),obj.construction.direction_feature]:vertices;for(const v of items)feature.add(new Option(v,v));for(const v of vertices)end.add(new Option(v,v));if(items.includes(old))feature.value=old;if(vertices.includes(previousEnd))end.value=previousEnd;else if(end.options.length>1)end.selectedIndex=1}
  $('line-end-label').hidden=$('mark-mode').value!=='line';
}
function renderObjectSelect(){const select=$('object');select.replaceChildren();for(const o of state?.objects||[])select.add(new Option(o.id,o.id));if(state?.objects?.some(o=>o.id===selected))select.value=selected;else select.selectedIndex=-1;renderFeatures()}
function select(id){if(selected!==id){recommendedObject=null;$('agent-photo-choices').hidden=true}selected=id;pendingLine=null;cancelZoom();renderTree();renderProperties();renderObjectSelect();viewer?.select(id);renderDimensions();drawPhoto('a');drawPhoto('b');if(!$('evidence-tab').hidden)refreshPhotoRelations()}
function populateViews(){
  const observed=[...new Set((state?.observations||[]).filter(o=>o.object_id===selected).map(o=>String(o.image_id)))];
  for(const side of ['a','b']){const el=$('view-'+side),old=el.value;el.replaceChildren();for(const cam of state?.cameras||[])el.add(new Option(cam.photo,String(cam.image_id)));if([...el.options].some(o=>o.value===old))el.value=old;else{const pick=observed[side==='a'?0:1];if([...el.options].some(o=>o.value===pick))el.value=pick;else if(side==='b'&&el.options.length>1)el.selectedIndex=1}$('frame-'+side).querySelector('.photo-empty').hidden=!!el.options.length}
}
async function drawPhoto(side){
  const serial=++viewSerial[side],cam=camFor(side),canvas=$('canvas-'+side),ctx=canvas.getContext('2d');
  if(!cam||canvas.dataset.imageId!==String(cam.image_id)){canvas.dataset.imageId='';ctx.clearRect(0,0,canvas.width,canvas.height)}if(!cam)return;
  const upload=uploadFor(cam);if(!upload){message('原始照片未上传。',true);return}
  let image;try{image=await getImage(upload.id)}catch(e){if(serial===viewSerial[side])message(e.message,true);return}
  if(serial!==viewSerial[side]||cam.image_id!==camFor(side)?.image_id)return;
  canvas.width=1000;canvas.height=Math.round(1000*cam.height_px/cam.width_px);ctx.drawImage(image,0,0,canvas.width,canvas.height);canvas.dataset.imageId=String(cam.image_id);
  const sx=canvas.width/cam.width_px,sy=canvas.height/cam.height_px;ctx.font='bold 16px sans-serif';
  const observations=(state?.observations||[]).filter(o=>o.object_id===selected&&o.image_id===cam.image_id);
  for(const o of observations.filter(o=>o.kind==='point')){ctx.beginPath();ctx.arc(o.pixel_xy[0]*sx,o.pixel_xy[1]*sy,5,0,2*Math.PI);ctx.fillStyle='#ed7767';ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='#fff';ctx.stroke();ctx.fillStyle='#fff';ctx.fillText(o.feature_id,o.pixel_xy[0]*sx+8,o.pixel_xy[1]*sy-8)}
  for(const o of observations.filter(o=>o.kind==='line')){ctx.beginPath();ctx.moveTo(o.points_px[0][0]*sx,o.points_px[0][1]*sy);ctx.lineTo(o.points_px[1][0]*sx,o.points_px[1][1]*sy);ctx.strokeStyle='#ffc160';ctx.lineWidth=3;ctx.stroke()}
  const obj=state?.solution?.objects?.find(o=>o.id===selected),p=obj?.projections?.find(x=>x.image_id===cam.image_id);
  if(p){ctx.beginPath();p.polygon_px.forEach((q,i)=>i?ctx.lineTo(q[0]*sx,q[1]*sy):ctx.moveTo(q[0]*sx,q[1]*sy));ctx.closePath();ctx.strokeStyle='#64e4ce';ctx.lineWidth=3;ctx.stroke()}
  if($('assistant-mode').value==='agent'&&$('agent-hypotheses').value){const h=agentInfo?.job?.hypotheses?.find(x=>x.id===$('agent-hypotheses').value),v=h?.views?.find(x=>x.image_id===cam.image_id&&x.photo_sha256===cam.sha256);if(v){const [x0,y0,x1,y1]=v.bbox_original_px;ctx.save();ctx.setLineDash([10,7]);ctx.strokeStyle='#ffd35c';ctx.lineWidth=3;ctx.strokeRect(x0*sx,y0*sy,(x1-x0)*sx,(y1-y0)*sy);ctx.fillStyle='#ffd35c';ctx.fillText('AI 未确认',x0*sx+4,Math.max(18,y0*sy-5));ctx.restore()}}
  if($('assistant-mode').value==='agent'){for(const o of agentInfo?.job?.observations||[]){if(o.stale||o.image_id!==cam.image_id||o.photo_sha256!==cam.sha256||($('agent-hypotheses').value&&o.hypothesis_id!==$('agent-hypotheses').value))continue;const pts=o.points_original_px||[];ctx.save();ctx.strokeStyle='#ffd35c';ctx.fillStyle='#ffd35c';ctx.lineWidth=3;ctx.beginPath();pts.forEach(([x,y],i)=>i?ctx.lineTo(x*sx,y*sy):ctx.moveTo(x*sx,y*sy));if(pts.length>1)ctx.stroke();for(const [x,y] of pts){ctx.beginPath();ctx.arc(x*sx,y*sy,5,0,2*Math.PI);ctx.fill()}if(pts.length)ctx.fillText('AI '+(o.feature_ids||[]).join('/')+' 未确认',pts[0][0]*sx+8,pts[0][1]*sy-8);ctx.restore()}}
  $('photo-'+side+'-status').textContent=observations.length?observations.length+' 项观察':'已注册';
}
function renderSuggestions(){const root=$('suggestions');root.replaceChildren();for(const item of state?.suggestions||[]){const row=element('div',`照片 ${item.target_image_id} · 轨迹 ${item.track_id} · 偏差 ${item.source_distance_px.toFixed(1)} px · ${item.status}`,'candidate-row');if(item.status==='proposed')for(const [label,decision] of [['接受','accept'],['拒绝','reject']]){const b=element('button',label);b.onclick=()=>silently(queue('正在记录对应建议…',async()=>{const result=await api('/api/modeler/decision',{state_revision:state.revision,suggestion_id:item.id,decision});state=result.state;renderState();message(decision==='accept'?'已接受建议，仍需核验物理对应。':'已拒绝建议。')}));row.append(b)}root.append(row)}}
function renderState({fit=false}={}){
  const ids=new Set([...(model?.elements||[]).map(e=>e.id),...(state?.objects||[]).map(o=>o.id)]);if(!ids.has(selected))selected=ids.values().next().value||null;
  $('project-name-display').textContent=project||'未命名项目';$('tree-project').textContent=project||'当前项目';$('photo-count').textContent=String(uploads.length);
  $('project-status').textContent=(state?.model_dirty?'观察已修改 · 需重新求解':(state?'相机与照片已载入':'等待导入照片'));
  $('status-version').textContent=model?'版本 '+model.revision:'尚无模型';$('status-scale').textContent='尺度与几何待核验';
  $('mode-candidate').disabled=!state?.solution?.objects?.length;
  renderTree();renderProperties();renderObjectSelect();populateViews();renderSuggestions();
  const signature=JSON.stringify([model?.revision,mesh?.objects?.length,state?.solution?.input_sha256,viewerMode]);
  if(viewer&&signature!==viewerSignature){viewerSignature=signature;viewer.setData(model,mesh,state?.solution);if(viewerMode==='candidate'&&!state?.solution?.objects?.length){viewerMode='ifc';viewer.setMode('ifc');$('mode-ifc').classList.add('active');$('mode-candidate').classList.remove('active')}viewer.select(selected)}else if(fit)viewer?.setView('iso');
  updateViewerLabels();renderDimensions();drawPhoto('a');drawPhoto('b');if(!$('evidence-tab').hidden)renderPhotos();
}
async function loadState(){const data=await api('/api/modeler/state');state=data.state;uploads=data.uploads;project=data.project;renderState()}
async function loadAll(){
  const [data,m,v,vs]=await Promise.all([api('/api/modeler/state'),api('/api/model'),api('/api/mesh'),api('/api/versions')]);state=data.state;uploads=data.uploads;project=data.project;model=m;mesh=v;versions=vs.revisions||[];
  const select=$('versions'),old=select.value;select.replaceChildren();for(const n of versions)select.add(new Option('版本 '+n,String(n)));if(versions.some(n=>String(n)===old))select.value=old;
  viewerSignature='';renderState();message('工作区已就绪 · 观察与假设需复核');
}
async function submitPixel(snapshot,pixel){
  if(snapshot.mode==='line'){
    if(!pendingLine){pendingLine={snapshot,pixel};message('请选择同一照片中的线段终点。');return}
    const previous=pendingLine;pendingLine=null;if(previous.snapshot.imageId!==snapshot.imageId||previous.snapshot.objectId!==snapshot.objectId||previous.snapshot.feature!==snapshot.feature||previous.snapshot.end!==snapshot.end)throw new Error('线段两点须属于同一照片和边界。');
    return queue('正在保存边界…',async()=>{const result=await api('/api/modeler/line',{state_revision:state.revision,object_id:snapshot.objectId,image_id:snapshot.imageId,sigma_px:snapshot.sigma,visibility:snapshot.visibility,feature_ids:[snapshot.feature,snapshot.end],points_px:[previous.pixel,pixel]});state=result.state;renderState();message('边界已记录；请在其他照片中标注对应边界。')});
  }
  return queue('正在保存观察…',async()=>{const result=await api('/api/modeler/point',{state_revision:state.revision,object_id:snapshot.objectId,image_id:snapshot.imageId,sigma_px:snapshot.sigma,visibility:snapshot.visibility,feature_id:snapshot.feature,pixel_xy:pixel});state=result.state;renderState();message('观察已记录；请在其他照片中标注相同编号。')});
}
async function beginPoint(side,event){
  if(!marking){message('点击“标注角点”后可在照片上标注。');return}const cam=camFor(side),obj=activeObject();if(!cam||!obj){message('请先选择已注册照片和候选构件。',true);return}
  if(event.currentTarget.dataset.imageId!==String(cam.image_id)){message('照片正在加载，请稍后标注。');return}
  const rect=event.currentTarget.getBoundingClientRect(),pixel=[(event.clientX-rect.left)*cam.width_px/rect.width,(event.clientY-rect.top)*cam.height_px/rect.height];
  if(pixel.some(v=>!Number.isFinite(v))||pixel[0]<0||pixel[1]<0||pixel[0]>=cam.width_px||pixel[1]>=cam.height_px)return;
  const snapshot={side,imageId:cam.image_id,objectId:obj.id,feature:$('feature').value,end:$('line-end').value,mode:$('mark-mode').value,sigma:Number($('sigma').value),visibility:$('visibility').value};
  if(!$('fine-mode').checked){await submitPixel(snapshot,pixel);return}
  const serial=++zoomSerial,cx=Math.max(0,Math.min(cam.width_px-1,Math.floor(pixel[0]))),cy=Math.max(0,Math.min(cam.height_px-1,Math.floor(pixel[1]))),size=200;
  const x=Math.max(0,Math.min(cam.width_px-size,cx-size/2)),y=Math.max(0,Math.min(cam.height_px-size,cy-size/2)),w=Math.min(size,cam.width_px-x),h=Math.min(size,cam.height_px-y),upload=uploadFor(cam);
  if(!upload)throw new Error('照片不可用。');message('正在载入原图局部…');
  const image=new Image();image.src='/api/photo-crop/'+encodeURIComponent(upload.id)+'?x='+cx+'&y='+cy;
  try{await image.decode()}catch(error){throw new Error('照片局部加载失败，请检查原图后重试。')}
  if(serial!==zoomSerial||snapshot.objectId!==selected||snapshot.imageId!==camFor(side)?.image_id)return;
  const canvas=$('zoom');canvas.height=Math.round(canvas.width*h/w);Object.assign(canvas.dataset,{cropX:String(x),cropY:String(y),cropWidth:String(w),cropHeight:String(h)});const ctx=canvas.getContext('2d');ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0,canvas.width,canvas.height);
  pendingZoom={...snapshot,x,y,w,h};$('zoom-panel').hidden=false;message('请在局部放大图中再次点击。');
}
function selectedScale(){
  if($('scale-kind').value==='assumed')return {basis:'assumed',metres_per_source_unit:Number($('scale').value)};
  const ids=[$('anchor-a').value,$('anchor-b').value],endpoints=ids.map(id=>({id,observations:(state?.observations||[]).filter(o=>o.kind==='point'&&o.object_id===selected&&o.feature_id===id&&o.visibility==='visible'&&!['proposed','rejected'].includes(o.confirmation)).map(o=>({image_id:o.image_id,photo_sha256:o.photo_sha256,pixel_xy:o.pixel_xy}))}));
  return {schema:'worldstate-multiview-scale-anchor/0.1',object_id:selected,confirmed:true,basis:$('anchor-basis').value,distance_m:Number($('scale').value),measurement_uncertainty_m:Number($('anchor-sigma').value),description:$('anchor-source').value,endpoints};
}

try{viewer=new WorkbenchViewer($('viewer'),id=>select(id));viewer.renderer.domElement.id='scene'}catch(error){$('viewer-fallback').hidden=false;message('三维视图不可用；照片标注仍可使用。',true)}
for(const b of document.querySelectorAll('[data-left-tab]'))b.onclick=()=>switchLeft(b.dataset.leftTab);
for(const b of document.querySelectorAll('[data-right-tab]'))b.onclick=()=>switchRight(b.dataset.rightTab);
$('new-wall').onclick=()=>{if(!state){switchLeft('evidence');message('请先导入照片与已注册相机。',true);return}let n=1;while(state.objects.some(o=>o.id==='wall-'+n))n++;$('object-id').value='wall-'+n;$('create-dialog').showModal()};
$('create-object').onclick=()=>{const candidate={id:$('object-id').value.trim(),vertices:Number($('vertex-count').value),construction:$('construction').value};silently(queue('正在创建候选…',async()=>{const result=await api('/api/modeler/object',{state_revision:state.revision,...candidate});state=result.state;selected=candidate.id;$('create-dialog').close();renderState();setMarking(true);message('已创建候选；请选择特征编号并标注照片。')}))};
$('mark-toggle').onclick=()=>{if(!activeObject()){message('请先选择一个可标注的候选。',true);return}setMarking(!marking)};
$('object').onchange=()=>select($('object').value);$('mark-mode').onchange=()=>{pendingLine=null;cancelZoom();renderFeatures()};$('feature').onchange=()=>{pendingLine=null;cancelZoom()};$('line-end').onchange=()=>{pendingLine=null;cancelZoom()};
for(const side of ['a','b']){$('view-'+side).onchange=()=>{pendingLine=null;cancelZoom();drawPhoto(side)};$('canvas-'+side).onclick=e=>beginPoint(side,e).catch(err=>message(err.message||'照片局部加载失败，请重试。',true))}
$('zoom-close').onclick=()=>{cancelZoom();message('已取消本次标注。')};
$('zoom').onclick=e=>{if(!pendingZoom)return;const z=pendingZoom,rect=e.currentTarget.getBoundingClientRect(),pixel=[z.x+(e.clientX-rect.left)*z.w/rect.width,z.y+(e.clientY-rect.top)*z.h/rect.height];cancelZoom();submitPixel(z,pixel).catch(err=>message(err.message,true))};
$('suggest').onclick=()=>{const request={object_id:selected,feature_id:$('feature').value,image_id:Number($('view-a').value)};silently(queue('正在查找对应建议…',async()=>{const result=await api('/api/modeler/suggest',{state_revision:state.revision,...request});state=result.state;renderState();message('对应建议未经验证，请逐项检查。')}))};
$('discard-object').onclick=()=>{const id=selected;if(!id||!confirm('放弃尚未保存的候选及其当前观察？观察仍会保留在修订记录中。'))return;silently(queue('正在放弃候选…',async()=>{const result=await api('/api/modeler/discard-unsaved-object',{state_revision:state.revision,object_id:id});state=result.state;selected=null;renderState();message('候选已放弃；请重新求解并保存其余构件。')}))};
$('solve').onclick=()=>silently(queue('正在求解多视图约束…',async()=>{const settings={samples:12,camera_position_sigma_source:.002,camera_rotation_sigma_deg:.05,focal_sigma_fraction:.001},result=await api('/api/modeler/solve',{state_revision:state.revision,sensitivity:settings});state=result.state;renderState();setViewerMode('candidate');message('候选已求解；像素残差不代表实测精度。')}));
$('open-delivery').onclick=()=>{if(!state?.solution){message('请先求解当前观察。',true);return}$('delivery-message').textContent='';$('delivery-dialog').showModal()};
$('scale-kind').onchange=()=>{$('anchor-fields').hidden=$('scale-kind').value!=='measured'};
$('commit').onclick=()=>{const settings={scale:selectedScale(),thickness_m:Number($('thickness').value),up_source:['up-x','up-y','up-z'].map(x=>Number($(x).value)),confirm_up_assumed:$('confirm-up').checked,allow_rectangular_approximation:$('confirm-rectangle').checked};silently(queue('正在生成 IFC 版本…',async()=>{try{const result=await api('/api/modeler/commit',{state_revision:state.revision,...settings});state=result.state;$('delivery-dialog').close();viewerMode='ifc';await loadAll();setViewerMode('ifc');message('已生成 IFC 版本，仍需独立核验。')}catch(error){$('delivery-message').textContent=error.message;throw error}}))};
$('mode-ifc').onclick=()=>setViewerMode('ifc');$('mode-candidate').onclick=()=>setViewerMode('candidate');for(const view of ['iso','top','front'])$('view-'+view).onclick=()=>{viewer?.setView(view);for(const item of ['iso','top','front'])$('view-'+item).classList.toggle('active',item===view)};$('zoom-in').onclick=()=>viewer?.zoomBy(.8);$('zoom-out').onclick=()=>viewer?.zoomBy(1.25);$('reset-view').onclick=()=>{viewer?.setView('iso');for(const item of ['iso','top','front'])$('view-'+item).classList.toggle('active',item==='iso')};
$('attribute').onchange=()=>{const option=$('attribute').selectedOptions[0];if(option)$('value').value=Number(option.dataset.value).toFixed(3)};
$('save').onclick=()=>{const edit={element_id:$('editor').dataset.target,attribute:$('attribute').value,value:Number($('value').value),reason:$('reason').value.trim()};silently(queue('正在保存参数修改…',async()=>{if(!Number.isFinite(edit.value)||!edit.reason)throw new Error('请输入有效数值和修改依据。');const result=await api('/api/revise',{revision:model.revision,...edit});activity(`已保存版本 ${result.model.revision}，需要重新验证。`);await loadAll();message('参数修改已保存。')}))};
function showAgent(info){
  agentInfo=info;$('assistant-mode').querySelector('[value="agent"]').disabled=!info.enabled;
  const agent=$('assistant-mode').value==='agent',job=info.job;$('agent-output').hidden=!agent||!job;
  $('agent-evidence-mode').hidden=!agent;
  $('recommend-views').hidden=!agent||$('agent-evidence-mode').value!=='photos';
  if(!agent||$('agent-evidence-mode').value!=='photos')$('agent-photo-choices').hidden=true;
  else if(recommendedObject===selected)$('agent-photo-choices').hidden=false;
  $('assistant-provider').textContent=agent?('Codex · '+(info.provider||'未配置')):'本地规则模式 · DSH 未连接';
  $('assistant-hint').textContent=agent?($('agent-evidence-mode').value==='model'?'仅发送模型数据，不发送照片。':'使用当前左右照片；发送前需确认模型数据使用。'):'可输入受支持的构件修改指令。';
  if(!agent)return;if(!job){activity('输入目标并确认所选照片的传输授权。');return}
  const events=(job.events||[]).map(e=>`${e.tool} · ${e.status}${e.error?' · '+e.error:''}`).join('\n');
  const selectedProposal=(job.revision_proposals||[]).find(x=>x.id===$('agent-revisions').value);
  const geometry=selectedProposal?.affected_geometry?.map(g=>{const pos=d=>{const r=d.reference_geometry;if(r)return `${r.kind}: [${r.start.map(x=>Number(x).toFixed(3)).join(', ')}] → [${r.end.map(x=>Number(x).toFixed(3)).join(', ')}]${r.height_m!==undefined?'，高 '+Number(r.height_m).toFixed(3):''}`;return (d.nodes||[]).map(n=>`${n.id}: (${Number(n.x).toFixed(3)}, ${Number(n.y).toFixed(3)})`).join('；')||'无可用参考几何'};return `${g.id}\n  修改前 ${pos(g.before)}\n  修改后 ${pos(g.after)}`}).join('\n');
  $('agent-trace').textContent=[job.result?'结果：\n'+job.result:'',geometry?'受影响构件坐标（米）：\n'+geometry:'',events?'工具记录：\n'+events:'',job.error].filter(Boolean).join('\n\n');
  const hypotheses=$('agent-hypotheses'),chosen=hypotheses.value;hypotheses.replaceChildren(new Option('照片中不显示 AI 建议',''));for(const h of job.hypotheses||[])hypotheses.add(new Option((semanticLabels[h.label]||h.label)+' · '+h.description.slice(0,28),h.id));if([...hypotheses.options].some(o=>o.value===chosen))hypotheses.value=chosen;hypotheses.hidden=hypotheses.options.length<2;
  const points=(job.observations||[]).filter(x=>!x.stale);$('agent-observations').textContent=points.length?`${points.length} 项 AI 点线建议显示在照片上；尚未确认，也未自动加入构件。`:(job.observations||[]).length?'AI 点线建议已过期，请重新分析。':'';
  const finished=['COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'].includes(job.status);
  const list=$('agent-candidates'),old=list.value;list.replaceChildren(new Option('请选择待核验候选',''));for(const id of job.candidates||[]){const stale=state?.revision!==job.source_revision,option=new Option(id+(stale?' · 已过期':' · 未核验'),id);option.disabled=stale;list.add(option)}if([...list.options].some(o=>o.value===old&&!o.disabled))list.value=old;
  list.hidden=list.options.length<2;$('agent-import').hidden=!list.value||!finished;
  const revisions=$('agent-revisions'),previous=revisions.value;revisions.replaceChildren(new Option('请选择修改建议',''));for(const r of job.revision_proposals||[]){const before=Number(r.diff?.before),after=Number(r.diff?.after),delta=after-before,stale=r.source_model_revision!==model?.revision||state?.model_dirty;const option=new Option(`${r.projection_evidence?'多视图拟合 · ':'参数预览 · '}${r.element_id} · ${r.attribute}: ${before.toFixed(3)} → ${after.toFixed(3)} m (${delta>=0?'+':''}${delta.toFixed(3)})${stale?' · 已过期':''}`,r.id);option.disabled=stale;revisions.add(option)}if([...revisions.options].some(o=>o.value===previous&&!o.disabled))revisions.value=previous;revisions.hidden=revisions.options.length<2;$('agent-apply-revision').hidden=!revisions.value||!finished;
  activity(job.status==='RUNNING'?'AI 正在分析照片和调用工具…':job.status==='COMPLETED_NO_SOLVED_CANDIDATE'?'本次没有可靠的已求解候选，请查看原因。':job.status==='APPROVAL_BLOCKED'?'模型工具调用未获授权，请查看记录并联系管理员。':job.status==='INTERRUPTED'?'任务因服务重启中断，未自动重试。':job.status==='FAILED'||job.status==='TIMEOUT'?'Agent 运行失败，请查看记录。':'Agent 已完成；候选仍需核验。',['FAILED','TIMEOUT','APPROVAL_BLOCKED','INTERRUPTED'].includes(job.status));
  drawPhoto('a');drawPhoto('b');
}
async function pollAgent(){
  clearTimeout(agentTimer);try{const info=await api('/api/agent/status');agentPollFailures=0;showAgent(info);if(info.job?.status==='RUNNING')agentTimer=setTimeout(pollAgent,1500)}
  catch(error){if(error.status===404){showAgent({enabled:false,provider:null,job:null});return}console.warn('[WorldState] agent status read failed',error.message);agentPollFailures++;if(agentPollFailures<3)agentTimer=setTimeout(pollAgent,1500*agentPollFailures);else activity('Agent 状态读取失败，请刷新核验；不会重复启动。',true)}
}
$('assistant-mode').onchange=()=>{if(agentInfo)showAgent(agentInfo);$('command').placeholder=$('assistant-mode').value==='agent'?'根据这些照片，尝试建立这个房间的可编辑模型。':'例如：将选中的墙延长20厘米'};
$('agent-evidence-mode').onchange=()=>{if(agentInfo)showAgent(agentInfo)};
$('recommend-views').onclick=()=>silently(queue('正在本地计算视角建议…',async()=>{if(!selected||!state)throw new Error('请先选择多视图对象。');const result=await api('/api/modeler/recommend-views?object_id='+encodeURIComponent(selected));if(!result.pairs.length)throw new Error(result.warning);const choices=$('agent-photo-choices');choices.replaceChildren();const pair=new Set(result.pairs[0].image_ids);for(const view of result.views){const coverage=view.projection_fraction===null?'仅参考点':`投影 ${(100*view.projection_fraction).toFixed(0)}%`;const option=new Option(`${view.photo} · ${coverage} · 遮挡未知`,String(view.image_id));option.selected=pair.has(view.image_id);choices.add(option)}recommendedObject=selected;choices.hidden=false;const bad=(result.excluded||[]).filter(x=>['PHOTO_HASH_MISMATCH','PHOTO_UNAVAILABLE','CAMERA_PHOTO_DIMENSION_MISMATCH'].includes(x.reason));activity(`本地推荐视差 ${result.pairs[0].parallax_deg}°；请检查遮挡，可多选 2–8 张。${bad.length?' 照片校验失败：'+bad.map(x=>x.image_id+' '+x.reason).join('、'):''}`);message(result.warning)}));
$('agent-hypotheses').onchange=()=>{drawPhoto('a');drawPhoto('b')};
$('send').onclick=()=>{
  const command=$('command').value,selectedId=selected;
  if($('assistant-mode').value==='agent'){
    const modelOnly=$('agent-evidence-mode').value==='model',selectedPhotos=recommendedObject===selected&&!$('agent-photo-choices').hidden?[...$('agent-photo-choices').selectedOptions].map(o=>state?.cameras?.find(c=>String(c.image_id)===o.value)):null,cameras=modelOnly?[]:(selectedPhotos||[camFor('a'),camFor('b')]);
    if(!command.trim()||(modelOnly&&!model)||(!modelOnly&&(cameras.length<2||cameras.length>8||cameras.some(c=>!c)||new Set(cameras.map(c=>c.image_id)).size!==cameras.length))){activity(modelOnly?'请输入任务并打开已有模型。':'请输入任务，并选择 2–8 张不同的已注册照片。',true);return}
    const consent=modelOnly?`将当前模型的构件和参数信息发送给 ${agentInfo?.provider||'模型'}，不发送照片。请确认您有权使用和传输模型信息。`:`将以下照片及当前模型的构件参数发送给已配置的 ${agentInfo?.provider||'多模态模型'} 进行分析：\n${cameras.map(c=>c.photo).join('\n')}\n请确认您有权使用和传输这些数据。`;
    if(!confirm(consent))return;
    const request={goal:command,image_ids:cameras.map(c=>c.image_id),selected_id:selectedId,allow_external_images:!modelOnly,allow_external_model:modelOnly,model_only:modelOnly};
    silently(queue('正在启动 AI 建模…',async()=>{showAgent(await api('/api/agent/start',request));message('Agent 已启动；不会自动提交 IFC。');pollAgent()}));return;
  }
  silently(queue('正在执行本地规则…',async()=>{if(!model)throw new Error('请先打开 IFC 模型。');const result=await api('/api/command',{revision:model.revision,selected_id:selectedId,command});activity(`已生成版本 ${result.model.revision}；请检查受影响构件。`);await loadAll();message('规则命令已执行。')}));
};
$('agent-candidates').onchange=()=>{if(agentInfo)showAgent(agentInfo)};$('agent-revisions').onchange=()=>{if(agentInfo)showAgent(agentInfo)};
$('agent-import').onclick=()=>{const job=agentInfo?.job,candidate=$('agent-candidates').value;if(!job||!candidate||!confirm(`导入未经核验的 AI 候选 ${candidate}？请随后检查照片、对应点及未知属性。`))return;const request={job_id:job.id,candidate_id:candidate,state_revision:state?.revision};silently(queue('正在导入候选…',async()=>{const result=await api('/api/agent/accept',request);state=result.state;selected=result.object_id;renderState();if(agentInfo)showAgent(agentInfo);switchRight('observations');message(result.warning)}))};
$('agent-apply-revision').onclick=()=>{const job=agentInfo?.job,proposal=job?.revision_proposals?.find(x=>x.id===$('agent-revisions').value);if(!proposal)return;const before=Number(proposal.diff?.before),after=Number(proposal.diff?.after),delta=after-before,warningsBefore=proposal.validation_before?.wall_axis_warnings?.length||0,warningsAfter=proposal.validation?.wall_axis_warnings?.length||0,fit=proposal.projection_evidence?`\n源照片拟合残差：${proposal.projection_evidence.before_line_rms_px.toFixed(2)} → ${proposal.projection_evidence.after_line_rms_px.toFixed(2)} px（非独立验证）`:'';if(!confirm(`应用待核验的 AI 修改建议？\n${proposal.element_id} · ${proposal.attribute}: ${before.toFixed(3)} → ${after.toFixed(3)} m\n变化：${delta>=0?'+':''}${delta.toFixed(3)} m\n受影响：${proposal.diff?.affected_elements?.join('、')||'未知'}\n未关联墙轴交叉警告：${warningsBefore} → ${warningsAfter}；非完整碰撞检查。${fit}\n依据：${proposal.reason}`))return;const request={job_id:job.id,proposal_id:proposal.id,revision:model?.revision};silently(queue('正在应用修改建议…',async()=>{const result=await api('/api/agent/accept-revision',request);activity(`已创建版本 ${result.model.revision}；请重新验证。`);await loadAll();if(agentInfo)showAgent(agentInfo);message('AI 修改建议已应用；仍需独立核验。')}))};
$('restore').onclick=()=>silently(queue('正在恢复版本…',async()=>{const result=await api('/api/restore',{revision:model.revision,source_revision:Number($('versions').value)});activity(`已从版本 ${result.source_revision} 创建版本 ${result.model.revision}。`);await loadAll();message('历史版本已恢复为新版本。')}));
$('sync-ifc').onclick=()=>{const edit={file:$('external-ifc').files[0],reason:$('reason').value.trim(),element_id:$('editor').dataset.target,attribute:$('attribute').value};silently(queue('正在核验 IFC 修改…',async()=>{if(!edit.file||!edit.reason)throw new Error('请选择 IFC 并填写修改依据。');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(edit.file)});const result=await api('/api/sync-ifc',{revision:model.revision,element_id:edit.element_id,attribute:edit.attribute,reason:edit.reason,data_base64:data});activity(`外部 IFC 已核验并生成版本 ${result.model.revision}。`);await loadAll();message('外部修改已回写，需重新验证。')}))};
$('add-evidence').onclick=()=>$('upload').click();$('upload').onchange=async e=>{for(const file of e.target.files){try{await queue('正在上传照片…',async()=>{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});await api('/api/upload',{data_base64:data});await loadState();message('照片已上传；关联相机后可参与建模。')})}catch(_){break}}e.target.value=''};
$('create-project').onclick=()=>silently(queue('正在创建项目…',async()=>{await api('/api/project',{name:$('new-project-name').value});await loadAll();message('项目已创建。')}));
$('camera-file').onchange=async e=>{try{const manifest=JSON.parse(await e.target.files[0].text());await queue('正在导入相机…',async()=>{await api('/api/modeler/cameras',{manifest});await loadState();message('已导入匹配照片的相机。')})}catch(error){message(error.message,true)}finally{e.target.value=''}};
$('ai-analyze').onclick=()=>{const photo=uploadFor(camFor('a'));silently(queue('正在分析左图…',async()=>{if(!photo)throw new Error('请选择已注册的左图。');const run=await api('/api/vision/analyze',{photo_id:photo.id});const image=$('vision-overlay');image.src='/api/vision/overlay-preview/'+encodeURIComponent(run.id);image.hidden=false;const root=$('vision-candidates');root.replaceChildren();for(const candidate of run.candidates.filter(c=>['wall_floor_line','wall_ceiling_line','line_endpoint'].includes(c.kind)).slice(0,20)){const row=element('div',(candidate.kind==='line_endpoint'?'端点建议':'边界建议')+' · 未验证','candidate-row');for(const [label,decision] of [['接受','accept'],['拒绝','reject']]){const b=element('button',label);b.onclick=()=>{const request={run_id:run.id,candidate_id:candidate.id,object_id:selected,decision,feature_id:$('feature').value,feature_ids:[$('feature').value,$('line-end').value],sigma_px:Number($('sigma').value)};silently(queue('正在记录视觉建议…',async()=>{const result=await api('/api/modeler/vision-decision',{state_revision:state.revision,...request});state=result.state;row.textContent='视觉建议已'+(decision==='accept'?'接受':'拒绝')+'，来源保留。';renderState();message('视觉建议已记录，仍需跨图核验。')}))};row.append(b)}root.append(row)}switchRight('observations');message('视觉分析完成；区域和线段仍需人工确认。')}))};
for(const link of document.querySelectorAll('a[href^="/api/export/model."]'))link.onclick=e=>{if(state?.model_dirty){e.preventDefault();message('观察已修改；请先求解并保存模型。',true)}};
setMarking(false);loadAll().then(()=>pollAgent()).catch(error=>message(error.message||'工作区加载失败。',true));
