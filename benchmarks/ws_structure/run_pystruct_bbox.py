"""Run PyStruct3D's bounding-box fitter on a frozen CRASLAB candidate mask.

Requires an isolated environment with the MIT-licensed PyStruct3D package.
This tests a geometry component, not the full BIMStruct3D pipeline, and does
not perform semantic detection or measure independent model accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pystruct3d
from pystruct3d.bbox import BBox


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--source-checkout", type=Path, required=True, help="Editable PyStruct3D checkout")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    revision = subprocess.run(["git", "-C", str(args.source_checkout), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
    if (revision != "fcbe3070deef2d9ed2662abd77fdf0ad35c39f87" or
            not Path(pystruct3d.__file__).resolve().is_relative_to(args.source_checkout.resolve())):
        raise ValueError("installed PyStruct3D must come from the pinned editable checkout")
    xyz, mask = np.load(args.points, allow_pickle=False), np.load(args.mask, allow_pickle=False)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or mask.dtype != bool or mask.shape != (len(xyz),):
        raise ValueError("input must be XYZ points and the corresponding boolean mask")
    selected = xyz[mask]
    if len(selected) < 4 or not np.isfinite(selected).all():
        raise ValueError("at least four finite selected points required")
    started = time.perf_counter()
    box = BBox()
    box.fit_horizontal_aligned(selected)
    elapsed = time.perf_counter() - started
    report = {"method": "PyStruct3D BBox.fit_horizontal_aligned", "package_revision": revision,
              "license": "MIT", "dataset": "CRASLAB CC-BY-4.0", "point_sha256": digest(args.points),
              "mask_sha256": digest(args.mask), "selected_points": len(selected), "fitting_seconds": elapsed,
              "envelope_m": {"length": float(box.length()), "width": float(box.width()), "height": float(box.height())},
              "corners_m": np.asarray(box.corner_points).tolist(),
              "limitations": ["same preselected candidate, not an independent end-to-end method",
                              "fitted point-envelope width is not wall thickness",
                              "semantic labels not loaded", "independent reference geometric error not measured"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
