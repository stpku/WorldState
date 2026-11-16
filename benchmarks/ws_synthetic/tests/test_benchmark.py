"""Synthetic oracle and isolation tests; none are evidence of real-room accuracy."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest

from benchmarks.ws_synthetic.evaluate import correspondence_metrics, room_metrics, verify_freeze
from benchmarks.ws_synthetic.generate import room


def test_room_generator_varies_geometry_and_keeps_simulated_provenance():
    rectangular=room(711,'rectangle');again=room(711,'rectangle');nonrect=room(711,'l-shape')
    assert rectangular==again
    assert len([e for e in rectangular['elements'] if e['ifc_type']=='IfcWall'])==4
    assert len([e for e in nonrect['elements'] if e['ifc_type']=='IfcWall'])==6
    assert all(e['classification']['status']=='simulated' for e in nonrect['elements'])


def test_independent_wall_matching_penalizes_duplicate_and_dimension_error():
    truth=room(711,'rectangle');candidate=copy.deepcopy(truth)
    candidate['elements'][0]['parameters']['height']['value']+=.2
    duplicate=copy.deepcopy(candidate['elements'][0]);duplicate['id']='duplicate-wall';candidate['elements'].append(duplicate)
    report=room_metrics(truth,candidate)
    assert report['wall_instances']['precision']==pytest.approx(.8)
    assert report['wall_instances']['recall']==1
    assert max(row['height_abs_m'] for row in report['wall_errors'])==pytest.approx(.2)


def test_reference_hashes_detect_tampering_and_traversal(tmp_path):
    item=tmp_path/'a';item.write_bytes(b'original')
    manifest={'schema':'ws-synthetic-freeze/0.1','files':{'a':hashlib.sha256(b'original').hexdigest()}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest));verify_freeze(tmp_path)
    item.write_bytes(b'changed')
    with pytest.raises(ValueError,match='mismatch'):verify_freeze(tmp_path)
    manifest['files']={'../outside':'a'*64};(tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='mismatch'):verify_freeze(tmp_path)


def test_correspondence_uses_depth_camera_and_visibility(tmp_path):
    a={'image_id':1,'camera_model':'SIMPLE_PINHOLE','intrinsics':[10.,5.,5.], 'width_px':11,'height_px':11,
       'rotation_camera_from_world':np.eye(3).tolist(),'translation_camera_from_world':[0.,0.,0.]}
    b=copy.deepcopy(a);b.update(image_id=2,translation_camera_from_world=[-.5,0.,0.])
    (tmp_path/'cameras-exact.json').write_text(json.dumps({'cameras':[a,b]}))
    depth=np.full((11,11),5,dtype=np.float32);instance=np.ones((11,11),dtype=np.uint16);semantic=np.ones((11,11),dtype=np.uint8)
    np.savez(tmp_path/'view-001-truth.npz',depth_z_m=depth,instance=instance,semantic=semantic)
    np.savez(tmp_path/'view-002-truth.npz',depth_z_m=depth,instance=instance,semantic=semantic)
    np.savez(tmp_path/'matches.npz',a=np.array([[5.,5.],[5.,5.]]),b=np.array([[4.,5.],[10.,10.]]))
    result=correspondence_metrics(tmp_path,tmp_path/'matches.npz',1,2)
    assert result['checked_visible']==2 and result['correct_at_3px']==1
    assert result['strict_accuracy_at_3px']==pytest.approx(.5)
