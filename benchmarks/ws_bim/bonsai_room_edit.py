"""Open one real multi-object IFC in Bonsai, change one wall length and save.

blender -b --python-exit-code 1 --python SCRIPT -- INPUT GUID LENGTH OUTPUT REPORT
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import bpy


def main():
    source, guid, length, output, report = sys.argv[sys.argv.index("--")+1:]
    source, output, report = Path(source), Path(output), Path(report)
    if not source.is_file() or output.exists() or report.exists() or float(length)<=0:
        raise ValueError("invalid input or destination exists")
    if "bl_ext.ws_bonsai.bonsai" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="bl_ext.ws_bonsai.bonsai")
    import bonsai.tool as tool
    if bpy.ops.bim.load_project(filepath=str(source.resolve())) != {"FINISHED"}:
        raise RuntimeError("Bonsai import failed")
    f=tool.Ifc.get();wall=f.by_guid(guid)
    if not wall or not wall.is_a("IfcWall"):
        raise ValueError("selected GUID is not a wall")
    obj=tool.Ifc.get_object(wall)
    if obj is None:
        raise ValueError("selected wall has no Blender object")
    bpy.ops.object.select_all(action="DESELECT");obj.select_set(True);bpy.context.view_layer.objects.active=obj
    before=[float(x) for x in obj.dimensions]
    if bpy.ops.bim.change_layer_length(length=float(length)) != {"FINISHED"}:
        raise RuntimeError("Bonsai wall edit failed")
    bpy.context.view_layer.update()
    after=[float(x) for x in obj.dimensions]
    if bpy.ops.bim.save_project(filepath=str(output.resolve()),should_save_as=True,skip_recent=True) != {"FINISHED"}:
        raise RuntimeError("Bonsai save failed")
    result={"application":"Blender "+bpy.app.version_string+" + Bonsai 0.9.0.post1",
            "operation":"native wall length edit", "wall_guid_before":guid,
            "wall_guid_after":f.by_guid(guid).GlobalId,"requested_length_m":float(length),
            "bounds_before_m":before,"bounds_after_m":after,
            "walls_after":len(f.by_type("IfcWall")),"windows_after":len(f.by_type("IfcWindow"))}
    report.write_text(json.dumps(result,indent=2)+"\n")
    print("WORLDSTATE_ROOM_EDIT "+json.dumps(result))


if __name__=="__main__":
    main()
