"""Offline Hunyuan3D-2mv research runner. NOT_TESTED without CUDA and weights.

Inputs must be locally authorized and prepared RGBA views. This runner does
not fetch weights or send images to any service. Output is an inferred mesh,
not a measured or semantic BIM object.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REVISION="f8db63096c8282cb27354314d896feba5ba6ff8a"
MODEL_REVISION="3a761b539b29fe4ff64714813aa9560fd66f5de0"


def sha(path: Path)->str:
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",type=Path,required=True);p.add_argument("--weights-dir",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True);p.add_argument("--checkpoint-sha256",required=True)
    p.add_argument("--manifest",type=Path,required=True);p.add_argument("--image-root",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True);args=p.parse_args()
    repo=args.repo.resolve(strict=True);weights=args.weights_dir.resolve(strict=True);checkpoint=args.checkpoint.resolve(strict=True)
    if not checkpoint.is_relative_to(weights) or sha(checkpoint)!=args.checkpoint_sha256:
        raise ValueError("checkpoint must be inside weights directory and match its SHA-256")
    revision=subprocess.run(["git","-C",str(repo),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
    if revision!=REVISION:raise ValueError("upstream source revision does not match the pinned experiment")
    manifest=json.loads(args.manifest.read_text())
    if manifest.get("local_inference_authorized") is not True or not manifest.get("data_license") or manifest.get("model_revision")!=MODEL_REVISION:
        raise ValueError("explicit local image rights, data license and model revision are required")
    views=manifest.get("views",{})
    if not isinstance(views,dict) or len(views)<2 or not set(views)<= {"front","back","left","right"}:
        raise ValueError("at least two explicitly named, authorized views are required")
    from PIL import Image
    images={}
    root=args.image_root.resolve(strict=True)
    for direction,item in views.items():
        file=(root/item["file"]).resolve(strict=True)
        if not file.is_relative_to(root) or sha(file)!=item["sha256"]:raise ValueError("image path or SHA-256 mismatch")
        image=Image.open(file)
        if image.mode!="RGBA":raise ValueError("prepare RGBA object crops with transparent backgrounds first")
        images[direction]=image.copy()
    os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
    import torch
    if not torch.cuda.is_available():raise RuntimeError("NOT_TESTED: CUDA GPU required; no inference performed")
    if args.output_dir.exists():raise FileExistsError("choose a new output directory")
    sys.path.insert(0,str(repo))
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    model=Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(str(weights),subfolder="hunyuan3d-dit-v2-mv",variant="fp16")
    torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();start=time.perf_counter()
    mesh=model(image=images,num_inference_steps=50,octree_resolution=380,num_chunks=20000,
               generator=torch.manual_seed(12345),output_type="trimesh")[0]
    torch.cuda.synchronize();elapsed=time.perf_counter()-start
    args.output_dir.mkdir(parents=True,exist_ok=False);mesh.export(str(args.output_dir/"candidate.glb"))
    report={"status":"UNVERIFIED_INFERRED_MESH", "source_revision":revision,"model_revision":MODEL_REVISION,
            "checkpoint_sha256":args.checkpoint_sha256,"input_sha256":{k:v["sha256"] for k,v in views.items()},
            "gpu":torch.cuda.get_device_name(),"seconds":elapsed,"peak_gpu_bytes":torch.cuda.max_memory_allocated(),
            "output_sha256":sha(args.output_dir/"candidate.glb"),"unit":"UNKNOWN",
            "warning":"not a measured surface, CAD solid or semantic IFC; validate on independent measurements"}
    (args.output_dir/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2));return 0


if __name__=="__main__":raise SystemExit(main())
