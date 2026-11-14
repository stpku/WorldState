"""Compare frozen kicker development outputs against sampled ETH3D laser scans.

Reference poses align photo-only SfM, so its scale cannot be assessed
independently; the known-pose model uses scanner-registered cameras. Sampled
whole-scene distances are diagnostic, not wall accuracy or an official metric.
"""
from __future__ import annotations
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import pycolmap
from scipy.spatial import cKDTree
from benchmarks.ws_geometry.compare_eyeful_poses import fit
from benchmarks.ws_geometry.evaluate_eth3d_scan import box_surface,distance_to_box,read_sample,sha,stats,verify_freeze
from benchmarks.ws_geometry.run_eth3d_known_pose import read_poses,rigid_pose


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze',type=Path,required=True)
    p.add_argument('--source-poses',type=Path,required=True);p.add_argument('--scan-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--stride',type=int,default=50);a=p.parse_args()
    if a.output.exists():raise FileExistsError('evaluation output already exists')
    if not 1<=a.stride<=10000:raise ValueError('invalid sample stride')
    # Nothing in scan-dir is opened until the model and code hashes are checked.
    freeze=verify_freeze(a.freeze);artifacts=freeze['artifacts'];read=lambda name:json.loads(Path(artifacts[name]['path']).read_text())
    geometry=read('photo_sfm');diagnostic=read('photo_structure');known=read('known29');box=read('pix8')
    if sha(a.source_poses)!=known['source_pose_sha256']:raise ValueError('reference camera poses changed')
    sparse=Path(artifacts['photo_sfm']['path']).parent/'sparse'/'0'
    for item in diagnostic['input']['source_reconstruction']:
        if Path(item['file']).name!=item['file'] or sha(sparse/item['file'])!=item['sha256']:raise ValueError('photo reconstruction changed')
    known_sparse=Path(artifacts['known29']['path']).parent
    for item in box['source_reconstruction']:
        if Path(item['file']).name!=item['file'] or sha(known_sparse/item['file'])!=item['sha256']:raise ValueError('known-pose reconstruction changed')
    reconstruction=pycolmap.Reconstruction(sparse);reference=read_poses(a.source_poses)
    cams=[c for c in geometry['registered_cameras'] if c['name'] in reference]
    if len(cams)<4:raise ValueError('not enough matching cameras')
    x=np.array([c['center'] for c in cams]);y=np.array([-rigid_pose(reference[c['name']]).rotation.matrix().T @
        np.asarray(reference[c['name']]['translation']) for c in cams])
    scale,rotation,translation=fit(x,y);residual=np.linalg.norm(scale*x@rotation+translation-y,axis=1);loo=[]
    for i in range(len(x)):
        keep=np.arange(len(x))!=i;s,r,t=fit(x[keep],y[keep]);loo.append(np.linalg.norm(s*x[i]@r+t-y[i]))
    points=np.array([pt.xyz for pt in reconstruction.points3D.values()]);aligned=scale*points@rotation+translation
    # Scanner geometry is accessed only after the frozen candidate has been verified.
    alignment=a.scan_dir/'scan_alignment.mlp';root=ET.parse(alignment).getroot();scans=[];details=[]
    for node in root.findall('./MeshGroup/MLMesh'):
        name=node.attrib['filename']
        if Path(name).name!=name:raise ValueError('unexpected scan path')
        matrix=np.fromstring(node.findtext('MLMatrix44'),sep=' ').reshape((4,4))
        if not np.allclose(matrix[3],[0,0,0,1]) or not np.isfinite(matrix).all():raise ValueError('invalid scan transform')
        path=a.scan_dir/name;xyz,total=read_sample(path,a.stride);scans.append(xyz@matrix[:3,:3].T+matrix[:3,3])
        details.append({'file':name,'sha256':sha(path),'total_vertices':total,'finite_sampled_vertices':len(xyz),
            'sampling':f'every {a.stride}th source vertex; not spatially uniform'})
    if len(scans)!=2:raise ValueError('expected two scanner files')
    scan=np.vstack(scans);tree=cKDTree(scan)
    result={'schema':'worldstate-eth3d-scan-diagnostic/0.1','status':'KICKER_DEVELOPMENT_ONLY_NOT_FORMAL_ACCEPTANCE',
        'freeze_sha256':sha(a.freeze),'source_poses_sha256':sha(a.source_poses),'scanner_alignment_sha256':sha(alignment),
        'scan_files':details,'units':'ETH3D source scanner frame units; scale is not independently assessed',
        'photo_only_camera_alignment':{'matches':len(cams),'method':'similarity fitted to reference camera centers',
            'fitted_scale_source_units_per_sfm_unit':scale,'in_sample_rmse':float(np.sqrt(np.mean(residual**2))),
            'leave_one_out_rmse':float(np.sqrt(np.mean(np.square(loo))))},
        'photo_only_sparse_points_to_sampled_scan':stats(tree.query(aligned,workers=1)[0]),
        'known_pose_cuboid_diagnostic':{'predicted_all_faces_to_sampled_scan':stats(tree.query(box_surface(box),workers=1)[0]),
            'sampled_whole_scan_to_predicted_faces':stats(distance_to_box(scan,box))},
        'wall_precision_recall':'NOT_MEASURED_NO_INDEPENDENT_LABELS','wall_dimensions':'NOT_MEASURED_NO_INDEPENDENT_DIMENSIONS',
        'layout_iou':'NOT_MEASURED_NO_REFERENCE_LAYOUT','labor_cost':'NOT_MEASURED_NO_HUMAN_PAIRED_RUNS',
        'limitations':['Reference camera poses and scans are registered; position and scale errors are correlated.',
            'Photo-only similarity is fitted to reference poses and is not an independently verified scale.',
            'Sampled whole-scene points include furniture and occlusion; results are not wall F-score, IoU, or independent wall dimensions.',
            'Cuboid includes unseen faces and assumes closure; a whole-surface diagnostic is not visible-wall accuracy.',
            'Development scene, not Room-Test; no independent human has labeled walls or authored reference IFC.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('photo_only_camera_alignment','photo_only_sparse_points_to_sampled_scan',
                                           'known_pose_cuboid_diagnostic')},indent=2))


if __name__=='__main__':main()
