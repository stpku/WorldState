"""Synthetic geometry and provenance checks, not real-room validation."""
import copy

import numpy as np
import pytest

from products.worldstate_bim.general_modeler import (
    SCHEMA_INPUT, _project, build_room_ir, camera_digest, solve_modeler,
)


def fixture():
    cameras=[]
    for i,center in enumerate(([-1.,0.,0.],[1.,0.,0.],[0.,1.,0.]),1):
        cameras.append({'image_id':i,'photo':f'{i}.jpg','sha256':str(i)*64,'width_px':640,'height_px':480,
          'camera_model':'SIMPLE_PINHOLE','intrinsics':[500.,320.,240.],
          'rotation_camera_from_world':np.eye(3).tolist(),'translation_camera_from_world':(-np.array(center)).tolist()})
    walls={'west':[[-.5,.5,5.],[.5,.5,5.],[.5,-.5,5.],[-.5,-.5,5.]],
           'north':[[.5,.5,5.],[.5,.5,6.],[.5,-.5,6.],[.5,-.5,5.]]}
    objects=[];observations=[]
    for ident,points in walls.items():
        vertices=['a','b','c','d'];objects.append({'id':ident,'ifc_type':'IfcWall','vertices':vertices,'surface_kind':'visible_surface_patch'})
        for vertex,point in zip(vertices,points):
            for cam in cameras:
                observations.append({'kind':'point','object_id':ident,'feature_id':vertex,'image_id':cam['image_id'],
                    'photo_sha256':cam['sha256'],'camera_sha256':camera_digest(cam),'pixel_xy':_project(np.array(point),cam).tolist(),
                    'origin':'automation','confirmation':'automation_unverified','visibility':'visible','sigma_px':.1,
                    'created_at':'2026-11-15T00:00:00Z'})
    return {'schema':SCHEMA_INPUT,'camera_mode':'SYNTHETIC','coordinate_system':{'name':'test','scale_status':'UNKNOWN'},
            'cameras':cameras,'objects':objects,'observations':observations,'object_constraints':[]}


def test_joint_two_wall_solution_sensitivity_ifc_and_guid(tmp_path):
    import ifcopenshell
    from products.worldstate_bim.room_ifc import export_room
    data=fixture();data['object_constraints']=[{'kind':'perpendicular','a':'west','b':'north',
        'origin':'automation','confirmation':'automation_unverified','created_at':'2026-11-15T00:00:00Z',
        'uncertainty':{'angle_rad':.05},'evidence_refs':[{'object_id':'west','image_id':1},{'object_id':'north','image_id':1}]}]
    for left,right in (('b','a'),('c','d')):
        data['object_constraints'].append({'kind':'coincident','a':'west','b':'north','vertex_a':left,'vertex_b':right,
            'origin':'automation','confirmation':'automation_unverified','created_at':'2026-11-15T00:00:00Z',
            'uncertainty':{'distance_source':.01},'evidence_refs':[{'object_id':'west','image_id':1},{'object_id':'north','image_id':1}]})
    sensitivity={'samples':8,'camera_position_sigma_source':.001,'camera_rotation_sigma_deg':.02,'focal_sigma_fraction':.0001}
    solution=solve_modeler(data,sensitivity=sensitivity)
    assert len(solution['objects'])==2 and solution['optimization']['point_max_px']<1e-5
    assert solution['sensitivity']['modes']['combined']['attempted']==8
    assert all(v['accepted']<=8 for v in solution['sensitivity']['modes']['combined']['vertices'])
    model=build_room_ir(data,solution,project_id='synthetic',scale={'basis':'assumed','metres_per_source_unit':1.},
        thickness_m=.1,up_source=[0,-1,0],allow_rectangular_approximation=True)
    assert len(model['elements'])==2 and model['constraints']==[]
    assert model['scale']['independent_measurement'] is False and model['validation']['scope']=='PARTIAL_OPEN'
    path=export_room(model,tmp_path/'model.ifc');file=ifcopenshell.open(str(path))
    assert len(file.by_type('IfcWall'))==2
    changed=copy.deepcopy(data);changed['observations'][0]['pixel_xy'][0]+=.1
    with pytest.raises(ValueError,match='changed; solve again'):
        build_room_ir(changed,solution,project_id='synthetic',scale={'basis':'assumed','metres_per_source_unit':1.},
            thickness_m=.1,up_source=[0,-1,0],allow_rectangular_approximation=True)


