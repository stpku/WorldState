"""Run real multiview semantic inference and geometry; no evaluation labels are read."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
from products.worldstate_bim.multiview_fusion import infer_masks, fuse_multiview, associate_surface_identities


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    i=sub.add_parser('infer');i.add_argument('--sparse',type=Path,required=True);i.add_argument('--images',type=Path,required=True)
    i.add_argument('--model',type=Path,required=True);i.add_argument('--output',type=Path,required=True)
    f=sub.add_parser('fuse');f.add_argument('--sparse',type=Path,required=True);f.add_argument('--images',type=Path,required=True)
    f.add_argument('--masks',type=Path,required=True);f.add_argument('--output',type=Path,required=True)
    m=sub.add_parser('associate');m.add_argument('--previous',type=Path,required=True);m.add_argument('--current',type=Path,required=True);m.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.cmd=='infer':infer_masks(a.sparse,a.images,a.model,a.output)
    if a.cmd=='fuse':
        if a.output.exists():raise FileExistsError('choose new output')
        result=fuse_multiview(a.sparse,a.images,a.masks);a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'tracks':len(result['tracks']),'wall_hypotheses':len(result['wall_surfaces']),
                          'floor_planes':len(result['floor_planes']),'junctions':len(result['wall_junctions'])}))
    if a.cmd=='associate':
        if a.output.exists():raise FileExistsError('choose new output')
        result=associate_surface_identities(json.loads(a.previous.read_text()),json.loads(a.current.read_text()))
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'matched':len(result['matches']),'unmatched_previous':len(result['unmatched_previous'])}))

if __name__=='__main__':main()
