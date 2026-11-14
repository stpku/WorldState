"""Local multi-object BIM studio backed by real IFC geometry and room IR."""
from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .modeling_tools import compare_revisions, validate_geometry
from .room_cli import save_version
from .room_ifc import export_room
from .room_ir import revise_element, validate_room
from .room_sync import _verify_geometry
from .photo_room import ANNOTATION_KINDS, build_photo_room
from .photo_scale import bind_scale


def _write_json(path: Path, value: dict) -> None:
    """Atomically persist product state without following a destination symlink."""
    if path.is_symlink():
        raise ValueError("状态文件不能是符号链接")
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".studio-", delete=False) as stream:
        stream.write(content); temporary = Path(stream.name)
    try:
        if path.is_symlink():
            raise ValueError("状态文件不能是符号链接")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StudioServer(ThreadingHTTPServer):
    """Serve an explicitly selected room project on loopback only."""
    def __init__(self, port: int, model_dir: Path | None, workspace: Path, point_cloud: Path | None = None, vision_model: Path | None = None):
        super().__init__(("127.0.0.1",port),Handler)
        self.workspace=workspace.resolve()
        if self.workspace.is_relative_to(Path(__file__).resolve().parents[2]):
            raise ValueError("Studio workspace must be outside the source repository")
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.project_path = self.workspace / "photo-project.json"
        if self.project_path.is_symlink():raise ValueError("project state cannot be a symlink")
        self.project = json.loads(self.project_path.read_text()) if self.project_path.exists() else None
        if self.project is not None and (not isinstance(self.project, dict) or self.project.get("schema") != "worldstate-photo-project/0.1"):
            raise ValueError("unsupported photo project state")
        if model_dir is None and self.project and self.project.get("current_revision"):
            revision = self.project["current_revision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError("invalid project revision")
            model_dir = self.workspace / f"revision-{revision:03}"
        self.model_dir=model_dir.resolve(strict=True) if model_dir is not None else None
        self.model=None
        if self.model_dir is not None:
            self.model=json.loads((self.model_dir/"model.json").read_text())
            validate_room(self.model)
            if self.project and self.project.get("id") != self.model.get("project_id"):
                raise ValueError("workspace project and selected model do not match")
            if not (self.model_dir/"model.ifc").is_file():raise ValueError("model.ifc required")
            import ifcopenshell
            with tempfile.TemporaryDirectory(prefix="worldstate-studio-") as temp:
                expected=Path(temp)/"model.ifc";export_room(self.model,expected)
                _verify_geometry(ifcopenshell.open(str(expected)),ifcopenshell.open(str(self.model_dir/"model.ifc")))
        self.lock=threading.Lock();self.token=secrets.token_urlsafe(24)
        self.vision_model=vision_model.resolve(strict=True) if vision_model is not None else None
        self.vision_provider=None
        self.cloud=None
        if point_cloud is not None:
            import numpy as np
            from .parametric_ir import digest
            source=point_cloud.resolve(strict=True)
            if source.suffix.lower() != ".npy" or source.stat().st_size>256_000_000:
                raise ValueError("point cloud must be an NPY file under 256 MB")
            points=np.load(source,allow_pickle=False,mmap_mode="r")
            if points.ndim!=2 or points.shape[1]!=3 or not (1<=len(points)<=2_000_000) or points.dtype.kind not in "fiu" or not np.isfinite(points).all():
                raise ValueError("point cloud must contain at most two million finite XYZ points")
            chosen=np.linspace(0,len(points)-1,min(len(points),8000),dtype=int)
            self.cloud={"points":np.asarray(points[chosen],dtype=float).tolist(),"source_points":len(points),
                        "sha256":digest(source),"status":"user_selected_alignment_unverified"}
        self.uploads=self.workspace/"evidence"
        if self.uploads.is_symlink():raise ValueError("evidence directory cannot be a symlink")
        self.uploads.mkdir(exist_ok=True)
        self.index=self.workspace/"evidence-index.json"
        if self.index.is_symlink():raise ValueError("evidence index cannot be a symlink")
        existing=json.loads(self.index.read_text()) if self.index.exists() else {"schema":"worldstate-studio-evidence/0.1","uploads":[]}
        if not isinstance(existing,dict) or existing.get("schema")!="worldstate-studio-evidence/0.1" or not isinstance(existing.get("uploads"),list):
            raise ValueError("unrecognized evidence index; refusing to overwrite it")
        self.uploaded=existing["uploads"]
        for item in self.uploaded:
            if (not isinstance(item,dict) or not re.fullmatch(r"[0-9a-f]{64}",str(item.get("sha256",""))) or
                item.get("extension") not in {".png",".jpg"} or item.get("id")!="upload-"+item["sha256"][:16] or
                item.get("mime") not in {"image/png","image/jpeg"}):
                raise ValueError("invalid evidence index entry")

    def record(self, action: str, **details: object) -> None:
        if self.project is None:
            raise ValueError("请先创建房间项目")
        self.project.setdefault("events", []).append({"action": action, "at": datetime.now(timezone.utc).isoformat(), **details})
        _write_json(self.project_path, self.project)


def mesh_data(model: dict, ifc_path: Path) -> dict:
    """Extract actual world-coordinate triangles from the current IFC file."""
    import ifcopenshell
    import ifcopenshell.geom
    from .room_ifc import stable_guid
    f=ifcopenshell.open(str(ifc_path));settings=ifcopenshell.geom.settings();settings.set("use-world-coords",True)
    objects=[];failures=[];total_faces=0
    for e in model["elements"]:
        if e["ifc_type"] not in {"IfcWall","IfcSlab","IfcDoor","IfcWindow"}:continue
        try:
            obj=f.by_guid(stable_guid(model["project_id"],e["ifc_type"],e["id"]))
            shape=ifcopenshell.geom.create_shape(settings,obj)
            verts=list(shape.geometry.verts);faces=list(shape.geometry.faces)
            total_faces+=len(faces)//3
            if total_faces>500000:raise ValueError("model is too large for the local preview")
            objects.append({"id":e["id"],"ifc_type":e["ifc_type"],"vertices":verts,"faces":faces})
        except (RuntimeError,ValueError,AttributeError) as exc:
            failures.append({"id":e["id"],"reason":str(exc)})
    return {"source":"current IFC triangulated by IfcOpenShell","objects":objects,"failures":failures}


def parse_local_command(model: dict, text: str, selected_id: str | None = None) -> tuple[str,str,float]:
    """Recognize a deliberately small local rule syntax; this is not an LLM."""
    if not isinstance(text,str) or len(text)>300:
        raise ValueError("命令过长或无效")
    relative=re.fullmatch(r"\s*(?:将|把)?\s*(?:选中的|当前)(?:墙|墙体)\s*(?:延长|增加)\s*(\d+(?:\.\d+)?)\s*(厘米|cm|米|m)\s*[，,。 ]*(?:检查相邻墙体和门窗是否仍然有效[。]?)?\s*",text)
    if relative:
        wall=next((e for e in model["elements"] if e["id"]==selected_id and e["ifc_type"]=="IfcWall"),None)
        if wall is None:raise ValueError("请先选择一面墙")
        nodes={n["id"]:n for n in model["nodes"]};a,b=nodes[wall["start"]],nodes[wall["end"]]
        import math
        increase=float(relative.group(1))/(100 if relative.group(2) in {"厘米","cm"} else 1)
        if increase<=0:raise ValueError("延长量必须大于零")
        return wall["id"],"length",math.hypot(b["x"]-a["x"],b["y"]-a["y"])+increase
    pattern=r"\s*(?:将|把)?\s*([A-Za-z0-9_-]+)\s*(?:的)?\s*(长度|高度|厚度|位置)\s*(?:设为|改为|调整为|=)\s*(\d+(?:\.\d+)?)\s*(?:米|m)?\s*"
    match=re.fullmatch(pattern,text)
    if not match:
        raise ValueError("本地规则格式：将 构件ID 的高度改为 3.5 米")
    ident,label,value=match.groups()
    item=next((e for e in model["elements"] if e["id"]==ident),None)
    if item is None:raise ValueError("找不到指定构件")
    attribute={"长度":"length","高度":"height","厚度":"thickness","位置":"offset"}[label]
    if item["ifc_type"] in {"IfcDoor","IfcWindow"}:
        if attribute not in {"offset","height"}:raise ValueError("请通过对应开口修改门窗参数")
        ident=item["opening"]
    return ident,attribute,float(value)


class Handler(BaseHTTPRequestHandler):
    server: StudioServer
    def log_message(self,format: str,*args: object)->None:
        pass
    def send_data(self,status: int,data: bytes,mime: str)->None:
        self.send_response(status);self.send_header("Content-Type",mime);self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'")
        self.end_headers();self.wfile.write(data)
    def send_json(self,status: int,value)->None:
        self.send_data(status,json.dumps(value,ensure_ascii=False,allow_nan=False).encode(),"application/json; charset=utf-8")
    def valid_host(self)->bool:
        return self.headers.get("Host")==f"127.0.0.1:{self.server.server_port}"
    def do_GET(self)->None:
        if not self.valid_host():self.send_data(403,b"local host required","text/plain");return
        path=urlsplit(self.path).path
        try:
            with self.server.lock:
                if path in {"/", "/builder"}:
                    filename="photo_studio.html" if path=="/builder" or self.server.model is None else "studio.html"
                    page=Path(__file__).with_name(filename).read_text().replace("__WS_TOKEN__",self.server.token)
                    self.send_data(200,page.encode(),"text/html; charset=utf-8")
                elif path=="/api/project":self.send_json(200,{"project":self.server.project,"uploads":self.server.uploaded,
                                                               "has_model":self.server.model is not None, "vision_configured":self.server.vision_model is not None})
                elif path=="/api/versions":
                    versions=[]
                    for directory in sorted(self.server.workspace.glob("revision-*")):
                        match=re.fullmatch(r"revision-([0-9]+)",directory.name)
                        if match and directory.is_dir() and not directory.is_symlink() and (directory/"model.json").is_file():
                            versions.append(int(match.group(1)))
                    self.send_json(200,{"revisions":versions,"current":self.server.model["revision"] if self.server.model else None})
                elif path=="/api/model":self.send_json(200,self.server.model)
                elif path=="/api/mesh":self.send_json(200,mesh_data(self.server.model,self.server.model_dir/"model.ifc") if self.server.model else {"objects":[],"failures":[]})
                elif path=="/api/evidence":self.send_json(200,{"model":self.server.model["evidence"] if self.server.model else [],"uploads":self.server.uploaded,
                    "point_cloud":({k:v for k,v in self.server.cloud.items() if k!="points"} if self.server.cloud else None)})
                elif path=="/api/pointcloud":self.send_json(200,self.server.cloud)
                elif path=="/api/report":self.send_json(200,{"geometry":validate_geometry(self.server.model) if self.server.model else None,
                    "quarantined":self.server.model.get("quarantined",[]) if self.server.model else [],
                    "history":self.server.model.get("history",[]) if self.server.model else [],
                    "photo_project":self.server.project})
                elif path=="/api/export/model.ifc":self.send_data(200,(self.server.model_dir/"model.ifc").read_bytes(),"application/octet-stream")
                elif path=="/api/export/model.json":self.send_json(200,self.server.model)
                elif path.startswith("/api/fusion/"):
                    ident=path.rsplit("/",1)[-1]
                    result=self.read_fusion(ident)
                    self.send_json(200,result)
                elif path.startswith("/api/vision/overlay/"):
                    ident=path.rsplit("/",1)[-1]
                    if not re.fullmatch(r"vision-[0-9a-f]{32}",ident):raise ValueError("视觉结果编号无效")
                    runs=(self.server.project or {}).get("vision_runs",[])
                    run=next((x for x in runs if x.get("id")==ident),None)
                    filename=self.server.workspace/"vision"/(ident+".png")
                    if not run or filename.is_symlink() or not filename.is_file():raise ValueError("视觉叠加图不可用")
                    raw=filename.read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=run.get("overlay_sha256"):raise ValueError("视觉叠加图哈希不符")
                    self.send_data(200,raw,"image/png")
                elif path.startswith("/api/photo/"):
                    ident=path.rsplit("/",1)[-1]
                    item=next((x for x in self.server.uploaded if x["id"]==ident),None)
                    if not item:self.send_data(404,b"not found","text/plain");return
                    filename=self.server.uploads/(item["sha256"]+item["extension"])
                    if filename.is_symlink() or not filename.is_file() or hashlib.sha256(filename.read_bytes()).hexdigest()!=item["sha256"]:
                        self.send_data(404,b"evidence unavailable","text/plain");return
                    self.send_data(200,filename.read_bytes(),item["mime"])
                else:self.send_data(404,b"not found","text/plain")
        except (ValueError,KeyError,RuntimeError,FileNotFoundError):
            self.send_json(400,{"error":"无法读取模型或证据"})
    def do_POST(self)->None:
        path=urlsplit(self.path).path
        if not self.valid_host() or self.headers.get("Origin")!=f"http://127.0.0.1:{self.server.server_port}" or not secrets.compare_digest(self.headers.get("X-WorldState-Token",""),self.server.token):
            self.send_data(403,b"local origin and session token required","text/plain");return
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size<=0 or size>16_000_000:raise ValueError("请求大小无效")
            body=json.loads(self.rfile.read(size))
            with self.server.lock:
                if path=="/api/upload":self.upload(body);return
                if path=="/api/project":self.create_project(body);return
                if path=="/api/geometry/reconstruct":self.reconstruct_photos(body);return
                if path=="/api/fusion/reconstruct":self.reconstruct_fusion(body);return
                if path=="/api/fusion/scale":self.solve_fusion_scale(body);return
                if path=="/api/fusion/generate":self.generate_fusion_room(body);return
                if path=="/api/vision/analyze":self.analyze_photo(body);return
                if path=="/api/vision/decision":self.decide_candidate(body);return
                if path=="/api/vision/accept-segments":self.accept_segments(body);return
                if path=="/api/annotation":self.add_annotation(body);return
                if path=="/api/annotation/delete":self.delete_annotation(body);return
                if path=="/api/layout":self.save_layout(body);return
                if path=="/api/scale/bind":self.bind_scale(body);return
                if path=="/api/generate":self.generate(body);return
                if path not in {"/api/revise","/api/command","/api/sync-ifc","/api/restore"}:self.send_data(404,b"not found","text/plain");return
                if self.server.model is None:raise ValueError("请先生成或打开模型")
                if body.get("revision")!=self.server.model["revision"]:
                    self.send_json(409,{"error":"模型已更新，请重新加载后再修改"});return
                if path=="/api/sync-ifc":self.sync_ifc(body);return
                if path=="/api/restore":self.restore(body);return
                if path=="/api/command":
                    ident,attribute,value=parse_local_command(self.server.model,body.get("command"),body.get("selected_id"))
                    reason="本地规则命令："+body["command"]
                else:
                    ident,attribute,value=body["element_id"],body["attribute"],body["value"]
                    reason=body["reason"]
                before=self.server.model
                operator="automation" if self.server.project and self.server.project.get("operator_kind")=="automation" else "user"
                revised,diff=revise_element(before,ident,attribute,value,reason=reason,operator=operator)
                target=self.server.workspace/f"revision-{revised['revision']:03}"
                save_version(revised,target,diff=diff)
                comparison=compare_revisions(before,revised)
                self.server.model,self.server.model_dir=revised,target
                if self.server.project:
                    self.server.project["current_revision"]=revised["revision"]
                    self.server.record("revise", element_id=ident, attribute=attribute)
                self.send_json(200,{"model":revised,"diff":diff,"comparison":comparison})
        except (KeyError,TypeError,ValueError,OSError,RuntimeError,json.JSONDecodeError,binascii.Error) as exc:
            self.send_json(400,{"error":str(exc)[:400]})

    def create_project(self, body: dict) -> None:
        if self.server.project is not None or self.server.model is not None:
            raise ValueError("当前工作区已有项目或模型；请为新房间选择新的工作区")
        name=body.get("name")
        if not isinstance(name,str) or not name.strip() or len(name)>120:
            raise ValueError("请输入不超过 120 字的项目名称")
        operator=body.get("operator_kind","user")
        if operator not in {"user","automation"}:raise ValueError("不支持的标注来源")
        self.server.project={"schema":"worldstate-photo-project/0.1","id":"photo-room-"+uuid.uuid4().hex,
                             "name":name.strip(),"operator_kind":operator,"created_at":datetime.now(timezone.utc).isoformat(),
                             "annotations":[],"layout":{},"reference":{},"events":[],"current_revision":None}
        self.server.record("project_created")
        self.send_json(201,self.server.project)

    def read_fusion(self, ident: str) -> dict:
        if not isinstance(ident,str) or not re.fullmatch(r"fusion-[0-9a-f]{32}",ident):raise ValueError("融合结果编号无效")
        run=next((x for x in (self.server.project or {}).get("fusion_runs",[]) if x.get("id")==ident),None)
        directory=self.server.workspace/"fusion"/ident;path=directory/"fusion.json"
        if not run or directory.is_symlink() or path.is_symlink() or not path.is_file():raise ValueError("融合结果不可用")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=run.get("sha256"):raise ValueError("融合结果哈希不符")
        return json.loads(path.read_text())

    def reconstruct_fusion(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        if self.server.vision_model is None:raise ValueError("请使用 --vision-model 配置本地视觉模型")
        geometry=next((x for x in project.get("geometry_runs",[]) if x.get("id")==body.get("geometry_run_id")),None)
        if not geometry or geometry.get("status")!="UNVERIFIED_RESEARCH_CANDIDATE":raise ValueError("请先获得足够已注册照片的多视图结果")
        if project['geometry_runs'][-1]['id']!=geometry['id']:raise ValueError('相机结果已更新，请融合最新重建')
        if project.get('fusion_camera_input_changed') and project.get('fusion_camera_dirty_geometry_id')==geometry['id']:
            raise ValueError('相机输入已改变，请先重新恢复相机')
        camera_inputs=body.get('camera_inputs')
        if camera_inputs is not None and not isinstance(camera_inputs,dict):raise ValueError('相机输入格式无效')
        camera_keys=('fx','fy','cx','cy','description','calibration_sha256','geometry_run_id')
        camera_snapshot={k:camera_inputs.get(k) for k in camera_keys} if camera_inputs is not None else None
        gid=geometry['id']
        if not re.fullmatch(r"geometry-[0-9a-f]{32}",gid):raise ValueError("几何结果编号无效")
        root=self.server.workspace/"geometry"/gid;sparse=root/"sparse"/"0";images=root/"input"
        if root.is_symlink() or sparse.is_symlink() or images.is_symlink() or not sparse.is_dir() or not images.is_dir():
            raise ValueError("多视图几何或照片不可用")
        expected_files=geometry.get('reconstruction_files')
        if not expected_files:raise ValueError('旧几何结果缺少完整哈希，请重新运行相机恢复')
        actual_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sparse.glob('*.bin') if not p.is_symlink()}
        if actual_files!={x['file']:x['sha256'] for x in expected_files}:raise ValueError('三维重建文件哈希不符')
        for item in geometry.get('inputs',[]):
            name=item.get('file','');path=images/name
            if Path(name).name!=name or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item.get('sha256'):
                raise ValueError('多视图原始照片哈希不符')
        if len(project.get("fusion_runs",[]))>=10:raise ValueError("融合次数已达工作区上限")
        parent=self.server.workspace/"fusion"
        if parent.is_symlink():raise ValueError("融合目录不能是符号链接")
        parent.mkdir(mode=0o700,exist_ok=True);ident="fusion-"+uuid.uuid4().hex;target=parent/ident;target.mkdir(mode=0o700)
        try:
            from .multiview_fusion import infer_masks,fuse_multiview
            masks=infer_masks(sparse,images,self.server.vision_model,target/"masks")
            result=fuse_multiview(sparse,images,target/"masks")
            if project.get('fusion_runs'):
                from .multiview_fusion import associate_surface_identities
                previous=self.read_fusion(project['fusion_runs'][-1]['id'])
                association=associate_surface_identities(previous,result)
                for match in association['matches']:
                    surface=next(x for x in result['wall_surfaces'] if x['id']==match['current_surface_id'])
                    surface['persistent_id']=match['persistent_id']
                result['previous_association']=association
        except ImportError as exc:raise ValueError("缺少多视图或视觉模型依赖") from exc
        except (ValueError,RuntimeError,OSError) as exc:
            self.server.record("fusion_failed",fusion_id=ident,reason=str(exc)[:300]);raise
        result['id']=ident;result['geometry_run_id']=gid;result['segmentation_seconds']=masks['runtime_seconds'];result['camera_calibration']=geometry.get('supplied_calibration')
        output=target/"fusion.json";_write_json(output,result)
        summary={'id':ident,'geometry_run_id':gid,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'registered_photos':len(result['cameras']),'track_count':len(result['tracks']),
            'wall_candidates':len(result['wall_surfaces']),'floor_planes':len(result['floor_planes']),
            'ambiguous_pairs':len(result['ambiguous_surface_pairs']),'segmentation_seconds':masks['runtime_seconds'],
            'camera_input_snapshot':camera_snapshot,
            'status':'UNVERIFIED_DEVELOPMENT_CANDIDATE'}
        project.setdefault('fusion_runs',[]).append(summary)
        project['fusion_camera_input_changed']=False
        project.pop('fusion_camera_dirty_geometry_id',None)
        self.server.record('fusion_reconstructed',fusion_id=ident,**{k:v for k,v in summary.items() if k not in {'id','sha256'}})
        self.send_json(201,summary)

    def require_current_fusion(self, fusion: dict) -> None:
        project=self.server.project
        geometry_runs=(project or {}).get('geometry_runs',[])
        if not geometry_runs or fusion.get('geometry_run_id')!=geometry_runs[-1].get('id'):
            raise ValueError('相机结果已更新，请重新进行多视图融合')
        if project.get('fusion_camera_input_changed'):
            raise ValueError('相机输入已改变，请重新恢复相机并进行多视图融合')

    def fusion_anchor(self, fusion: dict, reference: dict, *, confirmed: bool) -> dict:
        project=self.server.project
        wall=reference.get('wall_index')
        if isinstance(wall,bool) or not isinstance(wall,int) or wall<1:raise ValueError('请选择尺度标注关联的墙段编号')
        anns=[a for a in project['annotations'] if a.get('kind')=='scale' and a.get('wall_id')==f'wall-{wall}']
        if len(anns)<2:raise ValueError('请在至少两张已注册照片中按相同顺序标记尺度的两个物理端点')
        photos={p['id']:p for p in self.server.uploaded};cameras={c['sha256']:c for c in fusion['cameras']}
        observations=[[],[]];seen=set();annotation_ids=[]
        for ann in anns:
            photo=photos.get(ann['photo_id']);camera=cameras.get(photo['sha256']) if photo else None
            if camera is None:raise ValueError('尺度标注必须使用已注册照片')
            path=self.server.uploads/(photo['sha256']+photo['extension'])
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=photo['sha256']:
                raise ValueError('尺度照片丢失或哈希不符')
            if camera['image_id'] in seen:raise ValueError('同一照片只能提供一组尺度端点')
            if len(ann.get('points',[]))!=2:raise ValueError('尺度标注需要两个端点')
            seen.add(camera['image_id']);annotation_ids.append(ann['id'])
            for i,point in enumerate(ann['points']):
                observations[i].append({'image_id':camera['image_id'],'photo_sha256':photo['sha256'],'pixel_xy':point})
        for obs in observations:obs.sort(key=lambda x:x['image_id'])
        return {'schema':'worldstate-multiview-scale-anchor/0.1','confirmed':confirmed,
            'basis':reference.get('basis'),'distance_m':reference.get('length_m'),
            'measurement_uncertainty_m':reference.get('measurement_uncertainty_m'),
            'description':reference.get('description'),'annotation_ids':sorted(annotation_ids),
            'endpoints':[{'id':f'wall-{wall}-scale-a','observations':observations[0]},
                         {'id':f'wall-{wall}-scale-b','observations':observations[1]}]}

    def solve_fusion_scale(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        fusion=self.read_fusion(body.get('fusion_id'))
        self.require_current_fusion(fusion)
        anchor=self.fusion_anchor(fusion,project.get('reference') or {},confirmed=body.get('confirmed_endpoints'))
        from .multiview_fusion import solve_multiview_scale
        solution=solve_multiview_scale(fusion,anchor)
        project['fusion_scale']={'fusion_id':fusion['id'],'anchor':anchor,'solution':solution}
        self.server.record('multiview_scale_solved',fusion_id=fusion['id'],basis=anchor['basis'],
                           binding_sha256=solution['binding_sha256'],operator=project.get('operator_kind','user'))
        self.send_json(200,solution)

    def generate_fusion_room(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        fusion=self.read_fusion(body.get('fusion_id'));stored=project.get('fusion_scale') or {}
        self.require_current_fusion(fusion)
        photos={p['sha256']:p for p in self.server.uploaded}
        for camera in fusion['cameras']:
            photo=photos.get(camera['sha256']);path=self.server.uploads/(photo['sha256']+photo['extension']) if photo else None
            if not photo or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=camera['sha256']:
                raise ValueError('融合来源照片丢失或哈希不符')
        if stored.get('fusion_id')!=fusion['id']:raise ValueError('请先求解当前融合结果的多视图尺度')
        if self.server.model is not None and body.get('confirm_regeneration') is not True:
            raise ValueError('重新生成会替换当前几何，请先确认；旧版本会保留')
        anchor=self.fusion_anchor(fusion,project.get('reference') or {},confirmed=True)
        from .multiview_fusion import build_multiview_room
        model=build_multiview_room(fusion,anchor,stored.get('solution') or {},body.get('surface_ids'),
            project_id=project['id'],assumed_thickness_m=(project.get('reference') or {}).get('thickness_m'),
            confirmed_candidates=body.get('confirmed_candidates'),allow_assumed_scale=body.get('allow_assumed_scale') is True,
            operator_kind=project.get('operator_kind','user'))
        before=self.server.model
        if before:
            model['revision']=before['revision']+1
            model['history']=before.get('history',[])+[{'revision':model['revision'],'action':'regenerated_from_multiview',
                'warning':'surface identity must be re-associated after a new SfM solve'}]
        target=self.server.workspace/f"revision-{model['revision']:03}";save_version(model,target)
        self.server.model,self.server.model_dir=model,target;project['current_revision']=model['revision']
        self.server.record('multiview_candidate_generated',fusion_id=fusion['id'],revision=model['revision'],
                           surface_ids=body['surface_ids'],operator=project.get('operator_kind','user'))
        self.send_json(201,{'revision':model['revision'],'model':model,'validation':model['validation']})

    def reconstruct_photos(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        if body.get("confirmed_same_camera") is not True:
            raise ValueError("请确认选择的照片来自同一相机，且没有包含留出评测照片")
        uploads=self.server.uploaded
        if not 4<=len(uploads)<=32:raise ValueError("多视图恢复需要 4 至 32 张已上传照片")
        if len({(p["width"],p["height"]) for p in uploads})!=1:
            raise ValueError("同一相机的照片需具有相同尺寸；请先检查裁剪或设备")
        for photo in uploads:
            filename=photo["sha256"]+photo["extension"];source=self.server.uploads/filename
            if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=photo["sha256"]:
                raise ValueError("照片不可用或哈希不符")
        if len(project.get("geometry_runs",[]))>=20:raise ValueError("多视图实验次数已达工作区上限")
        directory=self.server.workspace/"geometry"
        if directory.is_symlink():raise ValueError("几何结果目录不能是符号链接")
        directory.mkdir(mode=0o700,exist_ok=True)
        ident="geometry-"+uuid.uuid4().hex;target=directory/ident
        target.mkdir(mode=0o700);input_dir=target/"input";input_dir.mkdir(mode=0o700)
        import shutil
        names=[];photo_by_name={}
        for i,photo in enumerate(uploads):
            # Preserve explicit upload order: COLMAP's initialization is sensitive
            # to image ordering. The content hash still identifies the evidence.
            filename=f"{i:04d}-"+photo["sha256"]+photo["extension"]
            shutil.copyfile(self.server.uploads/(photo["sha256"]+photo["extension"]),input_dir/filename)
            names.append(filename);photo_by_name[filename]=photo["id"]
        try:
            from .colmap_provider import reconstruct_uncalibrated_images
            calibration=body.get('camera_calibration')
            if calibration is not None and not isinstance(calibration,dict):raise ValueError('相机标定格式无效')
            result=reconstruct_uncalibrated_images(input_dir,names,target,calibration=calibration)
        except ImportError as exc:
            raise ValueError("缺少 pycolmap；请安装 benchmarks/ws_geometry/requirements-round2-cpu.txt") from exc
        except (ValueError,RuntimeError,OSError) as exc:
            self.server.record("geometry_failed",geometry_run_id=ident,reason=str(exc)[:300])
            raise
        result["id"]=ident;result["created_at"]=datetime.now(timezone.utc).isoformat()
        source_sparse=target/'sparse'/'0'
        result['reconstruction_files']=[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                                         for p in sorted(source_sparse.glob('*.bin')) if p.is_file() and not p.is_symlink()]
        for camera in result["registered_cameras"]:camera["photo_id"]=photo_by_name[camera["name"]]
        for entry in result["inputs"]:entry["photo_id"]=photo_by_name[entry["file"]]
        _write_json(target/"geometry-candidate.json",result)
        project.setdefault("geometry_runs",[]).append(result)
        self.server.record("geometry_reconstructed",geometry_run_id=ident,status=result["status"],
                           registered=len(result["registered_cameras"]),photos=len(uploads),
                           elapsed_seconds=result["timing_seconds"]["total"])
        self.send_json(201,result)

    def analyze_photo(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        if self.server.vision_model is None:raise ValueError("视觉模型未配置；请使用 --vision-model 指向已下载的受支持 ONNX 权重")
        photo=next((p for p in self.server.uploaded if p["id"]==body.get("photo_id")),None)
        if photo is None:raise ValueError("请选择已上传照片")
        path=self.server.uploads/(photo["sha256"]+photo["extension"])
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=photo["sha256"]:
            raise ValueError("照片不可用或哈希不符")
        if len(project.get("vision_runs",[]))>=100:raise ValueError("视觉分析次数已达工作区上限")
        try:
            if self.server.vision_provider is None:
                from .semantic_vision import UperNetOnnxProvider
                self.server.vision_provider=UperNetOnnxProvider(self.server.vision_model)
            result,overlay=self.server.vision_provider.analyze(path)
        except ImportError as exc:
            raise ValueError("缺少 CPU 视觉依赖；请安装 benchmarks/bim_real_room/requirements-cpu-py312.txt") from exc
        if result["image_sha256"]!=photo["sha256"]:raise ValueError("识别结果照片哈希不符")
        ident="vision-"+uuid.uuid4().hex
        directory=self.server.workspace/"vision"
        if directory.is_symlink():raise ValueError("视觉结果目录不能是符号链接")
        directory.mkdir(exist_ok=True)
        target=directory/(ident+".png")
        with target.open("xb") as stream:stream.write(overlay)
        result.update(id=ident,photo_id=photo["id"],overlay_sha256=hashlib.sha256(overlay).hexdigest(),
                      created_at=datetime.now(timezone.utc).isoformat())
        project.setdefault("vision_runs",[]).append(result)
        self.server.record("vision_analyzed",vision_run_id=ident,photo_id=photo["id"],
                           elapsed_seconds=result["runtime_seconds"],candidate_count=len(result["candidates"]))
        self.send_json(201,result)

    def accept_segments(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        if body.get("confirmed_proposals") is not True:raise ValueError("请先检查识别线段并确认接受")
        if project.get("annotations"):raise ValueError("批量接受适用于尚无标注的新项目；已有标注请逐项确认")
        run=next((r for r in project.get("vision_runs",[]) if r.get("id")==body.get("run_id")),None)
        if run is None:raise ValueError("未找到视觉结果")
        elapsed=body.get("elapsed_ms",0)
        if isinstance(elapsed,bool) or not isinstance(elapsed,int) or not 0<=elapsed<=86_400_000:raise ValueError("操作耗时无效")
        from .semantic_vision import suggest_disconnected_segments
        suggestions=suggest_disconnected_segments(run,limit=3)
        if not suggestions:raise ValueError("没有可用墙地线段；请重新拍摄或手工标注")
        operator=project.get("operator_kind","user");created=[]
        for i,suggestion in enumerate(suggestions,1):
            for j,candidate in enumerate([suggestion["line"],*suggestion["endpoints"]]):
                ann={"id":"ann-"+uuid.uuid4().hex,"photo_id":run["photo_id"],
                     "kind":"wall_boundary" if j==0 else "corner","wall_id":f"wall-{i}",
                     "points":candidate["points_px"],"object_id":None if j==0 else f"node-{2*i-2+j}",
                     "dimensions":None,"operator_kind":operator,"elapsed_ms":0,
                     "created_at":datetime.now(timezone.utc).isoformat(),"origin":"vision_candidate",
                     "vision_run_id":run["id"],"vision_candidate_id":candidate["id"],
                     "vision_model_sha256":run["model_sha256"]}
                created.append(ann)
        for ann in created:
            candidate=next(c for c in run["candidates"] if c["id"]==ann["vision_candidate_id"])
            candidate["status"]="accepted";candidate["annotation_id"]=ann["id"]
        project["annotations"].extend(created)
        self.server.record("vision_segments_accepted",vision_run_id=run["id"],
                           candidate_ids=[x["vision_candidate_id"] for x in created],
                           annotation_ids=[x["id"] for x in created],elapsed_ms=elapsed,operator=operator)
        self.send_json(201,{"wall_segments":len(suggestions),"annotation_ids":[x["id"] for x in created],
                            "warning":"线段端点不一定是实际墙角；遮挡和连接未知，需要人工检查"})

    def decide_candidate(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        run=next((r for r in project.get("vision_runs",[]) if r.get("id")==body.get("run_id")),None)
        candidate=next((c for c in (run or {}).get("candidates",[]) if c.get("id")==body.get("candidate_id")),None)
        if run is None or candidate is None:raise ValueError("未找到视觉候选")
        if candidate.get("status")!="proposed":raise ValueError("该候选已处理")
        decision=body.get("decision")
        if decision=="rejected":
            candidate["status"]="rejected"
            self.server.record("vision_rejected",vision_run_id=run["id"],candidate_id=candidate["id"])
            self.send_json(200,{"status":"rejected"});return
        if decision!="accepted":raise ValueError("请选择接受或拒绝")
        wall=body.get("wall_id"); kind=candidate.get("kind")
        if not isinstance(wall,str) or not re.fullmatch(r"wall-[1-9][0-9]*",wall):raise ValueError("请输入关联墙段编号")
        mapping={"wall_floor_line":"wall_boundary","wall_ceiling_line":"ceiling_line","line_endpoint":"corner",
                 "door_region":"door","window_region":"window"}
        if kind not in mapping:raise ValueError("语义区域不是独立构件；请先确认边界或关联墙段")
        annotation_kind=mapping[kind]
        points=candidate.get("points_px")
        if annotation_kind in {"door","window"}:
            x1,y1,x2,y2=candidate["bbox_px"];points=[[x1,y1],[x2,y2]]
            if not isinstance(body.get("dimensions"),dict):raise ValueError("门窗尺寸需另行测量或明确假设")
        object_id=body.get("object_id")
        if annotation_kind=="corner" and (not isinstance(object_id,str) or not re.fullmatch(r"node-[1-9][0-9]*",object_id)):
            raise ValueError("请为角点输入 node-1 等编号；线段端点可能并非真实墙角")
        if annotation_kind in {"door","window"} and (not isinstance(object_id,str) or not re.fullmatch(annotation_kind+r"-[A-Za-z0-9_-]{1,40}",object_id)):
            raise ValueError("请指定 door-1 或 window-1 等编号")
        if len(project["annotations"])>=1000:raise ValueError("标注数量已达上限")
        elapsed=body.get("elapsed_ms",0)
        if isinstance(elapsed,bool) or not isinstance(elapsed,int) or not 0<=elapsed<=86_400_000:raise ValueError("操作耗时无效")
        ann={"id":"ann-"+uuid.uuid4().hex,"photo_id":run["photo_id"],"kind":annotation_kind,"wall_id":wall,
             "points":points,"object_id":object_id,"dimensions":body.get("dimensions"),
             "operator_kind":project.get("operator_kind","user"),"elapsed_ms":elapsed,
             "created_at":datetime.now(timezone.utc).isoformat(),"origin":"vision_candidate",
             "vision_run_id":run["id"],"vision_candidate_id":candidate["id"],
             "vision_model_sha256":run["model_sha256"]}
        project["annotations"].append(ann);candidate["status"]="accepted";candidate["annotation_id"]=ann["id"]
        self.server.record("vision_accepted",vision_run_id=run["id"],candidate_id=candidate["id"],annotation_id=ann["id"])
        self.send_json(201,ann)

    def add_annotation(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        photo=next((p for p in self.server.uploaded if p["id"]==body.get("photo_id")),None)
        kind=body.get("kind"); points=body.get("points"); wall=body.get("wall_id")
        if not photo or kind not in ANNOTATION_KINDS or not isinstance(wall,str) or not re.fullmatch(r"wall-[1-9][0-9]*",wall):
            raise ValueError("请选择已上传照片、标注类型和有效墙段")
        from .photo_room import _point
        if not isinstance(points,list) or len(points)!=(1 if kind=="corner" else 2):
            raise ValueError("该标注的点数不正确")
        for point in points:_point(point,photo["width"]-1,photo["height"]-1)
        if len(points)==2 and points[0]==points[1]:raise ValueError("两个标注点不能相同")
        elapsed=body.get("elapsed_ms",0)
        if isinstance(elapsed,bool) or not isinstance(elapsed,int) or not 0<=elapsed<=86_400_000:
            raise ValueError("标注耗时无效")
        ann={"id":"ann-"+uuid.uuid4().hex,"photo_id":photo["id"],"kind":kind,"wall_id":wall,"points":points,
             "object_id":body.get("object_id"),"dimensions":body.get("dimensions"),
             "operator_kind":project.get("operator_kind","user"),"elapsed_ms":elapsed,"created_at":datetime.now(timezone.utc).isoformat()}
        json.dumps(ann,allow_nan=False)
        if len(project["annotations"])>=1000:raise ValueError("标注数量已达上限")
        project["annotations"].append(ann)
        self.server.record("annotation_added",annotation_id=ann["id"],elapsed_ms=elapsed)
        self.send_json(201,ann)

    def delete_annotation(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        ident=body.get("id"); before=len(project["annotations"])
        project["annotations"]=[a for a in project["annotations"] if a["id"]!=ident]
        if len(project["annotations"])==before:raise ValueError("未找到标注")
        self.server.record("annotation_deleted",annotation_id=ident)
        self.send_json(200,{"deleted":ident})

    def save_layout(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        layout=body.get("layout"); reference=body.get("reference")
        if not isinstance(layout,dict) or not isinstance(reference,dict):raise ValueError("草图和尺度格式无效")
        json.dumps({"layout":layout,"reference":reference},allow_nan=False)
        old_camera=(project.get('layout') or {}).get('camera') or {}
        new_camera=layout.get('camera') or {}
        camera_keys=('fx','fy','cx','cy','description','calibration_sha256','geometry_run_id')
        fusion_runs=project.get('fusion_runs',[])
        snapshot=fusion_runs[-1].get('camera_input_snapshot') if fusion_runs else None
        baseline=snapshot if snapshot is not None else (old_camera if project.get('fusion_scale') else None)
        if baseline is not None and any(baseline.get(k)!=new_camera.get(k) for k in camera_keys):
            project['fusion_camera_input_changed']=True
            runs=project.get('geometry_runs',[])
            project['fusion_camera_dirty_geometry_id']=runs[-1]['id'] if runs else None
        project["layout"]=layout;project["reference"]=reference
        self.server.record("layout_saved",point_count=len(layout.get("points",[])) if isinstance(layout.get("points"),list) else 0)
        self.send_json(200,{"saved":True})

    def bind_scale(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        binding=bind_scale(project,self.server.uploaded,confirmed=body.get("confirmed_endpoints"))
        project["scale_binding"]=binding
        self.server.record("scale_bound",sha256=binding["sha256"],operator=project.get("operator_kind","user"))
        self.send_json(200,binding)

    def generate(self, body: dict) -> None:
        project=self.server.project
        if project is None:raise ValueError("请先创建房间项目")
        if body.get("confirmed_candidate") is not True:
            raise ValueError("请先确认已检查照片标注、尺度和假设，再生成候选 IFC")
        if self.server.model is not None and body.get("confirm_regeneration") is not True:
            raise ValueError("重新生成会用当前标注和草图替换编辑后的几何，请先确认")
        layout=project.get("layout") or {}
        run_id=(layout.get("camera") or {}).get("geometry_run_id") if layout.get("mode") in {"photo_floor","photo_floor_segments"} else None
        run=next((r for r in project.get("geometry_runs",[]) if r.get("id")==run_id),None)
        geometry_photo_ids={x.get("photo_id") for x in (run or {}).get("inputs",[])}
        for photo in self.server.uploaded:
            if photo["id"] in geometry_photo_ids or any(a.get("photo_id")==photo["id"] for a in project["annotations"]):
                path=self.server.uploads/(photo["sha256"]+photo["extension"])
                if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=photo["sha256"]:
                    raise ValueError("照片证据缺失或哈希已变化，请重新上传")
        try:
            model=build_photo_room(project,self.server.uploaded)
        except ValueError as exc:
            self.server.record("generation_failed",reason=str(exc)[:300])
            raise
        before=self.server.model
        if before:
            model["revision"]=before["revision"]+1
            model["history"]=before.get("history",[]) + [{"revision":model["revision"],"action":"regenerated_from_user_annotations",
                "warning":"wall IDs follow the current sketch segment order; review identity after changing topology"}]
        target=self.server.workspace/f"revision-{model['revision']:03}"
        save_version(model,target)
        self.server.model,self.server.model_dir=model,target
        project["current_revision"]=model["revision"]
        self.server.record("candidate_generated",revision=model["revision"],confirmed_by=project.get("operator_kind","user"),
                           wall_count=sum(e["ifc_type"]=="IfcWall" for e in model["elements"]))
        self.send_json(201,{"revision":model["revision"],"validation":model["validation"],"model":model})

    def sync_ifc(self, body: dict) -> None:
        from .room_sync import sync_external_ifc
        raw=base64.b64decode(body.get("data_base64",""),validate=True)
        if not raw or len(raw)>10_000_000:raise ValueError("IFC 文件须在 10 MB 以内")
        if not raw.lstrip().startswith(b"ISO-10303-21;"):
            raise ValueError("文件不是受支持的 IFC STEP 文本")
        reason=body.get("reason")
        if not isinstance(reason,str) or not reason.strip():raise ValueError("请填写外部修改依据")
        before=self.server.model
        with tempfile.NamedTemporaryFile(dir=self.server.workspace,suffix=".ifc",prefix=".external-",delete=False) as stream:
            stream.write(raw); external=Path(stream.name)
        try:
            import ifcopenshell
            try:
                operator="automation" if self.server.project and self.server.project.get("operator_kind")=="automation" else "user"
                revised,diff=sync_external_ifc(before,self.server.model_dir/"model.ifc",external,
                    element_id=body["element_id"],attribute=body["attribute"],reason=reason,operator=operator)
            except ifcopenshell.Error as exc:
                raise ValueError("IFC 文件无法解析") from exc
            target=self.server.workspace/f"revision-{revised['revision']:03}"
            save_version(revised,target,diff=diff)
            (target/"external.ifc").write_bytes(raw)
            comparison=compare_revisions(before,revised)
            self.server.model,self.server.model_dir=revised,target
            if self.server.project:
                self.server.project["current_revision"]=revised["revision"]
                self.server.record("external_ifc_synced",element_id=body["element_id"],attribute=body["attribute"])
            self.send_json(200,{"model":revised,"diff":diff,"comparison":comparison})
        finally:external.unlink(missing_ok=True)

    def restore(self, body: dict) -> None:
        source_revision=body.get("source_revision")
        if isinstance(source_revision,bool) or not isinstance(source_revision,int) or source_revision<1:
            raise ValueError("请选择有效的历史版本")
        directory=self.server.workspace/f"revision-{source_revision:03}"
        if directory.is_symlink() or not directory.is_dir() or (directory/"model.json").is_symlink():
            raise ValueError("历史版本不存在或路径不安全")
        before=self.server.model; restored=json.loads((directory/"model.json").read_text())
        validate_room(restored)
        if restored["project_id"]!=before["project_id"] or restored["revision"]!=source_revision:
            raise ValueError("历史版本不属于当前项目")
        restored["revision"]=before["revision"]+1
        restored["history"]=copy.deepcopy(before.get("history",[]))+[{"revision":restored["revision"],
            "action":"restore_snapshot","source_revision":source_revision}]
        restored["validation"]={"status":"REQUIRES_REVALIDATION","note":"Restored historical version; verify before use"}
        target=self.server.workspace/f"revision-{restored['revision']:03}"
        save_version(restored,target)
        comparison=compare_revisions(before,restored)
        self.server.model,self.server.model_dir=restored,target
        if self.server.project:
            self.server.project["current_revision"]=restored["revision"]
            self.server.record("restore",source_revision=source_revision,revision=restored["revision"])
        self.send_json(200,{"model":restored,"comparison":comparison,"source_revision":source_revision})
    def upload(self,body: dict)->None:
        from PIL import Image
        raw=base64.b64decode(body.get("data_base64",""),validate=True)
        if not raw or len(raw)>10_000_000:raise ValueError("图片大小须在 10 MB 以内")
        try:
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in {"PNG","JPEG"} or img.width*img.height>30_000_000:
                    raise ValueError("仅支持不超过 3000 万像素的 PNG 或 JPEG")
                width,height,fmt=img.width,img.height,img.format;img.verify()
            with Image.open(io.BytesIO(raw)) as img:
                if img.getexif().get(274,1)!=1:
                    raise ValueError("照片含旋转方向元数据，请先旋转并另存，确保标注坐标一致")
        except (OSError,Image.DecompressionBombError) as exc:
            raise ValueError("图片格式无效或尺寸过大") from exc
        sha=hashlib.sha256(raw).hexdigest();ext=".png" if fmt=="PNG" else ".jpg"
        path=self.server.uploads/(sha+ext)
        if path.is_symlink():raise ValueError("证据路径不安全")
        if not path.exists():
            with path.open("xb") as stream:stream.write(raw)
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError("现有证据哈希不符")
        ident="upload-"+sha[:16]
        existing=next((x for x in self.server.uploaded if x["id"]==ident),None)
        if existing is None:
            import cv2
            import numpy as np
            with Image.open(io.BytesIO(raw)) as img:
                gray=img.convert("L");gray.thumbnail((640,640)); sample=np.asarray(gray)
            brightness=float(sample.mean());sharpness=float(cv2.Laplacian(sample,cv2.CV_64F).var())
            warnings=[]
            if min(width,height)<480:warnings.append("分辨率较低")
            if brightness<35 or brightness>225:warnings.append("可能过暗或过曝")
            if sharpness<40:warnings.append("可能模糊")
            existing={"id":ident,"sha256":sha,"extension":ext,"mime":"image/png" if fmt=="PNG" else "image/jpeg",
                      "width":width,"height":height,"captured_at":"UNKNOWN",
                      "added_at":datetime.now(timezone.utc).isoformat(),"status":"unassociated",
                      "quality":{"brightness_mean":round(brightness,2),"laplacian_variance":round(sharpness,2),
                                 "warnings":warnings,"note":"heuristic only; coverage and registration not verified"}}
            self.server.uploaded.append(existing)
            content=json.dumps({"schema":"worldstate-studio-evidence/0.1","uploads":self.server.uploaded},indent=2)+"\n"
            with tempfile.NamedTemporaryFile(mode="w",dir=self.server.workspace,prefix=".evidence-",delete=False) as stream:
                stream.write(content);temporary=Path(stream.name)
            try:
                if self.server.index.is_symlink():raise ValueError("evidence index cannot be a symlink")
                os.replace(temporary,self.server.index)
            finally:temporary.unlink(missing_ok=True)
            if self.server.project:self.server.record("photo_uploaded",photo_id=ident)
        self.send_json(201,existing)


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir",type=Path,help="Existing IFC/IR directory; omit to create or resume a photo project")
    parser.add_argument("--workspace",type=Path,required=True)
    parser.add_argument("--point-cloud",type=Path,help="Optional explicitly selected metre-coordinate NPY XYZ; alignment is not assumed")
    parser.add_argument("--vision-model",type=Path,help="Local supported UperNet ONNX model; no download is performed")
    parser.add_argument("--port",type=int,default=8766)
    args=parser.parse_args();server=StudioServer(args.port,args.model_dir,args.workspace,args.point_cloud,args.vision_model)
    print(f"WorldState Studio: http://127.0.0.1:{server.server_port}/",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=="__main__":raise SystemExit(main())
