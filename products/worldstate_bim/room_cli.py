"""Local multi-component BIM: import, validate, revise and export versioned IR."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cloud2bim_provider import import_cloud2bim
from .room_ifc import export_room
from .room_ir import geometry_issues, revise_element


def save_version(model: dict, output: Path, *, report: dict | None = None,
                 registry: dict | None = None, diff: dict | None = None) -> None:
    """Create a new revision directory without replacing previous results."""
    output.mkdir(parents=True, exist_ok=False)
    export_room(model, output / "model.ifc")
    for name, data in (("model.json", model), ("import-report.json", report), ("identities.json", registry), ("diff.json", diff)):
        if data is not None:
            (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import-cloud2bim")
    ingest.add_argument("--ifc", type=Path, required=True)
    ingest.add_argument("--project-id", required=True)
    ingest.add_argument("--identity-map", type=Path)
    ingest.add_argument("--output-dir", type=Path, required=True)
    revise = sub.add_parser("revise")
    revise.add_argument("--model", type=Path, required=True)
    revise.add_argument("--element-id", required=True)
    revise.add_argument("--attribute", required=True)
    revise.add_argument("--value", type=float, required=True)
    revise.add_argument("--reason", required=True)
    revise.add_argument("--operator", choices=("user", "analyst"), required=True)
    revise.add_argument("--output-dir", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--model", type=Path, required=True)
    sync = sub.add_parser("sync-ifc", help="Import one independently verified external edit")
    sync.add_argument("--model", type=Path, required=True)
    sync.add_argument("--baseline-ifc", type=Path, required=True)
    sync.add_argument("--edited-ifc", type=Path, required=True)
    sync.add_argument("--element-id", required=True)
    sync.add_argument("--attribute", required=True)
    sync.add_argument("--reason", required=True)
    sync.add_argument("--operator", choices=("user", "analyst"), required=True)
    sync.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "import-cloud2bim":
        mapping = json.loads(args.identity_map.read_text()) if args.identity_map else None
        model, mapping, report = import_cloud2bim(args.ifc, project_id=args.project_id, registry=mapping)
        save_version(model, args.output_dir, report=report, registry=mapping)
        print(json.dumps({"status": "UNVERIFIED_DRAFT", "ifc": str(args.output_dir / "model.ifc"),
                          "counts": report["imported_counts"], "quarantined": len(report["quarantined"])}, indent=2))
    elif args.command == "revise":
        model = json.loads(args.model.read_text())
        revised, diff = revise_element(model, args.element_id, args.attribute, args.value, reason=args.reason, operator=args.operator)
        save_version(revised, args.output_dir, diff=diff)
        print(json.dumps({"status": "REQUIRES_REVALIDATION", "ifc": str(args.output_dir / "model.ifc"), "diff": diff}, indent=2))
    elif args.command == "sync-ifc":
        from .room_sync import sync_external_ifc
        model = json.loads(args.model.read_text())
        revised,diff = sync_external_ifc(model, args.baseline_ifc, args.edited_ifc,
            element_id=args.element_id, attribute=args.attribute, reason=args.reason, operator=args.operator)
        save_version(revised, args.output_dir, diff=diff)
        print(json.dumps({"status":"REQUIRES_REVALIDATION", "ifc":str(args.output_dir / "model.ifc"), "diff":diff}, indent=2))
    else:
        issues = geometry_issues(json.loads(args.model.read_text()))
        print(json.dumps({"issues": issues, "status": "CONFLICT" if issues else "UNVERIFIED_DRAFT"}, indent=2))
        return int(bool(issues))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
