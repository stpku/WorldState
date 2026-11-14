"""Run official PixCuboid on ETH3D kicker photos and additional known poses.

Runs upstream Apache-2.0 code in its isolated environment. Inputs contain no
laser scan. The learned cuboid assumes a closed Manhattan room; it is not a
verified room, observation of hidden surfaces, IFC, or independent metric scale.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as torch_functional
from omegaconf import OmegaConf
from pixloc.pixlib.datasets.base_dataset import collate
from pixloc.pixlib.datasets.cuboid_sampling import sample_cuboid_cams
from pixloc.pixlib.datasets.view import read_view
from pixloc.pixlib.geometry import Camera,Pose
from pixloc.pixlib.models import get_model
from pixloc.pixlib.utils.tensor import batch_to_device
from pixloc.utils.colmap import read_model

UPSTREAM='ff26dafd4aa608bfdff0e68e404f6fbe74a817ce'
WEIGHT_SHA256='ff6ee1d09a98e73b372c5c9b0cc11284daf69fd69646c34b10af7890ed1212ac'


def sha(path: Path)->str:
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--known-pose-sfm',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--views',type=int,default=5)
    p.add_argument('--threads',type=int,default=4);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose new output')
    commit=subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()
    if commit!=UPSTREAM or sha(a.checkpoint)!=WEIGHT_SHA256:raise ValueError('upstream commit or checkpoint hash mismatch')
    if not 3<=a.views<=24 or not 1<=a.threads<=16:raise ValueError('invalid view or thread count')
    manifest=json.loads((a.input/'manifest.json').read_text()); records={x['file']:x for x in manifest['modeling_images']}
    if manifest.get('schema')!='worldstate-eth3d-kicker-photo-input/0.1':raise ValueError('unexpected input manifest')
    cameras,images,_=read_model(a.known_pose_sfm,ext='.bin')
    candidates=sorted(images.values(),key=lambda im:im.name)
    if len(candidates)<a.views:raise ValueError('not enough provided poses')
    indices=np.linspace(0,len(candidates)-1,a.views,dtype=int);chosen=[candidates[i] for i in indices]
    if len({im.name for im in chosen})!=a.views:raise ValueError('duplicate input selection')
    for image in chosen:
        path=a.input/'photos'/image.name;record=records.get(image.name)
        if Path(image.name).name!=image.name or path.is_symlink() or not path.is_file() or not record or sha(path)!=record['sha256']:
            raise ValueError('source image hash mismatch')
    np.random.seed(0);torch.manual_seed(0);torch.set_num_threads(a.threads);torch.set_grad_enabled(False)
    permitted=[np._core.multiarray.scalar,np.dtype,type(np.dtype('float64')),type(np.dtype('float32')),type(np.dtype('int64'))]
    with torch.serialization.safe_globals(permitted):ckpt=torch.load(a.checkpoint,map_location='cpu',weights_only=True)
    conf=OmegaConf.create(ckpt['conf']['model']);OmegaConf.set_struct(conf,False)
    # The complete checkpoint is loaded below; no separate pretrained encoder download.
    conf.extractor.weights=None;conf.pre_optimize_vp=False;conf.optimizer.num_iters=15
    conf.optimizer.edge_cost_scale=.05;conf.optimizer.vp_cost_scale=0
    start=time.monotonic();model=get_model(conf.name)(conf).eval()
    model.load_state_dict(ckpt['model'],strict=True)
    conf_view=OmegaConf.create({'grayscale':False,'resize':480,'resize_by':'min','crop':False,'pad':False})
    views=[]
    for image in chosen:
        camera=Camera.from_colmap(cameras[image.camera_id]);pose=Pose.from_colmap(image)
        view=read_view(conf_view,a.input/'photos'/image.name,camera,pose,np.empty((0,3)),np.empty(0))
        # Kicker resizes to 480 x 721, which fails upstream's UNet skip
        # connection assertion. Pad right/bottom to a multiple of 16; as in
        # upstream zero_pad, the valid camera size and intrinsics stay unchanged.
        # Padding can affect network predictions and is part of this run's input.
        h,w=view['image'].shape[-2:]
        view['image']=torch_functional.pad(view['image'],(0,(-w)%16,0,(-h)%16),value=0)
        views.append(view)
    batch=collate(views);batch['cuboid_init']=sample_cuboid_cams(batch['T_w2cam'],seed=0).float()
    batch=batch_to_device(collate([batch]),'cpu');predict=model(batch);cuboid=predict['cuboid_opt'][-1][0]
    rotation=cuboid.R.detach().cpu().numpy();offsets=cuboid.d.detach().cpu().numpy();corners=cuboid.corners.detach().cpu().numpy()
    if not all(np.isfinite(x).all() for x in (rotation,offsets,corners)) or not np.all(offsets[3:]>offsets[:3]):
        raise ValueError('PixCuboid output is non-finite or degenerate')
    summary={'schema':'worldstate-pixcuboid-candidate/0.1','status':'UNVERIFIED_CLOSED_CUBOID_NOT_IFC',
        'upstream_commit':commit,'checkpoint_sha256':WEIGHT_SHA256,'device':'CPU','threads':a.threads,
        'input_mode':'KNOWN_POSE_ADDITIONAL_REFERENCE_POSES','photos':[{'file':im.name,'sha256':records[im.name]['sha256']} for im in chosen],
        'source_reconstruction':[{'file':f.name,'sha256':sha(f)} for f in sorted(a.known_pose_sfm.glob('*.bin'))],
        'config':{'image_short_side':480,'views':a.views,'initialization_seed':0,'torch_seed':0,'optimizer_iterations':15,
                  'right_bottom_zero_pad_multiple':16,'camera_size_intrinsics':'unchanged by padding',
                  'line_segments':'not supplied; vanishing point optimization disabled','edge_cost_scale':.05},
        'output':{'R_world_to_cuboid':rotation.tolist(),'plane_offsets':offsets.tolist(),
                  'size_source_units':(offsets[3:]-offsets[:3]).tolist(),'corners_world':corners.tolist()},
        'runtime_seconds':round(time.monotonic()-start,3),'license':'source Apache-2.0; ETH3D input research only CC BY-NC-SA 4.0',
        'limitations':['Uses additional official poses, not automatic photo-only registration.',
          'Cuboid imposes a closed Manhattan layout; invisible faces are not observed evidence.',
          'Source scale and pose are scanner-registered; no independent physical dimension accuracy is claimed.',
          'Optimizer failure flag is not exposed by the upstream refiner output.']}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':summary['status'],'views':a.views,'size_source_units':summary['output']['size_source_units'],
                      'runtime_seconds':summary['runtime_seconds']},indent=2))


if __name__=='__main__':main()
