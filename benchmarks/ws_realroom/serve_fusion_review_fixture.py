"""Serve an existing real fusion as an automation-only Studio review fixture.

This fixture does not reconstruct photographs or measure a human operator. It
verifies source hashes and keeps all images in the caller's external workspace.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
from products.worldstate_bim.studio_server import StudioServer,_write_json


def digest(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--port',type=int,default=18731);a=p.parse_args()
    if a.workspace.exists():raise FileExistsError('choose a new external workspace')
    fusion=json.loads(a.fusion.read_text());source={}
    for track in fusion['tracks']:
        if track.get('status')!='SUPPORTED' or track.get('semantic_class')!=3:continue
        for obs in track.get('observations',[]):
            if obs.get('semantic_class')!=3:continue
            name=obs['photo'];sha=obs['photo_sha256'];path=a.images/name
            if Path(name).name!=name or path.is_symlink() or not path.is_file() or digest(path)!=sha:
                raise ValueError('fixture source photo hash mismatch')
            source[sha]=path
    if not source:raise ValueError('no supported floor observations')
    server=StudioServer(a.port,None,a.workspace)
    for sha,path in sorted(source.items()):
        with Image.open(path) as image:
            if image.format!='JPEG':raise ValueError('fixture currently accepts JPEG photos only')
            width,height=image.size
        shutil.copyfile(path,server.uploads/(sha+'.jpg'))
        server.uploaded.append({'id':'upload-'+sha[:16],'sha256':sha,'extension':'.jpg','mime':'image/jpeg',
            'width':width,'height':height,'quality':{'warnings':[]},'status':'automation_review_fixture','captured_at':'UNKNOWN'})
    _write_json(server.index,{'schema':'worldstate-studio-evidence/0.1','uploads':server.uploaded})
    gid='geometry-'+'1'*32;fid='fusion-'+'2'*32;fusion['id']=fid;fusion['geometry_run_id']=gid
    directory=server.workspace/'fusion'/fid;directory.mkdir(parents=True);_write_json(directory/'fusion.json',fusion)
    server.project={'schema':'worldstate-photo-project/0.1','id':'photo-room-'+'3'*32,
        'name':'Seeded fusion review fixture: not a reconstruction run','operator_kind':'automation',
        'created_at':datetime.now(timezone.utc).isoformat(),'annotations':[],'layout':{},'reference':{},'events':[],
        'current_revision':None,'geometry_runs':[{'id':gid,'status':'AUTOMATION_REVIEW_FIXTURE_ONLY',
            'registered_cameras':[],'inputs':[],'sparse_points':len(fusion['tracks'])}],
        'fusion_runs':[{'id':fid,'geometry_run_id':gid,'sha256':digest(directory/'fusion.json')}]}
    _write_json(server.project_path,server.project)
    print(f'Automation-only seeded fusion fixture: http://127.0.0.1:{server.server_port}/builder',flush=True)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
