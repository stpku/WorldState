"""Numerical and evidence contracts; these synthetic tests are not real-room measurements."""
import copy
import math
import numpy as np
import pytest
from products.worldstate_bim.multiview_fusion import (
    apply_multiview_scale, plane_intersection, solve_multiview_scale, triangulate_observations,
)


def scene():
    cameras=[]
    for i,center in enumerate(([-1.,0.,0.],[1.,0.,0.],[0.,1.,0.]),1):
        cameras.append({'image_id':i,'photo':f'p{i}.jpg','sha256':str(i)*64,'width_px':640,'height_px':480,
          'camera_model':'SIMPLE_PINHOLE','intrinsics':[500.,320.,240.],
          'rotation_camera_from_world':np.eye(3).tolist(),'translation_camera_from_world':(-np.asarray(center)).tolist(),
          'center_world':center})
    def obs(point):
        out=[]
        for c in cameras:
            x,y,z=np.asarray(point)-c['center_world'];out.append({'image_id':c['image_id'],'photo_sha256':c['sha256'],
                                                                     'pixel_xy':[500*x/z+320,500*y/z+240]})
        return out
    a,b=[0.,0.,5.],[2.,0.,5.]
    anchor={'schema':'worldstate-multiview-scale-anchor/0.1','confirmed':True,'basis':'independent_user_declared',
        'distance_m':3.,'measurement_uncertainty_m':.01,'description':'synthetic measured reference',
        'endpoints':[{'id':'a','observations':obs(a)},{'id':'b','observations':obs(b)}]}
    plane={'normal':[0.,1.,0.],'offset':-2.,'centroid':[1.,2.,3.],
           'fit_rms_arbitrary':.02,'fit_threshold_arbitrary':.1}
    surface={**plane,'visible_candidate':{'floor_line_start':[0.,2.,0.],'floor_line_end':[2.,2.,0.],
                                         'visible_height_range_arbitrary':[0.,2.]}}
    fusion={'coordinate_system':{'name':'COLMAP world','unit':'arbitrary','scale_status':'UNKNOWN'},'cameras':cameras,
        'tracks':[{'xyz':[2.,2.,2.]}],'floor_planes':[plane],'ceiling_planes':[],
        'raw_wall_planes':[],'wall_surfaces':[surface],
        'floor_wall_intersections':[{'point':[2.,2.,2.],'direction':[1.,0.,0.],'visible_extent_arbitrary':[0.,2.]}],
        'wall_junctions':[{'xyz':[2.,2.,2.]}],'limitations':[]}
    return fusion,anchor,obs


def test_triangulates_corresponding_observations_and_applies_scale_everywhere():
    fusion,anchor,_=scene();sol=solve_multiview_scale(fusion,anchor)
    assert sol['metres_per_sfm_unit']==pytest.approx(1.5)
    assert sol['endpoint_solutions'][0]['xyz']==pytest.approx([0,0,5],abs=1e-8)
    assert sol['endpoint_solutions'][0]['max_reprojection_error_px']<1e-8
    scaled=apply_multiview_scale(fusion,anchor,sol)
    assert scaled['coordinate_system']['unit']=='m'
    assert scaled['cameras'][0]['center_world']==pytest.approx([-1.5,0,0])
    assert scaled['cameras'][0]['translation_camera_from_world']==pytest.approx([1.5,0,0])
    assert scaled['tracks'][0]['xyz']==pytest.approx([3,3,3])
    assert scaled['floor_planes'][0]['offset']==pytest.approx(-3)
    assert scaled['floor_planes'][0]['fit_rms_m']==pytest.approx(.03)
    assert scaled['wall_surfaces'][0]['visible_candidate']['visible_height_range_m']==pytest.approx([0,3])
    assert scaled['floor_wall_intersections'][0]['visible_extent_m']==pytest.approx([0,3])
    assert scaled['wall_junctions'][0]['xyz']==pytest.approx([3,3,3])
    assert scaled['cameras'][0]['intrinsics']==fusion['cameras'][0]['intrinsics']


