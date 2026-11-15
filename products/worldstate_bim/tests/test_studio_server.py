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


def test_studio_and_modeler_share_workbench_with_allowlisted_assets(server):
    home=api(server,'/');modeler=api(server,'/modeler')
    assert home[0]==modeler[0]==200 and home[1]==modeler[1]
    assert b'/assets/workbench.js' in home[1]
    assert api(server,'/assets/workbench.js')[0]==200
    assert api(server,'/assets/three.module.js')[0]==200
    assert api(server,'/assets/../../studio_server.py')[0]==404


def test_explicit_https_origin_preserves_host_origin_pair_and_token_checks(tmp_path):
    """Only the configured HTTPS host and matching origin may use the proxy."""
    import http.client
    trusted='https://studio.example.ts.net:18790'
    instance=StudioServer(0,ROOT,tmp_path/'proxy',trusted_origins=(trusted,))
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        local=f'127.0.0.1:{instance.server_port}'
        def request(method, host, origin=None, token=None):
            conn=http.client.HTTPConnection('127.0.0.1',instance.server_port,timeout=10)
            headers={'Host':host}
            if origin is not None:headers['Origin']=origin
            if token is not None:headers['X-WorldState-Token']=token
            conn.request(method,'/api/does-not-exist',body='{}' if method=='POST' else None,headers=headers)
            response=conn.getresponse();response.read();status=response.status;conn.close();return status
        assert request('GET','studio.example.ts.net:18790')==404
        assert request('GET','other.example.ts.net:18790')==403
        assert request('POST','studio.example.ts.net:18790',trusted,instance.token)==404
        assert request('POST','studio.example.ts.net:18790','https://attacker.example:18790',instance.token)==403
        assert request('POST','studio.example.ts.net:18790',f'http://{local}',instance.token)==403
        assert request('POST',local,trusted,instance.token)==403
        assert request('POST','studio.example.ts.net:18790',trusted,'incorrect')==403
        assert request('POST',local,f'http://{local}',instance.token)==404
        assert request('POST','studio.example.ts.net:18790',None,instance.token)==403
    finally:
        instance.shutdown();instance.server_close();thread.join()


@pytest.mark.parametrize('origin',[
    'http://studio.example.ts.net:18790','https://*.example.ts.net:18790',
    'https://studio.example.ts.net','https://studio.example.ts.net:18790/path',
    'https://studio.example.ts.net:18790.evil.test','https://user@studio.example.ts.net:18790',
])
def test_trusted_origins_reject_inexact_or_non_https_values(origin, tmp_path):
    with pytest.raises(ValueError,match='exact HTTPS DNS origin'):
        StudioServer(0,ROOT,tmp_path/'invalid',trusted_origins=(origin,))


def test_upload_is_validated_and_explicitly_unassociated(server):
    image=Image.new("RGB",(3,3),"white");buffer=io.BytesIO();image.save(buffer,format="PNG")
    payload={"data_base64":base64.b64encode(buffer.getvalue()).decode()}
    status,item=api(server,"/api/upload",payload)
    assert status==201 and item["status"]=="unassociated" and item["captured_at"]=="UNKNOWN"
    assert api(server,"/api/photo/"+item["id"])[0]==200
    assert api(server,"/api/upload",{"data_base64":base64.b64encode(b"invalid").decode()})[0]==400
    (server.uploads/(item['sha256']+item['extension'])).write_bytes(b'tampered')
    assert api(server,'/api/photo-preview/'+item['id'])[0]==400


def test_large_photo_preview_is_bounded_without_changing_source_dimensions(server):
    """Previewing a large photo must not change evidence coordinates."""
    image=Image.new('RGB',(3200,1600),'white');buffer=io.BytesIO();image.save(buffer,format='JPEG')
    status,item=api(server,'/api/upload',{'data_base64':base64.b64encode(buffer.getvalue()).decode()})
    assert status==201 and (item['width'],item['height'])==(3200,1600)
    status,preview=api(server,'/api/photo-preview/'+item['id']);assert status==200
    with Image.open(io.BytesIO(preview)) as small:assert small.size==(1600,800)
    status,thumbnail=api(server,'/api/photo-thumbnail/'+item['id']);assert status==200
    with Image.open(io.BytesIO(thumbnail)) as small:assert small.size==(240,120)
    status,crop=api(server,'/api/photo-crop/'+item['id']+'?x=100&y=200');assert status==200
    with Image.open(io.BytesIO(crop)) as detail:assert detail.size==(200,200)
    status,original=api(server,'/api/photo/'+item['id']);assert status==200
    with Image.open(io.BytesIO(original)) as source:assert source.size==(3200,1600)


