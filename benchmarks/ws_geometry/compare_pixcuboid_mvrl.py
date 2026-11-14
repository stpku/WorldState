"""Measure agreement of two real PixCuboid outputs with upstream MVRL IoU.

Both inputs are predictions, potentially on different photos. This is NOT
accuracy, ground truth, or a fair ranking. MeshLib is an isolated research
runtime dependency with a separate license; it is not a Core dependency.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
import numpy as np

UPSTREAM='cb45ace442b6f988216f9607a67f7ab2b8608968'


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--left',type=Path,required=True);p.add_argument('--right',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    commit=subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()
    if commit!=UPSTREAM:raise ValueError('upstream MVRL version mismatch')
    left=json.loads(a.left.read_text());right=json.loads(a.right.read_text())
    if any(x.get('schema')!='worldstate-pixcuboid-candidate/0.1' for x in (left,right)):raise ValueError('invalid candidate')
    sys.path.insert(0,str(a.upstream))
    # Import the actual upstream IoU module without importing its package's
    # unrelated visualization/chamfer dependencies in __init__.py.
    package=types.ModuleType('mvrl.metrics');package.__path__=[str(a.upstream/'mvrl'/'metrics')];sys.modules['mvrl.metrics']=package
    from mvrl.cuboid import Cuboid
    from mvrl.metrics.iou3d import iou3d
    def cuboid(x: dict):return Cuboid.from_Rd(np.array(x['output']['R_world_to_cuboid']),np.array(x['output']['plane_offsets']))
    score=float(iou3d(cuboid(left),cuboid(right)))
    result={'schema':'worldstate-mvrl-prediction-agreement/0.1','status':'PREDICTION_AGREEMENT_NOT_ACCURACY',
      'mvrl_commit':commit,'left_sha256':sha(a.left),'right_sha256':sha(a.right),
      'left_views':len(left['photos']),'right_views':len(right['photos']),
      'photo_inputs_identical':left['photos']==right['photos'],'iou3d_prediction_to_prediction':score,
      'limitations':['Neither input is a reference layout.','Different photo counts are not comparable accuracy trials.',
         'Results use inferred closed cuboids and known-pose inputs.','MeshLib licensing is separate from MultiViewRoomLayout.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
