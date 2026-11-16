"""Run predeclared synthetic natural-language tasks; Agent and rules stay separate."""
from __future__ import annotations
import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from products.worldstate_bim.agent_runner import run_codex_agent
from products.worldstate_bim.room_cli import save_version
from products.worldstate_bim.room_ifc import export_room,stable_guid
from products.worldstate_bim.room_ir import geometry_issues,revise_element
from products.worldstate_bim.studio_server import parse_local_command

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def setup(root, source, task):
    workspace=root/'workspace';workspace.mkdir(parents=True);model=copy.deepcopy(source)
    if task.get('variant')=='unconstrained':model['constraints']=[]
    save_version(model,workspace/'revision-001')
    if task.get('variant')=='history':
        model,_=revise_element(model,'wall-2','height',2.9,reason='synthetic setup',operator='analyst')
        save_version(model,workspace/'revision-002')
    project={'schema':'worldstate-photo-project/0.1','id':model['project_id'],'name':'Simulated Benchmark Room',
             'operator_kind':'automation','current_revision':model['revision'],'events':[]}
    write(workspace/'photo-project.json',project);write(workspace/'evidence-index.json',{'schema':'worldstate-studio-evidence/0.1','uploads':[]})
    return workspace,model


def mesh_signature(settings,entity):
    shape=ifcopenshell.geom.create_shape(settings,entity);v=list(shape.geometry.verts)
    return sorted(tuple(round(v[i+j],6) for j in range(3)) for i in range(0,len(v),3))


def ifc_check(before,after,required_keep,work):
    first=export_room(before,work/'before.ifc');second=export_room(after,work/'after.ifc')
    f=ifcopenshell.open(str(first));g=ifcopenshell.open(str(second));logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(g,logger)
    ids=lambda x:{e.GlobalId for e in x.by_type('IfcProduct') if e.GlobalId}
    settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    keep=[]
    for ident in required_keep:
        e=next(x for x in before['elements'] if x['id']==ident);guid=stable_guid(before['project_id'],e['ifc_type'],ident)
        keep.append({'id':ident,'same_vertices':mesh_signature(settings,f.by_guid(guid))==mesh_signature(settings,g.by_guid(guid))})
    checks=[]
    for typ in ('IfcWall','IfcSlab','IfcDoor','IfcWindow'):
        for entity in g.by_type(typ):
            try:shape=ifcopenshell.geom.create_shape(settings,entity);checks.append(bool(shape.geometry.verts))
            except Exception:checks.append(False)
    return {'ifc4':g.schema=='IFC4','schema_errors':len(logger.statements),'guid_sets_equal':ids(f)==ids(g),
            'keep':keep,'geometry_ok':sum(checks),'geometry_total':len(checks),'ir_issues':geometry_issues(after),
            'links':{'voids':len(g.by_type('IfcRelVoidsElement')),'fills':len(g.by_type('IfcRelFillsElement'))}}


def score(task,model,proposals,text,tool_errors,work):
    kind=task['kind'];text=' '.join([text or '',*tool_errors]);lower=text.lower()
    proposed=[(p.get('element_id'),p.get('attribute'),p.get('value')) for p in proposals]
    result={'id':task['id'],'kind':kind,'status':'FAIL','reason':'', 'actual_proposals':proposed}
    if kind in {'edit','multi'}:
        expected=[tuple(x) for x in task['steps']]
        if len(proposed)!=len(expected):result['reason']='wrong proposal count';return result
        for got,want in zip(proposed,expected):
            if got[:2]!=want[:2] or not isinstance(got[2],(int,float)) or abs(got[2]-want[2])>1e-5:
                result['reason']='wrong target, parameter, order or value';return result
        changed=copy.deepcopy(model);diffs=[]
        try:
            for ident,attribute,value in proposed:
                changed,diff=revise_element(changed,ident,attribute,value,reason='automated synthetic benchmark',operator='analyst');diffs.append(diff)
            checks=ifc_check(model,changed,task.get('keep',[]),work)
            result['ifc']=checks;result['diffs']=diffs
            if (checks['ifc4'] and not checks['schema_errors'] and checks['guid_sets_equal'] and
                checks['geometry_ok']==checks['geometry_total'] and not checks['ir_issues'] and all(x['same_vertices'] for x in checks['keep'])):
                result.update(status='PASS',reason='expected proposal(s), synthetic IR and IFC checks passed')
            else:result['reason']='IFC, GUID, topology/geometry or unchanged-object check failed'
        except Exception as exc:result['reason']='deterministic validation failed: '+str(exc)[:300]
        return result
    if kind=='restore_action':
        result['reason']='No supported version-restore proposal and verified restoration artifact';return result
    patterns={
      'OPENING_OUTSIDE_WALL':r'opening_outside_wall|越界|超出|墙长|过短|太短',
      'OPENING_ABOVE_WALL':r'opening_above_wall|墙高|门洞|门高|超出|太矮',
      'invalid dimension':r'负|大于零|正数|无效|不能|invalid|negative',
      'unknown element':r'不存在|找不到|未找到|未发现|没有|unknown|not found',
      'ANGULAR_CONSTRAINT_CONFLICT':r'angular_constraint_conflict|垂直|角度|约束|冲突',
      'ambiguous wall':r'哪面|哪个|选择|指定|明确|哪一|多面|多个',
      'stale suggestion':r'过期|旧|重新|更新|版本|stale',
      'version restore requires explicit supported operation':r'确认|不支持|没有|无法|不能|工具|版本|confirm|unsupported',
    }
    pattern=patterns[task['reason']]
    if not proposals and re.search(pattern,lower,re.I):
        result.update(status='PASS',reason='no mutation proposal and an explicit matching explanation')
    else:result['reason']='unsafe proposal or missing explicit matching explanation'
    return result


