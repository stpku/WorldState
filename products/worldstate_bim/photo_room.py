"""Build a partial room candidate from photo annotations and a measured sketch.

Two explicit paths are supported: a proportional top-down sketch, or pinhole
backprojection of manually marked photo corners onto an assumed level floor.
Both require a user-supplied metric reference, height and wall-thickness
assumption. Neither treats perspective-image pixel distance as a metric length.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .room_ir import SCHEMA, geometry_issues, quantity, validate_room
from .photo_scale import require_current_scale

ANNOTATION_KINDS = {"corner", "wall_boundary", "floor_line", "ceiling_line", "door", "window", "scale"}


def _number(value: Any, label: str, *, low: float = 0, high: float = 1000, zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}必须是有限数值")
    value = float(value)
    if (value < low if zero else value <= low) or value > high:
        raise ValueError(f"{label}超出允许范围")
    return value


def _point(value: Any, width: float, height: float) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("标注点格式无效")
    return (_number(value[0], "点横坐标", high=width, zero=True),
            _number(value[1], "点纵坐标", high=height, zero=True))


def _camera_floor_points(layout: dict, annotations: list, photos: dict) -> tuple[list[tuple[float, float]], dict]:
    """Intersect pinhole rays with a level floor in arbitrary camera-height units."""
    photo = photos.get(layout.get("photo_id"))
    camera = layout.get("camera")
    if photo is None or not isinstance(camera, dict) or layout.get("confirmed_camera_assumptions") is not True:
        raise ValueError("请选择相机照片并确认平地、相机姿态和零横滚假设")
    fx = _number(camera.get("fx"), "相机 fx", high=100000)
    fy = _number(camera.get("fy"), "相机 fy", high=100000)
    cx = _number(camera.get("cx"), "相机 cx", high=photo["width"], zero=True)
    cy = _number(camera.get("cy"), "相机 cy", high=photo["height"], zero=True)
    pitch = camera.get("pitch_down_deg")
    if isinstance(pitch, bool) or not isinstance(pitch, (int, float)) or not math.isfinite(pitch) or not -85 <= pitch <= 85:
        raise ValueError("相机向下俯角须是 -85 至 85 度的有限数值")
    description=camera.get("description")
    if not isinstance(description,str) or not description.strip() or len(description)>500:
        raise ValueError("请说明相机内参和俯角的来源及是否为假设")
    corners={}
    for ann in annotations:
        if not isinstance(ann,dict) or ann.get("kind")!="corner" or ann.get("photo_id")!=photo["id"]:
            continue
        match=re.fullmatch(r"node-([1-9][0-9]*)",str(ann.get("object_id","")))
        if not match:
            continue
        index=int(match.group(1))
        if index in corners:raise ValueError("同一张照片中角点编号不能重复")
        if not isinstance(ann.get("points"),list) or len(ann["points"])!=1:
            raise ValueError("地面角点必须有一个像素位置")
        corners[index]=(_point(ann["points"][0],photo["width"]-1,photo["height"]-1),ann.get("id"))
    if not 2<=len(corners)<=40 or sorted(corners)!=list(range(1,len(corners)+1)):
        raise ValueError("请在同一张照片依次标注至少 node-1、node-2 两个地面墙角")
    angle=math.radians(float(pitch));s,c=math.sin(angle),math.cos(angle)
    points=[];refs=[]
    for index in sorted(corners):
        (u,v),ref=corners[index]
        x,y=(u-cx)/fx,(v-cy)/fy
        denominator=s+y*c
        if denominator<=0.0001:
            raise ValueError(f"node-{index} 位于假设的地平线以上，无法与地面求交；请检查俯角或角点")
        t=1/denominator
        points.append((x*t,(c-y*s)*t));refs.append(ref)
    return points,{"photo_id":photo["id"],"corner_refs":refs,"fx":fx,"fy":fy,"cx":cx,"cy":cy,
                   "pitch_down_deg":float(pitch),"description":description.strip(),"roll_deg":0,
                   "assumptions":"level floor, pinhole camera, camera roll zero; lens distortion not compensated; no multiview triangulation"}


def build_photo_room(project: dict[str, Any], uploads: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert explicit photo annotations, sketch and scale to room IR 0.3."""
    ident = project.get("id")
    if not isinstance(ident, str) or not re.fullmatch(r"photo-room-[0-9a-f]{32}", ident):
        raise ValueError("房间项目标识无效")
    operator=project.get("operator_kind","user")
    if operator not in {"user","automation"}:raise ValueError("不支持的标注来源")
    confirmation="human_confirmed" if operator=="user" else "simulated"
    photos = {item["id"]: item for item in uploads}
    if not photos:
        raise ValueError("请先上传至少一张房间照片")
    layout = project.get("layout") or {}
    annotations = project.get("annotations", [])
    if not isinstance(annotations, list) or len(annotations) > 1000:
        raise ValueError("照片标注数量无效")
    mode=layout.get("mode","manual_schematic")
    camera_evidence=None
    if mode=="manual_schematic":
        if layout.get("confirmed_schematic") is not True:
            raise ValueError("请确认俯视草图是人工估计，非照片自动恢复")
        raw_points = layout.get("points")
        if not isinstance(raw_points, list) or not 2 <= len(raw_points) <= 40:
            raise ValueError("俯视草图至少需要两个墙角，最多 40 个")
        points = [_point(point, 800, 500) for point in raw_points]
    elif mode=="photo_floor":
        points,camera_evidence=_camera_floor_points(layout,annotations,photos)
        raw_points=[list(p) for p in points]
    else:
        raise ValueError("不支持的几何求解路径")
    if len(set(points)) != len(points):
        raise ValueError("草图墙角不能重复；关闭房间请使用闭合选项")
    closed = layout.get("closed") is True
    if closed and len(points) < 3:
        raise ValueError("闭合草图至少需要三个墙角")
    edges = [(i, i + 1) for i in range(len(points) - 1)]
    if closed:
        edges.append((len(points) - 1, 0))
    if any(math.dist(points[a], points[b]) < (3 if mode=="manual_schematic" else 1e-5) for a, b in edges):
        raise ValueError("草图墙体过短，请重新标注")
    reference = project.get("reference") or {}
    wall_index = reference.get("wall_index")
    if isinstance(wall_index, bool) or not isinstance(wall_index, int) or not 1 <= wall_index <= len(edges):
        raise ValueError("请选择尺度参照对应的草图墙段")
    anchor_m = _number(reference.get("length_m"), "尺度参照长度", high=100)
    basis = reference.get("basis")
    if basis not in {"independent_user_declared", "same_sensor", "assumed"}:
        raise ValueError("请说明尺度参照是独立测量、同传感器还是假设")
    source = reference.get("description")
    if not isinstance(source, str) or not source.strip() or len(source) > 500:
        raise ValueError("请填写尺度参照的来源")
    height = _number(reference.get("height_m"), "墙高", high=100)
    height_basis = reference.get("height_basis")
    if height_basis not in {"user_measurement", "assumed"}:
        raise ValueError("请说明墙高是用户测量还是假设")
    thickness = _number(reference.get("thickness_m"), "假设墙厚", high=5)
    aa, bb = edges[wall_index - 1]
    scale = anchor_m / math.dist(points[aa], points[bb])
    scale_binding = require_current_scale(project, uploads)

    by_wall: dict[str, list[dict[str, Any]]] = {}
    opening_groups: dict[str, list[dict[str, Any]]] = {}
    evidence: list[dict[str, Any]] = []
    used_photos: set[str] = set()
    for ann in annotations:
        if not isinstance(ann, dict) or not re.fullmatch(r"ann-[0-9a-f]{32}", str(ann.get("id", ""))):
            raise ValueError("照片标注标识无效")
        photo = photos.get(ann.get("photo_id")); kind = ann.get("kind"); wall_id = ann.get("wall_id")
        if photo is None or kind not in ANNOTATION_KINDS:
            raise ValueError("标注必须关联已上传照片和支持的类型")
        if not isinstance(wall_id, str) or not re.fullmatch(r"wall-[1-9][0-9]*", wall_id):
            raise ValueError("每条标注都需关联一个草图墙段")
        index = int(wall_id.split("-")[1])
        if index > len(edges):
            raise ValueError(f"标注引用了不存在的墙段 {wall_id}")
        coords = ann.get("points")
        expected = 1 if kind == "corner" else 2
        if not isinstance(coords, list) or len(coords) != expected:
            raise ValueError("照片标注的点数无效")
        for point in coords:
            _point(point, photo["width"] - 1, photo["height"] - 1)
        if len(coords) == 2 and math.dist(coords[0], coords[1]) < 2:
            raise ValueError("照片标注的两个点过近")
        used_photos.add(photo["id"])
        by_wall.setdefault(wall_id, []).append(ann)
        if ann.get("operator_kind",operator)!=operator:raise ValueError("标注来源与项目不一致")
        annotation_evidence={"id": ann["id"], "kind": "manual_photo_annotation" if operator=="user" else "scripted_photo_annotation", "photo_ref": photo["id"],
                         "annotation_type": kind, "wall_id": wall_id, "points_px": coords,
                         "object_id": ann.get("object_id"), "operator": operator,
                         "created_at": ann.get("created_at"), "elapsed_ms": ann.get("elapsed_ms"),
                         "status": "user_supplied_unverified" if operator=="user" else "scripted_test"}
        if ann.get("origin")=="vision_candidate":
            run=next((r for r in project.get("vision_runs",[]) if r.get("id")==ann.get("vision_run_id")),None)
            candidate=next((c for c in (run or {}).get("candidates",[]) if c.get("id")==ann.get("vision_candidate_id")),None)
            if not run or not candidate or run.get("image_sha256")!=photo["sha256"] or run.get("photo_id")!=photo["id"] or candidate.get("annotation_id")!=ann["id"] or candidate.get("status")!="accepted" or run.get("model_sha256")!=ann.get("vision_model_sha256"):
                raise ValueError("视觉候选来源或照片哈希不匹配")
            expected=candidate.get("points_px")
            if candidate.get("kind") in {"door_region","window_region"}:
                x1,y1,x2,y2=candidate["bbox_px"];expected=[[x1,y1],[x2,y2]]
            if coords!=expected:raise ValueError("视觉候选被修改；请将修改记录为人工标注")
            annotation_evidence.update(kind="vision_candidate_accepted",vision_run_id=run["id"],
                vision_candidate_id=candidate["id"],vision_model_sha256=run["model_sha256"],
                vision_provider=run["provider"],overlay_sha256=run["overlay_sha256"],
                status="ai_proposed_human_accepted_unverified" if operator=="user" else "ai_proposed_script_accepted")
        evidence.append(annotation_evidence)
        if kind in {"door", "window"}:
            object_id = ann.get("object_id")
            if not isinstance(object_id, str) or not re.fullmatch(r"(?:door|window)-[a-zA-Z0-9_-]{1,40}", object_id) or not object_id.startswith(kind + "-"):
                raise ValueError("门窗需要对应的稳定对象名，例如 window-1")
            opening_groups.setdefault(object_id, []).append(ann)
    for i in range(1, len(edges) + 1):
        if not any(a["kind"] == "wall_boundary" for a in by_wall.get(f"wall-{i}", [])):
            raise ValueError(f"请在照片中为 wall-{i} 标注可见墙边界；不要补造不可见墙")
    for photo_id in sorted(used_photos):
        p = photos[photo_id]
        evidence.append({"id": p["id"], "kind": "image", "sha256": p["sha256"], "width_px": p["width"],
                         "height_px": p["height"], "captured_at": p.get("captured_at", "UNKNOWN"),
                         "authorization": "user_supplied_unverified", "quality": p.get("quality", {})})
    layout_evidence={"id": "layout-1", "kind": "manual_schematic_floor_layout" if mode=="manual_schematic" else "pinhole_floor_backprojection",
        "points": raw_points, "closed": closed,
        "note": "user-drawn proportional sketch, not geometry recovered from image pixels" if mode=="manual_schematic" else
                "manual photo corner rays intersect an assumed level floor; camera calibration and pose require verification"}
    if camera_evidence:
        layout_evidence["photo_ref"]=camera_evidence["photo_id"]
        layout_evidence["corner_refs"]=camera_evidence["corner_refs"]
        evidence.append({"id":"camera-1","kind":"user_camera_calibration",**camera_evidence,"status":"user_supplied_unverified"})
    evidence.extend([
        layout_evidence,
        {"id": "scale-1", "kind": "user_scale_reference", "basis": basis, "description": source.strip(),
         "wall_id": f"wall-{wall_index}", "relative_endpoints": [list(points[aa]), list(points[bb])],
         "distance_m": anchor_m, "relative_distance":math.dist(points[aa],points[bb]),
         "metres_per_relative_unit": scale, "binding": scale_binding, "verification": "NOT_INDEPENDENTLY_VERIFIED"},
        {"id": "height-1", "kind": "user_height", "basis": height_basis, "value_m": height,
         "verification": "NOT_INDEPENDENTLY_VERIFIED"},
        {"id": "thickness-1", "kind": "user_assumption", "value_m": thickness,
         "description": "unobserved wall thickness assumed for IFC geometry"},
    ])
    nodes = []
    for i, (x, y) in enumerate(points):
        linked = [annotation["id"] for k, edge in enumerate(edges, 1) if i in edge
                  for annotation in by_wall.get(f"wall-{k}", [])]
        refs = list(dict.fromkeys(["layout-1", "scale-1"] + (["camera-1"] if camera_evidence else []) + linked))
        nodes.append({"id": f"node-{i+1}", "x": (x - points[0][0]) * scale,
                      "y": (y - points[0][1]) * scale * (-1 if mode=="manual_schematic" else 1), "status": "inferred", "evidence_refs": refs})
    walls = []
    for i, (a, b) in enumerate(edges, 1):
        wall_id = f"wall-{i}"; refs = [ann["id"] for ann in by_wall[wall_id]]
        walls.append({"id": wall_id, "ifc_type": "IfcWall", "start": f"node-{a+1}", "end": f"node-{b+1}",
                      "storey": "storey-1", "classification": {"status": confirmation, "evidence_refs": refs},
                      "parameters": {
                          "height": quantity(height, confirmation if height_basis == "user_measurement" else "assumed", ["height-1"], "Supplied by operator; not independently verified"),
                          "thickness": quantity(thickness, "assumed", ["thickness-1"], "Not observed"),
                          "base_elevation": quantity(0, "assumed", ["layout-1"], "Local reference elevation")},
                      "unknown": ["actual wall thickness", "occluded wall extent and openings",
                          "wall identity and " + ("sketch proportions" if mode=="manual_schematic" else "camera calibration and floor assumptions") + " require independent verification"]})
    elements: list[dict[str, Any]] = walls[:]
    for object_id, group in sorted(opening_groups.items()):
        first = group[0]; dimensions = first.get("dimensions")
        if not isinstance(dimensions, dict) or any(a.get("wall_id") != first["wall_id"] or a.get("dimensions") != dimensions for a in group):
            raise ValueError(f"{object_id} 的多张照片标注需要相同宿主墙和尺寸")
        dim_basis = dimensions.get("basis")
        if dim_basis not in {"user_measurement", "assumed"}:
            raise ValueError(f"{object_id} 需要说明门窗尺寸是测量还是假设")
        vals = {name: _number(dimensions.get(name), f"{object_id} {name}", high=100,
                              zero=name in {"offset", "sill"}) for name in ("offset", "width", "height", "sill")}
        panel = _number(dimensions.get("panel_thickness"), f"{object_id} 板厚", high=2)
        refs = [a["id"] for a in group]
        evidence.append({"id": "dimensions-" + object_id, "kind": "user_opening_dimensions", "basis": dim_basis,
                         "values_m": vals, "panel_thickness_m": panel, "verification": "NOT_INDEPENDENTLY_VERIFIED"})
        param_refs = refs + ["dimensions-" + object_id]
        status = confirmation if dim_basis == "user_measurement" else "assumed"
        opening_id = "opening-" + object_id
        elements.append({"id": opening_id, "ifc_type": "IfcOpeningElement", "host": first["wall_id"], "fill": object_id,
                         "storey": "storey-1", "classification": {"status": confirmation, "evidence_refs": refs},
                         "parameters": {k: quantity(v, status, param_refs, "User-supplied dimension; verify on site") for k, v in vals.items()},
                         "unknown": ["position and dimensions require independent verification"]})
        elements.append({"id": object_id, "ifc_type": "IfcDoor" if first["kind"] == "door" else "IfcWindow",
                         "opening": opening_id, "storey": "storey-1",
                         "classification": {"status": confirmation, "evidence_refs": refs},
                         "parameters": {"panel_thickness": quantity(panel, "assumed", param_refs, "Assumed panel thickness")},
                         "unknown": ["panel thickness and material"]})
    if closed:
        elements.append({"id": "space-1", "ifc_type": "IfcSpace", "storey": "storey-1",
                         "classification": {"status": confirmation, "evidence_refs": ["layout-1"]},
                         "boundary_walls": [w["id"] for w in walls], "boundary_status": "closed_confirmed", "parameters": {},
                         "unknown": ["boundary is a user-confirmed sketch, not independently verified"]})
    model = {"schema": SCHEMA, "project_id": ident, "mode": "assisted", "revision": 1,
             "coordinate_system": {"name": "user_schematic_local" if mode=="manual_schematic" else "camera_floor_local", "unit": "m", "georeferencing": "UNKNOWN"},
             "evidence": evidence, "nodes": nodes,
             "storeys": [{"id": "storey-1", "elevation": quantity(0, "assumed", ["layout-1"], "Local datum")}],
             "elements": elements, "constraints": [],
             "scale": {"status": "applied", "anchor_ref": "scale-1", "metres_per_relative_unit": scale,
                       "independence": basis, "method":mode},
             "validation": {"status": "UNVERIFIED_DRAFT", "scope": "user_closed_unverified" if closed else "PARTIAL_OPEN",
                            "warning": ("Manual sketch proportions and user measurements are not recovered from the photos" if mode=="manual_schematic" else
                            "Photo corner backprojection assumes a level floor, known camera intrinsics, pitch, zero roll and no lens distortion") +
                            "; the anchor must still identify the same physical endpoints after annotation edits; independent verification is required"}}
    validate_room(model)
    issues = geometry_issues(model)
    if issues:
        raise ValueError("几何有冲突：" + ", ".join(f"{x['id']}:{x['code']}" for x in issues))
    return model