def test_stale_scale_is_rejected_and_changed_correspondence_retriangulates():
    fusion,anchor,obs=scene();sol=solve_multiview_scale(fusion,anchor)
    changed=copy.deepcopy(anchor);changed['distance_m']=6
    with pytest.raises(ValueError,match='重新求解'):apply_multiview_scale(fusion,changed,sol)
    assert solve_multiview_scale(fusion,changed)['metres_per_sfm_unit']==pytest.approx(3)
    changed=copy.deepcopy(anchor);changed['endpoints'][1]['observations']=obs([1.,0.,5.])
    with pytest.raises(ValueError,match='重新求解'):apply_multiview_scale(fusion,changed,sol)
    assert solve_multiview_scale(fusion,changed)['metres_per_sfm_unit']==pytest.approx(3)
    changed_fusion=copy.deepcopy(fusion);changed_fusion['cameras'][0]['translation_camera_from_world'][0]+=.1
    with pytest.raises(ValueError,match='重新求解'):apply_multiview_scale(changed_fusion,anchor,sol)
    two_view_anchor=copy.deepcopy(anchor)
    for endpoint in two_view_anchor['endpoints']:endpoint['observations']=endpoint['observations'][:2]
    two_view_solution=solve_multiview_scale(fusion,two_view_anchor)
    changed_fusion=copy.deepcopy(fusion);changed_fusion['cameras'][2]['translation_camera_from_world'][0]+=.1
    with pytest.raises(ValueError,match='重新求解'):apply_multiview_scale(changed_fusion,two_view_anchor,two_view_solution)


def test_wrong_correspondence_missing_measurement_and_degenerate_rays_fail_closed():
    fusion,anchor,_=scene();bad=copy.deepcopy(anchor)
    bad['endpoints'][1]['observations'][0]['pixel_xy'][1]+=100
    with pytest.raises(ValueError,match='重投影'):solve_multiview_scale(fusion,bad)
    bad=copy.deepcopy(anchor);bad['measurement_uncertainty_m']=None
    with pytest.raises(ValueError,match='不确定性'):solve_multiview_scale(fusion,bad)
    bad=copy.deepcopy(anchor);bad['endpoints'][0]['observations'][1]['image_id']=bad['endpoints'][0]['observations'][0]['image_id']
    with pytest.raises(ValueError,match='不同的已注册照片'):solve_multiview_scale(fusion,bad)
    bad=copy.deepcopy(anchor);bad['endpoints'][0]['observations'][0]['photo_sha256']='0'*64
    with pytest.raises(ValueError,match='哈希'):solve_multiview_scale(fusion,bad)
    identical=copy.deepcopy(fusion['cameras']);identical[1]['translation_camera_from_world']=identical[0]['translation_camera_from_world']
    with pytest.raises(ValueError,match='退化|视差'):
        triangulate_observations(identical,anchor['endpoints'][0]['observations'][:2])


def test_plane_intersection_is_in_3d_and_parallel_planes_do_not_invent_line():
    a={'normal':[1.,0.,0.],'offset':-2.};b={'normal':[0.,0.,1.],'offset':-3.}
    line=plane_intersection(a,b)
    assert line['point']==pytest.approx([2,0,3]);assert abs(line['direction'][1])==pytest.approx(1)
    assert plane_intersection(a,{'normal':[1.,0.,0.],'offset':-2.1}) is None


