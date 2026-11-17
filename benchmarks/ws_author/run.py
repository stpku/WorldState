"""Run frozen synthetic authoring tasks with the actual scoped Codex provider."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from products.worldstate_bim.agent_runner import run_codex_agent
from products.worldstate_bim.general_modeler import digest
from products.worldstate_bim.history_tools import restore_preview, restored_model
from products.worldstate_bim.room_cli import save_version
from products.worldstate_bim.room_ifc import export_room, stable_guid
from products.worldstate_bim.room_ir import geometry_issues, revise_element
from products.worldstate_bim.text_author import build_design

ROOT=Path(__file__).resolve().parents[2]


def write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def check_ifc(model, path):
    """Use the independent IFC reader, validator and geometry engine."""
    export_room(model,path)
    file=ifcopenshell.open(str(path))
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(file,logger)
    settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    geometry=[]
    for kind in ('IfcWall','IfcSlab','IfcDoor','IfcWindow'):
        for entity in file.by_type(kind):
            try:geometry.append(bool(ifcopenshell.geom.create_shape(settings,entity).geometry.verts))
            except Exception:geometry.append(False)
    expected={kind:sum(e['ifc_type']==kind for e in model['elements'])
              for kind in ('IfcWall','IfcSlab','IfcDoor','IfcWindow','IfcSpace','IfcOpeningElement')}
    counts={kind:len(file.by_type(kind)) for kind in expected}
    opening_count=expected['IfcOpeningElement']
    voids=file.by_type('IfcRelVoidsElement');fills=file.by_type('IfcRelFillsElement')
    by_id={e['id']:e for e in model['elements']}
    guid=lambda e:stable_guid(model['project_id'],e['ifc_type'],e['id'])
    relationships=len(voids)==opening_count and len(fills)==opening_count
    for opening in (e for e in model['elements'] if e['ifc_type']=='IfcOpeningElement'):
        relationships=relationships and any(r.RelatingBuildingElement.GlobalId==guid(by_id[opening['host']]) and
                      r.RelatedOpeningElement.GlobalId==guid(opening) for r in voids)
        relationships=relationships and any(r.RelatingOpeningElement.GlobalId==guid(opening) and
                      r.RelatedBuildingElement.GlobalId==guid(by_id[opening['fill']]) for r in fills)
    return {'schema':file.schema,'schema_errors':len(logger.statements),'expected_counts':expected,'ifc_counts':counts,
            'geometry_ok':sum(geometry),'geometry_total':len(geometry),'host_relations_ok':relationships,
            'ir_issues':geometry_issues(model)}


def check_design(task, workspace, output):
    proposals=[p for p in output.glob('design-proposal-*.json') if not p.stem.endswith('-model')]
    if len(proposals)!=1:raise ValueError('expected exactly one design proposal')
    proposal=json.loads(proposals[0].read_text());spec=proposal['spec']
    if spec!=task['expected']:raise ValueError('proposed specification differs from frozen reference')
    project=json.loads((workspace/'photo-project.json').read_text())
    if proposal['project_id']!=project['id']:raise ValueError('project identity mismatch')
    model=build_design(spec,project_id=project['id'],user_request=task['prompt'])
    saved=json.loads((output/(proposal['id']+'-model.json')).read_text())
    if digest(saved)!=digest(model) or digest(model)!=proposal['model_sha256']:
        raise ValueError('candidate differs from deterministic reconstruction')
    if sha(output/(proposal['id']+'.ifc'))!=proposal['ifc_sha256']:
        raise ValueError('IFC proposal hash mismatch')
    if any(x['classification']['status']!='simulated' for x in model['elements']):
        raise ValueError('design was not marked simulated')
    if model['evidence'][0]['source_text']!=task['prompt'] or model['validation']['scope']!='SIMULATED_TEXT_TO_BIM':
        raise ValueError('missing simulated request provenance')
    info=check_ifc(model,output/'independently-checked.ifc')
    if (info['schema']!='IFC4' or info['schema_errors'] or info['expected_counts']!=info['ifc_counts'] or
        info['geometry_ok']!=info['geometry_total'] or not info['host_relations_ok'] or info['ir_issues']):
        raise ValueError('IFC geometry, schema, object counts, hosts or IR constraints failed: '+str(info))
    return proposal,model,info


def run_agent(workspace, output, goal, args, *, author=False):
    output.mkdir()
    return run_codex_agent(workspace=workspace,output=output,image_ids=[],goal=goal,
          codex=args.codex,node=args.node,model=args.model,timeout=args.timeout,
          author_only=author,model_only=not author)


def check_sequence(task, workspace, source_model, output, args):
    """Actually run and auto-confirm the task's follow-up edit and restore."""
    save_version(source_model,workspace/'revision-001')
    project=json.loads((workspace/'photo-project.json').read_text());project['current_revision']=1
    write(workspace/'photo-project.json',project)
    edit_text,restore_text=task['prompt'].split('；',1)[1].split('，最后',1)
    edit_goal=edit_text+'；请只生成预览，等待确认。'
    edit_dir=output/'edit';edit_meta=run_agent(workspace,edit_dir,edit_goal,args)
    edit_files=list(edit_dir.glob('revision-proposal-*.json'))
    if len(edit_files)!=1:raise ValueError('follow-up edit did not produce exactly one proposal')
    proposal=json.loads(edit_files[0].read_text());expected=task['expected_edit']
    if any(proposal.get(k)!=v for k,v in expected.items()) or proposal.get('source_model_sha256')!=digest(source_model):
        raise ValueError('edit differs from frozen expected action or source revision')
    edited,_=revise_element(source_model,expected['element_id'],expected['attribute'],expected['value'],reason='automated benchmark confirmation',operator='automation')
    save_version(edited,workspace/'revision-002');project['current_revision']=2;write(workspace/'photo-project.json',project)
    restore_dir=output/'restore';restore_meta=run_agent(workspace,restore_dir,'请预览'+restore_text+'；等待确认。',args)
    files=list(restore_dir.glob('restore-proposal-*.json'))
    if len(files)!=1:raise ValueError('follow-up restore did not produce exactly one preview')
    restore=json.loads(files[0].read_text());previous,preview=restore_preview(workspace,edited,task['restore_revision'])
    if (restore['source_model_sha256']!=digest(edited) or restore['target_model_sha256']!=digest(previous) or restore['preview']!=preview):
        raise ValueError('restore preview is stale or inaccurate')
    final=restored_model(edited,previous);save_version(final,workspace/'revision-003')
    if (final['elements']!=source_model['elements'] or final['nodes']!=source_model['nodes'] or
        {e['id'] for e in final['elements']}!={e['id'] for e in source_model['elements']}):
        raise ValueError('restored model or object identity differs from version 1')
    original=ifcopenshell.open(str(workspace/'revision-001/model.ifc'))
    restored=ifcopenshell.open(str(workspace/'revision-003/model.ifc'))
    ids=lambda f:{e.GlobalId for e in f.by_type('IfcProduct') if e.GlobalId}
    if ids(original)!=ids(restored):raise ValueError('IFC GUID identity changed on restore')
    return {'edit':edit_meta,'restore':restore_meta,'restored_revision':3,'guid_preserved':True,'confirmation':'automation'}