def test_slow_photo_preview_does_not_block_project_reads(server,monkeypatch):
    """Large photo decoding must not hold the shared project mutation lock."""
    from concurrent.futures import ThreadPoolExecutor
    import products.worldstate_bim.studio_server as studio
    image=Image.new('RGB',(640,480),'white');buffer=io.BytesIO();image.save(buffer,format='JPEG')
    status,item=api(server,'/api/upload',{'data_base64':base64.b64encode(buffer.getvalue()).decode()});assert status==201
    started=threading.Event();release=threading.Event();original=studio._photo_preview
    def slow(path,width,height):
        started.set();assert release.wait(5);return original(path,width,height)
    monkeypatch.setattr(studio,'_photo_preview',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        preview=pool.submit(api,server,'/api/photo-preview/'+item['id'])
        try:
            assert started.wait(3)
            model=pool.submit(api,server,'/api/model')
            assert model.result(timeout=2)[0]==200
        finally:release.set()
        assert preview.result(timeout=5)[0]==200


def test_local_rule_is_explicit_and_bounded(server):
    model=server.model;wall=next(e for e in model["elements"] if e["ifc_type"]=="IfcWall")
    ident,attr,value=parse_local_command(model,"把 "+wall["id"]+" 的高度改为 3.6 米")
    assert (ident,attr,value)==(wall["id"],"height",3.6)
    ident,attr,value=parse_local_command(model,"将选中的墙延长20厘米，检查相邻墙体和门窗是否仍然有效",wall["id"])
    nodes={n["id"]:n for n in model["nodes"]};a,b=nodes[wall["start"]],nodes[wall["end"]]
    import math
    assert (ident,attr)==(wall["id"],"length") and value==pytest.approx(math.dist((a["x"],a["y"]),(b["x"],b["y"]))+.2)
    with pytest.raises(ValueError):parse_local_command(model,"delete everything")


def test_camera_change_invalidates_fusion_even_before_first_scale_solution(server):
    """A saved camera edit cannot be applied to an old 3D reconstruction."""
    import hashlib
    server.model=None;server.model_dir=None  # This test creates an isolated project.
    assert api(server,'/api/project',{'name':'Camera change guard'})[0]==201
    geometry_id='geometry-'+'1'*32;fusion_id='fusion-'+'2'*32
    camera={'fx':500.,'fy':500.,'cx':320.,'cy':240.,'description':'test camera',
            'calibration_sha256':None,'geometry_run_id':None}
    server.project['geometry_runs']=[{'id':geometry_id,'status':'UNVERIFIED_RESEARCH_CANDIDATE'}]
    directory=server.workspace/'fusion'/fusion_id;directory.mkdir(parents=True)
    raw=json.dumps({'id':fusion_id,'geometry_run_id':geometry_id}).encode();(directory/'fusion.json').write_bytes(raw)
    server.project['fusion_runs']=[{'id':fusion_id,'geometry_run_id':geometry_id,
       'sha256':hashlib.sha256(raw).hexdigest(),'camera_input_snapshot':camera.copy()}]
    body={'layout':{'camera':camera.copy()},'reference':{}}
    assert api(server,'/api/layout',body)[0]==200
    assert not server.project.get('fusion_camera_input_changed')
    body['layout']['camera']['fx']=501.
    assert api(server,'/api/layout',body)[0]==200
    assert server.project['fusion_camera_input_changed'] is True
    status,error=api(server,'/api/fusion/scale',{'fusion_id':fusion_id,'confirmed_endpoints':True})
    assert status==400 and '重新恢复相机' in error['error']
    server.vision_model=Path('/test-only-do-not-load')
    status,error=api(server,'/api/fusion/reconstruct',{'geometry_run_id':geometry_id,'camera_inputs':body['layout']['camera']})
    assert status==400 and '重新恢复相机' in error['error']


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


def test_local_wall_projection_and_corner_correction_create_traced_revision(tmp_path):
    """Synthetic browser API contract; scripted edits are not human input."""
    import hashlib
    from products.worldstate_bim.model_first import build_local_wall_ir, solve_local_wall
    from products.worldstate_bim.room_cli import save_version
    from products.worldstate_bim.tests.test_model_first import scene
    data,pix=scene()
    photo=io.BytesIO();Image.new('RGB',(640,480),'white').save(photo,format='PNG');raw=photo.getvalue()
    digest=hashlib.sha256(raw).hexdigest();data['cameras'][0]['sha256']=digest
    for observations in data['corners'].values():observations[0]['photo_sha256']=digest
    data['ceiling_lines'][0]['photo_sha256']=digest
    solution=solve_local_wall(data,pix)
    model=build_local_wall_ir(data,solution,project_id='studio-local',assumed_scale=1.,assumed_thickness_m=.1,allow_assumed=True)
    model_dir=tmp_path/'start';save_version(model,model_dir)
    instance=StudioServer(0,model_dir,tmp_path/'local-work')
    instance.project={'schema':'worldstate-photo-project/0.1','id':'studio-local','operator_kind':'automation','events':[]}
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        status,uploaded=api(instance,'/api/upload',{'data_base64':base64.b64encode(raw).decode()});assert status==201
        status,projections=api(instance,'/api/model/projections');assert status==200
        assert projections['views'][0]['upload_id']==uploaded['id']
        old=data['corners']['left_top'][0]['pixel_xy']
        request={'revision':1,'image_id':1,'corner':'left_top','pixel_xy':[old[0]+.5,old[1]]}
        status,result=api(instance,'/api/model/reoptimize',request)
        assert status==200 and result['model']['revision']==2 and result['diff']['operator']=='automation'
        assert result['model']['history'][-1]['pixel_after']==request['pixel_xy']
        assert result['model']['scale']['status']=='assumed'
        assert result['before_projection']['views'][0]['polygon_px']!=result['after_projection']['views'][0]['polygon_px']
        assert api(instance,'/api/model/reoptimize',request)[0]==409
        request.update(revision=2,pixel_xy=[old[0]+80,old[1]+80])
        assert api(instance,'/api/model/reoptimize',request)[0]==400
        assert api(instance,'/api/model')[1]['revision']==2
    finally:
        instance.shutdown();instance.server_close();thread.join()


def test_vision_candidate_decisions_preserve_source_in_ifc_evidence(tmp_path):
    """Fake provider tests API wiring only; real inference is a separate browser run."""
    import hashlib
    model_path=tmp_path/'fake-weights.onnx';model_path.write_bytes(b'not a model')
    instance=StudioServer(0,None,tmp_path/'vision-work',vision_model=model_path)
    overlay=io.BytesIO();Image.new('RGB',(640,480),'white').save(overlay,format='PNG');overlay=overlay.getvalue()
    class FakeProvider:
        def analyze(self,path):
            return ({'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'provider':'FAKE_TEST_ONLY','model_sha256':'f'*64,'runtime_seconds':0,
                     'candidates':[{'id':'line-1','kind':'wall_floor_line','points_px':[[10,20],[100,20]],'status':'proposed'},
                                   {'id':'line-2','kind':'wall_floor_line','points_px':[[100,20],[130,60]],'status':'proposed'}]},overlay)
    instance.vision_provider=FakeProvider()
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        assert api(instance,'/api/project',{'name':'Provider wiring','operator_kind':'automation'})[0]==201
        image=Image.new('RGB',(640,480),'white');buffer=io.BytesIO();image.save(buffer,format='PNG')
        photo=api(instance,'/api/upload',{'data_base64':base64.b64encode(buffer.getvalue()).decode()})[1]
        status,run=api(instance,'/api/vision/analyze',{'photo_id':photo['id']});assert status==201
        assert api(instance,'/api/vision/overlay/'+run['id'])[1]==overlay
        status,preview=api(instance,'/api/vision/overlay-preview/'+run['id']);assert status==200
        with Image.open(io.BytesIO(preview)) as image:assert image.size==(640,480)
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


def test_multiview_endpoint_requires_consent_and_maps_photo_provenance(tmp_path,monkeypatch):
    """Fake geometry provider checks wiring; real COLMAP browser run is separate."""
    from products.worldstate_bim import colmap_provider
    def fake(images,names,output_dir,*,calibration=None):
        output_dir.mkdir(parents=True,exist_ok=True)
        return {'schema':'worldstate-bim-geometry-candidate/0.1','provider':'FAKE_TEST_ONLY',
                'status':'UNVERIFIED_RESEARCH_CANDIDATE','inputs':[{'file':n} for n in names],
                'registered_cameras':[{'name':n} for n in names[:3]],'sparse_points':8,
                'scale':{'status':'unknown','unit':'arbitrary'},'timing_seconds':{'total':0}}
    monkeypatch.setattr(colmap_provider,'reconstruct_uncalibrated_images',fake)
    instance=StudioServer(0,None,tmp_path/'sfm-work')
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:
        assert api(instance,'/api/project',{'name':'Synthetic SfM wiring','operator_kind':'automation'})[0]==201
        ids=[]
        for color in ['red','blue','green','yellow']:
            image=Image.new('RGB',(640,480),color);buffer=io.BytesIO();image.save(buffer,format='PNG')
            status,photo=api(instance,'/api/upload',{'data_base64':base64.b64encode(buffer.getvalue()).decode()})
            assert status==201;ids.append(photo['id'])
        assert api(instance,'/api/geometry/reconstruct',{})[0]==400
        status,result=api(instance,'/api/geometry/reconstruct',{'confirmed_same_camera':True})
        assert status==201 and result['provider']=='FAKE_TEST_ONLY' and result['scale']['status']=='unknown'
        assert {x['photo_id'] for x in result['inputs']}==set(ids)
        assert len(result['registered_cameras'])==3
        assert api(instance,'/api/project')[1]['project']['events'][-1]['action']=='geometry_reconstructed'
    finally:
        instance.shutdown();instance.server_close();thread.join()


def test_floor_review_is_auditable_and_blocks_old_fusion(server):
    """A review is new evidence, not a silent rewrite of semantic predictions."""
    import hashlib
    server.model=None;server.model_dir=None
    assert api(server,'/api/project',{'name':'Floor review','operator_kind':'user'})[0]==201
    gid='geometry-'+'a'*32;fid='fusion-'+'b'*32
    server.project['geometry_runs']=[{'id':gid}]
    directory=server.workspace/'fusion'/fid;directory.mkdir(parents=True)
    fusion={'id':fid,'geometry_run_id':gid,'tracks':[{'id':7,'observations':[
        {'semantic_class':3,'photo_sha256':'c'*64,'pixel_xy':[123,456]}]}]}
    raw=json.dumps(fusion).encode();(directory/'fusion.json').write_bytes(raw)
    server.project['fusion_runs']=[{'id':fid,'sha256':hashlib.sha256(raw).hexdigest()}]
    assert api(server,'/api/fusion/floor-review',{'fusion_id':fid,'track_id':8,'decision':'suspect','reason':'chair'})[0]==400
    status,review=api(server,'/api/fusion/floor-review',{'fusion_id':fid,'track_id':7,'decision':'suspect','reason':'可能是椅腿'})
    assert status==201 and review['observations'][0]['photo_sha256']=='c'*64
    status,error=api(server,'/api/fusion/scale',{'fusion_id':fid,'confirmed_endpoints':True})
    assert status==400 and '人工疑点' in error['error']
    assert json.loads((directory/'fusion.json').read_bytes())==fusion
    # Re-running with the same image pixels and a different track ID must not
    # silently discard the review; old cached fusion is rejected as well.
    fid2='fusion-'+'d'*32;newdir=server.workspace/'fusion'/fid2;newdir.mkdir(parents=True)
    newfusion={'id':fid2,'geometry_run_id':gid,'tracks':[{'id':9,'observations':fusion['tracks'][0]['observations']}]}
    newraw=json.dumps(newfusion).encode();(newdir/'fusion.json').write_bytes(newraw)
    server.project['fusion_runs'].append({'id':fid2,'sha256':hashlib.sha256(newraw).hexdigest()})
    status,error=api(server,'/api/fusion/scale',{'fusion_id':fid,'confirmed_endpoints':True})
    assert status==400 and '最新结果' in error['error']
    status,error=api(server,'/api/fusion/scale',{'fusion_id':fid2,'confirmed_endpoints':True})
    assert status==400 and '人工疑点' in error['error']
    assert api(server,'/api/fusion/floor-review',{'fusion_id':fid2,'track_id':9,'decision':'retract','reason':'误报'})[0]==201
    assert len(server.project['floor_reviews'])==2
    assert api(server,'/api/fusion/scale',{'fusion_id':fid2,'confirmed_endpoints':True})[1]['error'].find('人工疑点')==-1
