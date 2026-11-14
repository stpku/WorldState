"""Freeze ETH3D kicker development candidates before scan reference access."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifact',action='append',required=True,metavar='NAME=PATH')
    p.add_argument('--code',action='append',default=[],type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('freeze already exists')
    artifacts={}
    for item in a.artifact:
        name,sep,value=item.partition('=');path=Path(value)
        if not sep or not name or name in artifacts or path.is_symlink() or not path.is_file():raise ValueError('invalid artifact')
        if 'evaluation-private' in path.resolve().parts:raise ValueError('scan references cannot be modeling artifacts')
        artifacts[name]={'path':str(path.resolve()),'sha256':digest(path),'bytes':path.stat().st_size}
    required={'input_manifest','photo_sfm','photo_masks','photo_structure','photo_fusion','known29','known8',
              'known8_structure','pix8','floor_review','cuboid_floor'}
    if not required.issubset(artifacts):raise ValueError('missing candidate artifacts: '+str(sorted(required-set(artifacts))))
    code=[]
    for path in a.code:
        if path.is_symlink() or not path.is_file():raise ValueError('missing source file')
        code.append({'path':str(path.resolve()),'sha256':digest(path)})
    result={'schema':'worldstate-eth3d-model-freeze/0.1','created_utc':datetime.now(timezone.utc).isoformat(),
        'status':'KICKER_DEVELOPMENT_CANDIDATES_FROZEN_BEFORE_SCAN_EVALUATION','artifacts':artifacts,'code':code,
        'protocol':'Photo-only excludes official poses, scans, and held-out images; known-pose and PixCuboid use official poses.',
        'limitations':['Development, not WS-RealRoom acceptance or independently labeled wall evaluation.',
            'Human visual diagnostic is not independent ground truth or human-efficiency measurement.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print('frozen',len(artifacts),'artifacts and',len(code),'source files')


if __name__=='__main__':main()
