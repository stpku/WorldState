"""CPU COLMAP experiment for photographs declared to come from one camera.

No ground-truth poses or evaluation dimensions are read. Results have unknown
scale; this is not a room model. Run in a new empty output directory.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from products.worldstate_bim.colmap_provider import reconstruct_uncalibrated_images


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--threads',type=int,default=4);args=p.parse_args()
    names=sorted(x.name for x in args.images.iterdir() if x.suffix.lower() in {'.jpg','.jpeg','.png'})
    result=reconstruct_uncalibrated_images(args.images,names,args.output,threads=args.threads)
    (args.output/'geometry-candidate.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'registered':len(result['registered_cameras']),
                      'points':result['sparse_points'],'reprojection_px':result.get('mean_reprojection_error_px'),
                      'timing':result['timing_seconds']}),flush=True)

if __name__=='__main__':main()
