"""Freeze modeling artifacts before a separate ETH3D scan evaluator runs."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact',action='append',required=True,metavar='NAME=PATH')
    p.add_argument('--code',action='append',default=[],type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('freeze already exists')
    artifacts={}
    for value in a.artifact:
        name,sep,text=value.partition('=');path=Path(text)
        if not sep or not name or name in artifacts or path.is_symlink() or not path.is_file():raise ValueError('invalid artifact')
        if 'evaluation-private' in path.resolve().parts:raise ValueError('reference scan cannot be a modeling artifact')
        artifacts[name]={'path':str(path.resolve()),'sha256':digest(path),'bytes':path.stat().st_size}
    if not {'input_manifest','photo_sfm','photo_structure','known24_structure','known5_structure','known8_structure','pix5','pix8'}<=set(artifacts):
        raise ValueError('required modeling artifacts missing')
    code=[]
    for path in a.code:
        if path.is_symlink() or not path.is_file():raise ValueError('missing source file')
        code.append({'path':str(path.resolve()),'sha256':digest(path)})
    result={'schema':'worldstate-eth3d-model-freeze/0.1','created_utc':datetime.now(timezone.utc).isoformat(),
        'status':'DEVELOPMENT_CANDIDATES_FROZEN_BEFORE_SCAN_EVALUATION','artifacts':artifacts,'code':code,
        'protocol':'Photo-only input excludes reference poses, scans and holdout images. Known-pose and PixCuboid use declared official poses.',
        'limits':['This is not WS-RealRoom formal acceptance or independent human evaluation.',
                  'No model quality, metric scale or human-cost success is implied by freezing.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print('frozen',len(artifacts),'modeling artifacts and',len(code),'source files')


if __name__=='__main__':main()
