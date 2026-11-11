"""Command-line boundary between photographic evidence, DSH proposal and IFC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract import read_proposal, release_check, verify_images
from .ifc_export import export_ifc


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldState BIM proposal / IFC compiler")
    parser.add_argument("--proposal", required=True, help="DSH-generated or manually reviewed scene JSON")
    parser.add_argument("--evidence-root", help="Root directory containing source photos")
    parser.add_argument("--output-ifc", help="Create an IFC4 BIM file here (requires IfcOpenShell)")
    parser.add_argument("--allow-approximate-scale", action="store_true")
    args = parser.parse_args()

    proposal = read_proposal(args.proposal)
    if args.evidence_root:
        verify_images(proposal, Path(args.evidence_root))
    elif args.output_ifc:
        parser.error("--evidence-root is required to export IFC")
    if args.output_ifc:
        release_check(proposal, allow_approximate=args.allow_approximate_scale)
        path = export_ifc(
            proposal, args.output_ifc, allow_approximate=args.allow_approximate_scale
        )
        print(json.dumps({"status": "draft_ifc_written", "path": str(path)}))
        return 0
    print(json.dumps({
        "contract": proposal.contract,
        "project": proposal.project_id,
        "image_count": len(proposal.images),
        "wall_count": len(proposal.walls),
        "metric_anchor": proposal.has_metric_anchor,
        "status": "validated_proposal_only_not_a_reconstructed_or_verified_bim",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
