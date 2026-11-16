"""Run local matching models on synthetic input only; do not access references."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import cv2
import numpy as np
from PIL import Image


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--images',type=int,nargs=2,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['gluestick','deeplsd','tinyroma'],required=True)
    p.add_argument('--upstream',type=Path,required=True);p.add_argument('--weights',type=Path,required=True)
    p.add_argument('--xfeat-root',type=Path);p.add_argument('--xfeat-weights',type=Path);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose new output')
    if a.images[0]==a.images[1]:raise ValueError('choose two distinct views')
    cameras={c['image_id']:c for c in json.loads((a.input/'cameras.json').read_text())['cameras']};views=[]
    for ident in a.images:
        c=cameras[ident];path=a.input/'images'/c['photo']
        if path.is_symlink() or sha(path)!=c['sha256']:raise ValueError('input photo hash mismatch')
        image=Image.open(path).convert('L');image.thumbnail((1024,1024));views.append((c,np.asarray(image)))
    a.output.mkdir(parents=True,mode=0o700);sys.path.insert(0,str(a.upstream));import torch
    torch.set_num_threads(2);torch.manual_seed(0);started=time.monotonic();pa=pb=la=lb=None;counts=[]
    def original(x,view):
        c,gray=view;return np.asarray(x,dtype=float)*[c['width_px']/gray.shape[1],c['height_px']/gray.shape[0]]
    if a.mode=='gluestick':
        from gluestick.models.two_view_pipeline import TwoViewPipeline
        conf={'name':'two_view_pipeline','use_lines':True,'extractor':{'name':'wireframe','sp_params':{'force_num_keypoints':False,'max_num_keypoints':600},
          'wireframe_params':{'merge_points':True,'merge_line_endpoints':True},'max_n_lines':150},
          'matcher':{'name':'gluestick','weights':str(a.weights),'trainable':False},'ground_truth':{'from_pose_depth':False}}
        model=TwoViewPipeline(conf).to('cpu').eval();data={f'image{i}':torch.from_numpy(v[1].copy()).float()[None,None]/255. for i,v in enumerate(views)}
        with torch.no_grad():out=model(data)
        q={k:v.detach().cpu().numpy()[0] for k,v in out.items() if isinstance(v,torch.Tensor)}
        mask=q['matches0']>=0;pa=original(q['keypoints0'][mask],views[0]);pb=original(q['keypoints1'][q['matches0'][mask]],views[1])
        mask=q['line_matches0']>=0;la=original(q['lines0'][mask],views[0]);lb=original(q['lines1'][q['line_matches0'][mask]],views[1])
    elif a.mode=='deeplsd':
        from deeplsd.models.deeplsd_inference import DeepLSD
        model=DeepLSD({'detect_lines':True,'line_detection_params':{'merge':False,'filtering':True,'grad_thresh':3,'grad_nfa':True}})
        model.load_state_dict(torch.load(str(a.weights),map_location='cpu',weights_only=False)['model']);model=model.to('cpu').eval();lines=[]
        for v in views:
            with torch.no_grad():out=model({'image':torch.from_numpy(v[1].copy()).float()[None,None]/255.})
            lines.append(original(out['lines'][0],v));counts.append(len(lines[-1]))
        np.savez_compressed(a.output/'detected-lines.npz',a=lines[0],b=lines[1])
    else:
        if not a.xfeat_root or not a.xfeat_weights:raise ValueError('Tiny RoMa requires XFeat source and weights')
        sys.path.insert(0,str(a.xfeat_root));from modules.xfeat import XFeat
        from romatch import tiny_roma_v1_outdoor
        model=tiny_roma_v1_outdoor('cpu',weights=torch.load(str(a.weights),map_location='cpu',weights_only=True),xfeat=XFeat(str(a.xfeat_weights)).net).eval()
        images=[Image.fromarray(cv2.resize(v[1],(512,352))).convert('RGB') for v in views]
        with torch.no_grad():
            warp,certainty=model.match(*images);matches,_=model.sample(warp,certainty,num=1000)
            x,y=model.to_pixel_coordinates(matches,views[0][0]['height_px'],views[0][0]['width_px'],views[1][0]['height_px'],views[1][0]['width_px'])
        pa=x.cpu().numpy();pb=y.cpu().numpy()
    if pa is not None:np.savez_compressed(a.output/'matches.npz',a=pa,b=pb)
    if la is not None:np.savez_compressed(a.output/'line-matches.npz',a=la,b=lb)
    result={'mode':a.mode,'images':a.images,'photo_sha256':[v[0]['sha256'] for v in views],'weights_sha256':sha(a.weights),
      'point_matches':len(pa) if pa is not None else None,'line_matches':len(la) if la is not None else None,'line_detections':counts,
      'elapsed_seconds':round(time.monotonic()-started,3),'max_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
      'status':'UNVERIFIED_MATCHES' if pa is not None else 'LINE_DETECTION_ONLY',
      'warning':'No reference labels or exact poses were used by this program. Counts are not accuracy.'}
    (a.output/'run.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