def test_real_removed_photo_reconstruction_updates_evidence_and_matches_surface_identity():
    """Real Eyeful development data; no independent wall accuracy is implied."""
    import json
    from pathlib import Path
    from products.worldstate_bim.multiview_fusion import associate_surface_identities
    root=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room/round6'
    before=json.loads((root/'fusion.json').read_text());after=json.loads((root/'fusion-remove-photo.json').read_text())
    photo='19_DSC0541.jpg'
    assert any(o['photo']==photo for t in before['tracks'] for o in t['observations'])
    assert all(o['photo']!=photo for t in after['tracks'] for o in t['observations'])
    association=associate_surface_identities(before,after)
    assert any(m['previous_surface_id']=='surface-4d70e4bffc47b76b' and m['shared_views']>=3 for m in association['matches'])
    assert any(m['previous_surface_id']=='surface-67c8391fca7258ec' and m['shared_views']>=3 for m in association['matches'])
    assert association['unmatched_previous']  # Weak candidates must not be silently assigned an identity.


def test_real_multiview_scale_counterfactual_invalidates_old_solution():
    """Real image tracks plus explicitly assumed, non-independent development scale."""
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room/round6'
    fusion=json.loads((root/'fusion.json').read_text());anchor=json.loads((root/'ifc/anchor-assumed.json').read_text())
    old=solve_multiview_scale(fusion,anchor);changed=copy.deepcopy(anchor);changed['distance_m']*=1.2
    with pytest.raises(ValueError,match='重新求解'):apply_multiview_scale(fusion,changed,old)
    new=solve_multiview_scale(fusion,changed)
    assert new['metres_per_sfm_unit']/old['metres_per_sfm_unit']==pytest.approx(1.2)
    assert old['basis']=='assumed' and old['measurement_uncertainty_m'] is None


def test_near_coplanar_overlapping_fragments_merge_provisionally_but_separate_planes_remain():
    from products.worldstate_bim.multiview_fusion import _combine_wall_planes
    tracks={};planes=[];pid=1
    for idx,x in enumerate((0.,.03,1.),1):
        ids=[]
        for y,z in ((0,0),(2,0),(0,2),(2,2)):
            tracks[pid]={'xyz':[x,y,z],'semantic_class':0,'observations':[
                {'image_id':v,'usable':True,'semantic_class':0,'pixel_xy':[10+y,20+z],
                 'photo':f'{v}.jpg','photo_sha256':str(v)*64} for v in (1,2,3)]}
            ids.append(pid);pid+=1
        planes.append({'id':f'p{idx}','normal':[1.,0.,0.],'offset':-x,'centroid':[x,1.,1.],
                       'support_point_ids':ids,'support_views':[1,2,3]})
    result=_combine_wall_planes(planes,tracks,.1,np.array([0.,0.,1.]))
    assert len(result)==2
    assert result[0]['raw_plane_ids']==['p1','p2']
    assert result[0]['association']=='PROVISIONAL_MERGE_IDENTITY_UNCONFIRMED'
    assert result[1]['raw_plane_ids']==['p3']


def test_real_near_duplicate_candidates_cannot_be_exported_as_distinct_walls():
    import json
    from pathlib import Path
    from products.worldstate_bim.multiview_fusion import build_multiview_room
    root=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room/round6'
    fusion=json.loads((root/'fusion.json').read_text());anchor=json.loads((root/'ifc/anchor-assumed.json').read_text())
    solution=solve_multiview_scale(fusion,anchor);pair=fusion['ambiguous_surface_pairs'][0]['surfaces']
    with pytest.raises(ValueError,match='可能重复'):
        build_multiview_room(fusion,anchor,solution,pair,project_id='test-project',assumed_thickness_m=.12,
                             confirmed_candidates=True,allow_assumed_scale=True,operator_kind='automation')


def test_scripted_candidate_confirmation_is_assisted_not_automatic_modeling():
    import json
    from pathlib import Path
    from products.worldstate_bim.multiview_fusion import build_multiview_room
    root=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room/round6'
    fusion=json.loads((root/'fusion.json').read_text());anchor=json.loads((root/'ifc/anchor-assumed.json').read_text())
    solution=solve_multiview_scale(fusion,anchor)
    model=build_multiview_room(fusion,anchor,solution,['surface-4d70e4bffc47b76b','surface-67c8391fca7258ec'],
        project_id='test-project',assumed_thickness_m=.12,confirmed_candidates=True,
        allow_assumed_scale=True,operator_kind='automation')
    assert model['mode']=='assisted'
    assert model['evidence'][0]['status']=='scripted_selection_not_human'


