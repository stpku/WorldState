"""Fuse actual COLMAP tracks with semantic predictions into plane hypotheses.

The result is arbitrary-scale and is NOT a set of verified wall instances. It
requires the original registered images and the pinned UperNet ONNX model.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import time
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort
import pycolmap
from products.worldstate_bim.semantic_vision import UperNetOnnxProvider


def fit_planes(points, seed=0):
    if len(points)<15:return []
    remaining=np.array(points,dtype=float)
    # A relative RANSAC tolerance, not metres and not reconstruction accuracy.
    tolerance=float(np.linalg.norm(np.ptp(remaining,axis=0))*.01)
    rng=np.random.default_rng(seed);out=[]
    for _ in range(4):
        if len(remaining)<15:break
        best=None
        for _ in range(2000):
            a,b,c=remaining[rng.choice(len(remaining),3,replace=False)]
            normal=np.cross(b-a,c-a);size=np.linalg.norm(normal)
            if size<1e-8:continue
            normal/=size;mask=np.abs((remaining-a)@normal)<tolerance
            if best is None or np.count_nonzero(mask)>np.count_nonzero(best):best=mask
        if best is None or np.count_nonzero(best)<15:break
        inliers=remaining[best];center=inliers.mean(axis=0)
        _,_,vh=np.linalg.svd(inliers-center,full_matrices=False);normal=vh[-1]
        if normal[np.argmax(np.abs(normal))]<0:normal=-normal
        residual=np.abs((inliers-center)@normal)
        out.append({'support_points':len(inliers),'normal':normal.tolist(),'point_on_plane':center.tolist(),
                    'offset':float(-center@normal),'mean_fit_residual_arbitrary':float(residual.mean()),
                    'point_bounds_arbitrary':[inliers.min(axis=0).tolist(),inliers.max(axis=0).tolist()],
                    'status':'UNVERIFIED_SURFACE_HYPOTHESIS'})
        remaining=remaining[~best]
    for i,item in enumerate(out):
        item['parallel_to_previous_hypothesis']=any(abs(np.dot(item['normal'],prev['normal']))>.966 for prev in out[:i])
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--images',type=Path,required=True)
    p.add_argument('--sparse',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('use a new output path')
    if hashlib.file_digest(args.model.open('rb'),'sha256').hexdigest()!=UperNetOnnxProvider.MODEL_SHA256:
        raise ValueError('model hash mismatch')
    reconstruction=pycolmap.Reconstruction(str(args.sparse));options=ort.SessionOptions();options.intra_op_num_threads=4
    session=ort.InferenceSession(str(args.model),sess_options=options,providers=['CPUExecutionProvider'])
    masks={};started=time.monotonic()
    for image_id,image in sorted(reconstruction.images.items(),key=lambda x:x[1].name):
        source=args.images/image.name
        rgb=cv2.imread(str(source))
        if rgb is None or rgb.shape[:2]!=(image.camera.height,image.camera.width):raise ValueError('missing or mismatched image')
        rgb=cv2.cvtColor(cv2.resize(rgb,(512,512)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        rgb=(rgb-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        logits=session.run(None,{'pixel_values':rgb.transpose(2,0,1)[None]})[0][0]
        masks[image_id]=np.argmax(logits,axis=0).astype(np.uint8)
        print('segmented',image.name,flush=True)
    classified=collections.defaultdict(list)
    for point in reconstruction.points3D.values():
        votes=[]
        for track in point.track.elements:
            image=reconstruction.images[track.image_id];x,y=image.points2D[track.point2D_idx].xy
            xi=max(0,min(127,int(x/image.camera.width*128)));yi=max(0,min(127,int(y/image.camera.height*128)))
            votes.append(int(masks[track.image_id][yi,xi]))
        label,count=collections.Counter(votes).most_common(1)[0]
        if count>=2 and count/len(votes)>=.6:classified[label].append(point.xyz.tolist())
    walls=classified.get(0,[]);floor=classified.get(3,[]);ceiling=classified.get(5,[])
    result={'schema':'worldstate-semantic-sfm-hypotheses/0.1','status':'UNVERIFIED_RESEARCH_CANDIDATE',
      'model_sha256':UperNetOnnxProvider.MODEL_SHA256,'registered_images':len(masks),
      'source_sfm_points':reconstruction.num_points3D(),'semantic_point_counts':{str(k):len(v) for k,v in classified.items()},
      'method':'two or more track observations and 60% semantic majority; sequential 3-point RANSAC',
      'wall_plane_hypotheses':fit_planes(walls),'floor_plane_hypotheses':fit_planes(floor),
      'ceiling_plane_hypotheses':fit_planes(ceiling),'units':'arbitrary','runtime_seconds':round(time.monotonic()-started,3),
      'limitations':['plane hypotheses are not wall instances; parallel fragments can duplicate surfaces',
        'no independent metric anchor or accuracy ground truth','sparse features and segmentation may miss or misclassify walls',
        'plane fitting residual is not reconstruction or wall dimension error','no automatic conversion to IFC from these planes']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'points':len(walls),'wall_hypotheses':len(result['wall_plane_hypotheses']),
                      'runtime_seconds':result['runtime_seconds']}),flush=True)

if __name__=='__main__':main()
