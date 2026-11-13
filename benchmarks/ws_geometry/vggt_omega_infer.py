"""GPU-only VGGT-Omega adapter; requires separately authorized model weights.

This package was prepared without executing the model in the CPU-only
environment. Outputs remain research-only under the upstream noncommercial
license. The caller must provide and verify a checkpoint SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from vggt_omega.models import VGGTOmega
from vggt_omega.utils.load_fn import load_and_preprocess_images
from vggt_omega.utils.pose_enc import encoding_to_camera


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, choices=(4, 8, 16, 32), default=16)
    parser.add_argument("--resolution", type=int, default=416)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("NOT_TESTED: NVIDIA CUDA GPU is required for this execution package")
    if sha256(args.checkpoint) != args.checkpoint_sha256:
        raise ValueError("checkpoint SHA-256 mismatch")
    rows = json.loads(args.manifest.read_text())
    if len(rows) != 32:
        raise ValueError("expected the fixed 32-image development manifest")
    chosen = [rows[i] for i in range(0, 32, 32//args.count)]
    files = []
    for row in chosen:
        if Path(row["name"]).name != row["name"]:
            raise ValueError("image names must be simple filenames")
        image = args.images / row["name"]
        if sha256(image) != row["sha256"]:
            raise ValueError(f"image hash mismatch: {row['name']}")
        files.append(str(image))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if (args.output_dir / "candidate.json").exists():
        raise FileExistsError("output already exists")
    model = VGGTOmega().to("cuda").eval()
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    images = load_and_preprocess_images(files, image_resolution=args.resolution).to("cuda")
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode():
        predictions = model(images)
    torch.cuda.synchronize()
    elapsed = time.perf_counter()-start
    extrinsics, intrinsics = encoding_to_camera(predictions["pose_enc"], predictions["images"].shape[-2:])
    np.savez_compressed(args.output_dir / "geometry.npz", depth=predictions["depth"].cpu().numpy(),
                        depth_conf=predictions["depth_conf"].cpu().numpy(),
                        extrinsics=extrinsics.cpu().numpy(), intrinsics=intrinsics.cpu().numpy())
    candidate = {"schema": "worldstate-bim-geometry-candidate/0.1", "provider": "VGGT-Omega",
        "provider_revision": "48b23c8ce72c9a8fcf987f0d7f43d8e4870759f6", "status": "RESEARCH_ONLY_NOT_BIM",
        "input_images": chosen, "checkpoint_sha256": args.checkpoint_sha256,
        "coordinate_frame": "upstream model frame; verify convention before alignment",
        "scale": {"status": "unknown", "unit": "model output"},
        "uncertainty": {"status": "model confidence, not calibrated accuracy"},
        "geometry_file": "geometry.npz", "gpu": torch.cuda.get_device_name(),
        "inference_seconds": elapsed, "peak_gpu_bytes_after_model_load": torch.cuda.max_memory_allocated()}
    (args.output_dir/"candidate.json").write_text(json.dumps(candidate, indent=2, allow_nan=False)+"\n")
    print(json.dumps(candidate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
