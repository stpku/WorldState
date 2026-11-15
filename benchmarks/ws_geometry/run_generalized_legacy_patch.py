"""Re-run a legacy real-photo edge/line observation through the general modeler.

The input retains its original automation provenance. Inferred corners and
explicit scale/thickness assumptions remain unverified; this is not a new
independent wall or a complete-room benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from products.worldstate_bim.general_modeler import SCHEMA_INPUT, build_room_ir, camera_digest, solve_modeler
from products.worldstate_bim.room_ifc import export_room


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path: Path,value: dict) -> None:
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--legacy-input',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--up',type=float,nargs=3,required=True);p.add_argument('--assume-metres-per-source-unit',type=float,required=True)
    p.add_argument('--assume-thickness-m',type=float,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    source=json.loads(a.legacy_input.read_text())
    if source.get('schema')!='worldstate-local-wall-observations/0.1' or source.get('operator')!='automation_ai_visual_selection':
        raise ValueError('this adapter only accepts explicitly automated legacy observations')
    cameras={c['image_id']:c for c in source['cameras']}
    for cam in cameras.values():
        path=a.images/cam['photo']
        if Path(cam['photo']).name!=cam['photo'] or path.is_symlink() or sha(path)!=cam['sha256']:raise ValueError('source photo hash mismatch')
    now=datetime.now(timezone.utc).isoformat();observations=[]
    for old,new in (('left_top','p1'),('right_top','p2'),('right_bottom','p5')):
        for item in source['corners'][old]:
            observations.append({**item,'kind':'point','object_id':'wall-patch','feature_id':new,
                'camera_sha256':camera_digest(cameras[item['image_id']]),'origin':'automation',
                'confirmation':'automation_unverified','visibility':'visible','sigma_px':2.,'created_at':now,
                'source_observation_time':'NOT_RECORDED_IN_LEGACY','legacy_origin':item.get('origin')})
    for item in source['ceiling_lines']:
        observations.append({**item,'kind':'line','object_id':'wall-patch','feature_ids':['p3','p4'],
            'camera_sha256':camera_digest(cameras[item['image_id']]),'origin':'automation',
            'confirmation':'automation_unverified','visibility':'visible','sigma_px':2.,'created_at':now,
            'source_observation_time':'NOT_RECORDED_IN_LEGACY','legacy_origin':item.get('origin')})
    data={'schema':SCHEMA_INPUT,'camera_mode':source['camera_mode'],
        'coordinate_system':{'name':'registered source','scale_status':'UNKNOWN'},
        'source_reconstruction':source['source_reconstruction'],'cameras':list(cameras.values()),
        'objects':[{'id':'wall-patch','ifc_type':'IfcWall','vertices':['p1','p2','p3','p4'],
            'surface_kind':'visible_surface_patch','construction':{'kind':'edge_to_line','direction_feature':'p5'},
            'semantic_warning':'door leaf and wall coplanarity is an unverified assumption'}],
        'observations':observations,'object_constraints':[]}
    sensitivity={'samples':24,'camera_position_sigma_source':.002,'camera_rotation_sigma_deg':.05,'focal_sigma_fraction':.001}
    solution=solve_modeler(data,sensitivity=sensitivity)
    model=build_room_ir(data,solution,project_id='generalized-legacy-patch',
        scale={'basis':'assumed','metres_per_source_unit':a.assume_metres_per_source_unit},
        thickness_m=a.assume_thickness_m,up_source=a.up,allow_rectangular_approximation=True)
    a.output.mkdir(parents=True);save(a.output/'input.json',data);save(a.output/'solution.json',solution);save(a.output/'model.json',model)
    export_room(model,a.output/'model.ifc');f=ifcopenshell.open(str(a.output/'model.ifc'));walls=f.by_type('IfcWall')
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger)
    if f.schema!='IFC4' or len(walls)!=1 or logger.statements or not ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),walls[0]):
        raise ValueError('IFC parsing or geometry failed')
    report={'schema':'worldstate-general-modeler-legacy-probe/0.1','status':'UNVERIFIED_PARTIAL_PATCH',
        'source_legacy_input_sha256':sha(a.legacy_input),'ifc_sha256':sha(a.output/'model.ifc'),
        'ifc_guid':walls[0].GlobalId,'ifc_schema':f.schema,'ifc_schema_errors':len(logger.statements),
        'point_and_line_rms_px':solution['optimization']['point_rms_px'],
        'sensitivity':solution['sensitivity'],'release_status':'NOT_RELEASE_READY',
        'limitations':['Reuses the same Round 9 door-top evidence; not a new wall, room or blind evaluation.',
            'Two rectangle endpoints are inferred from a line; the source feature may be offset from the wall.',
            'Scale, thickness and up direction are assumptions; no human annotations or labor costs were recorded.']}
    save(a.output/'report.json',report)
    print(json.dumps({'status':report['status'],'ifc_guid':report['ifc_guid'],
                      'point_and_line_rms_px':report['point_and_line_rms_px'],'output':str(a.output)},indent=2))


if __name__=='__main__':main()
