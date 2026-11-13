"""Exercise the XYZ-to-semantic-IFC boundary without external data downloads."""
from __future__ import annotations

import copy
import math

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")
import ifcopenshell
import ifcopenshell.geom

from products.worldstate_bim.parametric_ir import validate_ir
from products.worldstate_bim.scan_to_bim import export_scan_ifc, infer_visible_wall, make_scan_ir


def sample_points():
    rng = np.random.default_rng(81)
    wall = np.column_stack((2 + rng.normal(0, .003, 4500), rng.uniform(-2, 2, 4500), rng.uniform(0, 2.5, 4500)))
    clutter = rng.uniform([-1, -2, 0], [4, 2, 2.5], (900, 3))
    return np.vstack((wall, clutter))


def test_geometry_to_semantic_ifc_and_identity(tmp_path):
    points = sample_points()
    candidate, mask = infer_visible_wall(points)
    assert mask[:4500].sum() > 1000
    assert mask[4500:].sum() < mask[:4500].sum() * .1
    assert math.isclose(candidate["start_m"][0], 2., abs_tol=.05)
    xyz = tmp_path / "xyz.npy"
    np.save(xyz, points)
    model = make_scan_ir(candidate, xyz, project_id="test-scan", source_url="https://example.org/dataset", archive_sha256="a"*64)
    assert model["mode"] == "automatic"
    assert model["elements"][0]["classification"]["status"] == "inferred"
    assert model["elements"][0]["parameters"]["thickness"]["status"] == "assumed"
    first, second = tmp_path / "one.ifc", tmp_path / "two.ifc"
    export_scan_ifc(model, first)
    export_scan_ifc(model, second)
    f1, f2 = ifcopenshell.open(str(first)), ifcopenshell.open(str(second))
    w1, w2 = f1.by_type("IfcWall")[0], f2.by_type("IfcWall")[0]
    assert f1.schema == "IFC4" and w1.GlobalId == w2.GlobalId
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), w1)
    vertices = np.asarray(shape.geometry.verts).reshape(-1, 3)
    assert np.ptp(vertices[:, 0]) == pytest.approx(candidate["length_m"])
    assert np.ptp(vertices[:, 2]) == pytest.approx(candidate["visible_height_m"])
    changed = copy.deepcopy(model)
    changed["elements"][0]["end_m"][0] += .2
    with pytest.raises(ValueError, match="endpoints"):
        export_scan_ifc(changed, tmp_path / "invalid.ifc")


def test_scan_scale_requires_source_and_unknown_dimensions_fail_closed(tmp_path):
    xyz = tmp_path / "xyz.npy"
    points = sample_points()
    np.save(xyz, points)
    candidate, _ = infer_visible_wall(points)
    model = make_scan_ir(candidate, xyz, project_id="test-scan", source_url="https://example.org/dataset", archive_sha256="b"*64)
    bad_scale = copy.deepcopy(model)
    bad_scale["scale"]["metres_per_unit"] = True
    with pytest.raises(ValueError, match="native metric"):
        validate_ir(bad_scale)
    unknown = copy.deepcopy(model)
    unknown["elements"][0]["parameters"]["thickness"].update(value=None, status="unknown")
    with pytest.raises(ValueError, match="unknown"):
        export_scan_ifc(unknown, tmp_path / "unknown.ifc")


def test_checked_in_real_scan_ifc_has_native_wall_and_geometry():
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "examples/bim_real_scan_craslab/scan-wall.ifc"
    model = ifcopenshell.open(str(path))
    walls = model.by_type("IfcWall")
    assert model.schema == "IFC4" and len(walls) == 1
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), walls[0])
    assert len(shape.geometry.verts) >= 24
