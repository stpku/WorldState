"""Compile a bounded wall proposal to editable IFC4.

Optional runtime dependency: pip install ifcopenshell numpy

This is a first **wall-only** technical slice: it does not infer geometry from
pixels, generate openings, validate construction compliance, or certify BIM.
"""

from __future__ import annotations

import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .contract import BuildingProposal, release_check


def _add_editable_wall_axis(model, wall, axis_context, length_m: float, thickness_m: float) -> None:
    """Give a wall an axis and an unspecified material layer for BIM editing.

    The geometric thickness comes from the proposal; the material is explicitly
    unspecified and must not be interpreted as an observed construction type.
    """
    import ifcopenshell.api.geometry
    import ifcopenshell.api.material

    axis = ifcopenshell.api.geometry.add_axis_representation(
        model, context=axis_context, axis=((0., 0.), (float(length_m), 0.))
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=axis)
    material = ifcopenshell.api.material.add_material(model, name="Unspecified material")
    layer_set = ifcopenshell.api.material.add_material_set(
        model, name="Geometric thickness; material unspecified", set_type="IfcMaterialLayerSet"
    )
    layer = ifcopenshell.api.material.add_layer(model, layer_set=layer_set, material=material)
    ifcopenshell.api.material.edit_layer(model, layer=layer, attributes={"LayerThickness": float(thickness_m)})
    ifcopenshell.api.material.assign_material(
        model, products=[wall], type="IfcMaterialLayerSetUsage", material=layer_set
    )


def export_ifc(
    proposal: BuildingProposal,
    output_path: str | Path,
    *,
    allow_approximate: bool = False,
) -> Path:
    """Export an IFC4 file with parametric IfcWall elements and evidence tags.

    The caller must validate input photographs and obtain a scene proposal
    from DSH or a manual reviewer *before* calling this compiler.
    """
    release_check(proposal, allow_approximate=allow_approximate)
    try:
        import ifcopenshell  # noqa: F401  # optional for this product, not Core
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.context
        import ifcopenshell.api.geometry
        import ifcopenshell.guid
        import ifcopenshell.api.project
        import ifcopenshell.api.pset
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.api.unit
    except ImportError as exc:
        raise RuntimeError(
            "IFC export requires optional packages: pip install ifcopenshell numpy"
        ) from exc

    def stable_guid(object_id: str) -> str:
        """Preserve IFC object identity across model revisions of a project."""
        identity = uuid5(NAMESPACE_URL, f"worldstate-bim:{proposal.project_id}:{object_id}")
        return ifcopenshell.guid.compress(identity.hex)

    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(
        model, ifc_class="IfcProject", name=proposal.project_name
    )
    project.GlobalId = stable_guid("project")

    length = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.unit.add_si_unit(model, unit_type="AREAUNIT")
    volume = ifcopenshell.api.unit.add_si_unit(model, unit_type="VOLUMEUNIT")
    ifcopenshell.api.unit.assign_unit(model, units=[length, area, volume])
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )
    plan = ifcopenshell.api.context.add_context(model, context_type="Plan")
    axis = ifcopenshell.api.context.add_context(
        model, context_type="Plan", context_identifier="Axis", target_view="GRAPH_VIEW", parent=plan
    )
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(
        model, ifc_class="IfcBuilding", name=proposal.project_name
    )
    storey = ifcopenshell.api.root.create_entity(
        model, ifc_class="IfcBuildingStorey", name="Ground level"
    )
    for object_id, spatial_object in (("site", site), ("building", building), ("storey-ground", storey)):
        spatial_object.GlobalId = stable_guid(object_id)
    for parent, child in ((project, site), (site, building), (building, storey)):
        ifcopenshell.api.aggregate.assign_object(
            model, products=[child], relating_object=parent
        )

    for element in proposal.walls:
        wall = ifcopenshell.api.root.create_entity(
            model, ifc_class="IfcWall", name=element.element_id
        )
        wall.GlobalId = stable_guid(f"wall:{element.element_id}")
        representation = ifcopenshell.api.geometry.create_2pt_wall(
            model,
            element=wall,
            context=body,
            p1=(element.start_m[0], element.start_m[1]),
            p2=(element.end_m[0], element.end_m[1]),
            elevation=element.start_m[2],
            height=element.height_m,
            thickness=element.thickness_m,
            is_si=True,
        )
        ifcopenshell.api.geometry.assign_representation(
            model, product=wall, representation=representation
        )
        _add_editable_wall_axis(model, wall, axis, math.dist(element.start_m[:2], element.end_m[:2]), element.thickness_m)
        ifcopenshell.api.spatial.assign_container(
            model, products=[wall], relating_structure=storey
        )
        pset = ifcopenshell.api.pset.add_pset(
            model, product=wall, name="Pset_WorldStateEvidence"
        )
        ifcopenshell.api.pset.edit_pset(
            model,
            pset=pset,
            properties={
                "EvidenceRefs": ",".join(element.evidence_refs),
                "GeometryBasis": element.basis,
                "ReconstructionStatus": "UNVERIFIED_DRAFT",
                "SourceProjectId": proposal.project_id,
                "MetricScaleAnchored": proposal.has_metric_anchor,
            },
        )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(destination))
    return destination
