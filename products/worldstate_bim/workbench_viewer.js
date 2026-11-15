import * as THREE from './three.module.js';
import {OrbitControls} from './OrbitControls.js';

// IFC coordinates are Z-up. Candidate coordinates are shown separately until
// their source frame is explicitly calibrated; they are never overlaid as IFC.
export class WorkbenchViewer {
  constructor(container, onSelect) {
    this.container=container;this.onSelect=onSelect;this.mode='ifc';this.selected=null;this.model=null;this.mesh=null;this.solution=null;
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#f1f5f3');
    this.camera=new THREE.PerspectiveCamera(42,1,0.001,10000);this.camera.up.set(0,0,1);
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});this.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
    this.renderer.outputEncoding=THREE.sRGBEncoding;this.renderer.domElement.setAttribute('aria-label','可旋转并选择构件的三维模型');
    this.renderer.domElement.tabIndex=0;container.replaceChildren(this.renderer.domElement);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;this.controls.dampingFactor=.12;
    this.controls.screenSpacePanning=true;this.controls.target.set(0,0,0);
    this.frame=null;this.controls.addEventListener('change',()=>this.requestRender());
    this.scene.add(new THREE.HemisphereLight(0xffffff,0xa4b6ae,.92));
    const light=new THREE.DirectionalLight(0xffffff,.8);light.position.set(4,-5,8);this.scene.add(light);
    this.group=new THREE.Group();this.helpers=new THREE.Group();this.dimensions=new THREE.Group();this.scene.add(this.group,this.helpers,this.dimensions);
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();this.pointerStart=null;
    this.renderer.domElement.addEventListener('pointerdown',e=>{this.pointerStart=[e.clientX,e.clientY]});
    this.renderer.domElement.addEventListener('pointerup',e=>{
      if(!this.pointerStart||Math.hypot(e.clientX-this.pointerStart[0],e.clientY-this.pointerStart[1])>4)return;
      const r=this.renderer.domElement.getBoundingClientRect();this.pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);
      this.raycaster.setFromCamera(this.pointer,this.camera);this.raycaster.params.Line.threshold=this.extent*.018;
      const hit=this.raycaster.intersectObjects(this.group.children,true).find(x=>x.object.userData.elementId);
      if(hit)this.onSelect(hit.object.userData.elementId);
    });
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);this.resize();
  }
  requestRender(){if(this.frame!==null)return;this.frame=requestAnimationFrame(()=>{this.frame=null;this.controls.update();this.renderer.render(this.scene,this.camera)})}
  resize(){const w=Math.max(1,this.container.clientWidth),h=Math.max(1,this.container.clientHeight);this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.requestRender()}
  clear(group){while(group.children.length){const object=group.children[0];group.remove(object);object.traverse(o=>{o.geometry?.dispose();if(o.material){for(const m of (Array.isArray(o.material)?o.material:[o.material])){m.map?.dispose();m.dispose()}}})}}
  setData(model,mesh,solution){this.model=model;this.mesh=mesh;this.solution=solution;this.renderData(true)}
  setMode(mode){if(mode==='candidate'&&!this.solution?.objects?.length)return false;this.mode=mode;this.renderData(true);return true}
  select(id){this.selected=id;this.applySelection();this.drawDimensions();this.requestRender()}
  renderData(fit=false){
    this.clear(this.group);this.clear(this.helpers);this.clear(this.dimensions);
    if(this.mode==='ifc'){
      const palette={IfcWall:'#a8c2b9',IfcSlab:'#aabcc3',IfcWindow:'#7eaaa8',IfcDoor:'#bea98a'};
      for(const o of this.mesh?.objects||[]){
        const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(o.vertices,3));geometry.setIndex(o.faces);geometry.computeVertexNormals();
        const material=new THREE.MeshStandardMaterial({color:palette[o.ifc_type]||'#a4b9ad',roughness:.84,metalness:0,side:THREE.DoubleSide});
        const item=new THREE.Mesh(geometry,material);item.userData={elementId:o.id,baseColor:material.color.getHex()};
        const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geometry,28),new THREE.LineBasicMaterial({color:'#729087',transparent:true,opacity:.7}));item.add(edges);this.group.add(item);
      }
    }else{
      for(const object of this.solution?.objects||[]){
        const points=object.vertices.map(v=>new THREE.Vector3(...v.xyz_source));
        const line=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:'#508d78'}));
        line.userData={elementId:object.id,baseColor:line.material.color.getHex()};this.group.add(line);
        const markers=new THREE.Points(new THREE.BufferGeometry().setFromPoints(points),new THREE.PointsMaterial({color:'#4a8c77',size:5,sizeAttenuation:false}));markers.userData.elementId=object.id;this.group.add(markers);
      }
    }
    let box=new THREE.Box3().setFromObject(this.group);if(box.isEmpty())box=new THREE.Box3(new THREE.Vector3(-.5,-.5,0),new THREE.Vector3(.5,.5,1));
    const size=box.getSize(new THREE.Vector3());this.extent=Math.max(size.x,size.y,size.z,.5);this.center=box.getCenter(new THREE.Vector3());
    const gridSize=this.extent*3.2,grid=new THREE.GridHelper(gridSize,16,'#b8c9c2','#dbe5df');grid.rotation.x=Math.PI/2;grid.position.set(this.center.x,this.center.y,box.min.z-this.extent*.03);this.helpers.add(grid);
    const axes=new THREE.AxesHelper(this.extent*.3);axes.position.set(this.center.x-gridSize*.38,this.center.y-gridSize*.38,box.min.z);this.helpers.add(axes);
    this.applySelection();this.drawDimensions();if(fit)this.setView('iso');this.requestRender();
  }
  applySelection(){for(const o of this.group.children){if(o.material?.color&&o.userData.baseColor!==undefined)o.material.color.setHex(o.userData.elementId===this.selected?0x38a77e:o.userData.baseColor)}}
  drawDimensions(){
    this.clear(this.dimensions);if(this.mode!=='ifc'||!this.model||!this.selected)return;
    const e=this.model.elements.find(x=>x.id===this.selected);if(!e||e.ifc_type!=='IfcWall')return;
    const a=this.model.nodes.find(n=>n.id===e.start),b=this.model.nodes.find(n=>n.id===e.end),z=e.parameters?.base_elevation?.value,h=e.parameters?.height?.value;
    if(!a||!b||![a.x,a.y,b.x,b.y,z].every(Number.isFinite))return;
    const offset=this.extent*.08,points=[new THREE.Vector3(a.x,a.y,z-offset),new THREE.Vector3(b.x,b.y,z-offset)];
    this.dimensions.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:'#268b6b'})));
    if(Number.isFinite(h)&&h>0){const p=new THREE.Vector3(b.x,b.y,z),q=new THREE.Vector3(b.x,b.y,z+h);this.dimensions.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([p,q]),new THREE.LineBasicMaterial({color:'#268b6b'})))}
  }
  label(text,position){const c=document.createElement('canvas');c.width=256;c.height=64;const x=c.getContext('2d');x.fillStyle='rgba(255,255,255,.94)';x.fillRect(0,0,256,64);x.fillStyle='#17674f';x.font='bold 28px sans-serif';x.textAlign='center';x.textBaseline='middle';x.fillText(text,128,33);const material=new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),depthTest:false});const sprite=new THREE.Sprite(material);sprite.scale.set(this.extent*.46,this.extent*.115,1);sprite.position.copy(position);this.dimensions.add(sprite)}
  setView(view){
    if(!this.center)return;const d=this.extent*1.2;this.camera.up.set(0,0,1);
    if(view==='top'){this.camera.up.set(0,1,0);this.camera.position.copy(this.center).add(new THREE.Vector3(0,0,d*2.1))}
    else if(view==='front')this.camera.position.copy(this.center).add(new THREE.Vector3(0,-d*2.1,0));
    else{
      let direction=new THREE.Vector3(1,0,0);
      if(this.mode==='ifc'){
        const wall=this.model?.elements?.find(e=>e.id===this.selected&&e.ifc_type==='IfcWall')||this.model?.elements?.find(e=>e.ifc_type==='IfcWall');
        const a=this.model?.nodes?.find(n=>n.id===wall?.start),b=this.model?.nodes?.find(n=>n.id===wall?.end);
        if(a&&b&&[a.x,a.y,b.x,b.y].every(Number.isFinite))direction.set(b.x-a.x,b.y-a.y,0).normalize();
      }else{
        const vertices=this.solution?.objects?.[0]?.vertices;if(vertices?.length>1)direction.set(vertices[1].xyz_source[0]-vertices[0].xyz_source[0],vertices[1].xyz_source[1]-vertices[0].xyz_source[1],0).normalize();
      }
      if(direction.lengthSq()<1e-10)direction.set(1,0,0);
      const normal=new THREE.Vector3(-direction.y,direction.x,0);
      this.camera.position.copy(this.center).addScaledVector(normal,d*1.8).addScaledVector(direction,d*.55).add(new THREE.Vector3(0,0,d*.8));
    }
    this.camera.near=Math.max(.001,d/10000);this.camera.far=d*100+100;this.camera.updateProjectionMatrix();this.controls.target.copy(this.center);this.controls.update()
  }
  zoomBy(factor){this.camera.position.sub(this.controls.target).multiplyScalar(factor).add(this.controls.target);this.controls.update()}
}
