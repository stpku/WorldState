"""Synthetic contract checks; real-photo browser runs are recorded separately."""
import copy
import math
import pytest
from products.worldstate_bim.photo_room import build_photo_room
from products.worldstate_bim.photo_scale import bind_scale


def fixture():
    uploads=[{"id":"upload-"+c*16,"sha256":c*64,"width":640,"height":480,"captured_at":"UNKNOWN"} for c in "ab"]
    annotations=[]
    for i in range(1,4):
        annotations.append({"id":"ann-"+str(i)*32,"photo_id":uploads[(i-1)%2]["id"],"kind":"wall_boundary",
                            "wall_id":f"wall-{i}","points":[[20,30],[120,100]],"elapsed_ms":2000})
    annotations.append({"id":"ann-"+"4"*32,"photo_id":uploads[0]["id"],"kind":"window","wall_id":"wall-1",
                        "points":[[30,40],[80,90]],"object_id":"window-1","dimensions":{
                            "basis":"assumed","offset":1,"width":1,"height":1.2,"sill":1,"panel_thickness":0.04}})
    annotations.append({"id":"ann-"+"a"*32,"photo_id":uploads[0]["id"],"kind":"scale","wall_id":"wall-1","points":[[20,100],[120,100]]})
    project={"id":"photo-room-"+"a"*32,"annotations":annotations,
             "layout":{"points":[[20,20],[220,20],[220,170],[60,170]],"closed":False,"confirmed_schematic":True},
             "reference":{"wall_index":1,"length_m":4,"basis":"independent_user_declared","description":"user ruler",
                          "height_m":2.8,"height_basis":"user_measurement","thickness_m":0.12}}
    project["scale_binding"]=bind_scale(project,uploads,confirmed=True)
    return project,uploads


def test_schematic_scale_is_applied_and_never_treated_as_photo_geometry():
    project,uploads=fixture();model=build_photo_room(project,uploads)
    nodes=model["nodes"]
    assert math.dist((nodes[0]["x"],nodes[0]["y"]),(nodes[1]["x"],nodes[1]["y"]))==pytest.approx(4)
    assert model["scale"]["status"]=="applied" and model["validation"]["scope"]=="PARTIAL_OPEN"
    assert len([e for e in model["elements"] if e["ifc_type"]=="IfcWall"])==3
    assert all(n["status"]=="inferred" for n in nodes)
    project["reference"]["length_m"]=8
    with pytest.raises(ValueError,match="尺度参照已失效"):build_photo_room(project,uploads)
    project["scale_binding"]=bind_scale(project,uploads,confirmed=True)
    changed=build_photo_room(project,uploads)
    assert changed["nodes"][1]["x"]==pytest.approx(nodes[1]["x"]*2)
    project["layout"]["points"][2][1]+=50
    changed_layout=build_photo_room(project,uploads)
    assert changed_layout["nodes"][2]["y"]!=changed["nodes"][2]["y"]


def test_photo_association_changes_evidence_without_inventing_image_depth():
    project,uploads=fixture();before=build_photo_room(project,uploads)
    project["annotations"][0]["photo_id"]=uploads[1]["id"]
    after=build_photo_room(project,uploads)
    assert before["nodes"]==after["nodes"]
    a=next(x for x in before["evidence"] if x["id"]==project["annotations"][0]["id"])
    b=next(x for x in after["evidence"] if x["id"]==a["id"])
    assert a["photo_ref"]!=b["photo_ref"]


def test_missing_constraints_or_visibility_fail_closed():
    project,uploads=fixture();project["reference"]["length_m"]=None
    with pytest.raises(ValueError,match="尺度参照长度"):build_photo_room(project,uploads)
    project,uploads=fixture();project["annotations"]=[a for a in project["annotations"] if a["wall_id"]!="wall-3"]
    with pytest.raises(ValueError,match="wall-3"):build_photo_room(project,uploads)
    project,uploads=fixture();project["layout"]["confirmed_schematic"]=False
    with pytest.raises(ValueError,match="人工估计"):build_photo_room(project,uploads)


