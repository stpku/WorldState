"""Local Studio endpoints for general multiview surface authoring."""
from __future__ import annotations

import copy
import hashlib
import math
import re
from datetime import datetime, timezone

from .general_modeler import SCHEMA_INPUT, _camera_matrix, _line, _point, build_room_ir, camera_digest, solve_modeler
from .room_cli import save_version


def _state(handler) -> dict:
    project=handler.server.project
    if project is None:raise ValueError('请先在照片建模入口创建项目')
    value=project.get('general_modeler')
    if value is None:raise ValueError('请先导入已注册相机')
    return value


def _operator(handler) -> str:
    return 'automation' if handler.server.project.get('operator_kind')=='automation' else 'user'


def _image(handler, sha: str) -> dict:
    item=next((x for x in handler.server.uploaded if x.get('sha256')==sha),None)
    path=handler.server.uploads/(item['sha256']+item['extension']) if item else None
    if not item or path.is_symlink() or not path.is_file():raise ValueError('对应原始照片尚未上传')
    with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=sha:raise ValueError('已上传照片哈希不符')
    return item


def _data(state: dict) -> dict:
    return {'schema':SCHEMA_INPUT,'camera_mode':state['camera_mode'],
        'coordinate_system':{'name':'registered reconstruction','scale_status':'UNKNOWN'},
        'source_reconstruction':state['source_reconstruction'],'cameras':state['cameras'],
        'objects':state['objects'],'observations':state['observations'],'object_constraints':state['object_constraints']}


def get_state(handler) -> None:
    project=handler.server.project
    handler.send_json(200,{'project':project.get('name') if project else None,
        'state':project.get('general_modeler') if project else None,
        'uploads':handler.server.uploaded,'has_model':handler.server.model is not None})


