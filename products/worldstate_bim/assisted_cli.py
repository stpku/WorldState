"""Create or revise an evidence-linked, assisted wall-patch IFC draft."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .assisted import create_candidate, import_external_wall_length, revise_length, write_model


def write_cloud(path: Path, points: np.ndarray) -> None:
    """Write the actual observed depth points used for the candidate plane."""
    with path.open("w", encoding="ascii") as stream:
        stream.write(f"ply\nformat ascii 1.0\ncomment metres in color camera frame\nelement vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\nend_header\n")
        np.savetxt(stream, points, fmt="%.7f")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Manually select a real RGB-D wall patch")
    create.add_argument("--image", type=Path, required=True)
    create.add_argument("--depth", type=Path, required=True)
    create.add_argument("--roi", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True)
    create.add_argument("--anchor-pixels", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True)
    create.add_argument("--intrinsics", type=float, nargs=4, metavar=("FX", "FY", "CX", "CY"), required=True)
    create.add_argument("--anchor-m", type=float, required=True)
    create.add_argument("--anchor-description", required=True)
    create.add_argument("--anchor-independence", choices=("independent_user_declared", "same_sensor"), required=True)
    create.add_argument("--thickness-m", type=float, required=True, help="Explicit assumed thickness, not a measurement")
    create.add_argument("--project-id", required=True)
    create.add_argument("--operator", choices=("analyst", "user"), required=True)
    create.add_argument("--vision-onnx", type=Path, help="Optional local relative-depth model for ROI prefiltering")
    create.add_argument("--output-dir", type=Path, required=True)
    revise = sub.add_parser("revise", help="Change one wall dimension and retain its IFC identity")
    revise.add_argument("--model", type=Path, required=True)
    revise.add_argument("--evidence-root", type=Path, required=True)
    revise.add_argument("--wall-id", required=True)
    revise.add_argument("--length-m", type=float, required=True)
    revise.add_argument("--reason", required=True)
    revise.add_argument("--operator", choices=("analyst", "user"), required=True)
    revise.add_argument("--output-dir", type=Path, required=True)
    sync = sub.add_parser("sync-ifc", help="Import a checked external wall-length edit; reject other geometry changes")
    sync.add_argument("--model", type=Path, required=True)
    sync.add_argument("--ifc", type=Path, required=True)
    sync.add_argument("--evidence-root", type=Path, required=True)
    sync.add_argument("--reason", required=True)
    sync.add_argument("--operator", choices=("analyst", "user"), required=True)
    sync.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        prediction, metadata = None, None
        if args.vision_onnx:
            from .vision_provider import infer_relative_depth
            prediction, metadata = infer_relative_depth(args.image, args.vision_onnx)
        model, points = create_candidate(args.image, args.depth, roi=tuple(args.roi),
            anchor_pixels=tuple(args.anchor_pixels), anchor_m=args.anchor_m,
            anchor_description=args.anchor_description, anchor_independence=args.anchor_independence,
            thickness_m=args.thickness_m, project_id=args.project_id, operator=args.operator, intrinsics=tuple(args.intrinsics),
            vision_depth=prediction, vision_metadata=metadata)
        ifc, ir = write_model(model, args.image.parent, args.output_dir)
        write_cloud(args.output_dir / "observed-surface.ply", points)
        print(json.dumps({"status": "PARTIAL_UNVERIFIED_DRAFT", "ifc": str(ifc), "ir": str(ir),
                          "point_cloud": str(args.output_dir / "observed-surface.ply"),
                          "warning": "not a complete room; thickness assumed; scale independence as recorded"}, indent=2))
        return 0
    model = json.loads(args.model.read_text())
    if args.command == "sync-ifc":
        revised, diff = import_external_wall_length(model, args.ifc, reason=args.reason, operator=args.operator)
    else:
        revised, diff = revise_length(model, args.wall_id, args.length_m, args.reason, operator=args.operator)
    ifc, ir = write_model(revised, args.evidence_root, args.output_dir)
    (args.output_dir / "diff.json").write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": "REQUIRES_REVALIDATION", "ifc": str(ifc), "ir": str(ir),
                      "diff": str(args.output_dir / "diff.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
