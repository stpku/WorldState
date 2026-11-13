"""Generate an explicitly simulated room to exercise doors, windows and edits.

Run from the repository root with the product dependencies installed. The
destination must not exist; no measured or photo-derived values are implied.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from products.worldstate_bim.room_cli import save_version
from products.worldstate_bim.room_ir import SCHEMA, quantity, revise_element


def synthetic_room() -> dict:
    refs = ["synthetic-design"]

    def provenance() -> dict:
        return {"status": "simulated", "evidence_refs": refs.copy()}

    def q(value: float) -> dict:
        return quantity(value, "simulated", refs.copy(), "Synthetic design; not a measurement")

    nodes = [{"id": name, "x": x, "y": y, **provenance()}
             for name, x, y in (("n1", 0, 0), ("n2", 4, 0), ("n3", 4, 3), ("n4", 0, 3))]
    edges = (("n1", "n2"), ("n2", "n3"), ("n3", "n4"), ("n4", "n1"))
    walls = [{"id": f"wall-{i}", "ifc_type": "IfcWall", "start": start, "end": end,
              "storey": "storey-1", "classification": provenance(),
              "parameters": {"height": q(2.8), "thickness": q(0.12), "base_elevation": q(0)}}
             for i, (start, end) in enumerate(edges, 1)]
    opening_door = {"id": "opening-door", "ifc_type": "IfcOpeningElement", "host": "wall-1", "fill": "door-1",
                    "storey": "storey-1", "classification": provenance(),
                    "parameters": {"offset": q(1), "width": q(0.9), "height": q(2.1), "sill": q(0)}}
    opening_window = {"id": "opening-window", "ifc_type": "IfcOpeningElement", "host": "wall-3", "fill": "window-1",
                      "storey": "storey-1", "classification": provenance(),
                      "parameters": {"offset": q(1), "width": q(1), "height": q(1.2), "sill": q(1)}}
    fills = [{"id": name, "ifc_type": kind, "opening": opening, "storey": "storey-1",
              "classification": provenance(), "parameters": {"panel_thickness": q(0.04)}}
             for name, kind, opening in (("door-1", "IfcDoor", "opening-door"),
                                         ("window-1", "IfcWindow", "opening-window"))]
    slab = {"id": "slab-1", "ifc_type": "IfcSlab", "storey": "storey-1", "classification": provenance(),
            "outline": ["n1", "n2", "n3", "n4"], "outline_status": provenance(),
            "parameters": {"elevation": q(-0.15), "thickness": q(0.15)}}
    space = {"id": "room-1", "ifc_type": "IfcSpace", "storey": "storey-1", "classification": provenance(),
             "boundary_walls": [wall["id"] for wall in walls], "boundary_status": "closed_confirmed", "parameters": {}}
    constraints = [{"id": f"right-angle-{i}", "kind": "perpendicular", "a": f"wall-{i}",
                    "b": f"wall-{i % 4 + 1}", **provenance()} for i in range(1, 5)]
    return {"schema": SCHEMA, "project_id": "synthetic-room-round3", "mode": "assisted", "revision": 1,
            "coordinate_system": {"name": "synthetic local coordinates", "unit": "m"},
            "evidence": [{"id": "synthetic-design", "kind": "synthetic_design",
                          "source": "Invented room; not a photograph or real measurement"}],
            "nodes": nodes, "storeys": [{"id": "storey-1", "elevation": q(0)}],
            "elements": walls + [opening_door, opening_window] + fills + [slab, space], "constraints": constraints}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="New directory for original and revised results")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    model = synthetic_room()
    save_version(model, args.output_dir / "original")
    revised, diff = revise_element(model, "wall-1", "length", 5, reason="Synthetic demonstration", operator="user")
    save_version(revised, args.output_dir / "revised", diff=diff)
    print(f"Synthetic original and revised IFC models created in {args.output_dir}")


if __name__ == "__main__":
    main()
