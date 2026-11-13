"""Bind a measured scale to physical endpoints and their image observations."""
from __future__ import annotations
import hashlib
import json
import math
from typing import Any


def scale_snapshot(project: dict, uploads: list[dict]) -> dict[str, Any]:
    """Describe the exact observations and geometry used by the scale anchor.

    A different photo, endpoint, camera or reference measurement makes this
    snapshot different. Recording a snapshot is not a verification of a ruler.
    """
    layout=project.get('layout') or {}; reference=project.get('reference') or {}
    wall=reference.get('wall_index'); length=reference.get('length_m')
    if isinstance(wall,bool) or not isinstance(wall,int) or wall<1:
        raise ValueError('请指定尺度参照墙段')
    if isinstance(length,bool) or not isinstance(length,(int,float)) or not math.isfinite(length) or length<=0:
        raise ValueError('尺度参照长度必须为正数')
    if reference.get('basis') not in {'independent_user_declared','same_sensor','assumed'}:
        raise ValueError('请说明尺度参照来源')
    if not isinstance(reference.get('description'),str) or not reference['description'].strip():
        raise ValueError('请说明标尺实际物理端点和测量来源')
    photos={x['id']:x for x in uploads}
    mode=layout.get('mode','manual_schematic')
    if mode=='photo_floor':
        photo=photos.get(layout.get('photo_id'))
        corners={}
        for ann in project.get('annotations',[]):
            if ann.get('kind')=='corner' and ann.get('photo_id')==layout.get('photo_id'):
                name=ann.get('object_id')
                if name in corners:raise ValueError('尺度墙段端点重复')
                corners[name]=ann
        first=f'node-{wall}'
        second=f'node-{wall+1}' if f'node-{wall+1}' in corners else ('node-1' if layout.get('closed') else '')
        a,b=corners.get(first),corners.get(second)
        if photo is None or a is None or b is None:
            raise ValueError('请先在相机照片标注标尺墙段的两个物理角点')
        observations=[{'annotation_id':ann['id'],'node_id':node,'points_px':ann['points']} for node,ann in ((first,a),(second,b))]
        geometry={'mode':mode,'camera':layout.get('camera'),'photo_id':photo['id']}
    elif mode=='manual_schematic':
        points=layout.get('points') or []
        if not isinstance(points,list) or len(points)<2 or wall>len(points)-(0 if layout.get('closed') else 1):
            raise ValueError('尺度参照墙段必须有两个草图端点')
        found=[a for a in project.get('annotations',[]) if a.get('kind')=='scale' and a.get('wall_id')==f'wall-{wall}']
        if len(found)!=1:
            raise ValueError('请在照片中标记且仅标记一组该墙段的尺度物理端点')
        ann=found[0];photo=photos.get(ann.get('photo_id'))
        if photo is None or not isinstance(ann.get('points'),list) or len(ann['points'])!=2:
            raise ValueError('尺度端点必须关联已上传照片')
        observations=[{'annotation_id':ann['id'],'node_ids':[f'node-{wall}',f'node-{wall%len(points)+1}'],
                       'points_px':ann['points']}]
        geometry={'mode':mode,'anchor_plan_points':[points[wall-1],points[wall%len(points)]]}
    else:
        raise ValueError('不支持的尺度几何路径')
    snapshot={'photo_id':photo['id'],'photo_sha256':photo['sha256'],'observations':observations,
              'wall_id':f'wall-{wall}','geometry':geometry,
              'measurement':{'length_m':length,'basis':reference['basis'],'description':reference['description']}}
    try:json.dumps(snapshot,allow_nan=False)
    except (ValueError,TypeError) as exc:raise ValueError('尺度端点或相机参数无效') from exc
    return snapshot


def snapshot_digest(snapshot: dict) -> str:
    """Stable digest to detect changes, not proof of a physical measurement."""
    value=json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(value.encode()).hexdigest()


def bind_scale(project: dict, uploads: list[dict], *, confirmed: bool) -> dict:
    """Explicitly attest the current measurement belongs to the pictured endpoints."""
    if confirmed is not True:
        raise ValueError('请确认长度确属当前物理端点；端点改变时需重新测量')
    snapshot=json.loads(json.dumps(scale_snapshot(project,uploads),allow_nan=False))
    return {'schema':'worldstate-scale-binding/0.1','snapshot':snapshot,'sha256':snapshot_digest(snapshot),
            'status':'user_confirmed_not_independently_verified'}


def require_current_scale(project: dict, uploads: list[dict]) -> dict:
    """Reject stale, absent or tampered scale bindings before model generation."""
    binding=project.get('scale_binding')
    if not isinstance(binding,dict) or binding.get('schema')!='worldstate-scale-binding/0.1':
        raise ValueError('请先将测量长度绑定到照片中的实际物理端点')
    snapshot=scale_snapshot(project,uploads)
    digest=snapshot_digest(snapshot)
    if binding.get('sha256')!=digest or binding.get('snapshot')!=snapshot:
        raise ValueError('尺度参照已失效：端点、照片、相机或测量发生变化；请重新核对或测量并绑定')
    return binding
