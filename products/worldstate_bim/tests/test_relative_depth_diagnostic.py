"""Check source-pixel alignment and fail-closed model provenance for the CPU diagnostic."""
import sys
import numpy as np
import pytest
from benchmarks.ws_geometry import run_relative_depth_multiview as diagnostic


def test_relative_depth_sampling_uses_original_pixel_coordinates():
    depth=np.array([[1.,2.],[3.,4.]],dtype=np.float32)
    sampled=diagnostic.sample(depth,np.array([0.,1.,0.,1.]),np.array([0.,0.,1.,1.]),2,2)
    assert sampled.tolist()==pytest.approx([1.,2.,3.,4.])


def test_unexpected_depth_checkpoint_is_rejected_before_any_results(tmp_path,monkeypatch):
    model=tmp_path/'wrong.onnx';model.write_bytes(b'not the registered relative depth model')
    output=tmp_path/'output'
    monkeypatch.setattr(sys,'argv',['depth-diagnostic','--sparse',str(tmp_path/'missing-sparse'),
        '--source-known-pose',str(tmp_path/'missing-known-pose'),
        '--images',str(tmp_path/'missing-images'),'--masks',str(tmp_path/'missing-masks'),
        '--selection',str(tmp_path/'missing-selection'),'--model',str(model),'--output',str(output)])
    with pytest.raises(ValueError,match='checkpoint hash mismatch'):diagnostic.main()
    assert not output.exists()
