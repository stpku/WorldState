"""Synthetic contract checks; no claims about ETH3D or engineering accuracy."""
import copy
import base64

import numpy as np
import pytest

from products.worldstate_bim.model_first import _project, build_local_wall_ir, project_local_wall_ir, solve_local_wall
from products.worldstate_bim.room_ifc import export_room
from products.worldstate_bim.room_ir import revise_element


def scene():
    cameras=[]
    for index,center in enumerate(([-1.,0.,0.],[1.,0.,0.],[0.,1.,0.]),1):
        cameras.append({'image_id':index,'photo':f'{index}.jpg','sha256':str(index)*64,
            'width_px':640,'height_px':480,'camera_model':'SIMPLE_PINHOLE','intrinsics':[500.,320.,240.],
            'rotation_camera_from_world':np.eye(3).tolist(),
            'translation_camera_from_world':(-np.asarray(center)).tolist()})
    points={'left_top':[-.5,-.5,5.], 'right_top':[.5,-.5,5.], 'right_bottom':[.5,.5,5.]}
    observations={key:[{'image_id':c['image_id'],'photo_sha256':c['sha256'],
        'pixel_xy':_project(np.asarray(point),c).tolist()} for c in cameras] for key,point in points.items()}
    lines=[{'image_id':c['image_id'],'photo_sha256':c['sha256'],
            'points_px':[_project(np.array(p),c).tolist() for p in ([-.7,-1.,5.],[.7,-1.,5.])]} for c in cameras]
    data={'schema':'worldstate-local-wall-observations/0.1','operator':'automation_synthetic_test',
          'camera_mode':'ETH3D_KNOWN_POSE_SCANNER_REGISTERED_NOT_PHOTO_ONLY',
          'source_reconstruction':[], 'cameras':cameras,'corners':observations,'ceiling_lines':lines}
    pix={'schema':'worldstate-pixcuboid-candidate/0.1','output':{'R_world_to_cuboid':[[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]],
          'plane_offsets':[4.5,-2.,-1.5,7.,2.,2.]}}
    return data,pix


def test_independent_local_patch_optimizes_observations_and_exports_assumptions(tmp_path):
    import ifcopenshell
    data,pix=scene();solution=solve_local_wall(data,pix)
    assert solution['width_source_units']==pytest.approx(1.,abs=1e-5)
    assert solution['height_source_units']==pytest.approx(.5,abs=1e-5)
    assert solution['before']['rms_px']>solution['after']['rms_px']
    kwargs={'project_id':'synthetic-local-wall','assumed_scale':1.,'assumed_thickness_m':.1,'allow_assumed':True}
    model=build_local_wall_ir(data,solution,**kwargs)
    assert model['validation']['scope']=='PARTIAL_OPEN'
    assert model['scale']['status']=='assumed' and not model['scale']['independent_measurement']
    assert model['elements'][0]['parameters']['thickness']['status']=='assumed'
    assert 'metric scale not independently measured' in model['elements'][0]['unknown']
    first=ifcopenshell.open(str(export_room(model,tmp_path/'first.ifc')))
    scaled=build_local_wall_ir(data,solution,**{**kwargs,'assumed_scale':2.})
    assert scaled['nodes'][1]['x']==pytest.approx(2*model['nodes'][1]['x'])
    assert scaled['elements'][0]['parameters']['height']['value']==pytest.approx(2*model['elements'][0]['parameters']['height']['value'])
    second=ifcopenshell.open(str(export_room(scaled,tmp_path/'second.ifc')))
    assert first.by_type('IfcWall')[0].GlobalId==second.by_type('IfcWall')[0].GlobalId
    with pytest.raises(ValueError,match='explicitly allowed'):
        build_local_wall_ir(data,solution,**{**kwargs,'allow_assumed':False})


def test_stale_observations_bad_correspondence_and_hash_mismatch_fail_closed():
    data,pix=scene();solution=solve_local_wall(data,pix)
    changed=copy.deepcopy(data);changed['corners']['left_top'][0]['pixel_xy'][0]+=1
    with pytest.raises(ValueError,match='solve the candidate again'):
        build_local_wall_ir(changed,solution,project_id='stale',assumed_scale=1.,assumed_thickness_m=.1,allow_assumed=True)
    wrong=copy.deepcopy(data);wrong['corners']['left_top'][0]['pixel_xy'][1]+=100
    with pytest.raises(ValueError,match='重投影'):
        solve_local_wall(wrong,pix)
    wrong=copy.deepcopy(data);wrong['ceiling_lines'][0]['photo_sha256']='f'*64
    with pytest.raises(ValueError,match='hash mismatch'):
        solve_local_wall(wrong,pix)


def test_weak_or_degenerate_evidence_is_not_filled_by_cuboid_prior():
    data,pix=scene();weak=copy.deepcopy(data)
    weak['ceiling_lines']=weak['ceiling_lines'][:1]
    with pytest.raises(ValueError,match='at least two ceiling'):
        solve_local_wall(weak,pix)
    weak=copy.deepcopy(data)
    for camera in weak['cameras'][1:]:
        camera['translation_camera_from_world']=weak['cameras'][0]['translation_camera_from_world']
    with pytest.raises(ValueError,match='退化|视差|重投影'):
        solve_local_wall(weak,pix)


def test_direct_solver_does_not_require_a_cuboid_or_global_floor_and_projection_tracks_revisions():
    data,_=scene();data['camera_mode']='KNOWN_POSE_UNVERIFIED'
    solution=solve_local_wall(data)
    assert solution['pixcuboid_prior_face'] is None
    assert solution['optimization']['initialization']=='triangulated_corners_and_image_lines'
    model=build_local_wall_ir(data,solution,project_id='projection',assumed_scale=1.,assumed_thickness_m=.1,allow_assumed=True)
    before=project_local_wall_ir(model)
    assert before['revision']==1 and len(before['views'])==3
    assert max(view['rms_px'] for view in before['views'])<1e-5
    revised,_=revise_element(model,'wall-above-opening','height',.65,reason='synthetic edit',operator='automation')
    after=project_local_wall_ir(revised)
    assert after['revision']==2 and max(view['rms_px'] for view in after['views'])>1
    assert before['views'][0]['polygon_px']!=after['views'][0]['polygon_px']


def test_correlated_semantic_pixels_are_one_soft_term_per_view_and_hash_bound():
    data,_=scene();cam=data['cameras'][0]
    view={'image_id':cam['image_id'],'photo_sha256':cam['sha256'],'shape':[128,128],
          'label':'wall_ADE20K_0','wall_mask_packbits_base64':base64.b64encode(bytes([255])*2048).decode()}
    data['semantic_views']=[view]
    solution=solve_local_wall(data)
    assert len(solution['semantic_after'])==1 and solution['semantic_after'][0]['samples']==25
    assert solution['semantic_after'][0]['sampled_mask_wall_fraction']==pytest.approx(1.)
    assert 'one uncalibrated' in solution['optimization']['semantic_term']
    bad=copy.deepcopy(data);bad['semantic_views'][0]['photo_sha256']='0'*64
    with pytest.raises(ValueError,match='semantic view'):
        solve_local_wall(bad)
