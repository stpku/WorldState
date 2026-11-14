"""Geometry tests only; real ETH3D inference is recorded separately."""
import numpy as np
import pytest
from products.worldstate_bim.floor_candidates import cuboid_floor_candidates


def view(name='photo.jpg'):
    return {'name':name,'image_sha256':'a'*64,'registered':True,'intrinsics':np.eye(3),
            'camera_from_world':np.eye(3),'camera_center':[0,0,0],'width':1,'height':1,
            'labels':np.array([[3]],dtype=np.uint8),'confidence':np.array([[.9]])}


def test_ray_support_is_traced_but_does_not_confirm_the_floor():
    out=cuboid_floor_candidates(np.eye(3),[-1,-1,1,1,1,3],[view()])
    assert out['state']=='UNCONFIRMED_NO_AUTOMATIC_FLOOR_SELECTION'
    assert [x['sampled_floor_pixels'] for x in out['candidates']]==[0,0,1,0,0,0]
    assert out['candidates'][2]['support_views'][0]['image_sha256']=='a'*64
    assert all(x['state']=='INFERRED_PRIOR_UNCONFIRMED' for x in out['candidates'])
    wall=view();wall['labels'][:]=0
    assert not any(x['sampled_floor_pixels'] for x in cuboid_floor_candidates(np.eye(3),[-1,-1,1,1,1,3],[wall])['candidates'])


def test_unregistered_duplicate_and_degenerate_inputs_are_rejected():
    bad=view();bad['registered']=False
    with pytest.raises(ValueError,match='registered'):cuboid_floor_candidates(np.eye(3),[-1,-1,1,1,1,3],[bad])
    with pytest.raises(ValueError,match='unique'):cuboid_floor_candidates(np.eye(3),[-1,-1,1,1,1,3],[view(),view()])
    with pytest.raises(ValueError,match='cuboid bounds'):cuboid_floor_candidates(np.eye(3),[-1,-1,1,1,1,1],[view()])
