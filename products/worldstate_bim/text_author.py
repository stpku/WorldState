"""Compile bounded text-derived *design* proposals into the existing Room IR.

All geometry is simulated, never observed. The Agent supplies only structured
parameters; this module validates them and the existing compiler writes IFC.
"""
from __future__ import annotations
import math
import re
from typing import Any
from .room_ir import SCHEMA, geometry_issues, quantity, validate_room

SCHEMA_AUTHOR='worldstate-bim-text-design/0.1'


def _number(value: Any, name: str, *, zero: bool=False) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite numeric metre value')
    if (value<0 if zero else value<=0) or value>100:
        raise ValueError(f'{name} must be within valid design bounds')
    return float(value)


def _source_numbers(text: str) -> list[float]:
    """Extract explicit numeric metric quantities, including cm/mm conversion.

    Numeric presence is a conservative provenance check, not proof that an AI
    associated each number with the intended parameter. Review remains needed.
    """
    if not isinstance(text,str) or not text.strip() or len(text)>4000:raise ValueError('a bounded user design request is required')
    pattern=r'(?<![\d.])([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(毫米|厘米|mm|cm|米|m)(?![A-Za-z])'
    result=[]
    for raw,unit in re.findall(pattern,text,re.I):
        factor={'毫米':.001,'mm':.001,'厘米':.01,'cm':.01,'米':1.,'m':1.}[unit.lower()]
        result.append(float(raw)*factor)
    return result