def test_floor_support_counts_exact_multiview_duplicate_pixels_once():
    """Two different 3D IDs must not turn the same two pixels into two votes."""
    from products.worldstate_bim.multiview_fusion import _deduplicate_floor_tracks
    def track(ident, first, second):
        return {'id': ident, 'observations': [
            {'image_id': 1, 'photo_sha256': 'a'*64, 'pixel_xy': first, 'usable': True},
            {'image_id': 2, 'photo_sha256': 'b'*64, 'pixel_xy': second, 'usable': True}]}
    tracks = [track(1,[1.,2.],[3.,4.]), track(2,[1.,2.],[3.,4.]),
              track(3,[1.,2.],[3.,4.001])]
    distinct, groups = _deduplicate_floor_tracks(tracks)
    assert [t['id'] for t in distinct] == [1,3]
    assert groups[0]['retained_track_id'] == 1 and groups[0]['redundant_track_ids'] == [2]
    assert len(groups[0]['pair_evidence'][0]['shared_observations']) == 2


def test_real_meeting_room_duplicate_floor_evidence_is_rejected_without_relaxing_minimum():
    """Real development evidence, with no claim about independent geometry."""
    import json
    from pathlib import Path
    from products.worldstate_bim.multiview_fusion import (
        _deduplicate_floor_tracks, _plane_fit, require_distinct_floor_support,
    )
    root=Path(__file__).resolve().parents[3]/'examples/bim_eyeful_room/round7/meeting_room_dev'
    fusion=json.loads((root/'fusion-original.json').read_text())
    floor_tracks=[t for t in fusion['tracks'] if t['status']=='SUPPORTED' and t['semantic_class']==3]
    distinct,groups=_deduplicate_floor_tracks(floor_tracks)
    assert len(floor_tracks)==10 and len(distinct)==8
    assert [(g['retained_track_id'],g['redundant_track_ids']) for g in groups] == [(104,[105]),(314,[315])]
    planes,_=_plane_fit(distinct,8,31)
    assert not planes
    with pytest.raises(ValueError,match='去重后地面支持不足'):
        require_distinct_floor_support(fusion)
    from products.worldstate_bim.multiview_fusion import build_multiview_room
    anchor=json.loads((root/'route-a-ifc/anchor-assumed.json').read_text())
    selection=json.loads((root/'route-a-ifc/run-summary.json').read_text())['selected_surface_ids']
    with pytest.raises(ValueError,match='去重后地面支持不足'):
        build_multiview_room(fusion,anchor,solve_multiview_scale(fusion,anchor),selection,
            project_id='test-duplicate-floor',assumed_thickness_m=.12,confirmed_candidates=True,
            allow_assumed_scale=True,operator_kind='automation')
    earlier=json.loads((root.parent.parent/'round6/fusion.json').read_text())
    require_distinct_floor_support(earlier)
    prior_id=earlier['floor_planes'][0]['support_point_ids'][0]
    invalid=copy.deepcopy(earlier)
    floor_track=next(t for t in invalid['tracks'] if t['id']==prior_id)
    next(o for o in floor_track['observations'] if o['usable'] and o['semantic_class']==3)['photo_sha256']='0'*64
    with pytest.raises(ValueError,match='缺少匹配的照片观测'):
        require_distinct_floor_support(invalid)
    duplicate=copy.deepcopy(next(t for t in earlier['tracks'] if t['id']==prior_id));duplicate['id']=9999999
    earlier['tracks'].append(duplicate);earlier['floor_planes'][0]['support_point_ids'].append(duplicate['id'])
    with pytest.raises(ValueError,match='含重复像素证据'):
        require_distinct_floor_support(earlier)
