"""Recreate registered image filenames from an authorized photo set by SHA-256."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    sources={}
    for path in a.images.iterdir():
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as f:sources[hashlib.file_digest(f,'sha256').hexdigest()]=path
    fusion=json.loads(a.fusion.read_text());a.output.mkdir(parents=True)
    for camera in fusion['cameras']:
        name=camera['photo'];digest=camera['sha256']
        if Path(name).name!=name or digest not in sources:raise ValueError('registered source photo missing or invalid')
        shutil.copyfile(sources[digest],a.output/name)
    print(f"materialized {len(fusion['cameras'])} verified registered images")

if __name__=='__main__':main()
