"""Re-test a floor hypothesis after an analyst flags one source observation.

This is a reversible development diagnostic, not a ground-truth label or an
edit to an old fusion result. Exact duplicate tracks are removed together;
existing support and fitting criteria remain unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from products.worldstate_bim.multiview_fusion import _deduplicate_floor_tracks, _plane_fit


def digest(path: Path) -> str:
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--exclude-track-id',type=int,required=True);p.add_argument('--inspection',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose new output')
    if not a.inspection.strip():raise ValueError('inspection reason is required')
    fusion=json.loads(a.fusion.read_text())
    tracks=[t for t in fusion['tracks'] if t['status']=='SUPPORTED' and t['semantic_class']==3]
    distinct,duplicates=_deduplicate_floor_tracks(tracks)
    groups=[[g['retained_track_id'],*g['redundant_track_ids']] for g in duplicates]
    excluded=next((g for g in groups if a.exclude_track_id in g),[a.exclude_track_id])
    if not any(t['id']==a.exclude_track_id for t in tracks):raise ValueError('track is not supported floor')
    before,threshold_before=_plane_fit(distinct,8,31)
    revised,duplicates_after=_deduplicate_floor_tracks([t for t in tracks if t['id'] not in excluded])
    after,threshold_after=_plane_fit(revised,8,31)
    source=[{'track_id':t['id'],'observations':[{'photo':o['photo'],'photo_sha256':o['photo_sha256'],
             'pixel_xy':o['pixel_xy'],'semantic_class':o['semantic_class']} for o in t['observations'] if o.get('usable')]}
            for t in tracks if t['id'] in excluded]
    out={'schema':'worldstate-floor-review-diagnostic/0.1','status':'ANALYST_REVIEW_NOT_GROUND_TRUTH',
         'fusion_sha256':digest(a.fusion),'inspection':a.inspection,'excluded_duplicate_group':excluded,
         'deduplicated_before':len(distinct),'deduplicated_after':len(revised),'minimum_support_unchanged':8,
         'threshold_before':threshold_before,'threshold_after':threshold_after,'planes_before':before,'planes_after':after,
         'remaining_duplicate_groups':duplicates_after,'source_observations':source,
         'limitations':['Visual review is not independently labeled ground truth and is not human-efficiency measurement.',
             'This diagnostic does not alter masks, source fusion, candidates, or any IFC.',
             'Fit residual is not independent floor accuracy; additional errors may remain.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(out,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    print(json.dumps({'removed_ids':excluded,'unique_before':len(distinct),'unique_after':len(revised),
                      'planes_before':len(before),'planes_after':len(after)},indent=2))


if __name__=='__main__':main()
