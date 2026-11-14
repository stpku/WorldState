"""Run local semantic inference on actual photos; input and output paths are explicit."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from products.worldstate_bim.semantic_vision import UperNetOnnxProvider


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('images', type=Path, nargs='+')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    provider=UperNetOnnxProvider(args.model)
    for image in args.images:
        result,overlay=provider.analyze(image)
        stem=image.stem+'-'+result['image_sha256'][:12]
        (args.output/(stem+'.json')).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        (args.output/(stem+'-overlay.png')).write_bytes(overlay)
        print(json.dumps({'image':str(image),'sha256':result['image_sha256'],'seconds':result['runtime_seconds'],
                          'candidates':len(result['candidates']),'overlay_sha256':hashlib.sha256(overlay).hexdigest()}),flush=True)

if __name__=='__main__': main()
