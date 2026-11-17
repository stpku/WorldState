"""Regrade stored real Agent outputs; never call the model or alter originals."""
import argparse
import json
from pathlib import Path
from benchmarks.ws_agent.run import score,sha,write


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--tasks',type=Path,default=Path(__file__).with_name('tasks.json'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new audit output')
    frozen=json.loads((a.run/'frozen-run.json').read_text())
    if frozen['mode']!='agent' or sha(a.tasks)!=frozen['tasks_sha256']:raise ValueError('task manifest is not the original frozen set')
    tasks=json.loads(a.tasks.read_text())['tasks'];a.output.mkdir(parents=True);results=[]
    for task in tasks:
        root=a.run/task['id'];run=json.loads((root/'agent'/'run.json').read_text());project=json.loads((root/'workspace'/'photo-project.json').read_text())
        model=json.loads((root/'workspace'/f"revision-{project['current_revision']:03}"/'model.json').read_text())
        proposals=[json.loads(f.read_text()) for f in sorted((root/'agent').glob('revision-proposal-*.json'),key=lambda x:x.stat().st_mtime_ns)]
        dest=a.output/task['id'];dest.mkdir();result=score(task,model,proposals,run.get('result',''),run.get('tool_failures',[]),dest)
        result.update(provider_status=run['status'],usage=run.get('usage'),elapsed_seconds=run.get('elapsed_seconds'))
        write(dest/'score.json',result);results.append(result)
    report={'status':'COMPLETED_REGRADING_NO_NEW_MODEL_CALL','tasks':len(results),'passed':sum(x['status']=='PASS' for x in results),
            'success_rate':sum(x['status']=='PASS' for x in results)/len(results),'tasks_sha256':frozen['tasks_sha256'],
            'reason':'Stricter audit: an unsupported parameter error is not proof that an angular constraint was checked.',
            'results':results}
    write(a.output/'summary.json',report);print(json.dumps({k:report[k] for k in ('tasks','passed','success_rate','reason')}))


if __name__=='__main__':main()
