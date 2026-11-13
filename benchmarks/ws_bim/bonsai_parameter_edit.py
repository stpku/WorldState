"""Exercise Bonsai wall-height or window-position operators on an existing IFC.

blender -b --python-exit-code 1 --python SCRIPT -- INPUT MODE GUID VALUE OUTPUT REPORT
MODE height expects an IfcWall GUID. MODE window_offset expects an opening GUID
with a window filling and requests its offset along the host wall in metres.
MODE window_recalculate_fill reproduces a known failed edit that drops the
opening representation on this source IFC; its output must not be delivered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    source, mode, guid, text, output, report = sys.argv[sys.argv.index("--")+1:]
    source,output,report=Path(source),Path(output),Path(report)
    value=float(text)
    if not source.is_file() or output.exists() or report.exists() or value<0 or mode not in {"height","window_offset","window_recalculate_fill"}:
        raise ValueError("invalid arguments or existing output")
    if "bl_ext.ws_bonsai.bonsai" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="bl_ext.ws_bonsai.bonsai")
    import bonsai.tool as tool
    import ifcopenshell.util.placement
    import numpy as np
    from mathutils import Vector
    if bpy.ops.bim.load_project(filepath=str(source.resolve()))!={"FINISHED"}:
        raise RuntimeError("Bonsai project import failed")
    f=tool.Ifc.get();entity=f.by_guid(guid)
    if entity is None:raise ValueError("GUID not found")
    if mode=="height":
        if not entity.is_a("IfcWall") or value<=0:raise ValueError("height requires a wall and positive value")
        obj=tool.Ifc.get_object(entity)
        bpy.ops.object.select_all(action="DESELECT");obj.select_set(True);bpy.context.view_layer.objects.active=obj
        before=list(map(float,obj.dimensions))
        if bpy.ops.bim.change_extrusion_depth(depth=value)!={"FINISHED"}:raise RuntimeError("Bonsai height operator failed")
        operation="native change_extrusion_depth"
    else:
        if not entity.is_a("IfcOpeningElement") or len(entity.HasFillings)!=1 or len(entity.VoidsElements)!=1:
            raise ValueError("offset requires one hosted, filled opening")
        filling=entity.HasFillings[0].RelatedBuildingElement
        if not filling.is_a("IfcWindow"):raise ValueError("opening must contain a window")
        host=entity.VoidsElements[0].RelatingBuildingElement;obj=tool.Ifc.get_object(filling)
        host_obj=tool.Ifc.get_object(host)
        host_matrix=ifcopenshell.util.placement.get_local_placement(host.ObjectPlacement)
        opening_matrix=ifcopenshell.util.placement.get_local_placement(entity.ObjectPlacement)
        before=float((np.linalg.inv(host_matrix)@opening_matrix)[0,3]);delta=value-before
        displacement=Vector((host_matrix[:3,0]*delta).tolist())
        if mode=="window_recalculate_fill":
            bpy.ops.object.select_all(action="DESELECT");obj.select_set(True);bpy.context.view_layer.objects.active=obj
            obj.matrix_world.translation += displacement;bpy.context.view_layer.update()
            if bpy.ops.bim.recalculate_fill()!={"FINISHED"}:raise RuntimeError("Bonsai filling operator failed")
            operation="move window and native recalculate_fill (known failed readback)"
        else:
            bpy.ops.object.select_all(action="DESELECT");host_obj.select_set(True);bpy.context.view_layer.objects.active=host_obj
            if bpy.ops.bim.show_openings()!={"FINISHED"}:raise RuntimeError("Bonsai could not show opening")
            opening_obj=tool.Ifc.get_object(entity)
            if opening_obj is None:raise RuntimeError("Bonsai did not expose opening object")
            obj.matrix_world.translation += displacement;opening_obj.matrix_world.translation += displacement
            bpy.context.view_layer.update()
            bpy.ops.object.select_all(action="DESELECT");obj.select_set(True);bpy.context.view_layer.objects.active=obj
            if bpy.ops.bim.edit_object_placement()!={"FINISHED"}:raise RuntimeError("Bonsai window placement failed")
            bpy.ops.object.select_all(action="DESELECT");opening_obj.select_set(True);bpy.context.view_layer.objects.active=opening_obj
            if bpy.ops.bim.edit_openings()!={"FINISHED"}:raise RuntimeError("Bonsai opening edit failed")
            operation="move window and opening with native Bonsai placement and opening tools"
    bpy.context.view_layer.update()
    if bpy.ops.bim.save_project(filepath=str(output.resolve()),should_save_as=True,skip_recent=True)!={"FINISHED"}:
        raise RuntimeError("Bonsai save failed")
    result={"application":"Blender "+bpy.app.version_string+" + Bonsai 0.9.0.post1", "operation":operation,
            "guid_before":guid,"guid_after":f.by_guid(guid).GlobalId,"before":before,"requested_value_m":value,
            "warning":"Independent model geometry and supported readback must still be checked."}
    report.write_text(json.dumps(result,indent=2)+"\n")
    print("WORLDSTATE_BONSAI_PARAMETER "+json.dumps(result))


if __name__=="__main__":main()
