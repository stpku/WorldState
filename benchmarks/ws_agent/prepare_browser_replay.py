"""Replay actual WS-Agent proposals in a new, isolated automated Studio project."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new isolated output')
    source=a.task_run.resolve(strict=True);run=json.loads((source/'agent'/'run.json').read_text());project=json.loads((source/'workspace'/'photo-project.json').read_text())
    if project.get('operator_kind')!='automation' or run.get('status')!='COMPLETED' or len(run.get('revision_proposals',[]))<2:
        raise ValueError('requires an actual completed automated multi-proposal Agent task')
    a.output.mkdir(parents=True,mode=0o700);shutil.copytree(source/'workspace',a.output/'workspace')
    ident='agent-'+uuid.uuid4().hex;job=a.output/'jobs'/ident;job.parent.mkdir();shutil.copytree(source/'agent',job)
    metadata={'id':ident,'project_id':project['id'],'status':run['status'],'source_revision':run['source_revision'],
              'image_ids':run['image_ids'],'selected_id':run.get('selected_id'),'result':run['result'],
              'candidates':run['candidates'],'error':None,'started_at':datetime.now(timezone.utc).isoformat(),
              'replay':'Actual Agent artifacts copied into an isolated automation workspace; no new model call.'}
    (job/'job.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'workspace':str(a.output/'workspace'),'jobs':str(a.output/'jobs'),'job_id':ident,'proposals':len(run['revision_proposals']),'operator':'automation'}))


if __name__=='__main__':main()
