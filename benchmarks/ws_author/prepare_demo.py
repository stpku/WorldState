"""Import the distributable synthetic text-design example into a new workspace."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import ifcopenshell
from products.worldstate_bim.room_ir import validate_room

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--operator',choices=['user','automation'],default='user')
    args=p.parse_args();workspace=args.output
    if workspace.exists() or workspace.is_symlink():raise FileExistsError('choose a new workspace; existing projects are not overwritten')
    example=ROOT/'examples/bim_text_author';model=json.loads((example/'model.json').read_text())
    validate_room(model)
    if model.get('revision')!=1 or model.get('validation',{}).get('scope')!='SIMULATED_TEXT_TO_BIM':
        raise ValueError('example is not an initial synthetic design')
    if ifcopenshell.open(str(example/'model.ifc')).schema!='IFC4':raise ValueError('example requires IFC4')
    workspace.mkdir(parents=True,mode=0o700);revision=workspace/'revision-001';revision.mkdir(mode=0o700)
    for name in ('model.json','model.ifc'):shutil.copyfile(example/name,revision/name)
    project={'schema':'worldstate-photo-project/0.1','id':model['project_id'],'name':'Text-to-BIM · Simulated Room',
             'operator_kind':args.operator,'current_revision':1,'events':[],
             'notes':'Synthetic text-authored design; not a site observation.'}
    (workspace/'photo-project.json').write_text(json.dumps(project,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'workspace':str(workspace),'operator_kind':args.operator,'revision':1,'status':'SIMULATED_NOT_OBSERVED'},ensure_ascii=False))


if __name__=='__main__':main()
