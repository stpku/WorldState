"""Download the explicitly pinned MIT-tagged ONNX model to a new local path."""
import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path
from products.worldstate_bim.semantic_vision import UperNetOnnxProvider

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
if a.output.exists() or a.output.is_symlink():raise FileExistsError('choose a new output file')
a.output.parent.mkdir(parents=True,exist_ok=True)
url=('https://huggingface.co/JElvis/upernet-convnext-tiny-ade-onnx/resolve/'
     +UperNetOnnxProvider.MODEL_REVISION+'/model.onnx')
fd,tmp=tempfile.mkstemp(dir=a.output.parent,prefix='.model-')
try:
    with os.fdopen(fd,'wb') as out,urllib.request.urlopen(url,timeout=180) as source:
        sha=hashlib.sha256();size=0
        while chunk:=source.read(1024*1024):
            size+=len(chunk)
            if size>250_000_000:raise ValueError('unexpected model size')
            sha.update(chunk);out.write(chunk)
    if sha.hexdigest()!=UperNetOnnxProvider.MODEL_SHA256:raise ValueError('model hash mismatch')
    os.replace(tmp,a.output);print('verified SHA-256',sha.hexdigest(),'bytes',size)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