def test_camera_floor_backprojection_uses_photo_corners_and_metric_anchor():
    project,uploads=fixture();fx=fy=525.;cx=319.5;cy=239.5;pitch=20.;camera_height=1.5
    angle=math.radians(pitch);s,c=math.sin(angle),math.cos(angle)
    # Synthetic ground truth is projected through a known pinhole camera.
    ground=[(-1.,2.),(1.,2.),(1.,4.),(-1.,4.)]
    for i,(x,y) in enumerate(ground,1):
        depth=c*y+s*camera_height
        u=fx*x/depth+cx;v=fy*(-s*y+c*camera_height)/depth+cy
        project["annotations"].append({"id":"ann-"+f"{i+4:x}"*32,"photo_id":uploads[0]["id"],
            "kind":"corner","wall_id":f"wall-{min(i,3)}","object_id":f"node-{i}","points":[[u,v]]})
    project["layout"]={"mode":"photo_floor","photo_id":uploads[0]["id"],"closed":False,
        "confirmed_camera_assumptions":True,"camera":{"fx":fx,"fy":fy,"cx":cx,"cy":cy,
        "pitch_down_deg":pitch,"description":"synthetic known calibration"}}
    project["reference"]["length_m"]=2
    project["scale_binding"]=bind_scale(project,uploads,confirmed=True)
    model=build_photo_room(project,uploads)
    for node,(x,y) in zip(model["nodes"],ground):
        assert node["x"]==pytest.approx(x-ground[0][0],abs=1e-10)
        assert node["y"]==pytest.approx(y-ground[0][1],abs=1e-10)
    assert model["scale"]["metres_per_relative_unit"]==pytest.approx(camera_height)
    project["annotations"][-1]["points"][0][0]+=10
    shifted=build_photo_room(project,uploads)
    assert shifted["nodes"][-1]["x"]!=pytest.approx(model["nodes"][-1]["x"])
    project["layout"]["camera"]["pitch_down_deg"]=-40
    with pytest.raises(ValueError,match="地平线"):build_photo_room(project,uploads)


def test_photo_candidate_exports_native_ifc_and_retains_open_space(tmp_path):
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
    from products.worldstate_bim.room_ifc import export_room
    project,uploads=fixture();model=build_photo_room(project,uploads)
    f=ifcopenshell.open(str(export_room(model,tmp_path/"model.ifc")))
    assert len(f.by_type("IfcWall"))==3 and len(f.by_type("IfcWindow"))==1
    assert len(f.by_type("IfcOpeningElement"))==len(f.by_type("IfcRelVoidsElement"))==len(f.by_type("IfcRelFillsElement"))==1
    assert not f.by_type("IfcSpace") and all(ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),w) for w in f.by_type("IfcWall"))
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger);assert not logger.statements


def test_scale_binding_rejects_changed_endpoint_or_anchor_association():
    project, uploads = fixture()
    scale = next(a for a in project['annotations'] if a['kind'] == 'scale')
    scale['points'][1][0] += 10
    with pytest.raises(ValueError, match='尺度参照已失效'):
        build_photo_room(project, uploads)
    with pytest.raises(ValueError, match='物理端点'):
        bind_scale(project, uploads, confirmed=False)
    # An explicit attestation is required; it does not claim independent truth.
    project['scale_binding'] = bind_scale(project, uploads, confirmed=True)
    assert build_photo_room(project, uploads)['scale']['independence'] == 'independent_user_declared'
    scale['photo_id'] = uploads[1]['id']
    with pytest.raises(ValueError, match='尺度参照已失效'):
        build_photo_room(project, uploads)


def test_camera_scale_binding_is_invalidated_when_calibration_changes():
    project, uploads = fixture()
    project['layout'] = {'mode':'photo_floor', 'photo_id':uploads[0]['id'], 'closed':False,
        'confirmed_camera_assumptions':True,
        'camera':{'fx':525,'fy':525,'cx':319,'cy':239,'pitch_down_deg':20,'description':'test'}}
    for i, point in enumerate(([250,330], [400,330], [400,400], [250,400]), 1):
        project['annotations'].append({'id':'ann-'+f'{i+4:x}'*32,'photo_id':uploads[0]['id'],
            'kind':'corner','wall_id':f'wall-{min(i,3)}','object_id':f'node-{i}','points':[list(point)]})
    project['scale_binding'] = bind_scale(project,uploads,confirmed=True)
    build_photo_room(project,uploads)
    project['layout']['camera']['fx'] = 530
    with pytest.raises(ValueError, match='尺度参照已失效'):
        build_photo_room(project,uploads)
    project['layout']['camera']['fx'] = 525
    project['annotations'][-3]['points'][0][0] += 1
    with pytest.raises(ValueError, match='尺度参照已失效'):
        build_photo_room(project,uploads)
