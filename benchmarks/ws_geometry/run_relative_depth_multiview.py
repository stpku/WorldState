"""Diagnostic: align monocular relative depth to same-input sparse geometry.

No scanner or official depth maps are read. Per-image inverse depth is fit to
COLMAP tracks from the same photographs; the resulting pseudo-scale is NOT an
independent measurement. Camera pose is supplied by the reconstruction and may
be a known-pose input. Semantic floor pixels and the model outputs are highly
correlated; this script does not confirm a floor or produce IFC.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort
import pycolmap
from scipy.optimize import least_squares

MODEL_SHA='afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c'
SEMANTIC_MODEL_SHA='fea729ab6c5d338bc79ad3d986b073e6faa12c97255eafd78a1f7145326e534e'


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def sample(map_: np.ndarray, x: np.ndarray, y: np.ndarray, width: int, height: int) -> np.ndarray:
    """Sample a prediction at original-image pixel centers with interpolation."""
    mx=(x+.5)*map_.shape[1]/width-.5;my=(y+.5)*map_.shape[0]/height-.5
    return cv2.remap(map_.astype(np.float32),mx.astype(np.float32).reshape(-1,1),
                     my.astype(np.float32).reshape(-1,1),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).ravel()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sparse',type=Path,required=True)
    p.add_argument('--source-known-pose',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--masks',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    if sha(a.model)!=MODEL_SHA:raise ValueError('relative-depth checkpoint hash mismatch')
    selection=json.loads(a.selection.read_text());expected={x['file']:x['sha256'] for x in selection['photos']}
    if (selection.get('schema')!='worldstate-pixcuboid-candidate/0.1' or len(expected)<3 or len(expected)!=len(selection['photos']) or
        selection.get('input_mode')!='KNOWN_POSE_ADDITIONAL_REFERENCE_POSES'):raise ValueError('invalid known-pose selection')
    manifest=json.loads((a.masks/'manifest.json').read_text());records={x['name']:x for x in manifest['images']}
    if manifest.get('schema')!='worldstate-multiview-masks/0.1' or manifest.get('model_sha256')!=SEMANTIC_MODEL_SHA:
        raise ValueError('unexpected semantic model or mask manifest')
    pose_summary=json.loads((a.sparse/'known-pose-summary.json').read_text())
    if (pose_summary.get('mode')!='KNOWN_POSE_ADDITIONAL_REFERENCE_POSES' or
        not pose_summary.get('fixed_existing_frames') or pose_summary.get('max_pose_matrix_difference',1)>1e-7 or
        {x['file']:x['sha256'] for x in pose_summary['selected_photos']}!=expected):
        raise ValueError('known-pose source does not match selected images')
    reconstruction=pycolmap.Reconstruction(a.sparse);images={x.name:x for x in reconstruction.images.values()}
    if set(images)!=set(expected):raise ValueError('sparse reconstruction differs from selected photos')
    source_files=[{'file':f.name,'sha256':sha(f)} for f in sorted(a.source_known_pose.glob('*.bin'))]
    if source_files!=selection['source_reconstruction']:raise ValueError('PixCuboid pose source changed')
    reference=pycolmap.Reconstruction(a.source_known_pose);source_images={x.name:x for x in reference.images.values()}
    for name,image in images.items():
        original=source_images.get(name)
        if (original is None or not np.allclose(image.cam_from_world().matrix(),original.cam_from_world().matrix(),atol=1e-7,rtol=0) or
            image.camera.model_name!=original.camera.model_name or image.camera.width!=original.camera.width or
            image.camera.height!=original.camera.height or not np.allclose(image.camera.params,original.camera.params,atol=1e-8,rtol=0)):
            raise ValueError('selected camera differs from PixCuboid input')
    options=ort.SessionOptions();options.intra_op_num_threads=4
    started=time.monotonic();session=ort.InferenceSession(str(a.model),sess_options=options,providers=['CPUExecutionProvider'])
    init=time.monotonic()-started;views=[];summaries=[];total_inference=0.
    for name in sorted(expected):
        image=images[name];camera=image.camera;path=a.images/name;record=records.get(name)
        if (Path(name).name!=name or path.is_symlink() or not path.is_file() or sha(path)!=expected[name] or
            not record or record['sha256']!=expected[name] or camera.model_name!='PINHOLE'):
            raise ValueError('photo, mask, or camera provenance mismatch: '+name)
        mask_path=a.masks/record['mask_file']
        if Path(record['mask_file']).name!=record['mask_file'] or sha(mask_path)!=record['mask_sha256']:
            raise ValueError('mask hash mismatch')
        with np.load(mask_path,allow_pickle=False) as data:labels=data['labels'];confidence=data['confidence']
        if labels.shape!=(128,128) or confidence.shape!=(128,128) or not np.isfinite(confidence).all():raise ValueError('invalid masks')
        rgb=cv2.imread(str(path));height,width=rgb.shape[:2]
        if (width,height)!=(camera.width,camera.height):raise ValueError('camera/photo size mismatch')
        scale=518/min(height,width);tw=max(14,round(width*scale/14)*14);th=max(14,round(height*scale/14)*14)
        rgb=cv2.cvtColor(cv2.resize(rgb,(tw,th),interpolation=cv2.INTER_CUBIC),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
        rgb=(rgb-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        start=time.monotonic();prediction=session.run(None,{session.get_inputs()[0].name:np.transpose(rgb,(2,0,1))[None]})[0][0]
        elapsed=time.monotonic()-start;total_inference+=elapsed
        if prediction.ndim!=2 or not np.isfinite(prediction).all():raise ValueError('non-finite depth prediction')
        pose=image.cam_from_world();rotation=np.asarray(pose.rotation.matrix());translation=np.asarray(pose.translation)
        observations=[];seen=set()
        for point in image.points2D:
            if not point.has_point3D():continue
            x,y=map(float,point.xy);key=(x,y)
            if key in seen or not (0<=x<width and 0<=y<height):continue
            seen.add(key);xyz=reconstruction.points3D[point.point3D_id].xyz;z=float((rotation@xyz+translation)[2])
            if z>0 and np.isfinite(z):observations.append((int(point.point3D_id),x,y,z))
        obs=np.array(observations,dtype=float).reshape(-1,4)
        if len(obs):values=sample(prediction,obs[:,1],obs[:,2],width,height);target=1./obs[:,3]
        else:values=np.array([]);target=np.array([])
        train=(obs[:,0].astype(np.int64)%5)!=0 if len(obs) else np.array([],dtype=bool);held=~train
        summary={'photo':name,'sha256':expected[name],'tracks':len(obs),'calibration_tracks':int(train.sum()),
                 'heldout_tracks':int(held.sum()),'inference_seconds':round(elapsed,3),'status':'INSUFFICIENT_OR_UNRELIABLE',
                 'calibration':'per-image affine inverse-depth fit to same-scene triangulated tracks',
                 'uncertainty':'UNKNOWN; held-out tracks are not independent of cameras or reconstruction'}
        estimate=None
        if train.sum()>=30 and held.sum()>=10 and np.ptp(values[train])>1e-8:
            design=np.column_stack((values[train],np.ones(train.sum())));initial=np.linalg.lstsq(design,target[train],rcond=None)[0]
            residual=design@initial-target[train];fscale=max(float(np.median(np.abs(residual)))*2,1e-8)
            fit=least_squares(lambda ab:design@ab-target[train],initial,loss='soft_l1',f_scale=fscale)
            inv=fit.x[0]*values[held]+fit.x[1];valid=np.isfinite(inv)&(inv>0)
            errors=np.abs((1./inv[valid])-obs[held,3][valid])/obs[held,3][valid]
            fraction=float(np.mean(valid));median=float(np.median(errors)) if len(errors) else None
            summary.update(inverse_depth_scale=float(fit.x[0]),inverse_depth_offset=float(fit.x[1]),
                heldout_positive_fraction=fraction,heldout_sparse_relative_error_median=median,
                heldout_sparse_relative_error_p90=float(np.percentile(errors,90)) if len(errors) else None)
            # Diagnostic guard chosen before running: not a release criterion.
            if fit.x[0]>0 and fraction>=.9 and median is not None and median<=.2:
                summary['status']='PASSES_CORRELATED_SPARSE_DIAGNOSTIC_NOT_GROUND_TRUTH';estimate=fit.x
        if estimate is not None:
            fy,fx=np.nonzero((labels==3)&(confidence>=.30))
            if len(fx)>256:
                idx=np.linspace(0,len(fx)-1,256,dtype=int);fx=fx[idx];fy=fy[idx]
            u=(fx+.5)*width/128;v=(fy+.5)*height/128
            inv=estimate[0]*sample(prediction,u,v,width,height)+estimate[1];ok=np.isfinite(inv)&(inv>1e-8)
            u=u[ok];v=v[ok];z=1./inv[ok];cal=camera.params
            world=(np.column_stack(((u-cal[2])/cal[0]*z,(v-cal[3])/cal[1]*z,z))-translation)@rotation
            summary['sampled_floor_pixels']=len(world)
            views.append({'name':name,'sha256':expected[name],'pixels':np.column_stack((u,v)),
                          'camera':camera,'rotation':rotation,'translation':translation,'world':world,
                          'prediction':prediction,'labels':labels,'confidence':confidence,'estimate':estimate})
        summaries.append(summary)
    cross=[];pairs=0
    for source in views:
        for target in views:
            if source['name']==target['name'] or not len(source['world']):continue
            q=source['world']@target['rotation'].T+target['translation'];cam=target['camera'];fx,fy,cx,cy=cam.params
            positive=q[:,2]>0;u=np.divide(q[:,0],q[:,2],out=np.zeros(len(q)),where=positive)*fx+cx
            v=np.divide(q[:,1],q[:,2],out=np.zeros(len(q)),where=positive)*fy+cy
            valid=positive&(u>=0)&(u<cam.width)&(v>=0)&(v<cam.height)
            indices=np.flatnonzero(valid)
            if not len(indices):continue
            mx=np.minimum(127,(u[indices]*128/cam.width).astype(int));my=np.minimum(127,(v[indices]*128/cam.height).astype(int))
            floor=(target['labels'][my,mx]==3)&(target['confidence'][my,mx]>=.30);indices=indices[floor]
            if not len(indices):continue
            raw=sample(target['prediction'],u[indices],v[indices],cam.width,cam.height)
            inv=target['estimate'][0]*raw+target['estimate'][1];ok=np.isfinite(inv)&(inv>0)
            if not ok.any():continue
            cross.extend((np.abs(1./inv[ok]-q[indices[ok],2])/q[indices[ok],2]).tolist());pairs+=1
    # Reuse the existing 1%-of-scene RANSAC distance convention, but require
    # at least eight sampled pixels from each of three distinct photos. The
    # samples are correlated predictions, not independent measured tracks.
    # This proposes a plane only; it never confirms a floor or creates IFC.
    points=np.vstack([v['world'] for v in views]) if views else np.empty((0,3))
    owners=np.concatenate([np.full(len(v['world']),i,dtype=int) for i,v in enumerate(views)]) if views else np.array([],dtype=int)
    plane={'status':'NO_CANDIDATE','sampled_points':len(points),'selection':'NOT_CONFIRMED'}
    if len(points)>=24:
        threshold=float(np.linalg.norm(np.ptp(points,axis=0))*.01);rng=np.random.default_rng(31);best=None
        if threshold>1e-9:
            for _ in range(5000):
                first,second,third=points[rng.choice(len(points),3,replace=False)]
                normal=np.cross(second-first,third-first);norm=np.linalg.norm(normal)
                if norm<1e-9:continue
                normal/=norm;inside=np.abs((points-first)@normal)<threshold
                if best is None or inside.sum()>best.sum():best=inside
        if best is not None:
            counts=[int(np.count_nonzero(best&(owners==i))) for i in range(len(views))]
            support=points[best]
            if len(support)>=24 and sum(c>=8 for c in counts)>=3:
                center=support.mean(axis=0);_,singular,vh=np.linalg.svd(support-center,full_matrices=False)
                if len(singular)>=2 and singular[0]>0 and singular[1]/singular[0]>=.08:
                    normal=vh[-1];normal*=np.sign(normal[np.argmax(np.abs(normal))]);offset=float(-normal@center)
                    residual=np.abs((support-center)@normal)
                    plane={'status':'UNCONFIRMED_CORRELATED_DEPTH_PLANE','selection':'NOT_CONFIRMED',
                        'normal':normal.tolist(),'offset':offset,'coordinate_frame':'provided reconstruction frame',
                        'sampled_points':len(points),'supporting_sampled_pixels':len(support),
                        'support_by_view':[{'photo':v['name'],'sha256':v['sha256'],'sampled_pixels':counts[i]}
                                           for i,v in enumerate(views) if counts[i]],
                        'fit_threshold_source_units':threshold,'fit_rms_source_units':float(np.sqrt(np.mean(residual**2))),
                        'in_plane_rank_ratio':float(singular[1]/singular[0]),
                        'caveat':'Correlated model pixels, semantic mistakes and occlusion can support a false plane.'}
    out_floor={'schema':'worldstate-relative-depth-floor-candidate/0.1','candidate':plane,
        'source_photos':[{'name':v['name'],'sha256':v['sha256']} for v in views],
        'evidence_note':'Original image pixels and their predicted 3D coordinates are stored in samples.npz, not independent measurements.'}
    samples={f'{i}_pixels':v['pixels'] for i,v in enumerate(views)}
    samples.update({f'{i}_world':v['world'] for i,v in enumerate(views)})
    out={'schema':'worldstate-relative-depth-multiview-diagnostic/0.1','status':'DEVELOPMENT_ONLY_NO_CONFIRMED_FLOOR_OR_IFC',
        'model_sha256':MODEL_SHA,'selection_sha256':sha(a.selection),'semantic_manifest_sha256':sha(a.masks/'manifest.json'),
        'mode':'KNOWN_POSE_SPARSE_FIT','known_pose_summary_sha256':sha(a.sparse/'known-pose-summary.json'),
        'source_reconstruction':[{'file':f.name,'sha256':sha(f)} for f in sorted(a.sparse.glob('*.bin'))],
        'device':'CPU','session_init_seconds':round(init,3),'total_inference_seconds':round(total_inference,3),
        'predeclared_correlated_fit_guard':{'minimum_train_tracks':30,'minimum_heldout_tracks':10,
            'minimum_positive_heldout_fraction':.9,'maximum_heldout_sparse_median_relative_error':.2,'positive_scale':True},
        'views':summaries,'views_passing_correlated_fit':len(views),'cross_view_floor_pixel_pairs':pairs,
        'cross_view_floor_comparisons':len(cross),'cross_view_floor_relative_depth_disagreement_median':float(np.median(cross)) if cross else None,
        'cross_view_floor_relative_depth_disagreement_p90':float(np.percentile(cross,90)) if cross else None,
        'floor_plane_status':plane['status'],
        'limitations':['No laser scan, reference IFC or held-out photo is read by this script.',
            'This diagnostic was designed after the scene scan summary was seen; not a blind independent evaluation.',
            'Depth is fitted to tracks from the same photos; sparse holdout is correlated with camera fitting and cannot prove accuracy.',
            'Known camera poses are extra source data; source metric scale is not independently measured.',
            'Floor masks and neighboring pixels are correlated and can label furniture; occlusion contributes to cross-view disagreement.',
            'No gravity assumption, floor plane selection, wall extent, physical thickness or IFC is fabricated.']}
    a.output.mkdir(parents=True)
    (a.output/'diagnostic.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    (a.output/'floor-plane-candidate.json').write_text(json.dumps(out_floor,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(a.output/'samples.npz',**samples)
    print(json.dumps({k:out[k] for k in ('status','views_passing_correlated_fit','cross_view_floor_pixel_pairs',
          'cross_view_floor_comparisons','cross_view_floor_relative_depth_disagreement_median','floor_plane_status','total_inference_seconds')},indent=2))


if __name__=='__main__':main()
