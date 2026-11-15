"""Run local AI semantics on three real views; track matches are proposals only."""
from __future__ import annotations
import argparse
import json
import math
import re
import time
import urllib.request
from pathlib import Path
from products.worldstate_bim.multiview_fusion import triangulate_observations


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:18790');p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+',a.url) or a.output.exists():raise ValueError('use local Studio and new output')
    a.output.mkdir(parents=True)
    def get(path):
        with urllib.request.urlopen(a.url+path,timeout=20) as response:return response.read()
    html=get('/modeler').decode();match=re.search(r'const token="([^"]+)"',html)
    if not match:raise ValueError('local Studio token missing')
    token=match.group(1)
    def post(path,body):
        request=urllib.request.Request(a.url+path,data=json.dumps(body).encode(),method='POST',
            headers={'Content-Type':'application/json','Origin':a.url,'X-WorldState-Token':token})
        with urllib.request.urlopen(request,timeout=300) as response:return json.load(response)
    state=json.loads(get('/api/modeler/state'));cameras={c['image_id']:c for c in state['state']['cameras']}
    tracks=json.loads((a.workspace/'modeler-tracks.json').read_text())['tracks'];output=[]
    for case,image_id in [('sofa-side-hypothesis',12),('table-side-hypothesis',14),('yellow-door-end-hypothesis',19)]:
        cam=cameras[image_id];photo_id='upload-'+cam['sha256'][:16];started=time.monotonic()
        run=post('/api/vision/analyze',{'photo_id':photo_id})
        if run['image_sha256']!=cam['sha256']:raise ValueError('photo hash mismatch')
        (a.output/(case+'-visual-candidates.json')).write_text(json.dumps(run,indent=2,ensure_ascii=False)+'\n')
        lines=[c for c in run['candidates'] if c['kind'] in {'wall_floor_line','wall_ceiling_line'}]
        regions=[c for c in run['candidates'] if c['kind'] in {'wall_region','door_region','window_region'}]
        matches=[]
        for line in lines[:8]:
            for point in line['points_px']:
                found=[]
                for track in tracks:
                    obs=next((o for o in track['observations'] if o['image_id']==image_id),None)
                    if obs:
                        dist=math.dist(point,obs['pixel_xy'])
                        if dist<=30:found.append((dist,track,obs))
                if not found:continue
                dist,track,source=min(found,key=lambda x:(x[0],x[1]['id']))
                others=track['observations'][:]
                observation=[{'image_id':x['image_id'],'photo_sha256':cameras[x['image_id']]['sha256'],
                    'photo':cameras[x['image_id']]['photo'],'pixel_xy':x['pixel_xy']} for x in others]
                try:
                    geometry=triangulate_observations(list(cameras.values()),observation)
                    diagnosis={'status':geometry['status'],'max_reprojection_error_px':geometry['max_reprojection_error_px'],
                               'max_parallax_degrees':geometry['max_parallax_degrees']}
                except ValueError as e:diagnosis={'status':'REJECTED','reason':str(e)}
                matches.append({'line_id':line['id'],'line_endpoint_px':point,'track_id':track['id'],
                    'source_track_pixel_px':source['pixel_xy'],'endpoint_track_distance_px':dist,
                    'observations':observation,'geometry':diagnosis,'origin':'deterministic_colmap_track',
                    'confirmation':'proposed_unverified','physical_feature':'UNKNOWN',
                    'warning':'Proximity to a semantic boundary does not prove the track is a wall corner.'})
        result={'case':case,'photo':cam['photo'],'photo_sha256':cam['sha256'],'image_id':image_id,
            'width_px':cam['width_px'],'height_px':cam['height_px'],'vision_run_id':run['id'],
            'overlay_file':str(a.workspace/'vision'/(run['id']+'.png')),'provider':run['provider'],
            'model_sha256':run['model_sha256'],'runtime_seconds':run['runtime_seconds'],
            'regions':regions,'boundary_lines':lines,'cross_view_suggestions':matches,
            'status':'AI_AND_TRACK_SUGGESTIONS_UNCONFIRMED',
            'limitations':['UPerNet semantic regions do not separate wall instances.',
                'Line endpoints may be occlusions or frame boundaries. Nearest tracks can be furniture.',
                'No physical wall or corner identity is confirmed. No human annotation or metric scale.']}
        output.append(result)
        (a.output/'report.json').write_text(json.dumps({'cases':output,'status':'PARTIAL_NOT_HUMAN_REVIEWED'},indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({'case':case,'photo':cam['photo'],'lines':len(lines),'regions':len(regions),
            'cross_view_suggestions':len(matches),'seconds':round(time.monotonic()-started,1)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
