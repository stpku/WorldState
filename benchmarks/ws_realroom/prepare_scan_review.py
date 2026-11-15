"""Prepare an independent, scan-only review pack; never read BIM candidates."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from benchmarks.ws_geometry.evaluate_eth3d_scan import read_sample


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read_xyz(path):
    with path.open('rb') as f:
        lines=[]
        while True:
            line=f.readline().decode('ascii').strip();lines.append(line)
            if line == 'end_header':break
        if lines[:2]!=['ply','format binary_little_endian 1.0'] or lines[3:6]!=['property float x','property float y','property float z']:
            raise ValueError('Unexpected review PLY layout')
        n=int(lines[2].split()[-1]); result=np.fromfile(f,dtype='<f4').reshape(-1,3)
        if len(result)!=n or not np.isfinite(result).all():raise ValueError('Invalid PLY points')
        return result


def save_xyz(path,points):
    points=np.asarray(points,dtype='<f4')
    with path.open('xb') as f:
        f.write(f'ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\nend_header\n'.encode('ascii'))
        points.tofile(f)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proposals',type=Path,required=True);p.add_argument('--scan-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('use a new review directory')
    doc=json.loads(a.proposals.read_text())
    if doc.get('schema')!='worldstate-eth3d-scan-plane-proposals/0.1':raise ValueError('unsupported proposal set')
    alignment=a.scan_dir/'scan_alignment.mlp'
    if sha(alignment)!=doc['scan_alignment_sha256']:raise ValueError('scan alignment hash mismatch')
    source_by_name={s['name']:s for s in doc['source_scans']};scans=[]
    for node in ET.parse(alignment).getroot().findall('./MeshGroup/MLMesh'):
        name=node.attrib['filename'];source=a.scan_dir/name
        if Path(name).name!=name or name not in source_by_name or sha(source)!=source_by_name[name]['sha256']:
            raise ValueError('scan source hash mismatch')
        transform=np.fromstring(node.findtext('MLMatrix44'),sep=' ').reshape(4,4)
        if not np.isfinite(transform).all() or not np.allclose(transform[3],[0,0,0,1]):raise ValueError('bad alignment')
        points,total=read_sample(source,doc['configuration']['stride'])
        scans.append(points@transform[:3,:3].T+transform[:3,3])
    if len(scans)!=2:raise ValueError('expected two scans')
    scene=np.vstack(scans);a.output.mkdir(parents=True)
    save_xyz(a.output/'scene-stride-100.ply',scene)
    planes=[]
    for plane in doc['planes']:
        artifact=plane['review_point_cloud'];source=Path(artifact['path'])
        if sha(source)!=artifact['sha256']:raise ValueError('plane hash mismatch')
        points=read_xyz(source);name=plane['id']+'.ply';shutil.copyfile(source,a.output/name)
        planes.append({'id':plane['id'],'point_count':len(points),'download':name,'sha256':artifact['sha256'],
                       'points':np.round(points[::max(1,len(points)//3000)],4).tolist()})
    # The background is only a viewing decimation, never a measurement reference.
    body={'schema':'worldstate-independent-scan-review/0.1','status':'UNREVIEWED',
          'source_scans':doc['source_scans'],'alignment_sha256':doc['scan_alignment_sha256'],
          'scene_download':'scene-stride-100.ply','scene_sha256':sha(a.output/'scene-stride-100.ply'),
          'background_points':np.round(scene[::max(1,len(scene)//15000)],4).tolist(),'planes':planes,
          'note':'Scan-only proposals; no model candidates were used or shown. Axes and lengths are scanner units; no human review.'}
    (a.output/'data.json').write_text(json.dumps(body,ensure_ascii=False,separators=(',',':'))+'\n')
    shutil.copyfile(Path(__file__).with_name('scan_review.html'),a.output/'index.html')
    print(json.dumps({'status':'UNREVIEWED_SCAN_ONLY','output':str(a.output),'planes':len(planes),
        'sampled_scene_points':len(scene),'scene_sha256':body['scene_sha256']},indent=2))

if __name__=='__main__':main()
