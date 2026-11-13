"""Blender + Bonsai headless native-wall dimension edit and IFC save.

Run: blender -b --python-exit-code 1 --python SCRIPT -- INPUT OUTPUT REPORT
The IFC should contain a Plan/Axis context and material layer usage. External
edits are not yet synchronized into the WorldState IR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    source, output, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
    if not source.is_file() or output.exists() or report_path.exists():
        raise ValueError("source must exist; output and report must not exist")
    if "bl_ext.ws_bonsai.bonsai" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="bl_ext.ws_bonsai.bonsai")
    import bonsai.tool as tool

    if bpy.ops.bim.load_project(filepath=str(source.resolve())) != {"FINISHED"}:
        raise RuntimeError("Bonsai failed to load IFC")
    file = tool.Ifc.get()
    walls = file.by_type("IfcWall")
    if len(walls) != 1 or len(file.by_type("IfcExtrudedAreaSolid")) != 1:
        raise ValueError("one native extruded wall is required")
    wall = walls[0]
    guid = wall.GlobalId
    obj = tool.Ifc.get_object(wall)
    if not obj or obj.type != "MESH":
        raise ValueError("Bonsai did not construct the wall geometry")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    before = [float(x) for x in obj.dimensions]
    if bpy.ops.bim.change_layer_length(length=0.5) != {"FINISHED"}:
        raise RuntimeError("Bonsai could not update the wall length")
    bpy.context.view_layer.update()
    after = [float(x) for x in obj.dimensions]
    if abs(after[0]-.5) > 1e-5 or len(file.by_type("IfcExtrudedAreaSolid")) != 1:
        raise RuntimeError("wall did not retain the expected parametric body")
    if bpy.ops.bim.save_project(filepath=str(output.resolve()), should_save_as=True, skip_recent=True) != {"FINISHED"}:
        raise RuntimeError("Bonsai failed to save IFC")
    report = {"application": "Blender " + bpy.app.version_string + " + Bonsai 0.9.0.post1",
              "operation": "Bonsai change_layer_length to 0.5 m; save as IFC4",
              "wall_guid_before": guid, "wall_guid_after": file.by_type("IfcWall")[0].GlobalId,
              "blender_bounds_before_m": before, "blender_bounds_after_m": after,
              "extruded_solids_after": len(file.by_type("IfcExtrudedAreaSolid")),
              "warning": "The external edit has not yet been synchronized into the WorldState IR."}
    report_path.write_text(json.dumps(report, indent=2)+"\n")
    print("WORLDSTATE_BONSAI_PARAMETRIC_REPORT "+json.dumps(report))


if __name__ == "__main__":
    main()
