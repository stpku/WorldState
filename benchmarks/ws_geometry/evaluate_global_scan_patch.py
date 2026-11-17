"""Compare a frozen known-pose patch with whole-scan references, without a model ROI.

ETH3D kicker is a development scene; scanner-registered poses are correlated
with the reference. These results are geometric diagnostics, not wall labels.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from benchmarks.ws_geometry.evaluate_eth3d_scan import read_sample,stats
from benchmarks.ws_geometry.evaluate_kicker_local_wall import patch_points
from products.worldstate_bim.model_first import _basis


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze',type=Path,required=True)
    p.add_argument('--scan-dir',type=Path,required=True);p.add_argument('--planes',type=Path,required=True)
    p.add_argument('--stride',type=int,default=100);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    if not 1<=a.stride<=10000:raise ValueError('invalid stride')
    frozen=json.loads(a.freeze.read_text());artifact=frozen['artifacts']['solution.json'];path=Path(artifact['path'])
    if path.is_symlink() or sha(path)!=artifact['sha256']:raise ValueError('candidate differs from frozen solution')
    solution=json.loads(path.read_text());params=np.asarray(solution['optimized_parameters'],float)
    proposals=json.loads(a.planes.read_text())
    if proposals.get('candidate_model_accessed') is not False:raise ValueError('planes must be extracted without candidate access')
    alignment=a.scan_dir/'scan_alignment.mlp'
    if sha(alignment)!=proposals['scan_alignment_sha256']:raise ValueError('scan alignment changed')
    root=ET.parse(alignment).getroot();scans=[];sources=[]
    expected={x['name']:x['sha256'] for x in proposals['source_scans']}
    for item in root.findall('./MeshGroup/MLMesh'):
        name=item.attrib['filename']
        if Path(name).name!=name:raise ValueError('unsafe source scan')
        scan=a.scan_dir/name;fingerprint=sha(scan)
        if fingerprint!=expected.get(name):raise ValueError('scan hash differs from source-only planes')
        matrix=np.fromstring(item.findtext('MLMatrix44'),sep=' ').reshape(4,4)
        if not np.allclose(matrix[3],[0,0,0,1]) or not np.isfinite(matrix).all():raise ValueError('bad alignment')
        points,total=read_sample(scan,a.stride);points=points@matrix[:3,:3].T+matrix[:3,3]
        scans.append(points);sources.append({'file':name,'sha256':fingerprint,'total':total,'sampled':len(points)})
    if len(scans)!=2:raise ValueError('expected two registered scans')
    left,right,bottom=params[:3],params[3:6],params[6:9];x,z,width,_=_basis(left,right,bottom)
    y=np.cross(z,x);height=params[9];surface=patch_points(params)
    def global_scan_to_patch(points):
        q=points-left;u=q@x;v=q@y;w=q@z
        return np.sqrt(np.maximum(-u,0)**2+np.maximum(u-width,0)**2+v*v+np.maximum(-w,0)**2+np.maximum(w-height,0)**2)
    details=[]
    for i,points in enumerate(scans):
        details.append({'source':sources[i]['file'],'candidate_surface_to_whole_scan':stats(cKDTree(points).query(surface,workers=1)[0]),
          'whole_scan_to_finite_patch':stats(global_scan_to_patch(points))})
    cross={'scan1_to_scan2':stats(cKDTree(scans[1]).query(scans[0],workers=1)[0]),
           'scan2_to_scan1':stats(cKDTree(scans[0]).query(scans[1],workers=1)[0])}
    planes=[]
    for plane in proposals['planes']:
        normal=np.asarray(plane['normal']);offset=plane['offset_source'];d=np.abs(surface@normal+offset)
        planes.append({'id':plane['id'],'median_candidate_distance_source':float(np.median(d)),
                       'source_status':plane['status'],'scan_support':plane['each_scan_support_against_shared_fitted_plane']})
    report={'status':'DEVELOPMENT_ONLY_NOT_WALL_REFERENCE','freeze_sha256':sha(a.freeze),'solution_sha256':sha(path),
      'source_only_plane_proposals_sha256':sha(a.planes),'source_only_planes_count':len(planes),'source_scans':sources,
      'stride':a.stride,'candidate_patch_count':len(surface),'scans':details,'cross_scan_nearest_neighbor':cross,'all_planes':planes,
      'wall_instance_precision_recall':'NOT_MEASURED','independent_dimensions':'NOT_MEASURED',
      'limitations':['The evaluation uses every sampled scan point, not a region selected by the model.',
        'Whole-scene scan-to-patch fraction is not wall recall or completeness.',
        'Laser scans and official known camera poses share registration; scale is not an independent physical measurement.',
        'Global planes include furniture, ceiling and walls; they are unaudited, and a plane was not chosen using this patch.',
        'Two aligned scan files may share occlusions and systematic errors; nearest neighbor is not independent truth.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'source_only_planes_count':len(planes),'scans':details,'cross_scan':cross},indent=2))


if __name__=='__main__':main()
