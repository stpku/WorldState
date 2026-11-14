"""Download the pinned public MIT Eyeful Tower development photos by hash."""
import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',required=True,type=Path)
p.add_argument('--sfm-only',action='store_true',help='exclude the vision-only photo')
p.add_argument('--manifest',type=Path,default=Path(__file__).with_name('eyeful-emptyroom-manifest.json'))
a=p.parse_args();manifest=json.loads(a.manifest.read_text())
a.output.mkdir(parents=True,exist_ok=True)
for item in manifest['input_photos']:
    if a.sfm_only and item['usage']=='vision_only':continue
    name=item['filename'];url=item['url']
    if Path(name).name!=name or not url.startswith('https://fb-baas-f32eacb9-8abb-11eb-b2b8-4857dd089e15.s3.amazonaws.com/EyefulTower/'):
        raise ValueError('invalid manifest entry')
    target=a.output/name
    if target.is_symlink():raise ValueError('destination cannot be a symlink')
    if target.exists():
        with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=item['sha256']:raise ValueError(f'existing file hash mismatch: {name}')
        print('verified',name,flush=True);continue
    fd,tmp=tempfile.mkstemp(dir=a.output,prefix='.download-')
    try:
        with os.fdopen(fd,'wb') as out, urllib.request.urlopen(url,timeout=120) as source:
            digest=hashlib.sha256();size=0
            while chunk:=source.read(1024*1024):
                size+=len(chunk)
                if size>item['bytes']:raise ValueError('download larger than manifest')
                digest.update(chunk);out.write(chunk)
        if digest.hexdigest()!=item['sha256'] or size!=item['bytes']:raise ValueError('download hash/size mismatch')
        os.replace(tmp,target);print('downloaded',name,flush=True)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
