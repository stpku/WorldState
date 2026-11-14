"""Compare frozen office development candidates with sampled ETH3D scans.

Not the ETH3D official evaluator or WS-RealRoom acceptance. Modeling artifacts
are verified before the evaluator opens the scanner point data. The scan is
never an input to the candidate generator. Official camera poses are used only
here for a similarity alignment of photo-only SfM; metric scale is therefore not
an independent measurement. Known-pose cameras are scanner-registered.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import pycolmap
from scipy.spatial import cKDTree
from benchmarks.ws_geometry.compare_eyeful_poses import fit
from benchmarks.ws_geometry.run_eth3d_known_pose import read_poses, rigid_pose


def sha(path: Path) -> str:
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_freeze(path: Path) -> dict:
    freeze = json.loads(path.read_text())
    if freeze.get('schema') != 'worldstate-eth3d-model-freeze/0.1': raise ValueError('unexpected freeze schema')
    for item in list(freeze['artifacts'].values()) + freeze['code']:
        f = Path(item['path'])
        if f.is_symlink() or not f.is_file() or sha(f) != item['sha256']:
            raise ValueError('frozen artifact or code changed: ' + str(f))
    return freeze


def read_sample(path: Path, stride: int) -> tuple[np.ndarray, int]:
    with path.open('rb') as stream:
        header = []
        while True:
            line = stream.readline()
            if not line or sum(map(len, header)) > 8192: raise ValueError('invalid PLY header')
            header.append(line.decode('ascii').strip())
            if line.strip() == b'end_header': break
        offset = stream.tell()
    expected = ['property float x', 'property float y', 'property float z',
                'property uchar red', 'property uchar green', 'property uchar blue']
    if header[0:2] != ['ply', 'format binary_little_endian 1.0'] or not (1 <= stride <= 10000):
        raise ValueError('unsupported PLY format or stride')
    v = next(i for i, line in enumerate(header) if line.startswith('element vertex '))
    if header[v+1:v+7] != expected: raise ValueError('unsupported vertex layout')
    count = int(header[v].split()[-1])
    dtype = np.dtype([('x','<f4'), ('y','<f4'), ('z','<f4'), ('r','u1'), ('g','u1'), ('b','u1')])
    vertices = np.memmap(path, dtype=dtype, mode='r', offset=offset, shape=(count,))[::stride]
    xyz = np.column_stack([vertices['x'], vertices['y'], vertices['z']]).astype(np.float64)
    return xyz[np.isfinite(xyz).all(axis=1)], count


def stats(values: np.ndarray) -> dict:
    if not len(values): return {'count': 0}
    return {'count': int(len(values)), 'mean': float(np.mean(values)), 'median': float(np.median(values)),
            'p90': float(np.percentile(values, 90)), 'fraction_below_0_05': float(np.mean(values < .05)),
            'fraction_below_0_10': float(np.mean(values < .10))}


def box_surface(candidate: dict, n: int = 40) -> np.ndarray:
    box = candidate['output']; r = np.asarray(box['R_world_to_cuboid']); d = np.asarray(box['plane_offsets'])
    if r.shape != (3, 3) or d.shape != (6,) or not np.all(d[3:] > d[:3]): raise ValueError('invalid box')
    faces = []
    for f in range(6):
        axis = f % 3; other = [i for i in range(3) if i != axis]
        a, b = np.meshgrid(np.linspace(d[other[0]],d[other[0]+3],n), np.linspace(d[other[1]],d[other[1]+3],n))
        points = np.zeros((n*n,3)); points[:,axis] = d[f]; points[:,other[0]] = a.ravel(); points[:,other[1]] = b.ravel()
        faces.append(points @ r)
    return np.vstack(faces)


def distance_to_box(points: np.ndarray, candidate: dict) -> np.ndarray:
    box = candidate['output']; r = np.asarray(box['R_world_to_cuboid']); d = np.asarray(box['plane_offsets'])
    local = points @ r.T; result = np.full(len(points), np.inf)
    for face in range(6):
        axis = face % 3; sq = (local[:,axis] - d[face]) ** 2
        for j in range(3):
            if j == axis: continue
            sq += np.maximum(d[j] - local[:,j], 0) ** 2 + np.maximum(local[:,j] - d[j+3], 0) ** 2
        np.minimum(result, sq, out=result)
    return np.sqrt(result)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', type=Path, required=True); p.add_argument('--source-poses', type=Path, required=True)
    p.add_argument('--scan-dir', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stride', type=int, default=50); a = p.parse_args()
    if a.output.exists(): raise FileExistsError('evaluation output already exists')
    if not 1 <= a.stride <= 10000: raise ValueError('invalid stride')
    # Verify all model and model-code hashes before opening reference scans.
    freeze = verify_freeze(a.freeze); artifacts = freeze['artifacts']
    read = lambda name: json.loads(Path(artifacts[name]['path']).read_text())
    geometry = read('photo_sfm'); diag = read('photo_structure'); known = read('known24_summary')
    boxes = {name:read(name) for name in ('pix5', 'pix8')}
    if sha(a.source_poses) != known['source_pose_sha256']: raise ValueError('reference camera file changed')
    sparse = Path(artifacts['photo_sfm']['path']).parent / 'sparse' / '0'
    for item in diag['input']['source_reconstruction']:
        if Path(item['file']).name != item['file'] or sha(sparse / item['file']) != item['sha256']:
            raise ValueError('frozen photo reconstruction changed')
    reconstruction = pycolmap.Reconstruction(sparse)
    reference = read_poses(a.source_poses)
    cams = [c for c in geometry['registered_cameras'] if c['name'] in reference]
    if len(cams) < 4: raise ValueError('not enough common cameras for similarity alignment')
    x = np.array([c['center'] for c in cams]); y = np.array([-rigid_pose(reference[c['name']]).rotation.matrix().T @
                   np.asarray(reference[c['name']]['translation']) for c in cams])
    scale, rotation, translation = fit(x, y)
    residual = np.linalg.norm(scale*x@rotation + translation - y, axis=1)
    loo = []
    for i in range(len(x)):
        keep = np.arange(len(x)) != i
        s, r, t = fit(x[keep], y[keep]); loo.append(np.linalg.norm(s*x[i]@r+t-y[i]))
    sparse_points = np.array([pt.xyz for pt in reconstruction.points3D.values()])
    aligned = scale * sparse_points @ rotation + translation
    # Reference access starts here, only after the complete model freeze audit.
    alignment_path = a.scan_dir / 'scan_alignment.mlp'
    root = ET.parse(alignment_path).getroot(); scans = []; details = []
    for node in root.findall('./MeshGroup/MLMesh'):
        name = node.attrib['filename']
        if Path(name).name != name: raise ValueError('unexpected scan path')
        matrix = np.fromstring(node.findtext('MLMatrix44'), sep=' ').reshape((4,4))
        if not np.allclose(matrix[3], [0,0,0,1]) or not np.isfinite(matrix).all(): raise ValueError('invalid scan transform')
        path = a.scan_dir / name; points, total = read_sample(path, a.stride)
        scans.append(points @ matrix[:3,:3].T + matrix[:3,3])
        details.append({'file': name, 'sha256': sha(path), 'total_vertices': total, 'finite_sampled_vertices': len(points),
                        'sampling': 'every '+str(a.stride)+'th source vertex; not uniform in space'})
    if len(scans) != 2: raise ValueError('expected two independent scanner files')
    scan = np.vstack(scans); tree = cKDTree(scan)
    point_distances = tree.query(aligned, workers=1)[0]
    evaluations = {}
    for name, box in boxes.items():
        sampled_surfaces = box_surface(box)
        evaluations[name] = {'predicted_all_faces_to_sampled_scan': stats(tree.query(sampled_surfaces, workers=1)[0]),
                             'sampled_whole_scan_to_predicted_faces': stats(distance_to_box(scan, box))}
    report = {'schema':'worldstate-eth3d-scan-diagnostic/0.1', 'status':'DEVELOPMENT_ONLY_NOT_FORMAL_ACCEPTANCE',
        'freeze_sha256':sha(a.freeze), 'source_poses_sha256':sha(a.source_poses),
        'scanner_alignment_sha256':sha(alignment_path), 'scan_files':details,
        'source_coordinate_units':'ETH3D scanner frame units; fitted photo-only scale is not independent',
        'photo_only_camera_alignment':{'matches':len(cams), 'method':'similarity fitted to reference camera centers',
            'fitted_scale_source_units_per_sfm_unit':scale, 'in_sample_rmse':float(np.sqrt(np.mean(residual**2))),
            'leave_one_out_rmse':float(np.sqrt(np.mean(np.square(loo))))},
        'photo_only_sparse_points_to_sampled_scan':stats(point_distances), 'known_pose_cuboid_diagnostics':evaluations,
        'wall_instance_precision_recall':'NOT_MEASURED_NO_INDEPENDENT_WALL_LABELS',
        'wall_dimension_error':'NOT_MEASURED_NO_INDEPENDENT_DIMENSIONS', 'layout_iou':'NOT_MEASURED_NO_REFERENCE_LAYOUT',
        'labor_cost':'NOT_MEASURED_NO_HUMAN_PAIRED_RUNS',
        'limitations':['Scan is a separate laser sensor, but official camera poses are scanner-registered; errors are correlated.',
            'Photo-only similarity uses reference camera positions; this is not independent scale accuracy or a standalone pipeline.',
            'Point subsampling and all-scene furniture/occlusion make these distances non-official and not wall accuracy, F-score, IoU, or completeness.',
            'Predicted cuboid includes hidden prior faces; they are not observed walls. Distances measure a hypothesis, not valid IFC walls.',
            'No human independently labeled walls or built reference IFC; ETH3D office is development, not Room-Test.']}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x') as stream: json.dump(report, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'photo_alignment':report['photo_only_camera_alignment'],
                      'photo_to_scan':report['photo_only_sparse_points_to_sampled_scan'], 'cuboids':evaluations}, indent=2))


if __name__ == '__main__': main()