def execute(task,root,args):
    started=time.monotonic();directory=root/task['id'];directory.mkdir();workspace=directory/'workspace';workspace.mkdir()
    project={'schema':'worldstate-photo-project/0.1','id':'ws-author-'+task['id']+'-'+uuid.uuid4().hex,
             'name':'Synthetic author benchmark','operator_kind':'automation','current_revision':None,'events':[]}
    write(workspace/'photo-project.json',project)
    write(workspace/'evidence-index.json',{'schema':'worldstate-studio-evidence/0.1','uploads':[]})
    result={'id':task['id'],'kind':task['kind'],'status':'FAIL','reason':'','model_fee':'NOT_MEASURED','human_labor':'NOT_MEASURED'}
    try:
        output=directory/'agent';meta=run_agent(workspace,output,task['prompt'],args,author=True)
        result.update(provider_status=meta['status'],elapsed_provider_seconds=meta['elapsed_seconds'],usage=meta['usage'],
                      successful_tools=meta['successful_tools'],tool_failures=meta['tool_failures'])
        if meta['status'] not in {'COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'}:
            raise ValueError('provider did not complete: '+meta['status'])
        if task['kind'] in {'create','sequence'}:
            proposal,model,checks=check_design(task,workspace,output);result['ifc']=checks
            if task['kind']=='sequence':result['sequence']=check_sequence(task,workspace,model,directory,args)
            result.update(status='PASS',reason='actual provider proposal matches frozen simulated design and IFC checks')
        else:
            files=[p for p in output.glob('design-proposal-*.json') if not p.stem.endswith('-model')]
            if files:raise ValueError('unsafe model proposal for missing or impossible input')
            text=(meta.get('result','')+' '+' '.join(meta.get('tool_failures',[]))).lower()
            patterns={'missing height':r'高|height','missing wall thickness':r'墙厚|thickness',
                      'notch exceeds overall size':r'缺口|大于|长度|不可能|notch',
                      'opening outside host':r'越|超|墙长|门洞|outside|conflict',
                      'unspecified host wall':r'哪面|哪一|哪堵|宿主|指定|位置|wall'}
            if not re.search(patterns[task['reason']],text,re.I):raise ValueError('did not explain the relevant missing or conflicting condition')
            result.update(status='PASS',reason='no model proposal; provider explained the missing or impossible condition')
    except Exception as exc:
        result['reason']=str(exc)[:700]
    result['elapsed_seconds']=round(time.monotonic()-started,3)
    write(directory/'score.json',result)
    print(json.dumps({k:result[k] for k in ('id','status','reason')},ensure_ascii=False),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks',type=Path,default=Path(__file__).with_name('tasks.json'));p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=1);p.add_argument('--timeout',type=int,default=150)
    p.add_argument('--codex',default='/home/dev/.local/node/bin/codex');p.add_argument('--node',default='/home/dev/.local/node/bin/node')
    p.add_argument('--model',default='gpt-6.1-terra');a=p.parse_args()
    if a.output.exists():raise FileExistsError('use a fresh output directory')
    if not 1<=a.workers<=2:raise ValueError('workers must be 1 or 2')
    tasks=json.loads(a.tasks.read_text())['tasks']
    if len(tasks)<15 or len({t['id'] for t in tasks})!=len(tasks):raise ValueError('at least 15 distinct tasks required')
    a.output.mkdir(parents=True,mode=0o700)
    write(a.output/'frozen-run.json',{'tasks_sha256':sha(a.tasks),'protocol_sha256':sha(Path(__file__).with_name('PROTOCOL.md')),
          'task_count':len(tasks),'provider':a.model,'mode':'actual_agent','automated_confirmation':True})
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(execute,t,a.output,a) for t in tasks];results=[f.result() for f in futures]
    passed=sum(r['status']=='PASS' for r in results)
    summary={'status':'COMPLETED','tasks':len(results),'passed':passed,'success_rate':passed/len(results),
             'model_cost':'NOT_MEASURED','human_cost':'NOT_MEASURED','results':results}
    write(a.output/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('tasks','passed','success_rate')}))


if __name__=='__main__':main()
