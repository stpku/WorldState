"""Compare line-fragment choices on an already associated development scene.

Association, cameras and the shared floor use all views; leave-one-view-out is
a sensitivity diagnostic, not an independent room or metric accuracy test.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from products.worldstate_bim.structure_from_lines import _floor_basis, _free_line, _free_line_error, _image_line, _line_error


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fusion',type=Path,required=True);parser.add_argument('--structure',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a new output file')
    fusion=json.loads(args.fusion.read_text());structure=json.loads(args.structure.read_text())
    if (fusion.get('source_reconstruction')!=structure.get('source_reconstruction') or
            fusion.get('semantic_manifest_sha256')!=structure.get('semantic_manifest_sha256')):
        raise ValueError('structure and source evidence differ')
    cameras={c['image_id']:c for c in fusion['cameras']};basis=_floor_basis(fusion);results=[]
    for group in structure['groups']:
        if group['support_view_count']<3:continue
        choices={}
        for mode in ('closest_existing','longest_visible'):
            if mode=='closest_existing':selected={line['image_id']:line for line in group['selected_observations']}
            else:
                selected={}
                for line in group['inlier_observations']:
                    prior=selected.get(line['image_id'])
                    if prior is None or math.dist(*line['points_px'])>math.dist(*prior['points_px']):selected[line['image_id']]=line
            if len(selected)!=group['support_view_count']:
                raise ValueError('line group has inconsistent view support')
            def objective(x, lines):
                residual=[]
                for line in lines.values():
                    projection=_image_line(x[0],x[1],cameras[line['image_id']],basis)
                    if projection is None:return np.full(2*len(lines),1e3)
                    residual.extend(float(projection@np.array([*p,1.])) for p in line['points_px'])
                return residual
            initial=[group['theta_rad'],group['offset_relative']]
            fitted=least_squares(objective,initial,args=(selected,),loss='soft_l1',f_scale=6,max_nfev=100)
            support={v:(0.,line) for v,line in selected.items()}
            floor_errors=[];free_errors=[];failures=[]
            for view,line in selected.items():
                train={k:v for k,v in selected.items() if k!=view}
                try:
                    fit=least_squares(objective,fitted.x,args=(train,),loss='soft_l1',f_scale=6,max_nfev=100)
                    floor_error=_line_error(float(fit.x[0]),float(fit.x[1]),line,cameras,basis)
                    direct=_free_line({k:v for k,v in support.items() if k!=view},cameras)
                    free_error=_free_line_error(direct,line,cameras)
                    if not math.isfinite(floor_error) or not math.isfinite(free_error):raise ValueError('degenerate projection')
                    floor_errors.append({'image_id':view,'error_px':floor_error,'pixel_tolerance':line['pixel_tolerance']})
                    free_errors.append({'image_id':view,'error_px':free_error,'pixel_tolerance':line['pixel_tolerance']})
                except ValueError as exc:
                    failures.append({'image_id':view,'reason':str(exc)})
            choices[mode]={'line_ids':[selected[v]['id'] for v in sorted(selected)],
                'floor_joint_leave_one_view_out':floor_errors,'free_line_leave_one_view_out':free_errors,
                'floor_max_px':max((x['error_px'] for x in floor_errors),default=None),
                'free_max_px':max((x['error_px'] for x in free_errors),default=None),
                'floor_within_pixel_tolerance':len(floor_errors)==len(selected) and all(x['error_px']<=x['pixel_tolerance'] for x in floor_errors),
                'free_within_pixel_tolerance':len(free_errors)==len(selected) and all(x['error_px']<=x['pixel_tolerance'] for x in free_errors),
                'failures':failures}
        results.append({'group_id':group['id'],'views':group['support_view_count'],'choices':choices})
    result={'schema':'worldstate-line-selection-probe/0.1','source_reconstruction':fusion['source_reconstruction'],
            'semantic_manifest_sha256':fusion['semantic_manifest_sha256'],'groups':results,
            'note':'Development comparison only: candidate associations, camera poses and floor include all views. No independent measurement or human time.',
            'decision':'Do not treat lower image residual alone as evidence of an accurate or complete wall.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    for group in results:
        print(group['group_id'],group['views'],{k:{'floor_max_px':round(v['floor_max_px'],2) if v['floor_max_px'] is not None else None,
            'free_max_px':round(v['free_max_px'],2) if v['free_max_px'] is not None else None} for k,v in group['choices'].items()})


if __name__=='__main__':main()