def build_design(spec: dict, *, project_id: str, user_request: str) -> dict:
    """Create a synthetic parameterized room, rejecting unknown/invalid data."""
    if not isinstance(spec,dict) or spec.get('schema')!=SCHEMA_AUTHOR:raise ValueError('unsupported design schema')
    if set(spec)-{'schema','shape','length_m','width_m','height_m','wall_thickness_m','slab_thickness_m',
                  'notch_length_m','notch_width_m','openings','assumptions'}:
        raise ValueError('unrecognized design field')
    if not isinstance(project_id,str) or not project_id.strip():raise ValueError('project ID required')
    sources=_source_numbers(user_request);assumptions=spec.get('assumptions',{})
    if not isinstance(assumptions,dict) or len(assumptions)>40 or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() or len(v)>300 for k,v in assumptions.items()):
        raise ValueError('assumptions must map field paths to explicit reasons')
    used=set()
    def field(container,name,path=None,zero=False):
        path=path or name;value=_number(container.get(name),path,zero=zero)
        if not any(abs(value-x)<=1e-7 for x in sources):
            if path not in assumptions:raise ValueError(f'{path} is not supported by an explicit metric quantity; ask the user or declare an assumption')
            used.add(path);return value,'assumed'
        if path in assumptions:used.add(path);return value,'assumed'
        return value,'simulated'
    length,ls=field(spec,'length_m');width,ws=field(spec,'width_m');height,hs=field(spec,'height_m')
    thick,ts=field(spec,'wall_thickness_m');slab,ss=field(spec,'slab_thickness_m')
    shape=spec.get('shape')
    shape_patterns={'rectangle':r'矩形|长方形|正方形|方形|rectangle|rectangular|square',
                    'l_shape':r'(?<![A-Za-z])l\s*(?:形|型|[- ]\s*shaped?)(?![A-Za-z])'}
    if shape not in shape_patterns:raise ValueError('shape must be rectangle or l_shape')
    if not re.search(shape_patterns[shape],user_request,re.I) and 'shape' not in assumptions:
        raise ValueError('room shape was not specified; ask the user or declare a shape assumption')
    shape_assumed='shape' in assumptions
    if shape_assumed:used.add('shape')
    layout_assumed=ls=='assumed' or ws=='assumed' or shape_assumed
    if spec.get('shape')=='rectangle':points=[(0,0),(length,0),(length,width),(0,width)]
    elif spec.get('shape')=='l_shape':
        notch_l,nls=field(spec,'notch_length_m');notch_w,nws=field(spec,'notch_width_m')
        layout_assumed=layout_assumed or nls=='assumed' or nws=='assumed'
        if notch_l>=length or notch_w>=width:raise ValueError('notch must be smaller than the overall room dimensions')
        points=[(0,0),(length,0),(length,width-notch_w),(length-notch_l,width-notch_w),(length-notch_l,width),(0,width)]
    else:raise ValueError('shape must be rectangle or l_shape')
    refs=['design-request'];provenance=lambda:{'status':'simulated','evidence_refs':refs.copy()}
    q=lambda value,status='simulated':quantity(value,status,refs.copy(),'Text design proposal; not a physical measurement')
    nodes=[{'id':f'n{i+1}','x':x,'y':y,**provenance()} for i,(x,y) in enumerate(points)]
    if layout_assumed:
        for node in nodes:node['status']='assumed'
    walls=[{'id':f'wall-{i+1}','ifc_type':'IfcWall','start':f'n{i+1}','end':f'n{(i+1)%len(nodes)+1}',
       'axis_reference':'centerline','storey':'storey-1','classification':provenance(),
       'parameters':{'height':q(height,hs),'thickness':q(thick,ts),'base_elevation':q(0)}} for i in range(len(nodes))]
    openings=spec.get('openings')
    if not isinstance(openings,list) or len(openings)>16:raise ValueError('openings must be a list of at most 16 objects')
    products=[];counts={'door':0,'window':0}
    for i,item in enumerate(openings,1):
        if not isinstance(item,dict) or set(item)!={'kind','wall','offset_m','width_m','height_m','sill_m','panel_thickness_m'}:
            raise ValueError('opening fields must be complete and explicitly structured')
        kind=item['kind'];wall=item['wall']
        if kind not in counts or not isinstance(wall,str) or wall not in {w['id'] for w in walls}:
            raise ValueError('opening needs a door/window kind and a host ID such as wall-1; valid IDs: '+', '.join(w['id'] for w in walls))
        counts[kind]+=1;fill=f'{kind}-{counts[kind]}';opening=f'opening-{i}';params={}
        for key in ('offset','width','height','sill'):
            value,status=field(item,key+'_m',f'openings.{i-1}.{key}_m',zero=key in {'offset','sill'});params[key]=q(value,status)
        panel,ps=field(item,'panel_thickness_m',f'openings.{i-1}.panel_thickness_m')
        products.append({'id':opening,'ifc_type':'IfcOpeningElement','host':wall,'fill':fill,'storey':'storey-1',
                         'classification':provenance(),'parameters':params})
        products.append({'id':fill,'ifc_type':'IfcDoor' if kind=='door' else 'IfcWindow','opening':opening,
                         'storey':'storey-1','classification':provenance(),'parameters':{'panel_thickness':q(panel,ps)}})
    if set(assumptions)!=used:raise ValueError('assumption refers to an unused or unknown parameter')
    floor={'id':'slab-1','ifc_type':'IfcSlab','storey':'storey-1','classification':provenance(),
           'outline':[n['id'] for n in nodes],'outline_status':{'status':'assumed' if layout_assumed else 'simulated','evidence_refs':refs.copy()},
           'parameters':{'elevation':q(-slab,ss),'thickness':q(slab,ss)}}
    space={'id':'room-1','ifc_type':'IfcSpace','storey':'storey-1','classification':provenance(),
           'boundary_walls':[w['id'] for w in walls],'boundary_status':'closed_confirmed','parameters':{}}
    constraints=[{'id':f'right-{i+1}','kind':'perpendicular','a':f'wall-{i+1}','b':f'wall-{(i+1)%len(walls)+1}',**provenance()} for i in range(len(walls))]
    model={'schema':SCHEMA,'project_id':project_id,'mode':'assisted','revision':1,
       'coordinate_system':{'name':'simulated design coordinates, origin explicitly conventional','unit':'m'},
       'evidence':[{'id':'design-request','kind':'text_design','status':'simulated','source_text':user_request,
                    'assumptions':assumptions,'warning':'Design intent only; not a photograph, site observation or measurement.'}],
       'nodes':nodes,'storeys':[{'id':'storey-1','elevation':q(0)}],'elements':walls+products+[floor,space],
       'constraints':constraints,'validation':{'status':'UNVERIFIED_DESIGN','scope':'SIMULATED_TEXT_TO_BIM'},
       'author_spec':spec}
    validate_room(model);issues=geometry_issues(model)
    if issues:raise ValueError('design geometry conflict: '+', '.join(f"{x['id']}:{x['code']}" for x in issues))
    return model
