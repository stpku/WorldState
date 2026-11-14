"""Inspect and exclude one visually identified floor-track misclassification.

This diagnostic never changes model masks or exports IFC. It records an analyst
inspection, reruns the unchanged sparse-floor fitter, and reports insufficient
evidence without lowering its minimum support or other fitting criteria.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
from products.worldstate_bim.multiview_fusion import _plane_fit


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True)
    p.add_argument('--exclude-track-id',type=int,required=True)
    p.add_argument('--inspection',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    if not a.inspection.strip():raise ValueError('inspection reason is required')
    f=json.loads(a.fusion.read_text())
    tracks=[t for t in f['tracks'] if t['status']=='SUPPORTED' and t['semantic_class']==3]
    matches=[t for t in tracks if t['id']==a.exclude_track_id]
    if len(matches)!=1:raise ValueError('track is not an unambiguous supported floor-class track')
    original,t0=_plane_fit(tracks,8,31)
    revised,t1=_plane_fit([t for t in tracks if t['id']!=a.exclude_track_id],8,31)
    obs=[o for o in matches[0]['observations'] if o['usable'] and o['semantic_class']==3]
    if len(obs)<2:raise ValueError('expected at least two source observations')
    a.output.mkdir(parents=True)
    crops=[]
    for i,o in enumerate(obs):
        name=o['photo'];source=a.images/name
        if Path(name).name!=name or source.is_symlink() or not source.is_file():raise ValueError('invalid source image')
        with source.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=o['photo_sha256']:raise ValueError('source image hash mismatch')
        x,y=o['pixel_xy'];ix,iy=round(x),round(y)
        with Image.open(source) as image:
            crop=image.convert('RGB').crop((ix-80,iy-80,ix+80,iy+80)).resize((640,640),Image.Resampling.LANCZOS)
        draw=ImageDraw.Draw(crop);px,py=(x-ix+80)*4,(y-iy+80)*4
        draw.ellipse((px-7,py-7,px+7,py+7),outline='red',width=3)
        filename=f'track-{a.exclude_track_id}-view-{i+1}.jpg';crop.save(a.output/filename,quality=92)
        crops.append({'photo':name,'sha256':actual,'pixel_xy':o['pixel_xy'],'crop':filename,
                      'model_score_uncalibrated':o['model_score_uncalibrated']})
    result={'schema':'worldstate-floor-track-probe/0.1','status':'DEVELOPMENT_VISUAL_INSPECTION_NOT_GROUND_TRUTH',
        'excluded_track_id':a.exclude_track_id,'inspection':a.inspection,
        'inspection_source':'analyst viewed original pixels; not automatic recognition or a human time study',
        'original_supported_floor_tracks':len(tracks),'after_exclusion_supported_floor_tracks':len(tracks)-1,
        'unchanged_minimum_floor_support_points':8,
        'original_fit_threshold_source_units':t0,'after_exclusion_fit_threshold_source_units':t1,
        'original_floor_hypotheses':original,'after_exclusion_floor_hypotheses':revised,'source_observations':crops,
        'limitations':['This is a targeted diagnostic, not an independent ground truth label.',
                       'Other tracks, candidate walls and source camera poses remain unverified.',
                       'No thresholds were relaxed and no IFC was generated from the modified diagnostic.']}
    (a.output/'probe.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({'before_floor_planes':len(original),'after_floor_planes':len(revised),
                      'source_observations':len(obs)},indent=2))


if __name__=='__main__':main()
