"""Make a separate development project from source-labelled line intersections.

The resulting tracks are unreviewed GlueStick line-intersection proposals,
not COLMAP tracks, human annotations, wall identities or validated corners.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def file_sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--probe',type=Path,required=True);p.add_argument('--images',nargs=2,type=int,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new project')
    original=json.loads((a.source/'photo-project.json').read_text());state=original['general_modeler']
    cameras=[c for c in state['cameras'] if c['image_id'] in a.images]
    if len(cameras)!=2 or len(set(a.images))!=2:raise ValueError('two registered photos required')
    index=json.loads((a.source/'evidence-index.json').read_text());uploads={u['sha256']:u for u in index['uploads']}
    for c in cameras:
        u=uploads[c['sha256']];path=a.source/'evidence'/(u['sha256']+u['extension'])
        if path.is_symlink() or file_sha(path)!=c['sha256']:raise ValueError('source photo hash mismatch')
    probe=json.loads(a.probe.read_text());by_id={c['image_id']:c for c in cameras}
    if [(v['image_id'],v['photo_sha256']) for v in probe.get('source_images',[])] != [(i,by_id[i]['sha256']) for i in a.images]:
        raise ValueError('probe camera order or source photos differ')
    from products.worldstate_bim.general_modeler import camera_digest
    if any(v['camera_sha256']!=camera_digest(by_id[v['image_id']]) for v in probe['source_images']):
        raise ValueError('probe camera version changed')
    candidates=probe['candidates'];tracks=[]
    for i,item in enumerate(candidates,1):
        if item['status']!='DETERMINISTIC_UNREVIEWED_NOT_HUMAN_CONFIRMED':raise ValueError('unexpected candidate status')
        tracks.append({'id':i,'source_line_ids':item['lines'],
                       'observations':[{'image_id':a.images[0],'pixel_xy':item['a']},
                                       {'image_id':a.images[1],'pixel_xy':item['b']}]})
    a.output.mkdir(mode=0o700,parents=True);(a.output/'evidence').mkdir(mode=0o700)
    chosen=[]
    for c in cameras:
        u=uploads[c['sha256']];chosen.append(u);shutil.copyfile(a.source/'evidence'/(u['sha256']+u['extension']),a.output/'evidence'/(u['sha256']+u['extension']))
    (a.output/'evidence-index.json').write_text(json.dumps({'schema':'worldstate-studio-evidence/0.1','uploads':chosen},indent=2)+'\n')
    track_file=a.output/'modeler-tracks.json';track_file.write_text(json.dumps({'tracks':tracks},indent=2,allow_nan=False)+'\n')
    new_state={'schema':'worldstate-studio-general-modeler/0.1','revision':1,'camera_mode':state['camera_mode'],
        'source_reconstruction':state['source_reconstruction'],'cameras':cameras,'objects':[],'observations':[],
        'object_constraints':[],'solution':None,'model_dirty':False,'track_sha256':file_sha(track_file),
        'track_count':len(tracks),'duplicate_view_tracks_excluded':0,'suggestions':[],
        'track_source':'GlueStick matched-line intersections; known-pose epipolar-filtered, NOT human reviewed',
        'track_source_sha256':file_sha(a.probe),'registration_status':state['registration_status']}
    project={'schema':'worldstate-photo-project/0.1','id':'office-line-intersection-research',
             'name':'ETH3D office · unreviewed line intersections','operator_kind':'automation',
             'current_revision':None,'events':[],'general_modeler':new_state}
    (a.output/'photo-project.json').write_text(json.dumps(project,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'workspace':str(a.output),'photos':len(cameras),'candidate_tracks':len(tracks),
                      'status':'UNREVIEWED_GEOMETRIC_FEATURE_CANDIDATES'}))


if __name__=='__main__':main()
