"""Render hash-verified original pixels for an analyst floor-track review."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image,ImageDraw


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    review=json.loads(a.review.read_text())
    if review.get('schema')!='worldstate-floor-review-diagnostic/0.1':raise ValueError('unexpected review')
    seen=set();items=[]
    for track in review['source_observations']:
        for obs in track['observations']:
            name=obs['photo'];path=a.images/name;key=(obs['photo_sha256'],*obs['pixel_xy'])
            if key in seen:continue
            if Path(name).name!=name or path.is_symlink() or not path.is_file() or sha(path)!=obs['photo_sha256']:
                raise ValueError('source photo hash mismatch')
            seen.add(key);x,y=obs['pixel_xy'];ix,iy=round(x),round(y)
            with Image.open(path) as image:
                if not (0<=x<image.width and 0<=y<image.height):raise ValueError('pixel outside photo')
                crop=image.convert('RGB').crop((ix-80,iy-80,ix+80,iy+80)).resize((320,320),Image.Resampling.LANCZOS)
            d=ImageDraw.Draw(crop);cx=(x-ix+80)*2;cy=(y-iy+80)*2;d.ellipse((cx-6,cy-6,cx+6,cy+6),outline='red',width=3)
            items.append((obs,crop))
    if not items:raise ValueError('review contains no source observations')
    columns=2;sheet=Image.new('RGB',(columns*320,((len(items)+1)//columns)*345),'white');d=ImageDraw.Draw(sheet)
    for i,(obs,crop) in enumerate(items):
        x=(i%columns)*320;y=(i//columns)*345;sheet.paste(crop,(x,y));d.text((x+3,y+322),obs['photo'],fill='black')
    a.output.mkdir(parents=True);sheet.save(a.output/'review-contact.png')
    manifest={'review_sha256':sha(a.review),'observations':[x[0] for x in items],
              'status':'VISUAL_REVIEW_NOT_GROUND_TRUTH','image':'review-contact.png'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('rendered',len(items),'distinct source observations')


if __name__=='__main__':main()
