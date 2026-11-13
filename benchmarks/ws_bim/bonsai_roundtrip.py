"""Run inside Blender with Bonsai enabled: edit a wall mesh and save its IFC.

Example: blender -b --python this_script.py -- INPUT.ifc OUTPUT.ifc REPORT.json
The external edit is deliberately not synchronized into the WorldState IR.
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
        raise RuntimeError("Bonsai did not load the IFC")
    walls = tool.Ifc.get().by_type("IfcWall")
    if len(walls) != 1:
        raise ValueError("this round trip requires one IFC wall")
    wall = walls[0]
    guid = wall.GlobalId
    obj = tool.Ifc.get_object(wall)
    if not obj or obj.type != "MESH":
        raise ValueError("Bonsai failed to construct the wall geometry")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    before = [float(x) for x in obj.dimensions]
    for vertex in obj.data.vertices:
        vertex.co.x *= 1.1
    obj.data.update()
    bpy.context.view_layer.update()
    after = [float(x) for x in obj.dimensions]
    # Bonsai's automatic extrusion inference failed on this triangulated mesh.
    # Explicit tessellation preserves an editable IfcWall but replaces its
    # parametric extruded representation; record this important limitation.
    if bpy.ops.bim.update_representation(obj=obj.name, ifc_representation_class="IfcTessellatedFaceSet") != {"FINISHED"}:
        raise RuntimeError("Bonsai failed to synchronize the wall edit")
    if bpy.ops.bim.save_project(filepath=str(output.resolve()), should_save_as=True, skip_recent=True) != {"FINISHED"}:
        raise RuntimeError("Bonsai failed to save the edited IFC")
    report = {"application": "Blender " + bpy.app.version_string + " + Bonsai 0.9.0.post1",
              "wall_guid_before": guid, "wall_guid_after": tool.Ifc.get().by_type("IfcWall")[0].GlobalId,
              "blender_bounds_before_m": before, "blender_bounds_after_m": after,
              "edit": "scale wall mesh local X by 1.1 and synchronize as tessellated geometry",
              "warning": "Tessellation replaces the parametric extrusion; external edit is not synced into IR. Revalidate."}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print("WORLDSTATE_BONSAI_REPORT " + json.dumps(report))


if __name__ == "__main__":
    main()
