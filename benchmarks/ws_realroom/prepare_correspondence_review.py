"""Package unverified real-photo line matches for independent human review.

Results and raster overlays remain in a caller-provided external directory;
this script does not assign truth labels or claim a reviewer participated.
"""
import argparse
import html
import json
from pathlib import Path
from PIL import Image, ImageDraw

from products.worldstate_bim.general_modeler import camera_digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample',action='append',nargs=2,metavar=('WORKSPACE','RESULT_DIR'),required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise FileExistsError('choose a new review package')
    args.output.mkdir(mode=0o700,parents=True);tasks=[];sections=[]
    for number,(workspace_path,result_path) in enumerate(args.sample,1):
        workspace=Path(workspace_path);result_dir=Path(result_path)
        result=json.loads((result_dir/'result.json').read_text())
        if result.get('mode')!='gluestick':raise ValueError('expected a joint point-line run')
        state=json.loads((workspace/'photo-project.json').read_text())['general_modeler']
        cameras={c['image_id']:c for c in state['cameras']};images=result['images']
        if len(images)!=2 or any(cameras[i['id']]['sha256']!=i['sha256'] for i in images):
            raise ValueError('camera and matching results are not from the same photos')
        overlay=f'sample-{number}-matches.jpg'
        candidates=[x for x in result['line_candidates'] if x['semantic_structure_candidate']]
        # Preserve a few additional lines as hard negatives without declaring their class.
        selected=candidates+[x for x in result['line_candidates'] if not x['semantic_structure_candidate']][:5]
        uploads={u['sha256']:u for u in json.loads((workspace/'evidence-index.json').read_text())['uploads']}
        rendered=[]
        for i,image in enumerate(images):
            u=uploads[image['sha256']];source=workspace/'evidence'/(u['sha256']+u['extension'])
            with Image.open(source) as photo:
                photo.draft('RGB',(1024,1024));photo.thumbnail((1024,1024));canvas=photo.convert('RGB')
            draw=ImageDraw.Draw(canvas);c=cameras[image['id']]
            for line in selected:
                coords=line['a_original_px' if i==0 else 'b_original_px']
                pixels=[(x*canvas.width/c['width_px'],y*canvas.height/c['height_px']) for x,y in coords]
                draw.line(pixels,fill='#ffdb35',width=3);draw.text(pixels[0],str(line['line_id']),fill='#ffdb35',stroke_width=2,stroke_fill='#111111')
            rendered.append(canvas)
        combined=Image.new('RGB',(sum(x.width for x in rendered),max(x.height for x in rendered)),'white')
        combined.paste(rendered[0],(0,0));combined.paste(rendered[1],(rendered[0].width,0));combined.save(args.output/overlay,quality=90)
        rows=[]
        for line in selected:
            task={'id':f'sample-{number}-line-{line["line_id"]}',
                  'scene':workspace.name,'method':'GlueStick point-line with UPerNet boundary suggestion',
                  'candidate_kind':'matched_image_lines_not_confirmed_building_structure',
                  'semantic_boundary_suggested':line['semantic_structure_candidate'],
                  'review_status':'AWAITING_INDEPENDENT_HUMAN_REVIEW',
                  'views':[{'image_id':images[i]['id'],'photo':images[i]['name'],'photo_sha256':images[i]['sha256'],
                            'camera_sha256':camera_digest(cameras[images[i]['id']]),
                            'line_endpoints_original_px':line['a_original_px' if i==0 else 'b_original_px'],
                            'visibility':'UNKNOWN'} for i in (0,1)],
                  'questions':['same physical feature?','wall / ceiling / floor / door / window / furniture / unknown?',
                               'physical boundary or occlusion / image edge?', 'visible in both images?',
                               'mark corresponding physical point if one exists; otherwise reject'],
                  'human_review':None}
            tasks.append(task)
            rows.append('<tr><td>'+html.escape(task['id'])+'</td><td>'+str(task['semantic_boundary_suggested'])+
                        '</td><td>'+html.escape(str(task['views'][0]['line_endpoints_original_px']))+'</td><td>'+
                        html.escape(str(task['views'][1]['line_endpoints_original_px']))+'</td></tr>')
        sections.append(f'<h2>Sample {number}: {html.escape(workspace.name)}</h2><p>Image IDs: {images[0]["id"]}, {images[1]["id"]}; original image hashes are recorded in tasks.json.</p>'+
                        f'<img src="{overlay}" alt="Unreviewed point-line matches"><table><tr><th>ID</th><th>Semantic boundary candidate</th><th>View A original pixels</th><th>View B original pixels</th></tr>'+''.join(rows)+'</table>')
    payload={'schema':'worldstate-correspondence-review/0.1','status':'AWAITING_INDEPENDENT_HUMAN_REVIEW',
             'scope':'ETH3D non-commercial research development scenes; not a blind Room-Test',
             'instructions':'Review each proposed match independently. Preserve unknown and occlusion; do not infer accuracy from candidate count.',
             'tasks':tasks}
    (args.output/'tasks.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    document='<!doctype html><html lang="en"><meta charset="utf-8"><title>Unreviewed correspondence tasks</title><style>body{font:15px sans-serif;max-width:1600px;margin:30px auto}img{width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:5px;vertical-align:top}</style><h1>Unreviewed physical correspondence tasks</h1><p>No independent reviewer has confirmed these candidates. Examine source photos, furniture and occlusion before marking any match.</p>'+''.join(sections)+'</html>'
    (args.output/'index.html').write_text(document)
    print(json.dumps({'status':payload['status'],'tasks':len(tasks),'samples':len(args.sample),'output':str(args.output)}))


if __name__=='__main__':main()
