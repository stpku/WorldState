"""Load the distributable synthetic room into a new Studio workspace."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil

from benchmarks.ws_realroom.prepare_agent_photo_project import prepare
from products.worldstate_bim.room_ir import validate_room


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--example',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--operator',choices=['user','automation'],default='user')
    a=p.parse_args();example=a.example.resolve(strict=True)
    if a.output.exists():raise FileExistsError('choose a new workspace; existing projects are never overwritten')
    model=json.loads((example/'reference'/'model.json').read_text());validate_room(model)
    if model['revision']!=1:raise ValueError('example must be an initial version')
    prepare(example/'input'/'images',example/'input'/'cameras.json',a.output,'Synthetic Room · Research Preview')
    project_path=a.output/'photo-project.json';project=json.loads(project_path.read_text())
    project['id']=model['project_id'];project['current_revision']=1;project['operator_kind']=a.operator
    project['notes']='Synthetic RGB, cameras and IFC are generated from the same simulated scene; not real evidence.'
    revision=a.output/'revision-001';revision.mkdir()
    for name in ('model.json','model.ifc'):shutil.copyfile(example/'reference'/name,revision/name)
    project_path.write_text(json.dumps(project,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'workspace':str(a.output),'operator':a.operator,'images':len(project['general_modeler']['cameras']),
                      'model':'SYNTHETIC_NOT_RECONSTRUCTED','revision':1},ensure_ascii=False))


if __name__=='__main__':main()
