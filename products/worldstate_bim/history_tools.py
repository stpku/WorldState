"""Inspect and preview immutable Room IR revisions without mutating them."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import re
from .modeling_tools import compare_revisions
from .room_ir import geometry_issues, validate_room


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():raise ValueError('historical model is unavailable or symlinked')
    return json.loads(path.read_text())


def historical_model(workspace: Path, current: dict, revision: int) -> dict:
    if isinstance(revision,bool) or not isinstance(revision,int) or revision<1:raise ValueError('invalid historical revision')
    directory=workspace/f'revision-{revision:03}'
    if directory.is_symlink() or not directory.is_dir():raise ValueError('historical revision unavailable or symlinked')
    model=_read(directory/'model.json');validate_room(model)
    if model['project_id']!=current['project_id'] or model['revision']!=revision:raise ValueError('historical model identity mismatch')
    return model


def list_versions(workspace: Path, current: dict) -> dict:
    """List only valid versions from the current project; never read arbitrary paths."""
    versions=[]
    for p in sorted(workspace.glob('revision-*')):
        match=re.fullmatch(r'revision-([0-9]+)',p.name)
        if not match or p.is_symlink() or not p.is_dir():continue
        try:
            rev=int(match.group(1));model=historical_model(workspace,current,rev)
            versions.append({'revision':rev,'elements':len(model['elements']),'status':model.get('validation',{}).get('status','UNKNOWN')})
        except (ValueError,OSError,KeyError):continue
    if len(versions)>1000:raise ValueError('too many project versions')
    return {'current_revision':current['revision'],'versions':versions,'warning':'Historical snapshots are not independently validated.'}


def restore_preview(workspace: Path,current: dict,revision: int) -> tuple[dict,dict]:
    """Compare the requested historical model with the exact current version."""
    previous=historical_model(workspace,current,revision);comparison=compare_revisions(current,previous)
    old={x['id']:x for x in current['elements']};new={x['id']:x for x in previous['elements']}
    changes=[]
    for ident in sorted(set(old)&set(new)):
        before={k:v.get('value') for k,v in old[ident].get('parameters',{}).items()}
        after={k:v.get('value') for k,v in new[ident].get('parameters',{}).items()}
        if before!=after:changes.append({'id':ident,'before_parameters_m':before,'after_parameters_m':after})
    current_nodes={x['id']:(x['x'],x['y']) for x in current['nodes']};old_nodes={x['id']:(x['x'],x['y']) for x in previous['nodes']}
    changed_nodes=[{'id':i,'before':list(current_nodes[i]),'after':list(old_nodes[i])} for i in sorted(current_nodes.keys()&old_nodes.keys()) if current_nodes[i]!=old_nodes[i]]
    preview={'current_revision':current['revision'],'source_revision':revision,'comparison':{k:v for k,v in comparison.items() if k!='history'},
             'parameter_changes':changes,'node_changes':changed_nodes,'geometry_issues':geometry_issues(previous),
             'warning':'Preview only; a new version requires explicit confirmation. Not engineering validation.'}
    return previous,preview


def restored_model(current: dict, previous: dict) -> dict:
    """Create a new revision from a snapshot while preserving current history."""
    validate_room(current);validate_room(previous)
    if current['project_id']!=previous['project_id']:raise ValueError('historical model belongs to another project')
    restored=copy.deepcopy(previous);restored['revision']=current['revision']+1
    restored['history']=copy.deepcopy(current.get('history',[]))+[{'revision':restored['revision'],'action':'restore_snapshot','source_revision':previous['revision']}]
    restored['validation']={'status':'REQUIRES_REVALIDATION','note':'Restored historical version; verify before use'}
    validate_room(restored);return restored
