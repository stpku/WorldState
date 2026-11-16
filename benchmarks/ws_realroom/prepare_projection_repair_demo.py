"""Copy an existing photo-backed wall and its earlier controlled perturbation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from products.worldstate_bim.general_modeler import camera_digest
from products.worldstate_bim.model_first import project_local_wall_ir


def prepare(source: Path, output: Path) -> None:
    source=source.resolve(strict=True)
    if output.exists():raise FileExistsError('choose a new workspace')
    project=json.loads((source/'photo-project.json').read_text())
    rev=project['current_revision'];model=json.loads((source/f'revision-{rev:03}'/'model.json').read_text())
    if project.get('operator_kind')!='automation' or not project_local_wall_ir(model):
        raise ValueError('expected an existing photo-backed automation patch')
    evidence={e['id']:e for e in model['evidence']};index=json.loads((source/'evidence-index.json').read_text())
    uploads={p['sha256']:p for p in index['uploads']}
    cameras=[c for c in evidence['camera']['cameras'] if c['sha256'] in uploads]
    if len(cameras)<2:raise ValueError('need at least two original registered photos')
    for camera in cameras:
        item=uploads[camera['sha256']];p=source/'evidence'/(item['sha256']+item['extension'])
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=camera['sha256']:
            raise ValueError('source photo hash mismatch')
        camera_digest(camera)
    output.mkdir(mode=0o700,parents=True);(output/'evidence').mkdir(mode=0o700)
    shutil.copytree(source/f'revision-{rev:03}',output/f'revision-{rev:03}')
    for item in index['uploads']:
        shutil.copyfile(source/'evidence'/(item['sha256']+item['extension']),output/'evidence'/(item['sha256']+item['extension']))
    (output/'evidence-index.json').write_text(json.dumps(index,indent=2)+'\n')
    tracks=output/'modeler-tracks.json';tracks.write_text(json.dumps({'tracks':[]})+'\n')
    project['general_modeler']={'schema':'worldstate-studio-general-modeler/0.1','revision':1,
        'camera_mode':'known-pose','source_reconstruction':evidence['camera']['source_reconstruction'],
        'cameras':cameras,'objects':[],'observations':[],'object_constraints':[],'solution':None,
        'model_dirty':False,'track_sha256':hashlib.sha256(tracks.read_bytes()).hexdigest(),
        'track_count':0,'duplicate_view_tracks_excluded':0,'suggestions':[],
        'registration_status':'MODEL_SOURCE_CAMERA_VERSION_REUSED_NOT_INDEPENDENTLY_VERIFIED'}
    project['name']='ETH3D kicker · controlled height perturbation · research only'
    project['notes']='Existing automation-created height perturbation; not a real observed change.'
    (output/'photo-project.json').write_text(json.dumps(project,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prepare(a.source,a.output)
    print(json.dumps({'workspace':str(a.output),'status':'CONTROLLED_PERTURBATION_NOT_SITE_CHANGE'}))
