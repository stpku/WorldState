"""Geometry contracts and an explicitly non-acceptance real-scene regression."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from products.worldstate_bim.multiview_fusion import solve_multiview_scale
from products.worldstate_bim.structure_from_lines import (
    _free_line, _parallel_separation_over_shared_support, build_structure_room,
    solve_lines, triangulate_annotated_corners,
)

ROOT=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room'


def camera(index, center):
    return {'image_id':index,'photo':f'{index}.jpg','sha256':str(index)*64,
      'width_px':640,'height_px':480,'camera_model':'SIMPLE_PINHOLE','intrinsics':[500.,320.,240.],
      'rotation_camera_from_world':np.eye(3).tolist(),
      'translation_camera_from_world':(-np.asarray(center,dtype=float)).tolist(),'center_world':center}


def pixel(cam, point):
    point=np.asarray(point)-np.asarray(cam['center_world']);return [500*point[0]/point[2]+320,500*point[1]/point[2]+240]


def test_multiview_line_uses_backprojection_planes_and_rejects_no_baseline():
    cams={c['image_id']:c for c in [camera(1,[-1.,0.,0.]),camera(2,[1.,0.,0.]),camera(3,[0.,1.,0.])]}
    start=np.array([-.7,.2,6.]);direction=np.array([1.,.3,.1]);direction/=np.linalg.norm(direction)
    support={i:(0,{'image_id':i,'points_px':[pixel(c,start),pixel(c,start+direction)]}) for i,c in cams.items()}
    line=_free_line(support,cams);actual=np.asarray(line['direction'])
    assert abs(actual@direction)==pytest.approx(1.,abs=1e-7)
    assert np.linalg.norm(np.cross(np.asarray(line['point'])-start,direction))<1e-7
    same={i:camera(i,[0.,0.,0.]) for i in cams}
    with pytest.raises(ValueError,match='相机基线为零'):_free_line(support,same)


def test_close_parallel_candidates_are_compared_where_visible_not_at_origin():
    a={'theta_rad':0.,'offset_relative':0.,'visible_support_intervals':[{'range_relative':[0.,10.]}]}
    b={'theta_rad':.1,'offset_relative':.5,'visible_support_intervals':[{'range_relative':[0.,10.]}]}
    assert _parallel_separation_over_shared_support(a,b)==pytest.approx(0.,abs=1e-12)
    b['visible_support_intervals']=[{'range_relative':[100.,110.]}]
    assert _parallel_separation_over_shared_support(a,b) is None


def test_same_corner_clicks_triangulate_but_do_not_force_topology():
    cameras=[camera(1,[-1.,0.,0.]),camera(2,[1.,0.,0.]),camera(3,[0.,1.,0.])]
    fusion={'cameras':cameras,'floor_up':[0.,1.,0.],
            'floor_planes':[{'normal':[0.,1.,0.],'offset':-1.,'fit_rms_arbitrary':.01}]}
    point=[0.,1.,6.];uploads=[{'id':f'photo-{c["image_id"]}','sha256':c['sha256']} for c in cameras]
    annotations=[{'id':f'ann-{i}','photo_id':f'photo-{i}','kind':'corner','object_id':'node-1',
                  'points':[pixel(cameras[i-1],point)],'operator_kind':'user'} for i in (1,2)]
    result=triangulate_annotated_corners(fusion,annotations,uploads)
    assert not result['rejected'] and result['accepted'][0]['xyz']==pytest.approx(point,abs=1e-8)
    assert result['accepted'][0]['status'].startswith('USER_DECLARED')
    assert result['accepted'][0]['topology']=='NOT_APPLIED_REQUIRES_EXPLICIT_ASSOCIATION'
    automated=copy.deepcopy(annotations);automated[0]['operator_kind']='automation'
    assert triangulate_annotated_corners(fusion,automated,uploads)['accepted'][0]['status'].startswith('SCRIPTED_OR_MIXED')
    automated[1]['photo_id']=automated[0]['photo_id']
    assert triangulate_annotated_corners(fusion,automated,uploads)['rejected']


def test_real_development_scene_reports_instability_and_exports_only_consistent_partial_lines(tmp_path):
    """Cached real Eyeful evidence; no independent accuracy or human time is claimed."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
    from products.worldstate_bim.room_ifc import export_room
    from products.worldstate_bim.room_ir import revise_element
    fusion=json.loads((ROOT/'round6/fusion.json').read_text())
    detections=json.loads((ROOT/'round7/detected-lines.json').read_text())
    anchor=json.loads((ROOT/'round6/ifc/anchor-assumed.json').read_text())
    structure=solve_lines(fusion,detections);groups=structure['groups']
    assert [x['support_view_count'] for x in groups[:3]]==[28,13,4]
    assert groups[2]['floor_joint_holdout_status']=='CONFLICT_OR_INSUFFICIENT'
    assert max(x['error_px'] for x in groups[2]['free_line_leave_one_view_out_px'])>100
    assert any(c['floor_consistency']=='CONFLICT_WITH_SPARSE_FLOOR' for c in structure['corner_candidates'])
    kwargs=dict(project_id='test-real-structure',height_m=2.3,height_basis='assumed',
        height_description='test assumption, not a measurement',thickness_m=.12,confirmed_candidates=True,
        allow_assumed_scale=True,operator_kind='automation')
    solution=solve_multiview_scale(fusion,anchor)
    with pytest.raises(ValueError,match='留出视图冲突'):
        build_structure_room(fusion,structure,anchor,solution,[groups[2]['id']],**kwargs)
    model=build_structure_room(fusion,structure,anchor,solution,[x['id'] for x in groups[:2]],**kwargs)
    assert model['mode']=='assisted' and model['validation']['scope']=='PARTIAL_OPEN'
    cached=copy.deepcopy(fusion);source_id=cached['floor_planes'][0]['support_point_ids'][0]
    duplicate=copy.deepcopy(next(t for t in cached['tracks'] if t['id']==source_id));duplicate['id']=9999999
    cached['tracks'].append(duplicate);cached['floor_planes'][0]['support_point_ids'].append(duplicate['id'])
    with pytest.raises(ValueError,match='含重复像素证据'):
        solve_lines(cached,detections)
    with pytest.raises(ValueError,match='含重复像素证据'):
        build_structure_room(cached,structure,anchor,solution,[x['id'] for x in groups[:2]],**kwargs)
    assert model['scale']['independence']=='assumed' and all(e['parameters']['height']['status']=='assumed' for e in model['elements'])
    assert len(model['nodes'])==4 and not model['constraints']
    path=tmp_path/'model.ifc';export_room(model,path);file=ifcopenshell.open(path)
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(file,logger)
    assert file.schema=='IFC4' and len(file.by_type('IfcWall'))==2 and not logger.statements
    assert all(ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),w) for w in file.by_type('IfcWall'))
    changed,_=revise_element(model,model['elements'][0]['id'],'height',2.5,reason='scripted edit',operator='automation')
    revised=ifcopenshell.open(export_room(changed,tmp_path/'revised.ifc'))
    assert {w.GlobalId for w in file.by_type('IfcWall')}=={w.GlobalId for w in revised.by_type('IfcWall')}
    assert model['elements'][0]['id'] and model['evidence'][0]['status']=='scripted_selection_not_human'
    measured={**kwargs,'height_basis':'user_measurement','height_description':'synthetic test measurement'}
    with pytest.raises(ValueError,match='需要记录测量不确定性'):
        build_structure_room(fusion,structure,anchor,solution,[groups[0]['id']],**measured)
    changed_anchor=copy.deepcopy(anchor);changed_anchor['distance_m']*=1.1
    with pytest.raises(ValueError,match='重新求解'):
        build_structure_room(fusion,structure,changed_anchor,solution,[groups[0]['id']],**kwargs)
