"""Freeze a development-only ETH3D local-wall experiment before evaluation.

The inputs are known-pose photos and AI-selected image observations. This does
not open the laser scans or the held-out image observations. The output IFC is
a single assumed-scale, assumed-thickness patch, not a measured room.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate
import numpy as np

from products.worldstate_bim.model_first import _basis, build_local_wall_ir, solve_local_wall
from products.worldstate_bim.room_ifc import export_room


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path: Path, obj: dict) -> None:
    with path.open('x') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def checked(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing or symlinked input: ' + str(path))
    return {'path': str(path.resolve()), 'sha256': sha(path)}


def validate_ifc(path: Path) -> dict:
    f = ifcopenshell.open(str(path))
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    walls = f.by_type('IfcWall')
    shapes = [ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), wall) for wall in walls]
    if f.schema != 'IFC4' or len(walls) != 1 or log.statements or not all(shapes):
        raise ValueError('IFC schema or geometry validation failed')
    return {'schema': f.schema, 'walls': len(walls), 'guid': walls[0].GlobalId,
            'schema_issues': len(log.statements), 'geometry_generated': len(shapes)}


def solution_at_prior(solution: dict) -> dict:
    """Reuse the same object identity for the unverified PixCuboid seed."""
    p = np.asarray(solution['initial_parameters'], dtype=float)
    x, z, width, _ = _basis(p[:3], p[3:6], p[6:9])
    return {**solution, 'frame': {'origin_source': p[:3].tolist(), 'x_axis_source': x.tolist(),
            'y_axis_source': np.cross(z, x).tolist(), 'z_axis_source': z.tolist()},
            'width_source_units': width, 'height_source_units': float(p[9])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--pixcuboid', type=Path, help='Optional prior in the same camera reconstruction frame')
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--reconstruction', type=Path, required=True)
    parser.add_argument('--assume-metres-per-source-unit', type=float, required=True)
    parser.add_argument('--assume-thickness-m', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    if a.output.exists():
        raise FileExistsError('choose a new output directory')
    inputs = [checked(a.training)] + ([checked(a.pixcuboid)] if a.pixcuboid else [])
    training = json.loads(a.training.read_text())
    pix = json.loads(a.pixcuboid.read_text()) if a.pixcuboid else None
    recon = [{'file': p.name, 'sha256': sha(p)} for p in sorted(a.reconstruction.glob('*.bin'))]
    if not recon or recon != training['source_reconstruction'] or (pix is not None and recon != pix['source_reconstruction']):
        raise ValueError('registered-camera reconstruction does not match observations and PixCuboid')
    for camera in training['cameras']:
        if Path(camera['photo']).name != camera['photo']:
            raise ValueError('invalid photo path')
        item = checked(a.images / camera['photo'])
        if item['sha256'] != camera['sha256']:
            raise ValueError('source photo changed')
        inputs.append(item)
    start = time.monotonic()
    solution = solve_local_wall(training, pix)
    elapsed = time.monotonic() - start
    settings = {'project_id': 'eth3d-kicker-r9-lintel', 'assumed_scale': a.assume_metres_per_source_unit,
                'assumed_thickness_m': a.assume_thickness_m, 'allow_assumed': True}
    prior = build_local_wall_ir(training, solution_at_prior(solution), **settings)
    prior['validation']['warning'] += (' Initial PixCuboid face is an unverified prior, not a result.' if pix is not None
                                       else ' Initial model uses directly triangulated corners and image lines.')
    model = build_local_wall_ir(training, solution, **settings)
    model['revision'] = 2
    model['history'] = [{'previous_revision': 1, 'revision': 2, 'element_id': 'wall-above-opening',
        'operator': 'automation', 'reason': ('Optimize a provisional PixCuboid face' if pix is not None else 'Optimize a directly triangulated patch')+' against image observations',
        'source': 'multiview corner and ceiling-line reprojections', 'status': 'UNVERIFIED'}]
    a.output.mkdir(parents=True)
    write(a.output / 'initial-model.json', prior)
    write(a.output / 'optimized-model.json', model)
    write(a.output / 'solution.json', solution)
    export_room(prior, a.output / 'initial.ifc')
    export_room(model, a.output / 'optimized.ifc')
    before_ifc = validate_ifc(a.output / 'initial.ifc')
    after_ifc = validate_ifc(a.output / 'optimized.ifc')
    if before_ifc['guid'] != after_ifc['guid']:
        raise ValueError('wall identity changed during optimization')
    artifacts = {p.name: checked(p) for p in sorted(a.output.iterdir())}
    code_paths = [Path(__file__), Path('products/worldstate_bim/model_first.py'),
                  Path('products/worldstate_bim/multiview_fusion.py'),
                  Path('products/worldstate_bim/room_ifc.py'), Path('products/worldstate_bim/room_ir.py'),
                  Path('benchmarks/ws_geometry/extract_kicker_lintel.py')]
    freeze = {'schema': 'worldstate-local-wall-freeze/0.1', 'input': inputs,
              'source_reconstruction': recon, 'artifacts': artifacts, 'code': [checked(p) for p in code_paths],
              'mode': training['camera_mode'], 'elapsed_solver_seconds': elapsed,
              'ifc_prior': before_ifc, 'ifc_optimized': after_ifc,
              'scale': 'ASSUMED_NOT_MEASURED', 'scope': 'ONE_PARTIAL_PATCH_NOT_A_COMPLETE_WALL_OR_ROOM',
              'operator': training['operator'], 'human_time': 'NOT_MEASURED',
              'holdout_and_scan_read_during_modeling': False}
    write(a.output / 'freeze.json', freeze)
    print(json.dumps({'freeze': str(a.output / 'freeze.json'), 'guid': after_ifc['guid'],
        'before_rms_px': solution['before']['rms_px'], 'after_rms_px': solution['after']['rms_px'],
        'maximum_after_px': solution['after']['maximum_px'], 'solver_seconds': elapsed,
        'release_status': 'NOT_RELEASE_READY'}, indent=2))


if __name__ == '__main__':
    main()