def test_polygon_is_not_forced_to_rectangular_ifc_and_camera_versions_are_bound():
    data=fixture();data['objects']=data['objects'][:1];data['objects'][0]['vertices']=['a','b','c']
    data['observations']=[o for o in data['observations'] if o['object_id']=='west' and o['feature_id']!='d']
    solution=solve_modeler(data);assert len(solution['objects'][0]['vertices'])==3
    with pytest.raises(ValueError,match='four-vertex candidate'):
        build_room_ir(data,solution,project_id='partial',scale={'basis':'assumed','metres_per_source_unit':1.},
            thickness_m=.1,up_source=[0,-1,0],allow_rectangular_approximation=True)
    wrong=copy.deepcopy(data);wrong['cameras'][0]['intrinsics'][0]+=1
    with pytest.raises(ValueError,match='camera version mismatch'):solve_modeler(wrong)
    wrong=copy.deepcopy(data);wrong['observations'][0]['confirmation']='user_confirmed'
    with pytest.raises(ValueError,match='cannot be human confirmed'):solve_modeler(wrong)


def test_duplicate_pixels_and_unsupported_topology_do_not_create_extra_walls():
    data=fixture()
    with pytest.raises(ValueError,match='same image pixel'):
        solve_modeler(data)  # The fixture shares a physical corner but has no explicit association.
    data['objects']=data['objects'][:1];data['observations']=[o for o in data['observations'] if o['object_id']=='west']
    data['object_constraints']=[{'kind':'unrecognized','a':'west','b':'missing'}]
    with pytest.raises(ValueError,match='unsupported object constraint'):
        solve_modeler(data)


def test_narrow_baseline_exposes_larger_pixel_sensitivity_despite_small_reprojection():
    points={'a':[-.5,.5,5.],'b':[.5,.5,5.],'c':[.5,-.5,5.],'d':[-.5,-.5,5.]}
    def solve(baseline):
        data=fixture();data['objects']=data['objects'][:1];data['cameras']=data['cameras'][:2]
        for cam,position in zip(data['cameras'],(-baseline/2,baseline/2)):
            cam['translation_camera_from_world']=[-position,0.,0.]
        by_id={c['image_id']:c for c in data['cameras']}
        data['observations']=[o for o in data['observations'] if o['object_id']=='west' and o['image_id'] in by_id]
        for obs in data['observations']:
            cam=by_id[obs['image_id']];obs['camera_sha256']=camera_digest(cam)
            obs['pixel_xy']=_project(np.array(points[obs['feature_id']]),cam).tolist()
        return solve_modeler(data,sensitivity={'samples':48,'camera_position_sigma_source':0.,
                             'camera_rotation_sigma_deg':0.,'focal_sigma_fraction':0.})
    wide,narrow=solve(2.),solve(.16)
    assert wide['optimization']['point_max_px']<1e-6 and narrow['optimization']['point_max_px']<1e-6
    w=wide['sensitivity']['modes']['pixel_only']['vertices'][0]['p90_displacement_source_units']
    n=narrow['sensitivity']['modes']['pixel_only']['vertices'][0]['p90_displacement_source_units']
    assert n>5*w


def test_generic_edge_to_line_marks_inferred_vertices_and_preserves_evidence(tmp_path):
    from products.worldstate_bim.tests.test_model_first import scene
    from products.worldstate_bim.room_ifc import export_room
    legacy,_=scene();cameras={c['image_id']:c for c in legacy['cameras']};observations=[]
    for old,new in (('left_top','p1'),('right_top','p2'),('right_bottom','p5')):
        for o in legacy['corners'][old]:
            observations.append({**o,'kind':'point','object_id':'patch','feature_id':new,
                'camera_sha256':camera_digest(cameras[o['image_id']]),'origin':'automation',
                'confirmation':'automation_unverified','visibility':'visible','sigma_px':1.,'created_at':'test'})
    for o in legacy['ceiling_lines']:
        observations.append({**o,'kind':'line','object_id':'patch','feature_ids':['p3','p4'],
            'camera_sha256':camera_digest(cameras[o['image_id']]),'origin':'automation',
            'confirmation':'automation_unverified','visibility':'visible','sigma_px':1.,'created_at':'test'})
    data={'schema':SCHEMA_INPUT,'camera_mode':'test','coordinate_system':{'scale_status':'UNKNOWN'},
        'source_reconstruction':[],'cameras':legacy['cameras'],'objects':[{'id':'patch','ifc_type':'IfcWall',
        'vertices':['p1','p2','p3','p4'],'surface_kind':'visible_surface_patch',
        'construction':{'kind':'edge_to_line','direction_feature':'p5'}}],'observations':observations,'object_constraints':[]}
    solution=solve_modeler(data);vertices=solution['objects'][0]['vertices']
    assert [v['status'] for v in vertices]==['triangulated_observation','triangulated_observation',
                                               'inferred_line_intersection','inferred_line_intersection']
    model=build_room_ir(data,solution,project_id='edge-test',scale={'basis':'assumed','metres_per_source_unit':1.},
                        thickness_m=.1,up_source=[0,-1,0],allow_rectangular_approximation=True)
    assert any('inferred' in text for text in model['elements'][0]['unknown'])
    assert export_room(model,tmp_path/'model.ifc').is_file()


