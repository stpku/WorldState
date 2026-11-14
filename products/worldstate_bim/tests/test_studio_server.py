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
    ident,attr,value=parse_local_command(model,"将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效",wall["id"])
    nodes={n["id"]:n for n in model["nodes"]};a,b=nodes[wall["start"]],nodes[wall["end"]]
    import math
    assert (ident,attr)==(wall["id"],"length") and value==pytest.approx(math.dist((a["x"],a["y"]),(b["x"],b["y"]))+.2)
    with pytest.raises(ValueError):parse_local_command(model,"delete everything")


def test_photo_project_annotation_generation_revision_restore_and_restart(tmp_path):
    workspace=tmp_path/"photo-project"
    instance=StudioServer(0,None,workspace)
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        assert api(instance,"/api/project")[1]["project"] is None
        assert api(instance,"/api/project",{"name":"Synthetic photo flow","operator_kind":"automation"})[0]==201
        image=Image.new("RGB",(640,480),"white");buffer=io.BytesIO();image.save(buffer,format="PNG")
        status,photo=api(instance,"/api/upload",{"data_base64":base64.b64encode(buffer.getvalue()).decode()})
        assert status==201
        for i in range(1,4):
            body={"photo_id":photo["id"],"kind":"wall_boundary","wall_id":f"wall-{i}",
                  "points":[[10,10+i],[100,60+i]],"elapsed_ms":100}
            assert api(instance,"/api/annotation",body)[0]==201
        assert api(instance,"/api/annotation",{"photo_id":photo["id"],"kind":"scale","wall_id":"wall-1","points":[[10,100],[100,100]]})[0]==201
        body={"layout":{"points":[[20,20],[220,20],[220,170],[60,170]],"closed":False,"confirmed_schematic":True},
              "reference":{"wall_index":1,"length_m":4,"basis":"independent_user_declared","description":"test ruler",
                           "height_m":2.8,"height_basis":"assumed","thickness_m":0.12}}
        assert api(instance,"/api/layout",body)[0]==200
        assert api(instance,"/api/generate",{})[0]==400
        assert api(instance,"/api/generate",{"confirmed_candidate":True})[0]==400
        assert api(instance,"/api/scale/bind",{"confirmed_endpoints":True})[0]==200
        status,result=api(instance,"/api/generate",{"confirmed_candidate":True})
        assert status==201 and result["model"]["validation"]["scope"]=="PARTIAL_OPEN"
        assert len([e for e in result["model"]["elements"] if e["ifc_type"]=="IfcWall"])==3
        assert all(e["classification"]["status"]=="simulated" for e in result["model"]["elements"])
        assert api(instance,"/api/export/model.ifc")[1].startswith(b"ISO-10303-21")
        status,result=api(instance,"/api/command",{"revision":1,"selected_id":"wall-1",
            "command":"将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效"})
        assert status==200 and result["diff"]["after"]==pytest.approx(4.2)
        assert next(n for n in result["model"]["nodes"] if n["id"]=="node-2")["status"]=="simulated"
        assert api(instance,"/api/generate",{"confirmed_candidate":True})[0]==400
        assert api(instance,"/api/sync-ifc",{"revision":2,"element_id":"wall-1","attribute":"length",
            "reason":"invalid","data_base64":base64.b64encode(b"not IFC").decode()})[0]==400
        status,result=api(instance,"/api/restore",{"revision":2,"source_revision":1})
        assert status==200 and result["model"]["revision"]==3
        assert api(instance,"/api/versions")[1]["revisions"]==[1,2,3]
    finally:
        instance.shutdown();instance.server_close();thread.join()
    resumed=StudioServer(0,None,workspace)
    try:
        assert resumed.model["revision"]==3 and resumed.project["current_revision"]==3
    finally:resumed.server_close()


def test_point_cloud_requires_explicit_finite_xyz_and_marks_alignment_unknown(tmp_path):
    import numpy as np
    path=tmp_path/"scan.npy";np.save(path,np.array([[1.,2.,3.],[3.,4.,5.]]))
    instance=StudioServer(0,ROOT,tmp_path/"workspace",path)
    try:
        assert instance.cloud["status"]=="user_selected_alignment_unverified"
        assert instance.cloud["source_points"]==2
        assert len(instance.cloud["points"])==2
    finally:instance.server_close()


def test_vision_candidate_decisions_preserve_source_in_ifc_evidence(tmp_path):
    """Fake provider tests API wiring only; real inference is a separate browser run."""
    import hashlib
    model_path=tmp_path/'fake-weights.onnx';model_path.write_bytes(b'not a model')
    instance=StudioServer(0,None,tmp_path/'vision-work',vision_model=model_path)
    class FakeProvider:
        def analyze(self,path):
            return ({'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'provider':'FAKE_TEST_ONLY','model_sha256':'f'*64,'runtime_seconds':0,
                     'candidates':[{'id':'line-1','kind':'wall_floor_line','points_px':[[10,20],[100,20]],'status':'proposed'},
                                   {'id':'line-2','kind':'wall_floor_line','points_px':[[100,20],[130,60]],'status':'proposed'}]},b'test overlay')
    instance.vision_provider=FakeProvider()
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        assert api(instance,'/api/project',{'name':'Provider wiring','operator_kind':'automation'})[0]==201
        image=Image.new('RGB',(640,480),'white');buffer=io.BytesIO();image.save(buffer,format='PNG')
        photo=api(instance,'/api/upload',{'data_base64':base64.b64encode(buffer.getvalue()).decode()})[1]
        status,run=api(instance,'/api/vision/analyze',{'photo_id':photo['id']});assert status==201
        assert api(instance,'/api/vision/overlay/'+run['id'])[1]==b'test overlay'
        status,ann=api(instance,'/api/vision/decision',{'run_id':run['id'],'candidate_id':'line-1',
                          'decision':'accepted','wall_id':'wall-1'})
        assert status==201 and ann['origin']=='vision_candidate'
        assert api(instance,'/api/vision/decision',{'run_id':run['id'],'candidate_id':'line-2','decision':'rejected'})[0]==200
        assert api(instance,'/api/vision/decision',{'run_id':run['id'],'candidate_id':'line-2','decision':'accepted','wall_id':'wall-1'})[0]==400
        assert api(instance,'/api/annotation',{'photo_id':photo['id'],'kind':'scale','wall_id':'wall-1','points':[[10,20],[100,20]]})[0]==201
        body={'layout':{'points':[[20,20],[220,20]],'closed':False,'confirmed_schematic':True},
              'reference':{'wall_index':1,'length_m':4,'basis':'assumed','description':'test assumption',
                           'height_m':2.8,'height_basis':'assumed','thickness_m':.12}}
        assert api(instance,'/api/layout',body)[0]==200
        assert api(instance,'/api/scale/bind',{'confirmed_endpoints':True})[0]==200
        status,result=api(instance,'/api/generate',{'confirmed_candidate':True});assert status==201
        ev=next(e for e in result['model']['evidence'] if e['id']==ann['id'])
        assert ev['kind']=='vision_candidate_accepted' and ev['vision_candidate_id']=='line-1'
        assert ev['status']=='ai_proposed_script_accepted' and ev['vision_provider']=='FAKE_TEST_ONLY'
        # Altering a stored accepted annotation cannot silently impersonate the model output.
        instance.project['annotations'][0]['points']=[[15,20],[100,20]]
        status,error=api(instance,'/api/generate',{'confirmed_candidate':True,'confirm_regeneration':True})
        assert status==400 and '视觉候选被修改' in error['error']
    finally:
        instance.shutdown();instance.server_close();thread.join()
