"""Exercise the local Studio against the real, checked-in multi-object IFC."""
import base64
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import pytest
from PIL import Image
from products.worldstate_bim.studio_server import StudioServer, parse_local_command

ROOT=Path(__file__).resolve().parents[3]/"examples/bim_real_scan_craslab/room_round3"


@pytest.fixture
def server(tmp_path):
    instance=StudioServer(0,ROOT,tmp_path/"work")
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    yield instance
    instance.shutdown();instance.server_close();thread.join()


def api(server,path,data=None,*,authorized=True):
    origin=f"http://127.0.0.1:{server.server_port}"
    headers={}
    if data is not None:
        headers={"Content-Type":"application/json","Origin":origin if authorized else "http://attacker.invalid",
                 "X-WorldState-Token":server.token}
        data=json.dumps(data).encode()
    request=urllib.request.Request(origin+path,data=data,headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=15) as response:
            raw=response.read()
            return response.status,json.loads(raw) if response.headers.get_content_type()=="application/json" else raw
    except urllib.error.HTTPError as exc:
        return exc.code,json.loads(exc.read()) if exc.headers.get_content_type()=="application/json" else None


def test_real_ifc_geometry_and_versioned_edits(server):
    status,model=api(server,"/api/model");assert status==200
    status,mesh=api(server,"/api/mesh");assert status==200 and not mesh["failures"]
    assert len([x for x in mesh["objects"] if x["ifc_type"]=="IfcWall"])==8
    assert all(x["vertices"] and x["faces"] for x in mesh["objects"])
    opening=next(e for e in model["elements"] if e["ifc_type"]=="IfcOpeningElement")
    request={"revision":1,"element_id":opening["id"],"attribute":"offset","value":100.,"reason":"bad test"}
    status,error=api(server,"/api/revise",request);assert status==400 and "OPENING_OUTSIDE_WALL" in error["error"]
    request["value"]=1.25
    status,result=api(server,"/api/revise",request);assert status==200 and result["model"]["revision"]==2
    assert opening["fill"] in result["diff"]["affected_elements"]
    assert api(server,"/api/revise",request)[0]==409
    assert api(server,"/api/export/model.ifc")[1].startswith(b"ISO-10303-21")
    assert api(server,"/api/revise",request,authorized=False)[0]==403


def test_upload_is_validated_and_explicitly_unassociated(server):
    image=Image.new("RGB",(3,3),"white");buffer=io.BytesIO();image.save(buffer,format="PNG")
    payload={"data_base64":base64.b64encode(buffer.getvalue()).decode()}
    status,item=api(server,"/api/upload",payload)
    assert status==201 and item["status"]=="unassociated" and item["captured_at"]=="UNKNOWN"
    assert api(server,"/api/photo/"+item["id"])[0]==200
    assert api(server,"/api/upload",{"data_base64":base64.b64encode(b"invalid").decode()})[0]==400


def test_local_rule_is_explicit_and_bounded(server):
    model=server.model;wall=next(e for e in model["elements"] if e["ifc_type"]=="IfcWall")
    ident,attr,value=parse_local_command(model,"把 "+wall["id"]+" 的高度改为 3.6 米")
    assert (ident,attr,value)==(wall["id"],"height",3.6)
    with pytest.raises(ValueError):parse_local_command(model,"delete everything")


def test_point_cloud_requires_explicit_finite_xyz_and_marks_alignment_unknown(tmp_path):
    import numpy as np
    path=tmp_path/"scan.npy";np.save(path,np.array([[1.,2.,3.],[3.,4.,5.]]))
    instance=StudioServer(0,ROOT,tmp_path/"workspace",path)
    try:
        assert instance.cloud["status"]=="user_selected_alignment_unverified"
        assert instance.cloud["source_points"]==2
        assert len(instance.cloud["points"])==2
    finally:instance.server_close()
