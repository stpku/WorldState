"""Extract development-only image observations around kicker's yellow door.

The image names, color threshold and ceiling-line search corridors were chosen
by an AI analyst inspecting the real development photographs. The coordinates
below seed image processing, not room geometry. Output is automation, not a
human annotation or independent test; no scan is opened by this script.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import pycolmap

# Four photo-specific search corridors, chosen from inspected photographs.
# Each tuple is (x_min, x_max, seed_x1, seed_y1, seed_x2, seed_y2).
SEARCH={'DSC_6497.JPG':(1800,2600,1600,1402,2600,1369),
        'DSC_6508.JPG':(3400,4200,3705.6,795.8,3870.6,788.7),
        'DSC_6515.JPG':(3050,3950,3481.9,664.9,3670.6,660.9),
        'DSC_6509.JPG':(2800,3500,3066.8,830.1,3173.2,835.2)}
TRAIN=('DSC_6497.JPG','DSC_6508.JPG','DSC_6515.JPG');HOLDOUT='DSC_6509.JPG'


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def features(image: np.ndarray, corridor: tuple) -> tuple[dict,dict,np.ndarray]:
    height,width=image.shape[:2];small=cv2.resize(image,(1553,1034));hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(13,70,50),(40,255,255));contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:raise ValueError('no yellow candidate')
    contour=max(contours,key=cv2.contourArea);x,y,w,h=cv2.boundingRect(contour)
    if w*h<10000 or h<w:raise ValueError('yellow candidate is too small or not door-like')
    poly=cv2.approxPolyDP(contour,.002*cv2.arcLength(contour,True),True).reshape(-1,2).astype(float)
    if len(poly)<3:raise ValueError('door contour is degenerate')
    converted=poly*np.array([width/1553,height/1034]);score=converted[:,0]+converted[:,1];difference=converted[:,0]-converted[:,1]
    corners={'left_top':converted[np.argmin(score)].tolist(),'right_top':converted[np.argmax(difference)].tolist(),
             'right_bottom':converted[np.argmax(score)].tolist()}
    x0,x1,sx,sy,tx,ty=corridor;gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);xs=[];ys=[]
    for xx in np.linspace(x0,x1,101).astype(int):
        yy=int(round(sy+(ty-sy)*(xx-sx)/(tx-sx)));lo=yy-10;hi=yy+11
        if lo<6 or hi+6>=height or xx<15 or xx+16>=width:raise ValueError('search corridor out of bounds')
        profile=np.mean(gray[lo-6:hi+6,xx-15:xx+16],axis=1).astype(float)
        smooth=cv2.GaussianBlur(profile.reshape(-1,1),(1,1),1).ravel();gradient=np.gradient(smooth)
        xs.append(xx);ys.append(int(np.argmax(gradient[6:-6]))+lo)
    xs=np.asarray(xs);ys=np.asarray(ys);fit=np.polyfit(xs,ys,1);inlier=np.abs(ys-np.polyval(fit,xs))<3
    if inlier.sum()<80:raise ValueError('ceiling edge search is inconsistent')
    fit=np.polyfit(xs[inlier],ys[inlier],1);rms=float(np.sqrt(np.mean((ys[inlier]-np.polyval(fit,xs[inlier]))**2)))
    line={'points_px':[[float(x0),float(np.polyval(fit,x0))],[float(x1),float(np.polyval(fit,x1))]],
          'corridor_seed_px':list(corridor),'edge_samples':len(xs),'line_fit_inliers':int(inlier.sum()),'line_fit_rms_px':rms}
    return corners,line,mask


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--reconstruction',type=Path,required=True);p.add_argument('--pixcuboid',type=Path)
    p.add_argument('--camera-mode',choices=('known-pose','photo-only'),default='known-pose')
    p.add_argument('--masks',type=Path,help='Optional precomputed UPerNet masks from this reconstruction')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    manifest=json.loads((a.input/'manifest.json').read_text());records={x['file']:x for x in manifest['modeling_images']}
    pred=json.loads(a.pixcuboid.read_text()) if a.pixcuboid else None
    if manifest.get('schema')!='worldstate-eth3d-kicker-photo-input/0.1' or (pred is not None and pred.get('schema')!='worldstate-pixcuboid-candidate/0.1'):raise ValueError('unexpected source')
    if a.camera_mode=='known-pose' and pred is None:raise ValueError('known-pose PixCuboid experiment needs its prior')
    bins=[{'file':f.name,'sha256':sha(f)} for f in sorted(a.reconstruction.glob('*.bin'))]
    if pred is not None and bins!=pred['source_reconstruction']:raise ValueError('camera source differs from PixCuboid input')
    rec=pycolmap.Reconstruction(a.reconstruction);images={im.name:im for im in rec.images.values()}
    a.output.mkdir(parents=True);cameras=[];extracted={}
    for name in (*TRAIN,HOLDOUT):
        path=a.input/'photos'/name;record=records[name]
        if path.is_symlink() or not path.is_file() or sha(path)!=record['sha256']:raise ValueError('photo hash mismatch')
        im=images[name];camera=im.camera;pose=im.cam_from_world();raw=cv2.imread(str(path))
        if raw is None or raw.shape[:2]!=(camera.height,camera.width):raise ValueError('photo/camera mismatch')
        corners,line,_=features(raw,SEARCH[name]);cam={'image_id':im.image_id,'photo':name,'sha256':record['sha256'],
            'camera_model':camera.model_name,'intrinsics':camera.params.tolist(),'width_px':camera.width,'height_px':camera.height,
            'rotation_camera_from_world':pose.rotation.matrix().tolist(),'translation_camera_from_world':pose.translation.tolist()}
        line.update(image_id=im.image_id,photo_sha256=record['sha256'],photo=name,origin='ai_selected_corridor_plus_image_gradient')
        cameras.append(cam);extracted[name]={'corners':corners,'line':line}
        preview=cv2.resize(raw,(1553,1034));scale=np.array([1553/camera.width,1034/camera.height])
        for label,xy in corners.items():
            point=tuple(np.round(np.array(xy)*scale).astype(int));cv2.circle(preview,point,8,(0,0,255),2)
            cv2.putText(preview,label,(point[0]+8,point[1]-8),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,255),1)
        ends=[tuple(np.round(np.array(pt)*scale).astype(int)) for pt in line['points_px']]
        cv2.line(preview,*ends,(0,255,255),2);cv2.putText(preview,'AI development observations; unverified',(20,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,255),2)
        if not cv2.imwrite(str(a.output/(Path(name).stem+'-observation.jpg')),preview):raise OSError('failed to write preview')
    def point(name,corner):
        return {'image_id':images[name].image_id,'photo_sha256':records[name]['sha256'],'photo':name,
                'pixel_xy':extracted[name]['corners'][corner],'origin':'opencv_yellow_component_corner',
                'operator_kind':'automation'}
    common={'schema':'worldstate-local-wall-observations/0.1','operator':'automation_ai_visual_selection',
        'camera_mode':('ETH3D_KNOWN_POSE_SCANNER_REGISTERED_NOT_PHOTO_ONLY' if a.camera_mode=='known-pose'
                       else 'PHOTO_ONLY_COLMAP_ARBITRARY_SCALE'),
        'source_reconstruction':bins,'source_manifest_sha256':sha(a.input/'manifest.json'),
        'observation_method':'AI-selected real images and corridors; OpenCV yellow-component corners and observed ceiling-edge gradients',
        'limitations':['No human annotation or human efficiency was measured.',
            'Door leaf corners and wall face may not be coplanar; their offset is unknown.',
            'Ceiling-line association is an AI-selected development hypothesis, not human verified.',
            'No laser scan, independent scale measurement or reference IFC was read.']}
    semantic=[]
    if a.masks:
        mask_manifest=json.loads((a.masks/'manifest.json').read_text())
        if mask_manifest.get('schema')!='worldstate-multiview-masks/0.1':raise ValueError('unexpected mask manifest')
        mask_records={x['image_id']:x for x in mask_manifest['images']}
        for cam in cameras:
            if cam['photo'] not in TRAIN:continue
            record=mask_records[cam['image_id']]
            name=record['mask_file'];mask_path=a.masks/name
            if (Path(name).name!=name or record['sha256']!=cam['sha256'] or record['name']!=cam['photo']
                or mask_path.is_symlink() or sha(mask_path)!=record['mask_sha256']):raise ValueError('mask/photo hash mismatch')
            with np.load(mask_path,allow_pickle=False) as arrays:labels=arrays['labels']
            if labels.shape!=(128,128) or labels.dtype!=np.uint8:raise ValueError('invalid semantic labels')
            semantic.append({'image_id':cam['image_id'],'photo_sha256':cam['sha256'],'shape':[128,128],
                'label':'wall_ADE20K_0','wall_mask_packbits_base64':base64.b64encode(np.packbits(labels==0).tobytes()).decode(),
                'mask_sha256':record['mask_sha256'],'model_sha256':mask_manifest['model_sha256'],
                'status':'uncalibrated_semantic_hypothesis_not_independent_ground_truth'})
    train={**common,'cameras':[c for c in cameras if c['photo'] in TRAIN],
        'corners':{'left_top':[point(n,'left_top') for n in TRAIN],
                   'right_top':[point(n,'right_top') for n in TRAIN],
                   'right_bottom':[point(n,'right_bottom') for n in ('DSC_6508.JPG','DSC_6515.JPG')]},
        'ceiling_lines':[extracted[n]['line'] for n in TRAIN], 'semantic_views':semantic}
    hold={**common,'cameras':[c for c in cameras if c['photo']==HOLDOUT],
        'corners':{'left_top':[point(HOLDOUT,'left_top')],'right_top':[point(HOLDOUT,'right_top')]},
        'ceiling_lines':[extracted[HOLDOUT]['line']],
        'scope':'Excluded from optimization, but selected after development-scene inspection; not blind or independent.'}
    for n,obj in [('training.json',train),('holdout.json',hold)]:
        (a.output/n).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'training_photos':len(TRAIN),'holdout_photos':1,'image_observations':sum(map(len,train['corners'].values())),
                      'operator':common['operator'],'output':str(a.output)},indent=2))


if __name__=='__main__':main()