def execute(task,source,root,mode,args):
    directory=root/task['id'];directory.mkdir();workspace,model=setup(directory,source,task);started=time.monotonic();proposals=[];text='';errors=[];metadata={}
    if mode=='rules':
        try:
            ident,attribute,value=parse_local_command(model,task['prompt'],task.get('selected'))
            # Run the deterministic guard before exposing the proposed change.
            revise_element(model,ident,attribute,value,reason='rule baseline',operator='analyst')
            proposals=[{'element_id':ident,'attribute':attribute,'value':value}]
        except Exception as exc:errors=[str(exc)]
    else:
        output=directory/'agent';output.mkdir()
        try:
            metadata=run_codex_agent(workspace=workspace,output=output,image_ids=[],goal=task['prompt'],
                codex=args.codex,node=args.node,model=args.model,timeout=args.timeout,selected_id=task.get('selected'),model_only=True)
            text=metadata.get('result','');errors=metadata.get('tool_failures',[])
            proposals=[json.loads(p.read_text()) for p in sorted(output.glob('revision-proposal-*.json'),key=lambda x:x.stat().st_mtime_ns)]
        except Exception as exc:errors=[str(exc)];metadata={'status':'RUNNER_FAILURE'}
    result=score(task,model,proposals,text,errors,directory)
    result.update(mode=mode,elapsed_seconds=round(time.monotonic()-started,3),provider_status=metadata.get('status'),
                  usage=metadata.get('usage'),successful_tools=metadata.get('successful_tools'),tool_failures=errors,
                  model_fee='NOT_MEASURED',human_labor='NOT_MEASURED')
    write(directory/'score.json',result);print(json.dumps({'task':task['id'],'mode':mode,'status':result['status'],'reason':result['reason']},ensure_ascii=False),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tasks',type=Path,default=Path(__file__).with_name('tasks.json'));p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['rules','agent'],required=True);p.add_argument('--workers',type=int,default=1);p.add_argument('--timeout',type=int,default=120)
    p.add_argument('--codex',default='/home/dev/.local/node/bin/codex');p.add_argument('--node',default='/home/dev/.local/node/bin/node');p.add_argument('--model',default='gpt-6.1-terra');a=p.parse_args()
    if a.output.exists():raise FileExistsError('use a new output directory')
    if not 1<=a.workers<=2:raise ValueError('workers must be 1 or 2; avoid overloading model service')
    manifest=json.loads(a.tasks.read_text());tasks=manifest['tasks'];source_path=ROOT/manifest['model'];source=json.loads(source_path.read_text())
    if len(tasks)<20 or len({x['id'] for x in tasks})!=len(tasks):raise ValueError('task set must contain at least 20 unique tasks')
    a.output.mkdir(parents=True,mode=0o700);write(a.output/'frozen-run.json',{'tasks_sha256':sha(a.tasks),'model_sha256':sha(source_path),'mode':a.mode,'task_count':len(tasks),'provider':a.model if a.mode=='agent' else 'local_rules'})
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as executor:
        futures=[executor.submit(execute,t,source,a.output,a.mode,a) for t in tasks];results=[f.result() for f in futures]
    result={'status':'COMPLETED','mode':a.mode,'tasks':len(results),'passed':sum(r['status']=='PASS' for r in results),
            'success_rate':sum(r['status']=='PASS' for r in results)/len(results),'model_cost':'NOT_MEASURED','human_cost':'NOT_MEASURED',
            'caveats':['Synthetic independent tasks. Multi-proposal scoring simulates deterministic confirmation; it does not prove atomic UI application.',
                       'Restore action remains failed unless a supported restore proposal and verified artifact exist.'], 'results':results}
    write(a.output/'summary.json',result);print(json.dumps({k:result[k] for k in ('mode','tasks','passed','success_rate')},ensure_ascii=False))


if __name__=='__main__':main()
