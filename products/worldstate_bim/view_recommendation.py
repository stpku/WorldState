"""Local, evidence-limited view ranking for an existing multiview surface.

Projection and camera angles do not establish that a wall is visible: furniture,
semantic errors and unmodeled occlusion must be checked in the source images.
"""
from __future__ import annotations

import hashlib
import itertools
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, box

from .general_modeler import _project, camera_digest, digest
from .multiview_fusion import _camera_matrix, triangulate_observations


def recommend_views(workspace: Path, state: dict, uploads: list[dict], object_id: str) -> dict:
    """Rank view pairs by object projection, viewpoint angle and local image evidence."""
    solution = state.get('solution') or {}
    if solution:
        from .studio_modeler import _data
        if state.get('model_dirty') or solution.get('input_sha256') != digest(_data(state)):
            return {'status':'STALE_OBJECT_GEOMETRY','object_id':object_id,'views':[],'pairs':[],
                    'warning':'对象观察或相机已变化；请先重新求解后再推荐视角。'}
    observations = [o for o in state.get('observations', []) if o.get('object_id') == object_id and
                    o.get('visibility') == 'visible' and o.get('confirmation') not in {'rejected', 'proposed'}]
    available = {x['sha256']:x for x in uploads}
    camera_index={c['image_id']:c for c in state.get('cameras',[])}
    for ident in {o.get('image_id') for o in observations}:
        camera=camera_index.get(ident);item=available.get(camera.get('sha256')) if camera else None
        if not item:
            return {'status':'SOURCE_EVIDENCE_UNAVAILABLE','object_id':object_id,'views':[],'pairs':[],
                    'warning':'对象的原始照片或相机不可用，请先恢复证据。'}
        path=workspace/'evidence'/(item['sha256']+item['extension'])
        if path.is_symlink() or not path.is_file():
            return {'status':'SOURCE_EVIDENCE_UNAVAILABLE','object_id':object_id,'views':[],'pairs':[],
                    'warning':'对象的原始照片不可用，请先恢复证据。'}
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=camera['sha256']:
                return {'status':'SOURCE_EVIDENCE_UNAVAILABLE','object_id':object_id,'views':[],'pairs':[],
                        'warning':'对象原始照片哈希不符，请先核验证据。'}
        if any(o.get('camera_sha256')!=camera_digest(camera) or o.get('photo_sha256')!=camera['sha256']
               for o in observations if o.get('image_id')==ident):
            return {'status':'SOURCE_EVIDENCE_UNAVAILABLE','object_id':object_id,'views':[],'pairs':[],
                    'warning':'对象观察所绑定的照片或相机版本不符。'}
    obj = next((o for o in solution.get('objects', []) if o.get('id') == object_id), None)
    point_support=None
    if obj:
        vertices = np.asarray([v['xyz_source'] for v in obj.get('vertices', [])], dtype=float)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3 or not np.isfinite(vertices).all():
            raise ValueError('object has invalid source geometry')
        center = vertices.mean(axis=0)
        _, _, vectors = np.linalg.svd(vertices-center, full_matrices=False)
        normal = vectors[-1]
    else:
        # An unfinished object can still have one well-conditioned physical
        # feature observed in multiple views. This is a point proposal only.
        if not any(o.get('id')==object_id for o in state.get('objects',[])):
            return {'status':'INSUFFICIENT_OBJECT_GEOMETRY','object_id':object_id,'views':[],'pairs':[],
                    'warning':'需要先选择已有对象并提供跨图观察；不能仅按共享特征数量推荐。'}
        by_id=camera_index;groups={}
        for o in observations:
            camera=by_id.get(o.get('image_id'));feature=o.get('feature_id')
            if (o.get('kind')=='point' and feature and camera and o.get('camera_sha256')==camera_digest(camera)):
                groups.setdefault(feature,[]).append(o)
        for feature,group in groups.items():
            if len({o['image_id'] for o in group})<2:continue
            try:result=triangulate_observations(list(by_id.values()),group)
            except ValueError:continue
            if point_support is None or result['max_parallax_degrees']>point_support['max_parallax_degrees']:
                point_support={'feature_id':feature,**result}
        if point_support is None:
            return {'status':'INSUFFICIENT_OBJECT_GEOMETRY','object_id':object_id,'views':[],'pairs':[],
                    'warning':'需要同一对象至少一个可靠的跨图对应点；不能仅按共享特征数量推荐。'}
        center=np.asarray(point_support['xyz'],dtype=float);normal=None;vertices=None
    views = [];centers = {};features = {};excluded=[]
    for camera in state.get('cameras', []):
        item = available.get(camera.get('sha256'))
        if not item:
            excluded.append({'image_id':camera.get('image_id'),'reason':'PHOTO_NOT_UPLOADED'});continue
        try:
            if vertices is None:
                x,y=_project(center,camera)
                if not (0<=x<camera['width_px'] and 0<=y<camera['height_px']):
                    excluded.append({'image_id':camera['image_id'],'reason':'POINT_PROJECTS_OUTSIDE_IMAGE'});continue
                radius=.025*min(camera['width_px'],camera['height_px'])
                clip=box(x-radius,y-radius,x+radius,y+radius).intersection(box(0,0,camera['width_px'],camera['height_px']))
                coverage=None
            else:
                polygon = np.asarray([_project(v, camera) for v in vertices])
                surface = Polygon(polygon)
                if not surface.is_valid or surface.area <= 1:
                    excluded.append({'image_id':camera['image_id'],'reason':'DEGENERATE_PROJECTION'});continue
                clip = surface.intersection(box(0, 0, camera['width_px'], camera['height_px']))
                coverage = min(1., max(0., clip.area/surface.area))
            if coverage is not None and coverage <= 0:
                excluded.append({'image_id':camera['image_id'],'reason':'PROJECTS_OUTSIDE_IMAGE'});continue
            image_path = workspace/'evidence'/(item['sha256']+item['extension'])
            if image_path.is_symlink() or not image_path.is_file():
                excluded.append({'image_id':camera['image_id'],'reason':'PHOTO_UNAVAILABLE'});continue
            with image_path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=item['sha256']:
                    excluded.append({'image_id':camera['image_id'],'reason':'PHOTO_HASH_MISMATCH'});continue
            with Image.open(image_path) as image:
                if image.size != (camera['width_px'],camera['height_px']):
                    excluded.append({'image_id':camera['image_id'],'reason':'CAMERA_PHOTO_DIMENSION_MISMATCH'});continue
                image.draft('L',(640,640));image.thumbnail((640,640));gray=np.asarray(image.convert('L'))
            # Measure image quality only where this object projects; high
            # texture on unrelated furniture should not make a view rank higher.
            if clip.geom_type!='Polygon':
                excluded.append({'image_id':camera['image_id'],'reason':'UNSUPPORTED_PROJECTION_SHAPE'});continue
            contour=np.asarray(clip.exterior.coords,dtype=float)*[gray.shape[1]/camera['width_px'],gray.shape[0]/camera['height_px']]
            mask=np.zeros(gray.shape,dtype=np.uint8);cv2.fillPoly(mask,[np.rint(contour).astype(np.int32)],1)
            pixels=mask.astype(bool)
            if pixels.sum()<16:
                excluded.append({'image_id':camera['image_id'],'reason':'PROJECTED_AREA_TOO_SMALL'});continue
            focus = float(cv2.Laplacian(gray,cv2.CV_64F)[pixels].var())
            brightness = float(gray[pixels].mean())/255.
            quality = (focus/(focus+100.)) * max(0., 1.-abs(brightness-.5)*1.5)
            _,r,t=_camera_matrix(camera);camera_center=-r.T@t
            ray=center-camera_center;norm=float(np.linalg.norm(ray))
            if norm<=1e-9:
                excluded.append({'image_id':camera['image_id'],'reason':'CAMERA_AT_OBJECT_CENTER'});continue
            incidence=abs(float(normal@(ray/norm))) if normal is not None else None
            obs=[o for o in observations if o.get('image_id')==camera['image_id']]
            features[camera['image_id']]={o.get('feature_id') for o in obs if o.get('feature_id')}
            line_count=sum(o.get('kind')=='line' for o in obs)
            wall_semantics=sum(o.get('kind')=='plane' and o.get('semantic_label') in {'wall','wall_ADE20K_0'} for o in obs)
            boundary=min(1., (len(features[camera['image_id']])+line_count)/4.)
            screen_fraction=clip.area/(camera['width_px']*camera['height_px']) if normal is not None else None
            score=(.3*coverage+.15*min(screen_fraction/.05,1.)+.15*incidence+.15*quality+.15*boundary+.1*min(wall_semantics,1)
                   if normal is not None else .25+.2*quality+.3*boundary+.1*min(wall_semantics,1))
            views.append({'image_id':camera['image_id'],'photo':camera['photo'],'photo_sha256':camera['sha256'],
                          'camera_sha256':camera_digest(camera),'projection_fraction':round(coverage,4) if coverage is not None else None,
                          'screen_fraction':round(screen_fraction,5) if screen_fraction is not None else None,
                          'incidence_abs_cos':round(incidence,4) if incidence is not None else None,'focus_variance':round(focus,3),
                          'brightness':round(brightness,4),'object_observations':len(obs),
                          'object_lines':line_count,'score':round(score,5),
                          'occlusion':'UNKNOWN','semantic_support':{'wall_plane_observations':wall_semantics,
                              'status':'UNVERIFIED' if wall_semantics else 'NOT_AVAILABLE'}})
            centers[camera['image_id']]=camera_center
        except (ValueError, OSError, KeyError, cv2.error):
            excluded.append({'image_id':camera.get('image_id'),'reason':'INVALID_CAMERA_OR_PHOTO'})
    pairs=[]
    for a,b in itertools.combinations(views,2):
        va=centers[a['image_id']]-center;vb=centers[b['image_id']]-center
        cosine=np.clip(float(va@vb/(np.linalg.norm(va)*np.linalg.norm(vb))),-1.,1.)
        angle=math.degrees(math.acos(cosine))
        shared=len(features[a['image_id']] & features[b['image_id']])
        angle_score=min(angle/15.,1.) if angle<=60 else max(0.,1.-(angle-60)/60.)
        score=.75*(a['score']+b['score'])/2+.2*angle_score+.05*min(shared/3.,1.)
        pairs.append({'image_ids':[a['image_id'],b['image_id']], 'parallax_deg':round(angle,3),
                      'shared_object_feature_ids':shared,'score':round(score,5)})
    views.sort(key=lambda v:(-v['score'],v['image_id']))
    pairs.sort(key=lambda p:(-p['score'],p['image_ids']))
    return {'status':('UNVERIFIED_POINT_RECOMMENDATION' if point_support else 'UNVERIFIED_LOCAL_RECOMMENDATION') if pairs else 'INSUFFICIENT_VISIBLE_VIEWS',
            'object_id':object_id,'source_revision':state['revision'], 'views':views,'pairs':pairs[:12],'excluded':excluded,
            'point_support':point_support,
            'warning':('仅依据未经核实的跨图点及其局部区域，不能推断整面墙的可见性；遮挡与尺度未知。' if point_support else
                       '基于现有候选投影、相机角度、照片清晰度和对象观察；遮挡、语义与注册精度未知，必须查看原图。')}
