"""Run a known-pose research comparison on two explicitly selected ETH3D photos.

Outputs are unreviewed candidates. Known-pose epipolar residuals are not
semantic correspondence ground truth, wall accuracy, or photo-only results.
Run separately per mode to measure peak process memory. No source images are
copied into the repository. Third-party code and weights remain external.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import threading
import time

import cv2
import numpy as np
from PIL import Image


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def load_inputs(workspace, ids, masks):
    project=json.loads((workspace/'photo-project.json').read_text());state=project['general_modeler']
    cameras={c['image_id']:c for c in state['cameras']};uploads={u['sha256']:u for u in json.loads((workspace/'evidence-index.json').read_text())['uploads']}
    manifest=json.loads((masks/'manifest.json').read_text());records={r['sha256']:r for r in manifest['images']}
    selected=[]
    for ident in ids:
        c=cameras[ident];u=uploads[c['sha256']];path=workspace/'evidence'/(u['sha256']+u['extension']);rec=records[c['sha256']]
        if path.is_symlink() or sha(path)!=c['sha256'] or sha(masks/rec['mask_file'])!=rec['mask_sha256']:
            raise ValueError('source or semantic mask hash mismatch')
        with Image.open(path) as im:
            if im.size!=(c['width_px'],c['height_px']):raise ValueError('image/camera dimensions differ')
            im.draft('L',(1024,1024));im.thumbnail((1024,1024),Image.Resampling.LANCZOS);gray=np.asarray(im.convert('L'))
        labels=np.load(masks/rec['mask_file'],allow_pickle=False)['labels']
        selected.append({'camera':c,'gray':gray,'labels':labels,'image_path':path,
                         'mask_sha256':rec['mask_sha256'],'mask_model_sha256':manifest['model_sha256']})
    return state,selected


def to_original(x, view):
    c=view['camera'];gray=view['gray'];return np.asarray(x,dtype=float)*[c['width_px']/gray.shape[1],c['height_px']/gray.shape[0]]


def camera_matrix(c):
    fx,fy,cx,cy=c['intrinsics'];return np.array([[fx,0,cx],[0,fy,cy],[0,0,1.]]),np.array(c['rotation_camera_from_world']),np.array(c['translation_camera_from_world'])


def point_diagnostics(points_a, points_b, va, vb):
    if len(points_a)==0:return {'count':0}
    k1,r1,t1=camera_matrix(va['camera']);k2,r2,t2=camera_matrix(vb['camera'])
    r=r2@r1.T;t=t2-r@t1;tx=np.array([[0,-t[2],t[1]],[t[2],0,-t[0]],[-t[1],t[0],0]])
    f=np.linalg.inv(k2).T@tx@r@np.linalg.inv(k1)
    a=np.c_[points_a,np.ones(len(points_a))];b=np.c_[points_b,np.ones(len(points_b))]
    fa=a@f.T;ftb=b@f;num=np.sum(b*fa,axis=1)**2;den=fa[:,0]**2+fa[:,1]**2+ftb[:,0]**2+ftb[:,1]**2
    distances=np.sqrt(num/np.maximum(den,1e-20))
    ray_a=(r1.T@np.linalg.inv(k1)@a.T).T;ray_b=(r2.T@np.linalg.inv(k2)@b.T).T
    ray_a/=np.linalg.norm(ray_a,axis=1)[:,None];ray_b/=np.linalg.norm(ray_b,axis=1)[:,None]
    angles=np.degrees(np.arccos(np.clip(np.sum(ray_a*ray_b,axis=1),-1,1)))
    return {'count':len(a),'sampson_px_median':float(np.median(distances)),
            'sampson_px_p90':float(np.percentile(distances,90)),
            'at_most_2px':int(np.sum(distances<=2)), 'ray_angle_deg_median':float(np.median(angles)),
            'ray_angle_deg_p10':float(np.percentile(angles,10)),
            'scope':'known-pose epipolar diagnostic only; not independently reviewed physical correspondence'}


def structural_fraction(line,view):
    labels=view['labels'];h,w=labels.shape;c=view['camera']
    a,b=np.asarray(line,dtype=float)*[w/c['width_px'],h/c['height_px']];d=b-a;length=np.linalg.norm(d)
    if length<1:return 0.
    n=np.array([-d[1],d[0]])/length;hits=0
    for t in np.linspace(.1,.9,13):
        p=a+t*d;values=[]
        for offset in (-2.,2.):
            q=p+n*offset;x=int(np.clip(q[0],0,w-1));y=int(np.clip(q[1],0,h-1));values.append(int(labels[y,x]))
        if 0 in values and any(v in {3,5,8,14} for v in values):hits+=1
    return hits/13.


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--masks',type=Path,required=True)
    p.add_argument('--images',type=int,nargs=2,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('colmap','gluestick','deeplsd','tinyroma'),required=True)
    p.add_argument('--upstream',type=Path);p.add_argument('--weights',type=Path)
    p.add_argument('--xfeat-root',type=Path);p.add_argument('--xfeat-weights',type=Path)
    a=p.parse_args()
    if a.images[0]==a.images[1] or a.output.exists():raise ValueError('choose two views and a new output')
    a.output.mkdir(mode=0o700,parents=True);started=time.monotonic()
    rss_samples=[];sampling=threading.Event()
    def sample_rss():
        while not sampling.is_set():
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith('VmRSS:'):rss_samples.append(int(line.split()[1])/1024);break
            sampling.wait(.05)
    monitor=threading.Thread(target=sample_rss,daemon=True);monitor.start()
    state,views=load_inputs(a.workspace,a.images,a.masks)
    pa=np.empty((0,2));pb=np.empty((0,2));la=np.empty((0,2,2));lb=np.empty((0,2,2));detected=[]
    if a.mode=='colmap':
        track_file=a.workspace/'modeler-tracks.json'
        if track_file.is_symlink() or sha(track_file)!=state.get('track_sha256'):raise ValueError('registered track hash mismatch')
        tracks=json.loads(track_file.read_text())['tracks']
        pairs=[]
        for t in tracks:
            obs={x['image_id']:x['pixel_xy'] for x in t['observations']}
            if all(i in obs for i in a.images):pairs.append((obs[a.images[0]],obs[a.images[1]]))
        if pairs:pa,pb=np.asarray(pairs).transpose(1,0,2)
    else:
        if not a.upstream or not a.weights:raise ValueError('upstream source and local weights are required')
        sys.path.insert(0,str(a.upstream));import torch
        torch.set_num_threads(2);torch.manual_seed(0)
        if a.mode=='gluestick':
            from gluestick.models.two_view_pipeline import TwoViewPipeline
            conf={'name':'two_view_pipeline','use_lines':True,'extractor':{'name':'wireframe',
                'sp_params':{'force_num_keypoints':False,'max_num_keypoints':600},
                'wireframe_params':{'merge_points':True,'merge_line_endpoints':True},'max_n_lines':150},
                'matcher':{'name':'gluestick','weights':str(a.weights),'trainable':False},
                'ground_truth':{'from_pose_depth':False}}
            model=TwoViewPipeline(conf).to('cpu').eval()
            data={'image0':torch.from_numpy(views[0]['gray'].copy()).float()[None,None]/255.,
                  'image1':torch.from_numpy(views[1]['gray'].copy()).float()[None,None]/255.}
            with torch.no_grad():out=model(data)
            q={k:v.detach().cpu().numpy()[0] for k,v in out.items() if isinstance(v,torch.Tensor)}
            valid=q['matches0']>=0;pa=to_original(q['keypoints0'][valid],views[0]);pb=to_original(q['keypoints1'][q['matches0'][valid]],views[1])
            valid=q['line_matches0']>=0;la=to_original(q['lines0'][valid],views[0]);lb=to_original(q['lines1'][q['line_matches0'][valid]],views[1])
        elif a.mode=='deeplsd':
            from deeplsd.models.deeplsd_inference import DeepLSD
            conf={'detect_lines':True,'line_detection_params':{'merge':False,'filtering':True,'grad_thresh':3,'grad_nfa':True}}
            model=DeepLSD(conf);checkpoint=torch.load(str(a.weights),map_location='cpu',weights_only=False)
            model.load_state_dict(checkpoint['model']);model=model.to('cpu').eval()
            for v in views:
                inp=torch.from_numpy(v['gray'].copy()).float()[None,None]/255.
                with torch.no_grad():out=model({'image':inp})
                detected.append(to_original(out['lines'][0],v))
        else:
            if not a.xfeat_root or not a.xfeat_weights:raise ValueError('Tiny RoMa needs explicitly selected XFeat source and weights')
            sys.path.insert(0,str(a.xfeat_root))
            from modules.xfeat import XFeat
            from romatch import tiny_roma_v1_outdoor
            xfeat=XFeat(str(a.xfeat_weights)).net
            weights=torch.load(str(a.weights),map_location='cpu',weights_only=True)
            model=tiny_roma_v1_outdoor('cpu',weights=weights,xfeat=xfeat).eval()
            # Limit dense CPU correlation memory; normalized matches map to original pixels.
            images=[Image.fromarray(cv2.resize(v['gray'],(512,352))).convert('RGB') for v in views]
            with torch.no_grad():
                warp,certainty=model.match(*images);matches,_=model.sample(warp,certainty,num=1000)
                x,y=model.to_pixel_coordinates(matches,views[0]['camera']['height_px'],views[0]['camera']['width_px'],
                                                views[1]['camera']['height_px'],views[1]['camera']['width_px'])
            pa=x.cpu().numpy();pb=y.cpu().numpy()
    line_results=[]
    for i,(x,y) in enumerate(zip(la,lb)):
        sa,sb=structural_fraction(x,views[0]),structural_fraction(y,views[1])
        line_results.append({'line_id':i,'a_original_px':x.tolist(),'b_original_px':y.tolist(),
                             'semantic_boundary_fraction_a':sa,'semantic_boundary_fraction_b':sb,
                             'semantic_structure_candidate':sa>=.3 and sb>=.3,
                             'review_status':'UNREVIEWED_PHYSICAL_CORRESPONDENCE'})
    labels=[]
    for lines,v in zip(detected,views):
        labels.append({'detected':len(lines),'semantic_structure_candidates':sum(structural_fraction(line,v)>=.3 for line in lines),
                       'status':'LINE_DETECTION_ONLY_NO_CROSS_VIEW_MATCH'})
    if len(pa):np.savez_compressed(a.output/'points.npz',a=pa,b=pb)
    if len(la):np.savez_compressed(a.output/'lines.npz',a=la,b=lb)
    if detected:np.savez_compressed(a.output/'detected-lines.npz',a=detected[0],b=detected[1])
    # Small, inspectable raster; its pixels are still derived from NC research data.
    ims=[cv2.cvtColor(v['gray'],cv2.COLOR_GRAY2BGR) for v in views];canvas=np.full((max(i.shape[0] for i in ims),sum(i.shape[1] for i in ims),3),245,dtype=np.uint8)
    canvas[:ims[0].shape[0],:ims[0].shape[1]]=ims[0];canvas[:ims[1].shape[0],ims[0].shape[1]:]=ims[1]
    for idx,(x,y) in enumerate(zip(la[:30],lb[:30])):
        color=tuple(int(v) for v in np.random.default_rng(idx).integers(60,250,3))
        for line,v,dx in ((x,views[0],0),(y,views[1],ims[0].shape[1])):
            scale=np.array([v['gray'].shape[1]/v['camera']['width_px'],v['gray'].shape[0]/v['camera']['height_px']]);coords=np.rint(line*scale).astype(int);coords[:,0]+=dx
            cv2.line(canvas,tuple(coords[0]),tuple(coords[1]),color,2);cv2.putText(canvas,str(idx),tuple(coords[0]),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1)
    cv2.imwrite(str(a.output/'overlay.jpg'),canvas)
    sampling.set();monitor.join()
    result={'mode':a.mode,'images':[{'id':v['camera']['image_id'],'name':v['camera']['photo'],'sha256':v['camera']['sha256'],
            'mask_sha256':v['mask_sha256'],'mask_model_sha256':v['mask_model_sha256']} for v in views],
            'camera_mode':state['camera_mode'],'resize_max_px':512 if a.mode=='tinyroma' else 1024,'point_diagnostics':point_diagnostics(pa,pb,*views),
            'joint_line_matches':len(line_results),'semantic_structure_candidates':sum(x['semantic_structure_candidate'] for x in line_results),
            'line_candidates':line_results,'deeplsd_detections':labels,'runtime_seconds':round(time.monotonic()-started,3),
            'max_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
            'sampled_peak_rss_mib':round(max(rss_samples),1) if rss_samples else None,
            'weights_sha256':sha(a.weights) if a.weights else None,
            'xfeat_weights_sha256':sha(a.xfeat_weights) if a.xfeat_weights else None,
            'caveat':'All semantic labels, line identities and physical matches are unreviewed; no independent accuracy or valid new wall is established.'}
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('mode','point_diagnostics','joint_line_matches','semantic_structure_candidates','deeplsd_detections','runtime_seconds','max_rss_mib')},ensure_ascii=False))


if __name__=='__main__':main()
