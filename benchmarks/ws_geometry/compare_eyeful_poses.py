"""Compare development SfM poses with Eyeful's correlated Metashape estimates.

The source is another reconstruction of the same images, NOT independent ground
truth. A fitted similarity removes scale, rotation and translation; these
numbers do not establish metric accuracy or an independent scale anchor.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np

REFERENCE_SHA256='5b1628c1e72f64052a471c8bfd96f98d2cca78fdf6b2feef45a1ed991e4b1283'
REFERENCE_URL=('https://fb-baas-f32eacb9-8abb-11eb-b2b8-4857dd089e15.s3.amazonaws.com/'
               'EyefulTower/raf_emptyroom/cameras.json')


def fit(a,b):
    ma,mb=a.mean(axis=0),b.mean(axis=0);ac=a-ma;bc=b-mb
    u,s,v=np.linalg.svd(ac.T@bc);d=np.ones(3);d[-1]=np.linalg.det(u@v)
    rotation=u@np.diag(d)@v;denom=np.sum(ac*ac)
    if denom<1e-12 or np.linalg.matrix_rank(ac)<2:raise ValueError('camera centers are degenerate')
    scale=float(np.sum(s*d)/denom)
    return scale,rotation,mb-scale*ma@rotation


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose new output')
    with a.reference.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=REFERENCE_SHA256:raise ValueError('reference dataset hash mismatch')
    source=json.loads(a.geometry.read_text());data=json.loads(a.reference.read_text())['KRT']
    reference={x['cameraId'].split('/')[-1]+'.jpg':x for x in data};samples=[]
    for camera in source['registered_cameras']:
        ref=reference.get(camera['name'])
        if not ref:continue
        transform=np.asarray(ref['T'],dtype=float).T
        rotation=transform[:3,:3];translation=transform[:3,3]
        samples.append((camera['name'],np.asarray(camera['center'],dtype=float),-rotation.T@translation,
                        np.asarray(camera['rotation_camera_from_world'],dtype=float),rotation))
    if len(samples)<4:raise ValueError('at least four matching cameras are required')
    x=np.array([s[1] for s in samples]);y=np.array([s[2] for s in samples]);scale,rotation,offset=fit(x,y)
    in_sample=np.linalg.norm(scale*x@rotation+offset-y,axis=1);loo=[];angles=[]
    for i,(_,_,_,r_sfm,r_ref) in enumerate(samples):
        mask=np.arange(len(samples))!=i;ls,lr,lt=fit(x[mask],y[mask]);loo.append(float(np.linalg.norm(ls*x[i]@lr+lt-y[i])))
        delta=r_ref@(r_sfm@rotation).T;angles.append(math.degrees(math.acos(float(np.clip((np.trace(delta)-1)/2,-1,1)))))
    result={'schema':'worldstate-correlated-pose-comparison/0.1','status':'DEVELOPMENT_DIAGNOSTIC_NOT_GROUND_TRUTH',
      'reference_url':REFERENCE_URL,'reference_sha256':digest,'matched_cameras':len(samples),
      'reference_units':'metres as documented by the data provider; origin of physical scale not independently verified',
      'fit':'similarity fit to all camera centers, leave-one-out for position consistency',
      'scale_reference_units_per_sfm_unit':scale,'in_sample_center_rmse_reference_m':float(np.sqrt(np.mean(in_sample**2))),
      'leave_one_out_center_rmse_reference_m':float(np.sqrt(np.mean(np.square(loo)))),
      'leave_one_out_center_median_reference_m':float(np.median(loo)),
      'leave_one_out_center_max_reference_m':max(loo),
      'rotation_median_degrees_after_all_camera_fit':float(np.median(angles)),
      'rotation_max_degrees_after_all_camera_fit':max(angles),
      'per_camera':[{'name':s[0],'leave_one_out_center_disagreement_reference_m':loo[i]} for i,s in enumerate(samples)],
      'limitations':['reference and candidate reconstruct the same photos; errors are correlated',
                     'similarity alignment fits scale; scale error cannot be independently assessed',
                     'not a held-out room, not ground truth, and not evidence of wall dimensions']}
    a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('matched_cameras','in_sample_center_rmse_reference_m',
      'leave_one_out_center_rmse_reference_m','rotation_median_degrees_after_all_camera_fit')}))

if __name__=='__main__':main()
