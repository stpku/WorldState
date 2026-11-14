"""Exercise real multiview correspondence and scale changes without claiming truth."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import numpy as np
from products.worldstate_bim.multiview_fusion import solve_multiview_scale,apply_multiview_scale


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--anchor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output file')
    fusion=json.loads(a.fusion.read_text());anchor=json.loads(a.anchor.read_text());baseline=solve_multiview_scale(fusion,anchor)
    changed=copy.deepcopy(anchor);changed['endpoints'][1]['observations'][0]['pixel_xy'][0]+=1
    try:apply_multiview_scale(fusion,changed,baseline)
    except ValueError as exc:stale=str(exc)
    else:raise RuntimeError('changed observation did not invalidate the previous scale')
    corrected=solve_multiview_scale(fusion,changed)
    delta=float(np.linalg.norm(np.asarray(corrected['endpoint_solutions'][1]['xyz'])-baseline['endpoint_solutions'][1]['xyz']))
    wrong=copy.deepcopy(anchor);wrong['endpoints'][1]['observations'][0]['pixel_xy'][1]+=100
    try:solve_multiview_scale(fusion,wrong)
    except ValueError as exc:wrong_status=str(exc)
    else:raise RuntimeError('test wrong correspondence was not rejected')
    resized=copy.deepcopy(anchor);resized['distance_m']*=1.2
    try:apply_multiview_scale(fusion,resized,baseline)
    except ValueError as exc:stale_length=str(exc)
    else:raise RuntimeError('changed reference length did not invalidate previous scale')
    new=solve_multiview_scale(fusion,resized)
    result={'operator':'automation','source':'real registered photo observations; one-pixel perturbation is artificial',
      'baseline_basis':anchor['basis'],'baseline_endpoint_xyz':baseline['endpoint_solutions'][1]['xyz'],
      'perturbed_endpoint_xyz':corrected['endpoint_solutions'][1]['xyz'],'endpoint_delta_arbitrary':delta,
      'perturbed_max_reprojection_px':corrected['endpoint_solutions'][1]['max_reprojection_error_px'],
      'stale_observation_rejected':stale,'wrong_correspondence_rejected':wrong_status,
      'stale_measurement_rejected':stale_length,'measurement_counterfactual_ratio':1.2,
      'resulting_scale_ratio':new['metres_per_sfm_unit']/baseline['metres_per_sfm_unit'],
      'independent_accuracy':'NOT_MEASURED'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