def post(handler, path: str, body: dict) -> bool:
    """Handle only bounded Modeler actions, returning False for other routes."""
    if not path.startswith('/api/modeler/'):return False
    server=handler.server;project=server.project
    if project is None:raise ValueError('请先创建项目')
    if path=='/api/modeler/cameras':
        current=project.get('general_modeler')
        if current and (current['objects'] or current['observations']):raise ValueError('已有观测，请在新项目中导入其他相机版本')
        manifest=body.get('manifest')
        if not isinstance(manifest,dict) or manifest.get('schema')!='worldstate-modeler-cameras/0.1' or manifest.get('camera_mode') not in {'known-pose','photo-only'}:
            raise ValueError('相机清单格式或模式无效')
        available={p['sha256']:p for p in server.uploaded};cameras=[];seen=set()
        for camera in manifest.get('cameras',[]):
            if camera.get('sha256') not in available:continue
            ident=camera.get('image_id');photo=_image(handler,camera['sha256'])
            if isinstance(ident,bool) or not isinstance(ident,int) or ident in seen:raise ValueError('相机 ID 无效或重复')
            if (camera.get('width_px'),camera.get('height_px'))!=(photo['width'],photo['height']):raise ValueError('照片尺寸与相机不一致')
            _camera_matrix(camera);cameras.append(copy.deepcopy(camera));seen.add(ident)
        if len(cameras)<2:raise ValueError('至少上传清单中两张原始照片')
        source=manifest.get('source_reconstruction')
        if not isinstance(source,list) or not source:raise ValueError('相机版本缺少重建来源')
        candidate_tracks=manifest.get('tracks',[])
        if not isinstance(candidate_tracks,list) or len(candidate_tracks)>20000:raise ValueError('对应候选数量无效')
        selected={c['image_id']:c for c in cameras};tracks=[];duplicate_view_tracks=0
        for track in candidate_tracks:
            if not isinstance(track,dict) or not isinstance(track.get('id'),int):raise ValueError('对应轨迹无效')
            observations=[];seen_views=set();duplicate=False
            for observation in track.get('observations',[]):
                cam=selected.get(observation.get('image_id'))
                if cam is None:continue
                if cam['image_id'] in seen_views:duplicate=True;break
                xy=_point(observation,cam).tolist();seen_views.add(cam['image_id'])
                observations.append({'image_id':cam['image_id'],'pixel_xy':xy})
            if duplicate:duplicate_view_tracks+=1;continue
            if len(observations)>=2:tracks.append({'id':track['id'],'observations':observations})
        from .studio_server import _write_json
        track_file=server.workspace/'modeler-tracks.json';_write_json(track_file,{'tracks':tracks})
        with track_file.open('rb') as stream:track_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        project['general_modeler']={'schema':'worldstate-studio-general-modeler/0.1','revision':1,
            'camera_mode':manifest['camera_mode'],'source_reconstruction':copy.deepcopy(source),
            'cameras':cameras,'objects':[],'observations':[],'object_constraints':[],'solution':None,
            'model_dirty':False,
            'track_sha256':track_sha,'track_count':len(tracks),'duplicate_view_tracks_excluded':duplicate_view_tracks,'suggestions':[],
            'registration_status':'USER_SUPPLIED_REGISTERED_CAMERAS_NOT_INDEPENDENTLY_VERIFIED'}
        server.record('modeler_cameras_imported',registered=len(cameras),camera_mode=manifest['camera_mode'],operator=_operator(handler))
        handler.send_json(201,project['general_modeler']);return True
    state=_state(handler)
    if body.get('state_revision')!=state['revision']:
        handler.send_json(409,{'error':'建模观测已更新，请刷新后重试'});return True
    if path=='/api/modeler/object':
        ident=body.get('id');count=body.get('vertices')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident):raise ValueError('构件 ID 只允许字母、数字、下划线和短横线')
        if any(o['id']==ident for o in state['objects']):raise ValueError('构件 ID 已存在')
        if isinstance(count,bool) or not isinstance(count,int) or not 3<=count<=12:raise ValueError('可见多边形需 3–12 个角点')
        construction=body.get('construction','polygon')
        if construction not in {'polygon','edge_to_line'} or (construction=='edge_to_line' and count!=4):
            raise ValueError('边到线构造需要四个边界顶点')
        obj={'id':ident,'ifc_type':'IfcWall','vertices':[f'p{i}' for i in range(1,count+1)],
             'surface_kind':'visible_surface_patch'}
        if construction=='edge_to_line':obj['construction']={'kind':'edge_to_line','direction_feature':'p5'}
        state['objects'].append(obj)
        event={'object_id':ident,'vertices':count,'construction':construction}
    elif path in {'/api/modeler/point','/api/modeler/line'}:
        obj=next((o for o in state['objects'] if o['id']==body.get('object_id')),None)
        camera=next((c for c in state['cameras'] if c['image_id']==body.get('image_id')),None)
        if not obj or not camera:raise ValueError('请选择已创建的构件和已注册照片')
        _image(handler,camera['sha256']);sigma=body.get('sigma_px')
        if isinstance(sigma,bool) or not isinstance(sigma,(int,float)) or not math.isfinite(sigma) or not 0<sigma<=100:
            raise ValueError('请输入正数像素不确定度')
        visibility=body.get('visibility','visible')
        if visibility not in {'visible','occluded','unknown'}:raise ValueError('请选择可见、遮挡或未知')
        operator=_operator(handler);kind='point' if path.endswith('/point') else 'line'
        observation={'kind':kind,'object_id':obj['id'],'image_id':camera['image_id'],
            'photo_sha256':camera['sha256'],'camera_sha256':camera_digest(camera),'origin':operator,
            'confirmation':'user_confirmed' if operator=='user' else 'automation_unverified',
            'visibility':visibility,'sigma_px':sigma,'created_at':datetime.now(timezone.utc).isoformat()}
        if kind=='point':
            feature=body.get('feature_id')
            construction=obj.get('construction',{});allowed=(obj['vertices'][:2]+[construction['direction_feature']]
                if construction.get('kind')=='edge_to_line' else obj['vertices'])
            if feature not in allowed:raise ValueError('角点编号不属于可观测特征')
            observation['feature_id']=feature;observation['pixel_xy']=_point(body,camera).tolist()
            match=lambda o:o['kind']=='point' and o['object_id']==obj['id'] and o['image_id']==camera['image_id'] and o.get('feature_id')==feature
        else:
            pair=body.get('feature_ids');pixels=body.get('points_px')
            if not isinstance(pair,list) or len(pair)!=2 or pair[0]==pair[1] or any(p not in obj['vertices'] for p in pair):raise ValueError('请选择两个不同角点作为线段端点')
            if not isinstance(pixels,list) or len(pixels)!=2:raise ValueError('线段需要两个像素位置')
            for point in pixels:_point({'pixel_xy':point},camera)
            _line(pixels);observation.update(feature_ids=pair,points_px=pixels)
            match=lambda o:o['kind']=='line' and o['object_id']==obj['id'] and o['image_id']==camera['image_id'] and o.get('feature_ids')==pair
        previous=next((o for o in state['observations'] if match(o)),None)
        state['observations']=[o for o in state['observations'] if not match(o)]+[observation]
        event={'object_id':obj['id'],'image_id':camera['image_id'],'kind':kind,'previous':previous,'current':observation}
    elif path=='/api/modeler/vision-decision':
        run=next((r for r in project.get('vision_runs',[]) if r.get('id')==body.get('run_id')),None)
        candidate=next((c for c in (run or {}).get('candidates',[]) if c.get('id')==body.get('candidate_id')),None)
        obj=next((o for o in state['objects'] if o['id']==body.get('object_id')),None);decision=body.get('decision')
        if not run or not candidate or not obj or decision not in {'accept','reject'}:raise ValueError('请选择有效的视觉候选和构件')
        camera=next((c for c in state['cameras'] if c['sha256']==run.get('image_sha256')),None)
        if not camera:raise ValueError('视觉候选没有匹配的已注册照片')
        _image(handler,camera['sha256']);operator=_operator(handler)
        if decision=='reject':
            state['revision']+=1;server.record('modeler_vision_decision',operator=operator,decision='reject',
                run_id=run['id'],candidate_id=candidate['id'],object_id=obj['id'])
            handler.send_json(200,{'state':state});return True
        kind='point' if candidate.get('kind')=='line_endpoint' else 'line' if candidate.get('kind') in {'wall_floor_line','wall_ceiling_line'} else None
        if kind is None:raise ValueError('语义区域不是物理边界，不能直接当作角点或线')
        sigma=body.get('sigma_px')
        if isinstance(sigma,bool) or not isinstance(sigma,(int,float)) or not math.isfinite(sigma) or sigma<=0:raise ValueError('请输入像素不确定度')
        observation={'kind':kind,'object_id':obj['id'],'image_id':camera['image_id'],
            'photo_sha256':camera['sha256'],'camera_sha256':camera_digest(camera),'origin':'ai_suggested',
            'confirmation':'accepted_unverified','accepted_by':operator,'visibility':'visible','sigma_px':sigma,
            'created_at':datetime.now(timezone.utc).isoformat(),'vision_run_id':run['id'],
            'vision_candidate_id':candidate['id'],'vision_model_sha256':run.get('model_sha256'),
            'uncertainty_note':candidate.get('uncertainty','model score uncalibrated')}
        pixels=candidate.get('points_px');construction=obj.get('construction',{})
        if kind=='point':
            feature=body.get('feature_id');allowed=(obj['vertices'][:2]+[construction['direction_feature']]
                if construction.get('kind')=='edge_to_line' else obj['vertices'])
            if feature not in allowed or not isinstance(pixels,list) or len(pixels)!=1:raise ValueError('视觉端点和构件角点不匹配')
            observation.update(feature_id=feature,pixel_xy=_point({'pixel_xy':pixels[0]},camera).tolist())
            match=lambda o:o['kind']=='point' and o['object_id']==obj['id'] and o['image_id']==camera['image_id'] and o.get('feature_id')==feature
        else:
            pair=body.get('feature_ids')
            if not isinstance(pair,list) or len(pair)!=2 or pair[0]==pair[1] or any(x not in obj['vertices'] for x in pair):raise ValueError('请选择线段对应的两个顶点')
            if not isinstance(pixels,list) or len(pixels)!=2:raise ValueError('视觉线段无效')
            for xy in pixels:_point({'pixel_xy':xy},camera)
            _line(pixels);observation.update(feature_ids=pair,points_px=copy.deepcopy(pixels))
            match=lambda o:o['kind']=='line' and o['object_id']==obj['id'] and o['image_id']==camera['image_id'] and o.get('feature_ids')==pair
        previous=next((o for o in state['observations'] if match(o)),None)
        state['observations']=[o for o in state['observations'] if not match(o)]+[observation]
        state['solution']=None;state['model_dirty']=True;state['suggestions']=[];state['revision']+=1
        server.record('modeler_vision_decision',operator=operator,decision='accept',run_id=run['id'],
            candidate_id=candidate['id'],object_id=obj['id'],previous=previous,current=observation)
        handler.send_json(200,{'state':state});return True
    elif path=='/api/modeler/suggest':
        obj=next((o for o in state['objects'] if o['id']==body.get('object_id')),None)
        image_id=body.get('image_id');feature=body.get('feature_id')
        allowed=(obj['vertices']+[obj['construction']['direction_feature']]
                 if obj and obj.get('construction',{}).get('kind')=='edge_to_line' else obj['vertices'] if obj else [])
        if feature not in allowed:raise ValueError('请选择已有角点')
        original=next((o for o in state['observations'] if o['kind']=='point' and o['object_id']==obj['id'] and
                       o.get('feature_id')==feature and o['image_id']==image_id),None)
        if not original or original.get('visibility')!='visible':raise ValueError('请先在选定照片中标注可见角点')
        path_tracks=server.workspace/'modeler-tracks.json'
        if path_tracks.is_symlink() or not path_tracks.is_file():raise ValueError('没有可用的相机轨迹候选')
        import json
        with path_tracks.open('rb') as stream:
            raw=stream.read()
        if hashlib.sha256(raw).hexdigest()!=state['track_sha256']:raise ValueError('轨迹文件已改变，请重新导入')
        tracks=json.loads(raw)['tracks'];nearest=None
        for track in tracks:
            here=next((x for x in track['observations'] if x['image_id']==image_id),None)
            if not here:continue
            distance=math.dist(original['pixel_xy'],here['pixel_xy'])
            if distance<=30 and (nearest is None or distance<nearest[0]-1e-8 or
                    (abs(distance-nearest[0])<=1e-8 and track['id']<nearest[1]['id'])):
                nearest=(distance,track,here)
        if nearest is None:raise ValueError('附近 30 个原始像素内没有跨图轨迹；请手动标注')
        distance,track,here=nearest
        alternatives=[t['id'] for t in tracks if t['id']!=track['id'] and any(
            o['image_id']==image_id and math.dist(o['pixel_xy'],here['pixel_xy'])<1e-6 for o in t['observations'])]
        state['suggestions']=[{'id':f"track-{track['id']}-view-{other['image_id']}",
            'object_id':obj['id'],'feature_id':feature,'source_image_id':image_id,'source_pixel_xy':here['pixel_xy'],
            'target_image_id':other['image_id'],'target_pixel_xy':other['pixel_xy'],'source_distance_px':distance,
            'track_id':track['id'],'duplicate_source_track_ids':alternatives,
            'status':'proposed','origin':'deterministic_colmap_track'}
            for other in track['observations'] if other['image_id']!=image_id][:12]
        state['revision']+=1
        server.record('modeler_correspondence_proposed',operator=_operator(handler),object_id=obj['id'],
                      feature_id=feature,track_id=track['id'],source_distance_px=distance)
        handler.send_json(200,{'state':state});return True
    elif path=='/api/modeler/decision':
        suggestion=next((x for x in state.get('suggestions',[]) if x['id']==body.get('suggestion_id')),None)
        decision=body.get('decision')
        if not suggestion or suggestion['status']!='proposed' or decision not in {'accept','reject'}:
            raise ValueError('请选择待处理候选')
        suggestion['status']='accepted' if decision=='accept' else 'rejected';operator=_operator(handler)
        previous=[]
        if decision=='accept':
            cameras={c['image_id']:c for c in state['cameras']}
            for image_id,pixel in ((suggestion['source_image_id'],suggestion['source_pixel_xy']),
                                   (suggestion['target_image_id'],suggestion['target_pixel_xy'])):
                cam=cameras[image_id];_image(handler,cam['sha256']);_point({'pixel_xy':pixel},cam)
                old=next((o for o in state['observations'] if o['kind']=='point' and o['object_id']==suggestion['object_id'] and
                          o['feature_id']==suggestion['feature_id'] and o['image_id']==image_id),None)
                if old:previous.append(old);state['observations'].remove(old)
                state['observations'].append({'kind':'point','object_id':suggestion['object_id'],
                    'feature_id':suggestion['feature_id'],'image_id':image_id,'pixel_xy':pixel,'photo_sha256':cam['sha256'],
                    'camera_sha256':camera_digest(cam),'origin':'deterministic','confirmation':'accepted_unverified',
                    'accepted_by':operator,'visibility':'visible','sigma_px':2.,'created_at':datetime.now(timezone.utc).isoformat(),
                    'track_id':suggestion['track_id']})
            state['solution']=None;state['model_dirty']=True
        state['revision']+=1
        server.record('modeler_correspondence_decision',operator=operator,decision=decision,
                      suggestion=copy.deepcopy(suggestion),previous=previous)
        handler.send_json(200,{'state':state});return True
    elif path=='/api/modeler/solve':
        settings=body.get('sensitivity')
        if settings is not None and not isinstance(settings,dict):raise ValueError('敏感性配置无效')
        solution=solve_modeler(_data(state),sensitivity=settings)
        state['solution']=solution;state['revision']+=1
        server.record('modeler_solved',operator=_operator(handler),objects=len(solution['objects']),
                      state_revision=state['revision'],point_rms_px=solution['optimization']['point_rms_px'])
        handler.send_json(200,{'state':state,'solution':solution});return True
    elif path=='/api/modeler/commit':
        if state.get('solution') is None:raise ValueError('请先求解当前观测')
        if body.get('confirm_up_assumed') is not True:raise ValueError('请确认场景向上方向是未经验证的假设或声明')
        scale=body.get('scale')
        if isinstance(scale,dict) and scale.get('schema')=='worldstate-multiview-scale-anchor/0.1':
            obj=next((o for o in state['objects'] if o['id']==scale.get('object_id')),None)
            endpoints=scale.get('endpoints')
            if not obj or not isinstance(endpoints,list) or len(endpoints)!=2:
                raise ValueError('请将标尺端点绑定到当前构件')
            allowed=obj['vertices']+([obj['construction']['direction_feature']]
                if obj.get('construction',{}).get('kind')=='edge_to_line' else [])
            for endpoint in endpoints:
                if not isinstance(endpoint,dict):raise ValueError('标尺端点无效')
                feature=endpoint.get('id');provided=endpoint.get('observations')
                if feature not in allowed or not isinstance(provided,list):raise ValueError('标尺端点无效')
                if any(not isinstance(o,dict) or isinstance(o.get('image_id'),bool) or not isinstance(o.get('image_id'),int) for o in provided):
                    raise ValueError('标尺观测无效')
                current=[{'image_id':o['image_id'],'photo_sha256':o['photo_sha256'],'pixel_xy':o['pixel_xy']}
                    for o in state['observations'] if o['kind']=='point' and o['object_id']==obj['id'] and
                    o.get('feature_id')==feature and o['visibility']=='visible' and
                    o['confirmation'] not in {'proposed','rejected'}]
                if len(current)<2 or sorted(provided,key=lambda x:x['image_id'])!=sorted(current,key=lambda x:x['image_id']):
                    raise ValueError('标尺端点或照片观测已改变，请重新绑定标尺')
        before=server.model
        if before and not any(e.get('kind')=='multiview_modeler_observations' for e in before['evidence']):
            raise ValueError('现有模型不是本建模器创建的；请使用独立项目')
        model=build_room_ir(_data(state),state['solution'],project_id=project['id'],scale=scale,
            thickness_m=body.get('thickness_m'),up_source=body.get('up_source'),
            allow_rectangular_approximation=body.get('allow_rectangular_approximation'))
        model['revision']=before['revision']+1 if before else 1
        event={'revision':model['revision'],'action':'modeler_solve_commit','operator':_operator(handler),
               'input_sha256':state['solution']['input_sha256'],'warning':'Visible patches and assumptions require review.'}
        model['history']=copy.deepcopy(before.get('history',[])) + [event] if before else [event]
        target=server.workspace/f"revision-{model['revision']:03}";save_version(model,target,diff=event)
        server.model,server.model_dir=model,target;project['current_revision']=model['revision']
        state['model_dirty']=False;state['revision']+=1;server.record('modeler_ifc_created',operator=_operator(handler),model_revision=model['revision'])
        handler.send_json(201,{'state':state,'model':model,'diff':event});return True
    else:return False
    state['solution']=None;state['model_dirty']=True;state['suggestions']=[];state['revision']+=1
    server.record('modeler_observation_changed' if 'kind' in event else 'modeler_object_created',
                  operator=_operator(handler),state_revision=state['revision'],**event)
    handler.send_json(201,{'state':state});return True
