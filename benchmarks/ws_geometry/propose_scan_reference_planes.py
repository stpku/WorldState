"""Propose development scan planes without reading any model candidate.

Outputs are unaudited plane proposals, not reference wall instances. This
script accepts only source scans and fixed global segmentation settings; it
does not load photo-model positions, dimensions, or IFC objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from benchmarks.ws_geometry.evaluate_eth3d_scan import read_sample


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scan-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--artifacts',type=Path,help='New directory for source-only point-cloud proposals for external review')
    p.add_argument('--stride',type=int,default=100);p.add_argument('--voxel-source',type=float,default=.05)
    p.add_argument('--distance-source',type=float,default=.03);p.add_argument('--planes',type=int,default=12)
    p.add_argument('--iterations',type=int,default=300);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    if a.artifacts is not None and a.artifacts.exists():raise FileExistsError('choose a new artifact directory')
    if not 1<=a.stride<=10000 or not 0<a.voxel_source<1 or not 0<a.distance_source<1 or not 1<=a.planes<=30 or not 10<=a.iterations<=5000:
        raise ValueError('invalid segmentation configuration')
    alignment=a.scan_dir/'scan_alignment.mlp';root=ET.parse(alignment).getroot();sources=[];scans=[]
    for node in root.findall('./MeshGroup/MLMesh'):
        name=node.attrib['filename']
        if Path(name).name!=name:raise ValueError('unsafe scan path')
        matrix=np.fromstring(node.findtext('MLMatrix44'),sep=' ').reshape(4,4)
        if not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):raise ValueError('invalid scanner transform')
        points,total=read_sample(a.scan_dir/name,a.stride);scans.append(points@matrix[:3,:3].T+matrix[:3,3])
        sources.append({'name':name,'sha256':sha(a.scan_dir/name),'total_vertices':total,'sampled_vertices':len(points)})
    if len(scans)!=2:raise ValueError('expected two ETH3D scan sources')
    xyz=np.vstack(scans);voxels=np.floor(xyz/a.voxel_source).astype(np.int64)
    _,unique=np.unique(voxels,axis=0,return_index=True);cloud=xyz[unique]
    del xyz,voxels,unique
    rng=np.random.default_rng(41731);initial_count=len(cloud);planes=[]
    if a.artifacts is not None:a.artifacts.mkdir(parents=True)
    for index in range(a.planes):
        if len(cloud)<1000:break
        sample=cloud[rng.choice(len(cloud),min(30000,len(cloud)),replace=False)]
        triples=sample[rng.integers(0,len(sample),size=(a.iterations,3))]
        normals=np.cross(triples[:,1]-triples[:,0],triples[:,2]-triples[:,0]);lengths=np.linalg.norm(normals,axis=1)
        good=lengths>1e-9;normals=normals[good]/lengths[good,None];offsets=-np.einsum('ij,ij->i',normals,triples[good,0])
        if not len(normals):break
        counts=[]
        for start in range(0,len(normals),24):
            distances=np.abs(sample@normals[start:start+24].T+offsets[start:start+24])
            counts.extend(np.count_nonzero(distances<a.distance_source,axis=0).tolist())
        best=int(np.argmax(counts));initial=np.abs(cloud@normals[best]+offsets[best])<a.distance_source
        if initial.sum()<1000:break
        first=cloud[initial];center=first.mean(axis=0);_,vectors=np.linalg.eigh((first-center).T@(first-center))
        normal=vectors[:,0];offset=-float(normal@center)
        inliers=np.abs(cloud@normal+offset)<a.distance_source;points=cloud[inliers];center=points.mean(axis=0)
        # The 5th–95th percentile box is coverage of points, not a wall boundary.
        artifact=None
        if a.artifacts is not None:
            artifact=a.artifacts/f'scan-plane-{index+1}.ply'
            header=('ply\nformat binary_little_endian 1.0\nelement vertex '+str(len(points))+
                    '\nproperty float x\nproperty float y\nproperty float z\nend_header\n').encode('ascii')
            with artifact.open('xb') as stream:stream.write(header);stream.write(np.asarray(points,dtype='<f4').tobytes())
        scan_support=[]
        for source,scan in zip(sources,scans):
            residual=np.abs(scan@normal+offset);inside=residual[residual<a.distance_source]
            scan_support.append({'name':source['name'],'sampled_inliers':len(inside),
                'median_residual_source':float(np.median(inside)) if len(inside) else None,
                'p90_residual_source':float(np.percentile(inside,90)) if len(inside) else None})
        planes.append({'id':f'scan-plane-{index+1}','normal':normal.tolist(),'offset_source':offset,
            'centroid_source':center.tolist(),'support_voxels':len(points),
            'review_point_cloud':({'path':str(artifact.resolve()),'sha256':sha(artifact)} if artifact else None),
            'each_scan_support_against_shared_fitted_plane':scan_support,
            'xyz_5th_percentile_source':np.percentile(points,5,axis=0).tolist(),
            'xyz_95th_percentile_source':np.percentile(points,95,axis=0).tolist(),
            'residual_median_source':float(np.median(np.abs(points@normal+offset))),
            'vertical_candidate_assuming_source_z_up':bool(abs(normal[2])<.25),
            'status':'UNREVIEWED_SCAN_PLANE_NOT_A_WALL_REFERENCE'})
        cloud=cloud[~inliers]
    result={'schema':'worldstate-eth3d-scan-plane-proposals/0.1','status':'UNREVIEWED_DEVELOPMENT_ONLY',
        'source_scans':sources,'scan_alignment_sha256':sha(alignment),'source_units':'scanner coordinate units',
        'configuration':{'stride':a.stride,'voxel_source':a.voxel_source,'distance_source':a.distance_source,
                         'max_planes':a.planes,'iterations':a.iterations,'ransac_sample_limit':30000,'seed':41731},
        'sampled_voxels':initial_count,'planes':planes,'candidate_model_accessed':False,
        'limitations':['Global RANSAC may merge or split walls and detect furniture; no object identity or boundary has been reviewed.',
                       'Source z-up classification is an assumption; percentile extents are not independent wall lengths.',
                       'Per-scan distances use the same plane fitted to both scans and are not independent accuracy.',
                       'No independent human has labelled wall instances or dimensions; formal accuracy is NOT_MEASURED.',
                       'ETH3D kicker was already used for development and is not a blind Room-Test.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'sampled_voxels':initial_count,'planes':len(planes),
                      'vertical_candidates':sum(x['vertical_candidate_assuming_source_z_up'] for x in planes),'output':str(a.output)},indent=2))


if __name__=='__main__':main()
