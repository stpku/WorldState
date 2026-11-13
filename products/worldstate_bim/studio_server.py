"""Local multi-object BIM studio backed by real IFC geometry and room IR."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .modeling_tools import compare_revisions, validate_geometry
from .room_cli import save_version
from .room_ifc import export_room
from .room_ir import revise_element, validate_room
from .room_sync import _verify_geometry


class StudioServer(ThreadingHTTPServer):
    """Serve an explicitly selected room project on loopback only."""
    def __init__(self, port: int, model_dir: Path, workspace: Path, point_cloud: Path | None = None):
        super().__init__(("127.0.0.1",port),Handler)
        self.model_dir=model_dir.resolve(strict=True)
        self.workspace=workspace.resolve()
        if self.workspace.is_relative_to(Path(__file__).resolve().parents[2]):
            raise ValueError("Studio workspace must be outside the source repository")
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.model=json.loads((self.model_dir/"model.json").read_text())
        validate_room(self.model)
        if not (self.model_dir/"model.ifc").is_file():raise ValueError("model.ifc required")
        import ifcopenshell
        with tempfile.TemporaryDirectory(prefix="worldstate-studio-") as temp:
            expected=Path(temp)/"model.ifc";export_room(self.model,expected)
            _verify_geometry(ifcopenshell.open(str(expected)),ifcopenshell.open(str(self.model_dir/"model.ifc")))
        self.lock=threading.Lock();self.token=secrets.token_urlsafe(24)
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


def parse_local_command(model: dict, text: str) -> tuple[str,str,float]:
    """Recognize a deliberately small local rule syntax; this is not an LLM."""
    if not isinstance(text,str) or len(text)>300:
        raise ValueError("命令过长或无效")
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
                if path=="/":
                    page=Path(__file__).with_name("studio.html").read_text().replace("__WS_TOKEN__",self.server.token)
                    self.send_data(200,page.encode(),"text/html; charset=utf-8")
                elif path=="/api/model":self.send_json(200,self.server.model)
                elif path=="/api/mesh":self.send_json(200,mesh_data(self.server.model,self.server.model_dir/"model.ifc"))
                elif path=="/api/evidence":self.send_json(200,{"model":self.server.model["evidence"],"uploads":self.server.uploaded,
                    "point_cloud":({k:v for k,v in self.server.cloud.items() if k!="points"} if self.server.cloud else None)})
                elif path=="/api/pointcloud":self.send_json(200,self.server.cloud)
                elif path=="/api/report":self.send_json(200,{"geometry":validate_geometry(self.server.model),
                    "quarantined":self.server.model.get("quarantined",[]),"history":self.server.model.get("history",[])})
                elif path=="/api/export/model.ifc":self.send_data(200,(self.server.model_dir/"model.ifc").read_bytes(),"application/octet-stream")
                elif path=="/api/export/model.json":self.send_json(200,self.server.model)
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
                if path not in {"/api/revise","/api/command"}:self.send_data(404,b"not found","text/plain");return
                if body.get("revision")!=self.server.model["revision"]:
                    self.send_json(409,{"error":"模型已更新，请重新加载后再修改"});return
                if path=="/api/command":
                    ident,attribute,value=parse_local_command(self.server.model,body.get("command"))
                    reason="本地规则命令："+body["command"]
                else:
                    ident,attribute,value=body["element_id"],body["attribute"],body["value"]
                    reason=body["reason"]
                before=self.server.model
                revised,diff=revise_element(before,ident,attribute,value,reason=reason,operator="user")
                target=self.server.workspace/f"revision-{revised['revision']:03}"
                save_version(revised,target,diff=diff)
                comparison=compare_revisions(before,revised)
                self.server.model,self.server.model_dir=revised,target
                self.send_json(200,{"model":revised,"diff":diff,"comparison":comparison})
        except (KeyError,TypeError,ValueError,OSError,json.JSONDecodeError,binascii.Error) as exc:
            self.send_json(400,{"error":str(exc)[:400]})
    def upload(self,body: dict)->None:
        from PIL import Image
        raw=base64.b64decode(body.get("data_base64",""),validate=True)
        if not raw or len(raw)>10_000_000:raise ValueError("图片大小须在 10 MB 以内")
        try:
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in {"PNG","JPEG"} or img.width*img.height>30_000_000:
                    raise ValueError("仅支持不超过 3000 万像素的 PNG 或 JPEG")
                width,height,fmt=img.width,img.height,img.format;img.verify()
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
            existing={"id":ident,"sha256":sha,"extension":ext,"mime":"image/png" if fmt=="PNG" else "image/jpeg",
                      "width":width,"height":height,"captured_at":"UNKNOWN",
                      "added_at":datetime.now(timezone.utc).isoformat(),"status":"unassociated"}
            self.server.uploaded.append(existing)
            content=json.dumps({"schema":"worldstate-studio-evidence/0.1","uploads":self.server.uploaded},indent=2)+"\n"
            with tempfile.NamedTemporaryFile(mode="w",dir=self.server.workspace,prefix=".evidence-",delete=False) as stream:
                stream.write(content);temporary=Path(stream.name)
            try:
                if self.server.index.is_symlink():raise ValueError("evidence index cannot be a symlink")
                os.replace(temporary,self.server.index)
            finally:temporary.unlink(missing_ok=True)
        self.send_json(201,existing)


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir",type=Path,required=True);parser.add_argument("--workspace",type=Path,required=True)
    parser.add_argument("--point-cloud",type=Path,help="Optional explicitly selected metre-coordinate NPY XYZ; alignment is not assumed")
    parser.add_argument("--port",type=int,default=8766)
    args=parser.parse_args();server=StudioServer(args.port,args.model_dir,args.workspace,args.point_cloud)
    print(f"WorldState Studio: http://127.0.0.1:{server.server_port}/",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=="__main__":raise SystemExit(main())
