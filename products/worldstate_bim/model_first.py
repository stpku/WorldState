"""Evidence-constrained local wall patches without a global floor model.

A patch above an observed opening uses triangulated opening corners, a jamb
vertical and multiview wall-ceiling line observations.  It is a bounded local
candidate, not a complete wall or proof that a door leaf is flush with a wall.
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import json
import math
from typing import Any
import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import map_coordinates
from .multiview_fusion import _camera_matrix, triangulate_observations
from .room_ir import SCHEMA, geometry_issues, quantity, validate_room


CORNER_KEYS=('left_top','right_top','right_bottom')


def _digest(value: Any) -> str:
    """Bind a solution to exact observation and camera inputs."""
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _cameras(data: dict) -> dict[int,dict]:
    if data.get('schema')!='worldstate-local-wall-observations/0.1':raise ValueError('unexpected observation schema')
    result={}
    for c in data.get('cameras',[]):
        ident=c.get('image_id')
        if isinstance(ident,bool) or not isinstance(ident,int) or ident in result or not isinstance(c.get('sha256'),str) or len(c['sha256'])!=64:
            raise ValueError('invalid or duplicate registered camera')
        _camera_matrix(c);result[ident]=c
    if not result:raise ValueError('registered cameras required')
    return result


def _pixel(obs: dict, cameras: dict[int,dict]) -> tuple[np.ndarray,dict]:
    camera=cameras.get(obs.get('image_id'))
    if camera is None or obs.get('photo_sha256')!=camera['sha256']:raise ValueError('observation camera or image hash mismatch')
    xy=np.asarray(obs.get('pixel_xy'),dtype=float)
    if xy.shape!=(2,) or not np.isfinite(xy).all() or not 0<=xy[0]<camera['width_px'] or not 0<=xy[1]<camera['height_px']:
        raise ValueError('observation pixel outside original photo')
    return xy,camera


def _line(obs: dict, cameras: dict[int,dict]) -> np.ndarray:
    points=obs.get('points_px')
    if not isinstance(points,list) or len(points)!=2:raise ValueError('ceiling observation needs two endpoints')
    a,camera=_pixel({**obs,'pixel_xy':points[0]},cameras);b,_=_pixel({**obs,'pixel_xy':points[1]},cameras)
    if np.linalg.norm(a-b)<50:raise ValueError('ceiling line is too short')
    line=np.cross(np.r_[a,1.],np.r_[b,1.]);line/=np.linalg.norm(line[:2]);return line


def _project(point: np.ndarray, camera: dict) -> np.ndarray:
    K,R,t=_camera_matrix(camera);q=R@point+t
    if q[2]<=1e-8:raise ValueError('model point behind camera')
    xy=K@q;return xy[:2]/xy[2]


def _basis(left: np.ndarray, right: np.ndarray, bottom: np.ndarray) -> tuple[np.ndarray,np.ndarray,float,float]:
    delta=right-left;width=float(np.linalg.norm(delta));vertical=right-bottom;vlen=float(np.linalg.norm(vertical))
    if width<1e-6 or vlen<1e-6:raise ValueError('opening dimensions are degenerate')
    along=delta/width;up=vertical-along*float(along@vertical);length=float(np.linalg.norm(up))
    if length<1e-6:raise ValueError('opening vertical is not identifiable')
    return along,up/length,width,abs(float(along@vertical))/vlen


def _semantic_views(data: dict, cameras: dict[int,dict]) -> list[tuple[dict,np.ndarray]]:
    """Decode at most one correlated wall-mask hypothesis per source image."""
    output=[];seen=set()
    for view in data.get('semantic_views',[]):
        camera=cameras.get(view.get('image_id'))
        if camera is None or view.get('photo_sha256')!=camera['sha256'] or view['image_id'] in seen:
            raise ValueError('semantic view does not match a unique source camera')
        if view.get('shape')!=[128,128] or view.get('label')!='wall_ADE20K_0':raise ValueError('unsupported semantic mask')
        try:packed=base64.b64decode(view['wall_mask_packbits_base64'],validate=True)
        except (KeyError,binascii.Error,TypeError) as exc:raise ValueError('invalid semantic mask') from exc
        if len(packed)!=2048:raise ValueError('invalid semantic mask size')
        mask=np.unpackbits(np.frombuffer(packed,dtype=np.uint8)).reshape(128,128).astype(float)
        output.append((camera,mask));seen.add(view['image_id'])
    return output


def _semantic_support(params: np.ndarray, views: list[tuple[dict,np.ndarray]]) -> list[dict]:
    left,right,bottom=params[:3],params[3:6],params[6:9];height=float(params[9])
    _,up,_,_=_basis(left,right,bottom);samples=np.linspace(.15,.85,5);output=[]
    for camera,mask in views:
        pixels=np.array([_project(left+a*(right-left)+b*height*up,camera) for a in samples for b in samples])
        coords=np.vstack([pixels[:,1]*128/camera['height_px']-.5,pixels[:,0]*128/camera['width_px']-.5])
        wall=map_coordinates(mask,coords,order=1,mode='constant',cval=0.)
        output.append({'photo':camera['photo'],'sampled_mask_wall_fraction':float(np.mean(wall)),
                       'samples':len(wall),'aggregation':'one correlated soft constraint per photo'})
    return output


def _residual(params: np.ndarray, data: dict, cameras: dict[int,dict], semantic: list[tuple[dict,np.ndarray]]) -> np.ndarray:
    left,right,bottom=params[:3],params[3:6],params[6:9];height=float(params[9]);values=[]
    count=sum(2*len(data['corners'].get(k,[])) for k in CORNER_KEYS)+2*len(data['ceiling_lines'])+len(semantic)
    try:
        _,up,_,_=_basis(left,right,bottom)
        for key,p in zip(CORNER_KEYS,(left,right,bottom)):
            for obs in data['corners'].get(key,[]):
                xy,camera=_pixel(obs,cameras);values.extend((_project(p,camera)-xy).tolist())
        for obs in data['ceiling_lines']:
            line=_line(obs,cameras);camera=cameras[obs['image_id']]
            for p in (left+height*up,right+height*up):values.append(float(line@np.r_[_project(p,camera),1.]))
        # Treat the 25 correlated pixels as ONE weak residual per image. The
        # classifier is uncalibrated; this is a tunable prior, not 25 measurements.
        values.extend(2.*(1.-item['sampled_mask_wall_fraction']) for item in _semantic_support(params,semantic))
    except ValueError:return np.full(count,1e6)
    return np.asarray(values,dtype=float)


def _pix_initial(pix: dict, triangulated: list[np.ndarray], data: dict, cameras: dict[int,dict]) -> tuple[np.ndarray,int]:
    if pix.get('schema')!='worldstate-pixcuboid-candidate/0.1':raise ValueError('invalid PixCuboid candidate')
    r=np.asarray(pix['output']['R_world_to_cuboid'],float);d=np.asarray(pix['output']['plane_offsets'],float)
    if r.shape!=(3,3) or d.shape!=(6,) or not np.isfinite(r).all() or not np.isfinite(d).all() or not np.allclose(r@r.T,np.eye(3),atol=1e-4):
        raise ValueError('invalid cuboid geometry')
    # Choose one of the four vertical prior faces by 3D door-top proximity;
    # this is a provisional association, not ground-truth wall recognition.
    candidates=(0,1,3,4);face=min(candidates,key=lambda i:sum(abs(float(r[i%3]@p-d[i])) for p in triangulated[:2]))
    n=r[face%3];points=[]
    for key in CORNER_KEYS:
        obs=data['corners'][key][0];xy,cam=_pixel(obs,cameras);K,R,t=_camera_matrix(cam)
        center=-R.T@t;ray=R.T@np.linalg.solve(K,np.r_[xy,1.]);den=float(n@ray)
        if abs(den)<1e-6:raise ValueError('initial PixCuboid face is parallel to observation ray')
        step=(d[face]-float(n@center))/den
        if step<=0:raise ValueError('initial PixCuboid face is behind camera')
        points.append(center+step*ray)
    _,up,_,_=_basis(*points)
    # Find an above-door cap of the candidate, leaving both unobserved caps unconfirmed.
    candidates_h=[]
    for cap in (2,5):
        den=float(r[2]@up)
        if abs(den)>1e-6:
            h=(d[cap]-float(r[2]@points[1]))/den
            if h>1e-4 and np.isfinite(h):candidates_h.append(float(h))
    if not candidates_h:raise ValueError('PixCuboid has no positive prior ceiling distance')
    return np.r_[*points,min(candidates_h)],face


def evaluate_patch(parameters: np.ndarray, data: dict) -> dict:
    """Compute per-observation reprojection errors without fitting to this data."""
    cameras=_cameras(data);left,right,bottom=parameters[:3],parameters[3:6],parameters[6:9];height=float(parameters[9])
    _,up,_,_=_basis(left,right,bottom);corners=[];lines=[]
    for key,p in zip(CORNER_KEYS,(left,right,bottom)):
        for obs in data.get('corners',{}).get(key,[]):
            actual,camera=_pixel(obs,cameras);projected=_project(p,camera)
            corners.append({'corner':key,'photo':camera['photo'],'photo_sha256':camera['sha256'],
                'observed_pixel_xy':actual.tolist(),'projected_pixel_xy':projected.tolist(),
                'error_px':float(np.linalg.norm(projected-actual))})
    for obs in data.get('ceiling_lines',[]):
        line=_line(obs,cameras);camera=cameras[obs['image_id']]
        projected=[_project(left+height*up,camera),_project(right+height*up,camera)]
        errors=[float(abs(line@np.r_[point,1.])) for point in projected]
        lines.append({'photo':camera['photo'],'photo_sha256':camera['sha256'],'observed_line_px':obs['points_px'],
                      'projected_endpoints_px':[point.tolist() for point in projected],
                      'endpoint_line_error_px':errors})
    values=[x['error_px'] for x in corners]+[v for x in lines for v in x['endpoint_line_error_px']]
    return {'corner_observations':corners,'ceiling_observations':lines,
            'rms_px':float(np.sqrt(np.mean(np.square(values)))) if values else None,
            'maximum_px':float(max(values)) if values else None,
            'limitations':['Line error measures agreement with an observed infinite image line; it is not physical dimension accuracy.',
                           'Photo correspondence, camera poses and semantic interpretation remain unverified.']}


def solve_local_wall(data: dict, pix: dict | None = None) -> dict:
    """Triangulate opening corners and optimize a local patch.

    Uses existing 3 px / 1 degree triangulation gates. A 3 px line/corner fit
    is a consistency guard, not an independent wall-accuracy requirement.
    """
    cameras=_cameras(data)
    semantic=_semantic_views(data,cameras)
    if data.get('camera_mode') not in {'ETH3D_KNOWN_POSE_SCANNER_REGISTERED_NOT_PHOTO_ONLY',
                                       'KNOWN_POSE_UNVERIFIED', 'PHOTO_ONLY_COLMAP_ARBITRARY_SCALE'}:
        raise ValueError('camera input mode must be explicit')
    if len(data.get('ceiling_lines',[]))<2:raise ValueError('at least two ceiling observations required')
    ceiling_ids=[x['image_id'] for x in data['ceiling_lines']]
    if len(set(ceiling_ids))!=len(ceiling_ids):raise ValueError('ceiling observations must use distinct views')
    for x in data['ceiling_lines']:_line(x,cameras)
    triangulated={key:triangulate_observations(list(cameras.values()),data['corners'][key]) for key in CORNER_KEYS}
    points=[np.asarray(triangulated[key]['xyz'],float) for key in CORNER_KEYS]
    along,up,width,orth_error=_basis(*points)
    if orth_error>math.sin(math.radians(10)):raise ValueError('observed opening edges conflict with rectangular local patch assumption')
    line_start=sum(2*len(data['corners'].get(k,[])) for k in CORNER_KEYS)
    def hfun(h):return _residual(np.r_[*points,h[0]],data,cameras,semantic)[line_start:line_start+2*len(data['ceiling_lines'])]
    direct=least_squares(hfun,[.3],bounds=(1e-6,np.inf),loss='soft_l1',f_scale=3.,max_nfev=200)
    if not direct.success or np.linalg.norm(direct.jac)<1e-6:raise ValueError('local upper boundary height is not identifiable')
    direct_params=np.r_[*points,direct.x[0]]
    initial,face=_pix_initial(pix,points,data,cameras) if pix is not None else (direct_params,None)
    result=least_squares(_residual,initial,args=(data,cameras,semantic),bounds=(np.r_[np.full(9,-np.inf),1e-6],np.full(10,np.inf)),
                         loss='soft_l1',f_scale=3.,x_scale='jac',max_nfev=400)
    if not result.success or not np.isfinite(result.x).all():raise ValueError('joint image optimization failed')
    along,up,width,orth_error=_basis(result.x[:3],result.x[3:6],result.x[6:9])
    if orth_error>math.sin(math.radians(10)):raise ValueError('optimized opening is not compatible with rectangular patch')
    score=evaluate_patch(result.x,data);before=evaluate_patch(initial,data)
    jac=np.asarray(result.jac);singular=np.linalg.svd(jac,compute_uv=False)
    if len(singular)<10 or singular[-1]<1e-8:raise ValueError('local model parameters are unidentifiable')
    if score['maximum_px'] is None or score['maximum_px']>3.:raise ValueError('optimized observations exceed 3 px consistency gate')
    return {'schema':'worldstate-model-first-local-wall/0.1','status':'UNVERIFIED_PARTIAL_PATCH',
        'observation_sha256':_digest(data),'pixcuboid_sha256':_digest(pix) if pix is not None else None,
        'triangulated':triangulated,'direct_parameters':direct_params.tolist(),'initial_parameters':initial.tolist(),
        'optimized_parameters':result.x.tolist(),'pixcuboid_prior_face':face,'before':before,'after':score,
        'semantic_before':_semantic_support(initial,semantic),'semantic_after':_semantic_support(result.x,semantic),
        'optimization':{'method':'scipy least_squares soft_l1','loss_scale_px':3.,'evaluations':result.nfev,
                        'initialization':'pixcuboid_face' if pix is not None else 'triangulated_corners_and_image_lines',
                        'semantic_term':'one uncalibrated 2 px-equivalent soft residual per image' if semantic else 'NOT_USED',
                        'sparse_point_depth_scale_topology_terms':'NOT_USED_IN_THIS_PARTIAL_PATCH',
                        'jacobian_singular_values':singular.tolist(),'jacobian_condition_number':float(singular[0]/singular[-1]),
                        'free_parameters':10,'corners_pixel_gate':3.,'ceiling_pixel_gate':3.},
        'frame':{'origin_source':result.x[:3].tolist(),'x_axis_source':along.tolist(),'z_axis_source':up.tolist(),
                 'y_axis_source':np.cross(up,along).tolist()},
        'width_source_units':width,'height_source_units':float(result.x[9]),
        'vertical_evidence':'right door-jamb direction; orthogonalized to observed top edge as explicit rectangular-patch assumption',
        'source_scale':'UNKNOWN_ASSUMED_ONLY_FOR_IFC_DRAFT',
        'unknown':['physical wall face offset from door leaf','actual wall thickness','complete wall bounds',
                   'metric scale not independently measured','gravity and spatial uncertainty not independently quantified',
                   'occlusion and unseen topology']}


def build_local_wall_ir(data: dict, solution: dict, *, project_id: str, assumed_scale: float,
                        assumed_thickness_m: float, allow_assumed: bool) -> dict:
    """Convert the observed partial patch to Room IR with explicit assumptions."""
    if allow_assumed is not True:raise ValueError('assumed scale and thickness must be explicitly allowed')
    if solution.get('status')!='UNVERIFIED_PARTIAL_PATCH':raise ValueError('unsupported local wall solution')
    if solution.get('observation_sha256')!=_digest(data):
        raise ValueError('observations or cameras changed; solve the candidate again')
    if not isinstance(project_id,str) or not project_id.strip():raise ValueError('project ID required')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in (assumed_scale,assumed_thickness_m)):
        raise ValueError('positive explicit scale and thickness assumptions required')
    width=solution['width_source_units']*assumed_scale;height=solution['height_source_units']*assumed_scale
    refs=['observations','camera','local-frame','assumed-scale']
    evidence=[{'id':'observations','kind':'multiview_opening_and_ceiling_pixels','operator':data['operator'],
               'corners':data['corners'],'ceiling_lines':data['ceiling_lines'],
               'semantic_views':data.get('semantic_views',[]),'status':'source_declared_unverified'},
              {'id':'camera','kind':'provided_multiview_cameras','camera_mode':data['camera_mode'],
               'source_reconstruction':data['source_reconstruction'],'cameras':data['cameras'],'status':'provided_unverified'},
              {'id':'local-frame','kind':'inferred_local_frame','frame':solution['frame'],'status':'inferred_unverified',
               'assumptions':['door leaf and wall approximately coplanar','opening jamb is locally vertical',
                              'wall patch is rectangular; ceiling line follows its upper edge']},
              {'id':'assumed-scale','kind':'scale_assumption','metres_per_source_unit':assumed_scale,
               'status':'assumed_not_a_measurement'},
              {'id':'assumed-thickness','kind':'thickness_assumption','value_m':assumed_thickness_m,
               'status':'assumed_not_observed'}]
    status={'status':'inferred','evidence_refs':refs}
    nodes=[{'id':'lintel-start','x':0.,'y':0.,**status},{'id':'lintel-end','x':width,'y':0.,**status}]
    wall={'id':'wall-above-opening','ifc_type':'IfcWall','start':'lintel-start','end':'lintel-end',
          'storey':'local-datum','classification':{'status':'inferred','evidence_refs':['observations','local-frame']},
          'axis_reference':'face','parameters':{
            'height':quantity(height,'inferred',refs,'Visible patch height from image line and opening-jamb hypothesis, not full wall height'),
            'base_elevation':quantity(0.,'assumed',['local-frame'],'Local datum at observed door top; not a floor elevation'),
            'thickness':quantity(assumed_thickness_m,'assumed',['assumed-thickness'],'Unobserved thickness assumption')},
          'unknown':solution['unknown']}
    model={'schema':SCHEMA,'project_id':project_id,'mode':'assisted','revision':1,
      'coordinate_system':{'name':'local opening-top datum','unit':'m','source_to_metres_assumed':assumed_scale,
                           'origin_in_source':solution['frame']['origin_source'],
                           'x_axis_in_source':solution['frame']['x_axis_source'],
                           'y_axis_in_source':solution['frame']['y_axis_source'],
                           'z_axis_in_source':solution['frame']['z_axis_source'],'georeferencing':'UNKNOWN'},
      'evidence':evidence,'nodes':nodes,'storeys':[{'id':'local-datum',
          'elevation':quantity(0.,'assumed',['local-frame'],'Local datum, not surveyed floor elevation')}],
      'elements':[wall],'constraints':[],
      'scale':{'status':'assumed','metres_per_source_unit':assumed_scale,'independent_measurement':False},
      'validation':{'status':'UNVERIFIED_DRAFT','scope':'PARTIAL_OPEN',
          'warning':'Only a patch above a detected door; scale, thickness and wall/door coplanarity are assumptions.'}}
    validate_room(model);issues=geometry_issues(model)
    if issues:raise ValueError('local wall geometry conflict: '+str(issues))
    return model


def project_local_wall_ir(model: dict) -> dict | None:
    """Project the current local-wall IR revision into its recorded photos.

    Uses the IR's current nodes and parameters, not an old optimized mesh.
    Image errors describe agreement with the original candidate observations;
    they do not validate dimensions, semantic identity or the scale assumption.
    Returns None for unrelated room models.
    """
    evidence={x['id']:x for x in model.get('evidence',[])}
    observed=evidence.get('observations');camera_evidence=evidence.get('camera')
    wall=next((e for e in model.get('elements',[]) if e.get('id')=='wall-above-opening' and e.get('ifc_type')=='IfcWall'),None)
    if not observed or not camera_evidence or not wall or observed.get('kind')!='multiview_opening_and_ceiling_pixels':return None
    cs=model['coordinate_system'];scale=cs['source_to_metres_assumed']
    if not isinstance(scale,(int,float)) or isinstance(scale,bool) or not math.isfinite(scale) or scale<=0:
        raise ValueError('invalid local-to-source scale')
    origin=np.asarray(cs['origin_in_source'],dtype=float)
    basis=np.column_stack([cs['x_axis_in_source'],cs['y_axis_in_source'],cs['z_axis_in_source']]).astype(float)
    if origin.shape!=(3,) or basis.shape!=(3,3) or not np.isfinite(origin).all() or not np.allclose(basis.T@basis,np.eye(3),atol=1e-5):
        raise ValueError('invalid local-to-source frame')
    nodes={node['id']:node for node in model['nodes']};start=nodes[wall['start']];end=nodes[wall['end']]
    base=wall['parameters']['base_elevation']['value'];height=wall['parameters']['height']['value']
    local=np.array([[start['x'],start['y'],base],[end['x'],end['y'],base],
                    [end['x'],end['y'],base+height],[start['x'],start['y'],base+height]],dtype=float)
    if not np.isfinite(local).all() or height<=0:raise ValueError('invalid wall geometry')
    source=origin+local@basis.T/scale
    cameras=_cameras({'schema':'worldstate-local-wall-observations/0.1','cameras':camera_evidence['cameras']})
    views=[]
    for ident,camera in cameras.items():
        polygon=[_project(point,camera) for point in source];points=[];lines=[]
        for key,index in (('left_top',0),('right_top',1)):
            for obs in observed['corners'].get(key,[]):
                if obs['image_id']!=ident:continue
                actual,_=_pixel(obs,cameras)
                points.append({'kind':key,'pixel_xy':actual.tolist(),'error_px':float(np.linalg.norm(polygon[index]-actual))})
        for obs in observed['ceiling_lines']:
            if obs['image_id']!=ident:continue
            line=_line(obs,cameras)
            lines.append({'points_px':obs['points_px'],'endpoint_error_px':
                          [float(abs(line@np.r_[polygon[index],1.])) for index in (2,3)]})
        values=[point['error_px'] for point in points]+[n for line in lines for n in line['endpoint_error_px']]
        views.append({'image_id':ident,'photo':camera['photo'],'photo_sha256':camera['sha256'],
            'width_px':camera['width_px'],'height_px':camera['height_px'],'polygon_px':[p.tolist() for p in polygon],
            'corners':points,'ceiling_lines':lines,'rms_px':float(np.sqrt(np.mean(np.square(values)))) if values else None})
    return {'schema':'worldstate-local-wall-projections/0.1','revision':model['revision'],'views':views,
            'status':'UNVERIFIED_PARTIAL_PATCH','scale':'ASSUMED_NOT_MEASURED',
            'warning':'Projection is compared to original candidate pixels, not independent dimensions or reviewed wall boundaries.'}
