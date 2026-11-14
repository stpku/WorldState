"""Compare two experimental IFC candidates on identical real SfM and masks.

This is a development diagnostic, not a real-room acceptance or a measurement
of physical dimensions. The required anchor may explicitly be an assumption.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate
import numpy as np

from products.worldstate_bim.multiview_fusion import build_multiview_room, fuse_multiview, solve_multiview_scale
from products.worldstate_bim.room_ifc import export_room
from products.worldstate_bim.room_ir import quantity, validate_room
from products.worldstate_bim.structure_from_lines import build_structure_room, extract_lines, solve_lines


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def check_ifc(path: Path) -> dict:
    file=ifcopenshell.open(str(path));walls=file.by_type('IfcWall')
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(file,logger)
    geometries=[ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),w) for w in walls]
    return {'schema':file.schema,'walls':len(walls),'geometry_generated':sum(bool(x) for x in geometries),
            'schema_issues':len(logger.statements),'guids':[w.GlobalId for w in walls]}


def candidate_extents(model: dict) -> list[dict]:
    nodes={n['id']:n for n in model['nodes']};output=[]
    for wall in model['elements']:
        if wall['ifc_type']!='IfcWall':continue
        a,b=nodes[wall['start']],nodes[wall['end']]
        output.append({'id':wall['id'],'visible_support_extent_assumed_m':math.hypot(b['x']-a['x'],b['y']-a['y']),
                       'height_assumed_m':wall['parameters']['height']['value'],
                       'warning':'Different support extents, not verified physical wall dimensions.'})
    return output


def draw_overlays(result: dict, fusion: dict, images: Path, output: Path) -> list[str]:
    """Visualize proposed real pixels; labels are hypotheses, not annotations."""
    output.mkdir();cameras={c['image_id']:c for c in fusion['cameras']}
    selected=[]
    for corner in result['corner_candidates']:
        for obs in corner['source_observations']:
            if obs['image_id'] not in selected:selected.append(obs['image_id'])
    colors=[(20,170,250),(50,210,80),(255,130,40),(220,70,200)]
    files=[]
    for image_id in selected:
        camera=cameras[image_id];image=cv2.imread(str(images/camera['photo']))
        if image is None:raise ValueError('source image missing for overlay')
        for index,group in enumerate(result['groups']):
            for line in group['inlier_observations']:
                if line['image_id']!=image_id:continue
                a,b=(tuple(map(int,p)) for p in line['points_px']);cv2.line(image,a,b,colors[index%len(colors)],3)
            eligible=(group['floor_joint_holdout_status']=='CONSISTENT_UNVERIFIED' and
                      group['floor_consistency']=='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY')
            cv2.putText(image,f"{index+1}: {group['support_view_count']} views - {'UNVERIFIED' if eligible else 'CONFLICT'}",
                        (10,30+27*index),cv2.FONT_HERSHEY_SIMPLEX,.55,colors[index%len(colors)],2)
        for corner in result['corner_candidates']:
            for obs in corner['source_observations']:
                if obs['image_id']!=image_id:continue
                point=tuple(round(x) for x in obs['pixel_xy']);color=(0,0,255) if corner['floor_consistency'].startswith('CONFLICT') else (30,255,255)
                cv2.circle(image,point,12,color,3)
        name=Path(camera['photo']).stem+'-structure.jpg'
        if not cv2.imwrite(str(output/name),image,[cv2.IMWRITE_JPEG_QUALITY,88]):raise OSError('cannot write overlay')
        files.append(name)
    return files


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sparse',type=Path,required=True);parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--masks',type=Path,required=True);parser.add_argument('--anchor',type=Path,required=True)
    parser.add_argument('--assumed-height-m',type=float,required=True);parser.add_argument('--assumed-thickness-m',type=float,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a new output directory')
    anchor=json.loads(args.anchor.read_text())
    if anchor.get('basis')!='assumed':raise ValueError('this development comparison accepts only an explicitly assumed anchor')
    start=time.monotonic();fusion=fuse_multiview(args.sparse,args.images,args.masks);route_a_seconds=time.monotonic()-start
    start=time.monotonic();detections=extract_lines(fusion,args.sparse,args.images,args.masks)
    structure=solve_lines(fusion,detections);route_b_seconds=time.monotonic()-start
    if not fusion['floor_planes']:raise ValueError('shared floor unavailable')
    solution=solve_multiview_scale(fusion,anchor)
    surfaces=sorted(fusion['wall_surfaces'],key=lambda s:-s['support_count']);baseline=[]
    for surface in surfaces:
        if surface.get('visible_candidate') and (not baseline or all(abs(float(np.dot(surface['normal'],x['normal'])))<math.cos(math.radians(35)) for x in baseline)):
            baseline.append(surface)
        if len(baseline)==2:break
    accepted=[g for g in structure['groups'] if g['floor_consistency']=='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'
              and g['floor_joint_holdout_status']=='CONSISTENT_UNVERIFIED' and g['visible_support_intervals']]
    if not baseline or not accepted:raise ValueError('no sufficiently supported draft candidates')
    ids_a=[x['id'] for x in baseline];ids_b=[x['id'] for x in accepted]
    model_a=build_multiview_room(fusion,anchor,solution,ids_a,project_id='eyeful-r7-route-a',
        assumed_thickness_m=args.assumed_thickness_m,confirmed_candidates=True,allow_assumed_scale=True,operator_kind='automation')
    model_a['evidence'].append({'id':'shared-assumed-height','kind':'height_input','basis':'assumed',
                                'value_m':args.assumed_height_m,'status':'assumed','description':'Same explicit development assumption for both routes; not measured'})
    for item in model_a['elements']:
        if item['ifc_type']=='IfcWall':
            item['parameters']['height']=quantity(args.assumed_height_m,'assumed',['shared-assumed-height'],
                                                    'Shared development-only height assumption, not a measurement')
    validate_room(model_a)
    model_b=build_structure_room(fusion,structure,anchor,solution,ids_b,project_id='eyeful-r7-route-b',
        height_m=args.assumed_height_m,height_basis='assumed',height_description='Same explicit development assumption for both routes; not measured',
        thickness_m=args.assumed_thickness_m,confirmed_candidates=True,allow_assumed_scale=True,operator_kind='automation')
    args.output.mkdir(parents=True)
    write(args.output/'fusion-common.json',fusion);write(args.output/'detected-lines.json',detections);write(args.output/'structure.json',structure)
    for name,model in [('route-a',model_a),('route-b',model_b)]:
        write(args.output/(name+'.json'),model);export_room(model,args.output/(name+'.ifc'))
    overlays=draw_overlays(structure,fusion,args.images,args.output/'overlays')
    summary={'schema':'worldstate-structure-comparison/0.1','input':{'registered_photos':len(fusion['cameras']),
        'tracks':len(fusion['tracks']),'source_reconstruction':fusion['source_reconstruction'],
        'semantic_manifest_sha256':fusion['semantic_manifest_sha256'],
        'scale':'ASSUMED_CORRELATED_NOT_INDEPENDENTLY_MEASURED','height':'ASSUMED_NOT_MEASURED',
        'height_m':args.assumed_height_m,'thickness_m':args.assumed_thickness_m},
      'route_a':{'method':'COLMAP + semantic 3D tracks + sparse planes','runtime_seconds':round(route_a_seconds,3),
        'selected_surfaces':[{'id':g['id'],'support_points':g['support_count'],'support_views':g['support_view_count']} for g in baseline],
        'candidate_extents':candidate_extents(model_a),
        'ifc':check_ifc(args.output/'route-a.ifc')},
      'route_b':{'method':'COLMAP cameras + UPerNet boundary lines + multiview plane intersections, with shared sparse floor prior',
        'runtime_seconds':round(route_b_seconds,3),'image_line_proposals':len(detections['lines']),
        'groups':[{'id':g['id'],'support_views':g['support_view_count'],'floor_consistency':g['floor_consistency'],
            'floor_joint_holdout_status':g['floor_joint_holdout_status'],
            'floor_joint_holdout_max_px':max((x['error_px'] for x in g['floor_joint_leave_one_view_out_px']),default=None),
            'free_line_holdout_max_px':max((x['error_px'] for x in g['free_line_leave_one_view_out_px']),default=None),
            'selected_for_ifc':g['id'] in ids_b} for g in structure['groups']],
        'corner_candidates':[{'line_ids':c['line_ids'],'views':len(c['source_observations']),
            'reprojection_max_px':c['max_reprojection_error_px'],'parallax_deg':c['max_parallax_degrees'],
            'floor_residual_relative':c['floor_plane_residual_relative'],'floor_consistency':c['floor_consistency']}
            for c in structure['corner_candidates']],
        'candidate_extents':candidate_extents(model_b),'ifc':check_ifc(args.output/'route-b.ifc')},
      'overlays':overlays,'independent_wall_precision_recall':'NOT_MEASURED',
      'independent_dimension_error':'NOT_MEASURED','human_time_and_cost':'NOT_MEASURED',
      'release_status':'NOT_RELEASE_READY',
      'caveats':['Both methods share the same cached registered photos, cameras, semantic masks and assumed scale.',
        'Route B also uses route A semantic floor as an association and consistency prior; it is a hybrid, not independent.',
        'One-view-out excludes a view only during line fitting; line association, camera poses and floor used all views.',
        'Pixel reprojection residuals, candidate counts and fitted plane residuals are not independent wall accuracy.',
        'No physical ruler, human annotation time or independent reference model is available in this development run.']}
    write(args.output/'comparison.json',summary);print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