def test_existing_edge_patch_and_new_polygon_share_frame_without_implied_topology():
    from products.worldstate_bim.tests.test_model_first import scene
    legacy,_=scene();cameras={c['image_id']:c for c in legacy['cameras']};observations=[]
    for old,new in (('left_top','p1'),('right_top','p2'),('right_bottom','p5')):
        for o in legacy['corners'][old]:
            observations.append({**o,'kind':'point','object_id':'existing','feature_id':new,
                'camera_sha256':camera_digest(cameras[o['image_id']]),'origin':'automation',
                'confirmation':'automation_unverified','visibility':'visible','sigma_px':1.,'created_at':'test'})
    for o in legacy['ceiling_lines']:
        observations.append({**o,'kind':'line','object_id':'existing','feature_ids':['p3','p4'],
            'camera_sha256':camera_digest(cameras[o['image_id']]),'origin':'automation',
            'confirmation':'automation_unverified','visibility':'visible','sigma_px':1.,'created_at':'test'})
    polygon=[np.array(p)+np.array([.3,0.,0.]) for p in ([.5,.5,5.],[.5,.5,6.],[.5,-.5,6.],[.5,-.5,5.])]
    for vertex,point in zip(['a','b','c','d'],polygon):
        for cam in cameras.values():
            observations.append({'kind':'point','object_id':'new','feature_id':vertex,'image_id':cam['image_id'],
                'photo_sha256':cam['sha256'],'camera_sha256':camera_digest(cam),'pixel_xy':_project(point,cam).tolist(),
                'origin':'automation','confirmation':'automation_unverified','visibility':'visible','sigma_px':1.,'created_at':'test'})
    data={'schema':SCHEMA_INPUT,'camera_mode':'test','coordinate_system':{'scale_status':'UNKNOWN'},
        'source_reconstruction':[],'cameras':legacy['cameras'],'objects':[
            {'id':'existing','ifc_type':'IfcWall','vertices':['p1','p2','p3','p4'],'surface_kind':'visible_surface_patch',
             'construction':{'kind':'edge_to_line','direction_feature':'p5'}},
            {'id':'new','ifc_type':'IfcWall','vertices':['a','b','c','d'],'surface_kind':'visible_surface_patch'}],
        'observations':observations,'object_constraints':[]}
    solution=solve_modeler(data)
    assert {o['id'] for o in solution['objects']}=={'existing','new'}
    assert 'independent per-object' in solution['optimization']['method']
    model=build_room_ir(data,solution,project_id='mixed',scale={'basis':'assumed','metres_per_source_unit':1.},
                        thickness_m=.1,up_source=[0,-1,0],allow_rectangular_approximation=True)
    assert len(model['elements'])==2 and model['constraints']==[]


def test_existing_multiview_metric_anchor_is_actually_applied():
    data=fixture();data['objects']=data['objects'][:1];data['observations']=[o for o in data['observations'] if o['object_id']=='west']
    solution=solve_modeler(data)
    ends=[]
    for vertex in ('a','b'):
        observations=[{'image_id':o['image_id'],'photo_sha256':o['photo_sha256'],'pixel_xy':o['pixel_xy']}
                      for o in data['observations'] if o['feature_id']==vertex]
        ends.append({'id':vertex,'observations':observations})
    anchor={'schema':'worldstate-multiview-scale-anchor/0.1','basis':'independent_user_declared','confirmed':True,
        'distance_m':2.,'measurement_uncertainty_m':.01,'description':'synthetic test reference', 'endpoints':ends}
    model=build_room_ir(data,solution,project_id='anchor',scale=anchor,thickness_m=.1,
                        up_source=[0,-1,0],allow_rectangular_approximation=True)
    assert model['coordinate_system']['source_to_metres']==pytest.approx(2.)
    assert model['scale']['independent_measurement']=='DECLARED_NOT_INDEPENDENTLY_VERIFIED'
