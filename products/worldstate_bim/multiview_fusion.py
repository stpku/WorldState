"""Evidence-linked multiview semantic geometry for WorldState BIM.

All coordinates remain in the input COLMAP world frame until a separately
recorded physical scale is applied. Semantic labels and planes are hypotheses.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pycolmap

from .semantic_vision import UperNetOnnxProvider


def _sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def infer_masks(sparse: Path, images: Path, model: Path, output: Path) -> dict[str, Any]:
    """Run pinned CPU segmentation on every registered view and bind hashes."""
    if output.exists():raise FileExistsError('choose a new semantic mask directory')
    reconstruction=pycolmap.Reconstruction(str(sparse))
    provider=UperNetOnnxProvider(model)
    output.mkdir(parents=True)
    records=[];start=time.monotonic()
    for image_id in sorted(reconstruction.reg_image_ids()):
        image=reconstruction.image(image_id)
        if Path(image.name).name!=image.name:raise ValueError('nested image paths are not supported')
        path=images/image.name
        if path.is_symlink() or not path.is_file():raise ValueError(f'missing registered image: {image.name}')
        raw=path.read_bytes();pixels=cv2.imdecode(np.frombuffer(raw,dtype=np.uint8),cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape[:2]!=(image.camera.height,image.camera.width):
            raise ValueError(f'image dimensions do not match camera: {image.name}')
        rgb=cv2.cvtColor(cv2.resize(pixels,(512,512)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        rgb=(rgb-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        logits=provider.session.run(None,{'pixel_values':rgb.transpose(2,0,1)[None]})[0][0]
        if logits.shape!=(150,128,128) or not np.isfinite(logits).all():raise ValueError('invalid model output')
        labels=np.argmax(logits,axis=0).astype(np.uint8)
        exp=np.exp(logits-logits.max(axis=0,keepdims=True));confidence=(exp.max(axis=0)/exp.sum(axis=0)).astype(np.float16)
        filename=f'image-{int(image_id)}.npz';np.savez_compressed(output/filename,labels=labels,confidence=confidence)
        records.append({'image_id':int(image_id),'name':image.name,'sha256':hashlib.sha256(raw).hexdigest(),
                        'width_px':int(image.camera.width),'height_px':int(image.camera.height),
                        'mask_file':filename,'mask_sha256':_sha(output/filename)})
        print(f'segmented {image.name} ({len(records)}/{reconstruction.num_reg_images()})',flush=True)
    result={'schema':'worldstate-multiview-masks/0.1','model_sha256':provider.MODEL_SHA256,
            'model_revision':provider.MODEL_REVISION,'mask_resolution':[128,128],
            'coordinate_mapping':'floor(x*128/image_width), floor(y*128/image_height); original image is resized to 512x512 before inference',
            'score':'softmax score, uncalibrated','images':records,'runtime_seconds':round(time.monotonic()-start,3)}
    (output/'manifest.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def _read_semantic_masks(reconstruction: Any, images: Path, mask_dir: Path) -> tuple[dict, dict]:
    manifest=json.loads((mask_dir/'manifest.json').read_text())
    if manifest.get('schema')!='worldstate-multiview-masks/0.1' or manifest.get('model_sha256')!=UperNetOnnxProvider.MODEL_SHA256:
        raise ValueError('semantic mask manifest or model hash mismatch')
    by_name={x['name']:x for x in manifest['images']}
    if len(by_name)!=len(manifest['images']):raise ValueError('duplicate source images in mask manifest')
    records={}
    for image_id in reconstruction.reg_image_ids():
        image=reconstruction.image(image_id);record=by_name.get(image.name)
        if record is None:raise ValueError(f'missing semantic mask for registered image: {image.name}')
        records[image_id]=record
    masks={}
    for image_id,record in records.items():
        image=reconstruction.image(image_id);source=images/image.name
        if Path(image.name).name!=image.name or source.is_symlink() or not source.is_file() or _sha(source)!=record['sha256']:
            raise ValueError('registered source image hash mismatch')
        if record['name']!=image.name or (record['width_px'],record['height_px'])!=(image.camera.width,image.camera.height):
            raise ValueError('semantic mask dimensions or camera mapping mismatch')
        filename=record['mask_file']
        if Path(filename).name!=filename:raise ValueError('invalid mask filename')
        path=mask_dir/filename
        if path.is_symlink() or _sha(path)!=record['mask_sha256']:raise ValueError('semantic mask hash mismatch')
        with np.load(path,allow_pickle=False) as data:
            labels=data['labels'];confidence=data['confidence']
        if labels.shape!=(128,128) or confidence.shape!=(128,128) or not np.isfinite(confidence).all():
            raise ValueError('invalid semantic mask shape')
        masks[image_id]=(labels,confidence)
    return records,masks


def _observation(image: Any, point: Any, point2d_index: int, labels: np.ndarray, confidence: np.ndarray, record: dict) -> dict:
    xy=np.asarray(image.points2D[point2d_index].xy,dtype=float)
    transform=image.cam_from_world();cam_xyz=transform.rotation.matrix()@point.xyz+transform.translation
    if cam_xyz[2]<=0:raise ValueError('COLMAP point is behind camera')
    projected=np.asarray(image.camera.img_from_cam(cam_xyz),dtype=float)
    error=float(np.linalg.norm(projected-xy));width,height=image.camera.width,image.camera.height
    if not (0<=xy[0]<width and 0<=xy[1]<height):raise ValueError('COLMAP observation outside image')
    x=min(127,int(xy[0]*128/width));y=min(127,int(xy[1]*128/height))
    label=int(labels[y,x]);patch=labels[max(0,y-1):min(128,y+2),max(0,x-1):min(128,x+2)]
    neighborhood=float(np.count_nonzero(patch==label)/patch.size)
    score=float(confidence[y,x]);valid=error<=3.0 and neighborhood>=.55 and score>=.30
    return {'image_id':int(image.image_id),'photo':image.name,'photo_sha256':record['sha256'],
            'point2d_index':int(point2d_index),'pixel_xy':xy.tolist(),'mask_xy':[x,y],
            'semantic_class':label,'model_score_uncalibrated':score,'local_label_agreement':neighborhood,
            'reprojection_error_px':error,'usable':bool(valid)}


def _plane_fit(tracks: list[dict], minimum: int, seed: int, up: np.ndarray | None = None, avoid: np.ndarray | None = None) -> tuple[list[dict],float]:
    if len(tracks)<minimum:return [],0.0
    remaining=list(tracks);arr=np.asarray([t['xyz'] for t in tracks]);threshold=float(np.linalg.norm(np.ptp(arr,axis=0))*.01)
    if threshold<1e-9:return [],threshold
    rng=np.random.default_rng(seed);planes=[]
    for index in range(6):
        if len(remaining)<minimum:break
        xyz=np.asarray([t['xyz'] for t in remaining]);best=None
        for _ in range(5000):
            a,b,c=xyz[rng.choice(len(xyz),3,replace=False)];normal=np.cross(b-a,c-a);norm=np.linalg.norm(normal)
            if norm<1e-9:continue
            normal/=norm
            # A gravity-consistency filter, not Manhattan alignment or a forced plane rotation.
            if up is not None and abs(float(normal@up))>.25:continue
            if avoid is not None and abs(float(normal@avoid))>math.cos(math.radians(35)):continue
            mask=np.abs((xyz-a)@normal)<threshold
            if best is None or mask.sum()>best.sum():best=mask
        if best is None or best.sum()<minimum:break
        support=[t for t,yes in zip(remaining,best) if yes];remaining=[t for t,yes in zip(remaining,best) if not yes]
        xyz=np.asarray([t['xyz'] for t in support]);center=xyz.mean(axis=0);_,singular,vh=np.linalg.svd(xyz-center,full_matrices=False)
        normal=vh[-1];normal*=np.sign(normal[np.argmax(np.abs(normal))]);offset=float(-normal@center)
        if (up is not None and abs(float(normal@up))>.30) or (avoid is not None and abs(float(normal@avoid))>math.cos(math.radians(30))):continue
        residual=np.abs((xyz-center)@normal)
        views=sorted({o['image_id'] for t in support for o in t['observations'] if o['usable'] and o['semantic_class']==t['semantic_class']})
        if len(views)<3 or len(singular)<2 or singular[1]/singular[0]<.08:continue
        planes.append({'id':f'raw-plane-{seed}-{index+1}','normal':normal.tolist(),'offset':offset,
            'centroid':center.tolist(),'support_point_ids':[t['id'] for t in support],
            'support_views':views,'support_count':len(support),'fit_rms_arbitrary':float(np.sqrt(np.mean(residual**2))),
            'fit_threshold_arbitrary':threshold,'in_plane_rank_ratio':float(singular[1]/singular[0]),
            'status':'UNVERIFIED_SURFACE_HYPOTHESIS'})
    return planes,threshold


def _combine_wall_planes(planes: list[dict], tracks_by_id: dict[int,dict], threshold: float, up: np.ndarray) -> list[dict]:
    """Merge overlapping near-coplanar fragments provisionally; retain ambiguity."""
    groups=[]
    for p in planes:
        n=np.asarray(p['normal']);c=np.asarray(p['centroid']);joined=False
        for group in groups:
            q=group[0];qn=np.asarray(q['normal']);qc=np.asarray(q['centroid'])
            if abs(float(n@qn))<math.cos(math.radians(12)):continue
            distance=max(abs(float(qn@c+q['offset'])),abs(float(n@qc+p['offset'])))
            if distance>threshold*2:continue
            if len(set(p['support_views'])&set(q['support_views']))<2:continue
            direction=np.cross(up,qn);norm=np.linalg.norm(direction)
            if norm<1e-8:continue
            direction/=norm
            def extent(plane):
                x=np.asarray([tracks_by_id[k]['xyz'] for k in plane['support_point_ids']]);return np.percentile(x@direction,[5,95])
            a,b=extent(p),extent(q);overlap=max(0.,min(a[1],b[1])-max(a[0],b[0]));short=max(1e-9,min(a[1]-a[0],b[1]-b[0]))
            if overlap/short<.25:continue
            group.append(p);joined=True;break
        if not joined:groups.append([p])
    surfaces=[]
    for group in groups:
        ids=sorted({pid for p in group for pid in p['support_point_ids']});xyz=np.asarray([tracks_by_id[x]['xyz'] for x in ids])
        center=xyz.mean(0);_,sv,vh=np.linalg.svd(xyz-center,full_matrices=False);normal=vh[-1]
        normal*=np.sign(normal[np.argmax(np.abs(normal))]);residual=np.abs((xyz-center)@normal)
        view_ids=sorted({v for p in group for v in p['support_views']})
        # This identity is tied to COLMAP track IDs and is not stable across a new SfM solve.
        digest=hashlib.sha256(','.join(map(str,ids)).encode()).hexdigest()[:16]
        view_evidence=[]
        for view_id in view_ids:
            observations=[o for point_id in ids for o in tracks_by_id[point_id]['observations']
                          if o['image_id']==view_id and o['usable'] and o['semantic_class']==0]
            if not observations:continue
            xy=np.asarray([o['pixel_xy'] for o in observations]);view_evidence.append({
                'image_id':view_id,'photo':observations[0]['photo'],'photo_sha256':observations[0]['photo_sha256'],
                'support_observations':len(observations),'support_bbox_px':[xy.min(0).tolist(),xy.max(0).tolist()]})
        surfaces.append({'id':'surface-'+digest,'semantic_class':'wall','normal':normal.tolist(),
            'offset':float(-normal@center),'centroid':center.tolist(),'support_point_ids':ids,
            'support_count':len(ids),'support_views':view_ids,'support_view_count':len(view_ids),'support_photo_evidence':view_evidence,
            'fit_rms_arbitrary':float(np.sqrt(np.mean(residual**2))),
            'spatial_uncertainty':'NOT_QUANTIFIED',
            'fit_threshold_arbitrary':threshold,'raw_plane_ids':[p['id'] for p in group],
            'association':'PROVISIONAL_MERGE_IDENTITY_UNCONFIRMED' if len(group)>1 else 'SINGLE_HYPOTHESIS_IDENTITY_UNCONFIRMED',
            'status':'UNVERIFIED_SURFACE_HYPOTHESIS',
            'unknown':['physical wall identity','unobserved extent','actual thickness','spatial uncertainty not quantified','independent geometric accuracy']})
    return surfaces


def plane_intersection(a: dict, b: dict) -> dict | None:
    """Intersection of two independent 3D planes in the same coordinate frame."""
    n1=np.asarray(a['normal'],float);n2=np.asarray(b['normal'],float);direction=np.cross(n1,n2);norm=float(np.linalg.norm(direction))
    if norm<math.sin(math.radians(5)):return None
    direction/=norm;matrix=np.stack([n1,n2,direction]);rhs=np.array([-a['offset'],-b['offset'],0.])
    if np.linalg.cond(matrix)>100:return None
    point=np.linalg.solve(matrix,rhs)
    return {'point':point.tolist(),'direction':direction.tolist(),'condition_number':float(np.linalg.cond(matrix))}


def fuse_multiview(sparse: Path, images: Path, mask_dir: Path) -> dict[str, Any]:
    """Fuse registered tracks, segment labels and planes without inventing dimensions."""
    start=time.monotonic();reconstruction=pycolmap.Reconstruction(str(sparse));records,masks=_read_semantic_masks(reconstruction,images,mask_dir)
    cameras=[]
    for image_id in sorted(records):
        image=reconstruction.image(image_id);transform=image.cam_from_world()
        cameras.append({'image_id':int(image_id),'photo':image.name,'sha256':records[image_id]['sha256'],
            'width_px':image.camera.width,'height_px':image.camera.height,'camera_model':image.camera.model_name,
            'intrinsics':image.camera.params.tolist(),'rotation_camera_from_world':transform.rotation.matrix().tolist(),
            'translation_camera_from_world':transform.translation.tolist(),'center_world':image.projection_center().tolist()})
    from collections import Counter
    tracks=[];status_counts=Counter()
    for pid,p in sorted(reconstruction.points3D.items()):
        obs=[]
        for t in p.track.elements:
            if t.image_id not in records:continue
            try:obs.append(_observation(reconstruction.image(t.image_id),p,t.point2D_idx,*masks[t.image_id],records[t.image_id]))
            except ValueError:continue
        votes=Counter(o['semantic_class'] for o in obs if o['usable'])
        label,count=votes.most_common(1)[0] if votes else (None,0);total=sum(votes.values());ratio=count/total if total else 0
        status='SUPPORTED' if p.error<=3 and count>=2 and ratio>=.7 else ('SEMANTIC_CONFLICT' if total>=2 and ratio<.7 else 'LOW_SUPPORT_OR_REPROJECTION')
        status_counts[status]+=1
        tracks.append({'id':int(pid),'xyz':p.xyz.tolist(),'mean_reprojection_error_px':float(p.error),
                       'semantic_class':label,'semantic_agreement':ratio,'status':status,'observations':obs})
    supported=[t for t in tracks if t['status']=='SUPPORTED'];by_id={t['id']:t for t in supported}
    floors,floor_threshold=_plane_fit([t for t in supported if t['semantic_class']==3],8,31)
    ceilings,_=_plane_fit([t for t in supported if t['semantic_class']==5],10,53)
    up=None;floor=floors[0] if floors else None
    if floor:
        up=np.asarray(floor['normal']);fpoint=-floor['offset']*up
        centers=np.asarray([c['center_world'] for c in cameras])
        if np.median((centers-fpoint)@up)<0:up=-up
    raw_walls,wall_threshold=_plane_fit([t for t in supported if t['semantic_class']==0],10,7,up)
    # Search one further differently oriented plane instead of letting a noisy
    # dominant wall consume all RANSAC hypotheses. The 35-degree exclusion is
    # only a search filter; it does not force orthogonality or modify geometry.
    if raw_walls and up is not None:
        first=raw_walls[0];used=set(first['support_point_ids'])
        distinct,_=_plane_fit([t for t in supported if t['semantic_class']==0 and t['id'] not in used],
                              12,97,up,np.asarray(first['normal']))
        raw_walls.extend(distinct[:1])
    surfaces=_combine_wall_planes(raw_walls,by_id,wall_threshold,up) if up is not None else []
    lines=[]
    if floor and up is not None:
        floor_point=-floor['offset']*np.asarray(floor['normal'])
        for surface in surfaces:
            line=plane_intersection(surface,floor)
            if not line:continue
            xyz=np.asarray([by_id[k]['xyz'] for k in surface['support_point_ids']]);point=np.asarray(line['point']);direction=np.asarray(line['direction'])
            positions=(xyz-point)@direction;lo,hi=np.percentile(positions,[5,95]);heights=(xyz-floor_point)@up;zlo,zhi=np.percentile(heights,[5,95])
            surface['visible_candidate']={'floor_line_start':(point+lo*direction).tolist(),'floor_line_end':(point+hi*direction).tolist(),
                'visible_height_range_arbitrary':[float(zlo),float(zhi)],'extent_method':'5th–95th percentile of supported sparse 3D tracks; not full wall boundary',
                'boundary_status':'INFERRED_SPARSE_SUPPORT_NOT_COMPLETE'}
            line.update(surface_id=surface['id'],floor_plane_id=floor['id'],visible_extent_arbitrary=[float(lo),float(hi)])
            lines.append(line)
    junctions=[]
    if floor:
        for i,a in enumerate(surfaces):
            for b in surfaces[i+1:]:
                if abs(float(np.dot(a['normal'],b['normal'])))>math.cos(math.radians(20)):continue
                matrix=np.asarray([a['normal'],b['normal'],floor['normal']],float);condition=float(np.linalg.cond(matrix))
                if not math.isfinite(condition) or condition>8:continue
                point=np.linalg.solve(matrix,-np.asarray([a['offset'],b['offset'],floor['offset']]))
                fractions=[]
                for surface in (a,b):
                    extent=surface.get('visible_candidate')
                    if not extent:fractions.append(None);continue
                    line_start=np.asarray(extent['floor_line_start']);line_end=np.asarray(extent['floor_line_end']);direction=line_end-line_start
                    fractions.append(float((point-line_start)@direction/(direction@direction)))
                junctions.append({'surfaces':[a['id'],b['id']],'xyz':point.tolist(),'condition_number':condition,
                    'fractions_along_projected_support':fractions,
                    'status':'INFERRED_PLANE_INTERSECTION_NOT_OBSERVED_CORNER','visibility':'UNKNOWN',
                    'note':'Do not join or truncate walls without confirmation; the intersection may be inside or beyond sparse support.'})
    ambiguous=[]
    for i,a in enumerate(surfaces):
        for b in surfaces[i+1:]:
            angle=math.degrees(math.acos(float(np.clip(abs(np.dot(a['normal'],b['normal'])),-1,1))))
            if angle<20 and len(set(a['support_views'])&set(b['support_views']))>=2:
                ambiguous.append({'surfaces':[a['id'],b['id']],'angle_deg':angle,
                    'status':'POSSIBLE_DUPLICATE_OR_NEAR_PARALLEL_DISTINCT_WALLS_REVIEW_REQUIRED'})
    return {'schema':'worldstate-multiview-semantic-fusion/0.1','status':'UNVERIFIED_DEVELOPMENT_CANDIDATE',
      'coordinate_system':{'name':'COLMAP world','unit':'arbitrary','scale_status':'UNKNOWN',
                           'camera_convention':'x_camera = R_camera_from_world @ x_world + t; pixel = K @ x_camera / z'},
      'model_sha256':UperNetOnnxProvider.MODEL_SHA256,
      'source_reconstruction':[{"file":x.name,"sha256":_sha(x)} for x in sorted(sparse.glob('*.bin'))],
      'semantic_manifest_sha256':_sha(mask_dir/'manifest.json'),'cameras':cameras,'tracks':tracks,'track_status_counts':dict(status_counts),
      'floor_planes':floors,'ceiling_planes':ceilings,'raw_wall_planes':raw_walls,'wall_surfaces':surfaces,
      'floor_wall_intersections':lines,'wall_junctions':junctions,'ambiguous_surface_pairs':ambiguous,'floor_up':up.tolist() if up is not None else None,
      'runtime_seconds':round(time.monotonic()-start,3),
      'limitations':['semantic scores are uncalibrated','plane fit residual is not independent wall accuracy',
        'wall identities, corners and unseen extents are unverified','gravity-based vertical-wall filter is an explicit assumption',
        '3D support is sparse and not a complete wall boundary','scale and thickness are unknown',
        'surface identity uses current COLMAP track IDs; a new reconstruction needs association']}


def _camera_matrix(camera: dict) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    model=camera.get('camera_model');params=camera.get('intrinsics',[])
    if model=='SIMPLE_PINHOLE' and len(params)==3:f,cx,cy=params;fx=fy=f
    elif model=='PINHOLE' and len(params)==4:fx,fy,cx,cy=params
    else:raise ValueError('triangulation requires an undistorted pinhole camera')
    K=np.array([[fx,0,cx],[0,fy,cy],[0,0,1]],dtype=float)
    R=np.asarray(camera.get('rotation_camera_from_world'),dtype=float);t=np.asarray(camera.get('translation_camera_from_world'),dtype=float)
    if R.shape!=(3,3) or t.shape!=(3,) or not np.isfinite(K).all() or not np.isfinite(R).all() or not np.isfinite(t).all() or fx<=0 or fy<=0:
        raise ValueError('invalid camera calibration')
    if not np.allclose(R.T@R,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(R),1,atol=1e-5):raise ValueError('invalid camera rotation')
    return K,R,t


def triangulate_observations(cameras: list[dict], observations: list[dict], *, max_reprojection_px: float = 3.0,
                             min_parallax_degrees: float = 1.0) -> dict:
    """Triangulate one physical point from distinct registered camera observations.

    This checks reprojection, cheirality and parallax; it does not verify that
    the user associated the same physical point in every image.
    """
    if not isinstance(observations,list) or len(observations)<2:raise ValueError('至少需要两个不同视角的同一端点')
    by_id={c['image_id']:c for c in cameras};used=set();rows=[];validated=[]
    for obs in observations:
        image_id=obs.get('image_id');camera=by_id.get(image_id)
        if camera is None or image_id in used:raise ValueError('端点观测需要不同的已注册照片')
        if obs.get('photo_sha256')!=camera['sha256']:raise ValueError('端点观测照片哈希不匹配')
        xy=np.asarray(obs.get('pixel_xy'),dtype=float)
        if xy.shape!=(2,) or not np.isfinite(xy).all() or not (0<=xy[0]<camera['width_px'] and 0<=xy[1]<camera['height_px']):
            raise ValueError('端点像素坐标无效')
        K,R,t=_camera_matrix(camera);P=K@np.column_stack((R,t))
        for row in (xy[0]*P[2]-P[0],xy[1]*P[2]-P[1]):
            norm=np.linalg.norm(row[:3])
            if norm<1e-12:raise ValueError('相机投影矩阵退化')
            rows.append(row/norm)
        used.add(image_id);validated.append((obs,camera,K,R,t,xy))
    centers=[-R.T@t for _,_,_,R,t,_ in validated]
    if max(np.linalg.norm(centers[i]-centers[j]) for i in range(len(centers)) for j in range(i+1,len(centers)))<1e-9:
        raise ValueError('相机基线为零，三角化退化')
    _,singular,vh=np.linalg.svd(np.asarray(rows),full_matrices=False);h=vh[-1]
    if abs(h[3])<1e-10 or singular[-2]<1e-10:raise ValueError('三角化退化')
    xyz=h[:3]/h[3];errors=[];rays=[];detail=[]
    for obs,camera,K,R,t,xy in validated:
        point=R@xyz+t
        if point[2]<=1e-9:raise ValueError('三角化点位于相机后方')
        projected=K@point;projected=projected[:2]/projected[2];err=float(np.linalg.norm(projected-xy));errors.append(err)
        center=-R.T@t;ray=xyz-center;length=np.linalg.norm(ray)
        if length<1e-9:raise ValueError('三角化点与相机重合')
        rays.append(ray/length);detail.append({'image_id':obs['image_id'],'pixel_xy':xy.tolist(),'reprojection_error_px':err})
    max_angle=max(math.degrees(math.acos(float(np.clip(rays[i]@rays[j],-1,1)))) for i in range(len(rays)) for j in range(i+1,len(rays)))
    if max(errors)>max_reprojection_px:raise ValueError('端点跨视图重投影误差过大，可能是错误对应')
    if max_angle<min_parallax_degrees:raise ValueError('端点视差不足，三角化退化')
    return {'xyz':xyz.tolist(),'observations':detail,'max_reprojection_error_px':max(errors),
            'rms_reprojection_error_px':float(np.sqrt(np.mean(np.square(errors)))),
            'max_parallax_degrees':max_angle,'uncertainty':'NOT_QUANTIFIED',
            'status':'MULTIVIEW_TRIANGULATED_CORRESPONDENCE_UNVERIFIED'}


def _anchor_snapshot(fusion: dict, anchor: dict) -> dict:
    if anchor.get('schema')!='worldstate-multiview-scale-anchor/0.1' or anchor.get('confirmed') is not True:
        raise ValueError('请确认多视图尺度端点与物理测量')
    basis=anchor.get('basis');length=anchor.get('distance_m');sigma=anchor.get('measurement_uncertainty_m');description=anchor.get('description')
    if basis not in {'independent_user_declared','same_sensor','assumed'}:raise ValueError('尺度来源必须明确声明')
    if isinstance(length,bool) or not isinstance(length,(int,float)) or not math.isfinite(length) or length<=0:raise ValueError('尺度长度无效')
    if sigma is None:
        if basis!='assumed':raise ValueError('实测尺度需要记录测量不确定性')
    elif isinstance(sigma,bool) or not isinstance(sigma,(int,float)) or not math.isfinite(sigma) or sigma<=0:
        raise ValueError('测量不确定性须为正数，假设尺度可标记未知')
    if not isinstance(description,str) or not description.strip() or len(description)>500:raise ValueError('请记录尺度测量来源和实际端点')
    endpoints=anchor.get('endpoints')
    if not isinstance(endpoints,list) or len(endpoints)!=2 or endpoints[0].get('id')==endpoints[1].get('id'):
        raise ValueError('需要两个不同的物理尺度端点')
    cameras={c['image_id']:c for c in fusion['cameras']};referenced=set()
    for endpoint in endpoints:
        if not isinstance(endpoint.get('id'),str) or not endpoint['id'].strip():raise ValueError('尺度端点需要标识')
        obs=endpoint.get('observations')
        if not isinstance(obs,list) or len(obs)<2:raise ValueError('每个尺度端点至少需要两个视角')
        referenced.update(x.get('image_id') for x in obs)
    if not referenced<=set(cameras):raise ValueError('尺度端点使用了未注册照片')
    # The complete calibration and source image hash are part of the binding.
    # Bind the whole reconstruction, not just the cameras containing the ruler:
    # a later camera/pose update can change the shared world coordinate frame.
    selected=[cameras[x] for x in sorted(cameras)]
    snapshot={'anchor':anchor,'cameras':selected,'source_reconstruction':fusion.get('source_reconstruction'),
              'coordinate_system':fusion['coordinate_system']}
    return json.loads(json.dumps(snapshot,sort_keys=True,allow_nan=False))


def solve_multiview_scale(fusion: dict, anchor: dict) -> dict:
    """Apply one declared physical distance to two multiview-triangulated points."""
    if fusion.get('coordinate_system',{}).get('scale_status')!='UNKNOWN':raise ValueError('尺度已应用；请从原始坐标重新求解')
    snapshot=_anchor_snapshot(fusion,anchor)
    ends=[triangulate_observations(fusion['cameras'],e['observations']) for e in anchor['endpoints']]
    distance=float(np.linalg.norm(np.asarray(ends[1]['xyz'])-np.asarray(ends[0]['xyz'])))
    if distance<1e-8:raise ValueError('尺度端点三维距离退化')
    factor=float(anchor['distance_m']/distance)
    fingerprint=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return {'schema':'worldstate-multiview-scale-solution/0.1','binding_sha256':fingerprint,
            'metres_per_sfm_unit':factor,'reference_distance_arbitrary':distance,
            'reference_distance_m':float(anchor['distance_m']),'measurement_uncertainty_m':(float(anchor['measurement_uncertainty_m']) if anchor['measurement_uncertainty_m'] is not None else None),
            'basis':anchor['basis'],'description':anchor['description'],'endpoint_solutions':ends,
            'measurement_only_scale_uncertainty_m_per_unit':(float(anchor['measurement_uncertainty_m'])/distance if anchor['measurement_uncertainty_m'] is not None else None),
            'applicability':'Uniform scale for the bound COLMAP reconstruction and its registered geometry only; not georeferenced.',
            'fitted_constraint_residual_m':abs(factor*distance-anchor['distance_m']),
            'uncertainty':('measurement uncertainty is unknown; triangulation and scale uncertainty NOT_QUANTIFIED' if anchor['measurement_uncertainty_m'] is None else 'measurement uncertainty recorded; triangulation and scale uncertainty NOT_QUANTIFIED'),
            'verification':'USER_DECLARATION_NOT_INDEPENDENTLY_VERIFIED',
            'warning':'The fitted anchor residual is tautological, not independent accuracy.'}


def apply_multiview_scale(fusion: dict, anchor: dict, solution: dict) -> dict:
    """Scale every spatial quantity only if the exact source binding is current."""
    import copy
    snapshot=_anchor_snapshot(fusion,anchor)
    digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if solution.get('schema')!='worldstate-multiview-scale-solution/0.1' or solution.get('binding_sha256')!=digest:
        raise ValueError('尺度端点、测量或相机已改变；请重新求解')
    fresh=solve_multiview_scale(fusion,anchor)
    if not math.isclose(solution.get('metres_per_sfm_unit',0),fresh['metres_per_sfm_unit'],rel_tol=1e-10,abs_tol=1e-10):
        raise ValueError('尺度解与当前端点不一致')
    factor=fresh['metres_per_sfm_unit'];out=copy.deepcopy(fusion)
    def vec(v):return (np.asarray(v,dtype=float)*factor).tolist()
    for c in out['cameras']:
        c['center_world']=vec(c['center_world']);c['translation_camera_from_world']=vec(c['translation_camera_from_world'])
    for t in out['tracks']:t['xyz']=vec(t['xyz'])
    for group in ('floor_planes','ceiling_planes','raw_wall_planes','wall_surfaces'):
        for p in out[group]:
            p['offset']*=factor;p['centroid']=vec(p['centroid']);p['fit_rms_m']=p.pop('fit_rms_arbitrary')*factor;p['fit_threshold_m']=p.pop('fit_threshold_arbitrary')*factor
            v=p.get('visible_candidate')
            if v:
                v['floor_line_start']=vec(v['floor_line_start']);v['floor_line_end']=vec(v['floor_line_end'])
                v['visible_height_range_m']=vec(v.pop('visible_height_range_arbitrary'))
    for line in out['floor_wall_intersections']:
        line['point']=vec(line['point']);line['visible_extent_m']=vec(line.pop('visible_extent_arbitrary'))
    for junction in out['wall_junctions']:junction['xyz']=vec(junction['xyz'])
    out['coordinate_system']={'name':'scaled COLMAP world','unit':'m','scale_status':anchor['basis'],
                              'camera_convention':'x_camera = R_camera_from_world @ x_world + t; pixel = K @ x_camera / z'}
    out['scale_solution']=fresh
    out['limitations'].append('metre scale is based on a user declaration and is not independently verified')
    return out


def build_multiview_room(fusion: dict, anchor: dict, solution: dict, selected_surface_ids: list[str],
                         *, project_id: str, assumed_thickness_m: float,
                         confirmed_candidates: bool, allow_assumed_scale: bool = False, operator_kind: str = "user") -> dict:
    """Compile selected 3D surfaces to partial Room IR with explicit assumptions.

    The extent is the sparse observed-support interval, not an inferred full
    room boundary. Plane intersections are not silently turned into topology.
    """
    from .room_ir import SCHEMA, geometry_issues, quantity, validate_room
    if confirmed_candidates is not True:raise ValueError('请先检查并确认三维墙面候选')
    if operator_kind not in {'user','automation'}:raise ValueError('候选选择来源无效')
    if anchor.get('basis')!='independent_user_declared' and allow_assumed_scale is not True:
        raise ValueError('非独立或假设尺度必须明确允许，仅可生成未验证草稿')
    if not isinstance(project_id,str) or not project_id.strip() or len(project_id)>120:raise ValueError('项目标识无效')
    if isinstance(assumed_thickness_m,bool) or not isinstance(assumed_thickness_m,(int,float)) or not 0<assumed_thickness_m<=2:
        raise ValueError('未知墙厚必须给出明确的正数假设')
    if not isinstance(selected_surface_ids,list) or not selected_surface_ids or len(set(selected_surface_ids))!=len(selected_surface_ids):
        raise ValueError('请选择不重复的墙面候选')
    scaled=apply_multiview_scale(fusion,anchor,solution)
    surfaces={s['id']:s for s in scaled['wall_surfaces']}
    if any(i not in surfaces or not surfaces[i].get('visible_candidate') for i in selected_surface_ids):
        raise ValueError('所选墙面缺少可用的三维可见范围')
    for pair in scaled.get('ambiguous_surface_pairs',[]):
        if set(pair['surfaces'])<=set(selected_surface_ids):
            raise ValueError('所选墙面可能重复或靠近；请人工区分后再导出')
    if not scaled['floor_planes'] or scaled.get('floor_up') is None:raise ValueError('地面支持不足，无法确定房间坐标系')
    floor=scaled['floor_planes'][0];up=np.asarray(scaled['floor_up'],float);floor_origin=-float(floor['offset'])*np.asarray(floor['normal'],float)
    first=surfaces[selected_surface_ids[0]]['visible_candidate'];xaxis=np.asarray(first['floor_line_end'])-np.asarray(first['floor_line_start'])
    xaxis-=up*float(xaxis@up);length=np.linalg.norm(xaxis)
    if length<1e-7:raise ValueError('墙面方向退化')
    xaxis/=length;yaxis=np.cross(up,xaxis);yaxis/=np.linalg.norm(yaxis)
    def local(point):
        delta=np.asarray(point,float)-floor_origin
        return [float(delta@xaxis),float(delta@yaxis),float(delta@up)]
    tracks={t['id']:t for t in scaled['tracks']};photos={c['image_id']:c for c in scaled['cameras']}
    evidence=[{'id':'selection-multiview-1','kind':'candidate_selection','operator':operator_kind,
               'status':'user_selection_unverified' if operator_kind=='user' else 'scripted_selection_not_human'},
              {'id':'cameras-multiview-1','kind':'multiview_camera_reconstruction',
               'registered_cameras':scaled['cameras'],'source_reconstruction':fusion['source_reconstruction'],
               'calibration':fusion.get('camera_calibration'),'status':'inferred_unverified'},
              {'id':'scale-multiview-1','kind':'multiview_scale_anchor','anchor':anchor,'solution':scaled['scale_solution'],
               'status':'user_declared_unverified' if anchor['basis']=='independent_user_declared' else anchor['basis']},
              {'id':'floor-multiview-1','kind':'multiview_semantic_floor','plane':floor,
               'source_model_sha256':fusion['model_sha256'],'status':'inferred_unverified'},
              {'id':'thickness-assumption-1','kind':'user_assumption','value_m':float(assumed_thickness_m),
               'description':'wall thickness is unobserved; explicit assumption for IFC geometry'}]
    for c in scaled['cameras']:
        evidence.append({'id':'photo-'+c['sha256'][:16],'kind':'image','sha256':c['sha256'],
                         'width_px':c['width_px'],'height_px':c['height_px'],'captured_at':'UNKNOWN',
                         'authorization':'user_supplied_unverified'})
    nodes=[];walls=[]
    for surface_id in selected_surface_ids:
        surface=surfaces[surface_id];visible=surface['visible_candidate'];refs=[]
        for point_id in surface['support_point_ids']:
            track=tracks[point_id]
            for obs in track['observations']:
                refs.append({'point3d_id':point_id,'image_id':obs['image_id'],
                    'photo_ref':'photo-'+obs['photo_sha256'][:16],'photo_sha256':obs['photo_sha256'],
                    'pixel_xy':obs['pixel_xy'],'semantic_class':obs['semantic_class'],'usable':obs['usable'],
                    'reprojection_error_px':obs['reprojection_error_px']})
        source_id='evidence-'+surface_id
        evidence.append({'id':source_id,'kind':'multiview_semantic_surface',
            'surface_id':surface_id,'persistent_id':surface.get('persistent_id',surface_id),'plane':{'normal':surface['normal'],'offset_m':surface['offset']},
            'support_point_ids':surface['support_point_ids'],'support_view_count':surface['support_view_count'],
            'support_photo_evidence':surface['support_photo_evidence'],'observations':refs,
            'fit_rms_m':surface['fit_rms_m'],'association':surface['association'],
            'source_reconstruction':fusion['source_reconstruction'],'status':'inferred_unverified'})
        a=local(visible['floor_line_start']);b=local(visible['floor_line_end'])
        if math.dist(a[:2],b[:2])<1e-4:raise ValueError('墙面可见长度退化')
        low,high=visible['visible_height_range_m']
        if high-low<1e-4:raise ValueError('墙面高度支持不足')
        persistent_id=surface.get('persistent_id',surface_id)
        if not isinstance(persistent_id,str) or not persistent_id.startswith('surface-'):raise ValueError('墙面持续身份无效')
        wall_id='wall-'+persistent_id[8:];node_a=wall_id+'-a';node_b=wall_id+'-b'
        node_refs=[source_id,'floor-multiview-1','scale-multiview-1','cameras-multiview-1']
        nodes.extend([{'id':node_a,'x':a[0],'y':a[1],'status':'inferred','evidence_refs':node_refs},
                      {'id':node_b,'x':b[0],'y':b[1],'status':'inferred','evidence_refs':node_refs}])
        walls.append({'id':wall_id,'ifc_type':'IfcWall','start':node_a,'end':node_b,'storey':'storey-1',
            'classification':{'status':'inferred','evidence_refs':[source_id]},
            'parameters':{'height':quantity(high-low,'inferred',node_refs,'Visible sparse-support height, not full wall height'),
                          'base_elevation':quantity(low,'inferred',node_refs,'Visible sparse-support lower extent, not confirmed floor contact'),
                          'thickness':quantity(assumed_thickness_m,'assumed',['thickness-assumption-1'],'Unobserved wall thickness')},
            'unknown':['wall-instance identity','full wall extent and floor/top contact','actual wall thickness',
                       'occluded openings and adjacent topology','spatial uncertainty not quantified','independent scale and dimension accuracy']})
    # A scripted confirmation reproduces an assisted workflow; it does not
    # turn candidate selection and an assumed scale into automatic modeling.
    model={'schema':SCHEMA,'project_id':project_id,'mode':'assisted','revision':1,
        'coordinate_system':{'name':'floor-aligned local frame from scaled COLMAP','unit':'m','georeferencing':'UNKNOWN',
          'origin_in_scaled_colmap':floor_origin.tolist(),'x_axis_in_colmap':xaxis.tolist(),
          'y_axis_in_colmap':yaxis.tolist(),'z_axis_in_colmap':up.tolist()},
        'evidence':evidence,'nodes':nodes,'storeys':[{'id':'storey-1','elevation':quantity(0,'assumed',['floor-multiview-1'],'Local floor datum; not surveyed')}],
        'elements':walls,'constraints':[],
        'scale':{'status':'applied','independence':anchor['basis'],'anchor_ref':'scale-multiview-1',
                 'metres_per_relative_unit':solution['metres_per_sfm_unit'],'binding_sha256':solution['binding_sha256']},
        'validation':{'status':'UNVERIFIED_DRAFT','scope':'PARTIAL_OPEN',
          'warning':'3D multiview sparse surface candidates; visibility extents, identities, connections and scale are not independently validated'}}
    validate_room(model);issues=geometry_issues(model)
    if issues:raise ValueError('几何冲突：'+', '.join(f"{x['id']}:{x['code']}" for x in issues))
    return model


def associate_surface_identities(previous: dict, current: dict) -> dict:
    """Match candidate identities across SfM versions by shared image observations.

    Matching is provisional, not proof of semantic wall identity. Ambiguous or
    weak matches remain unresolved; coordinates are never compared across
    unrelated SfM frames without alignment.
    """
    def signatures(fusion):
        tracks={t['id']:t for t in fusion['tracks']};result={}
        for surface in fusion['wall_surfaces']:
            result[surface['id']]={(o['photo_sha256'],round(o['pixel_xy'][0],1),round(o['pixel_xy'][1],1))
              for pid in surface['support_point_ids'] for o in tracks[pid]['observations']
              if o['usable'] and o['semantic_class']==0}
        return result
    left,right=signatures(previous),signatures(current);scores=[]
    for old_id,a in left.items():
        for new_id,b in right.items():
            shared=a&b;views=len({v[0] for v in shared});ratio=len(shared)/min(len(a),len(b)) if a and b else 0
            if len(shared)>=10 and views>=3 and ratio>=.5:
                scores.append({'previous_surface_id':old_id,'current_surface_id':new_id,
                               'shared_observations':len(shared),'shared_views':views,'overlap_ratio':ratio})
    matches=[]
    for item in sorted(scores,key=lambda x:-x['overlap_ratio']):
        alternatives_old=sorted([x['overlap_ratio'] for x in scores if x['previous_surface_id']==item['previous_surface_id']],reverse=True)
        alternatives_new=sorted([x['overlap_ratio'] for x in scores if x['current_surface_id']==item['current_surface_id']],reverse=True)
        if item['overlap_ratio']!=alternatives_old[0] or item['overlap_ratio']!=alternatives_new[0]:continue
        if len(alternatives_old)>1 and alternatives_old[0]-alternatives_old[1]<.15:continue
        if len(alternatives_new)>1 and alternatives_new[0]-alternatives_new[1]<.15:continue
        old=next(s for s in previous['wall_surfaces'] if s['id']==item['previous_surface_id'])
        item['persistent_id']=old.get('persistent_id',old['id']);item['status']='PROVISIONAL_SHARED_FEATURE_ASSOCIATION';matches.append(item)
    return {'schema':'worldstate-surface-association/0.1','matches':matches,
            'unmatched_previous':[s['id'] for s in previous['wall_surfaces'] if not any(m['previous_surface_id']==s['id'] for m in matches)],
            'unmatched_current':[s['id'] for s in current['wall_surfaces'] if not any(m['current_surface_id']==s['id'] for m in matches)],
            'warning':'Shared image features link candidate surfaces; they do not independently verify physical wall identity.'}
