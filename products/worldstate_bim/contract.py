"""Minimal, strict photo-evidence -> parametric BIM proposal contract.

The DSH/multimodal model produces a candidate proposal; this module checks
its shape, units, source references, and geometry before an IFC compiler may
consume it. A proposal is not an observation and is not an engineering approval.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "worldstate-bim-proposal/0.1"
VALID_BASIS = {"inferred", "documented", "measured", "simulated"}


@dataclass(frozen=True)
class EvidenceImage:
    evidence_id: str
    path: str
    sha256: str
    captured_at: str | None
    provenance: str


@dataclass(frozen=True)
class MetricAnchor:
    evidence_id: str
    distance_m: float
    basis: str


@dataclass(frozen=True)
class Wall:
    element_id: str
    start_m: tuple[float, float, float]
    end_m: tuple[float, float, float]
    height_m: float
    thickness_m: float
    basis: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class BuildingProposal:
    project_id: str
    project_name: str
    images: tuple[EvidenceImage, ...]
    anchors: tuple[MetricAnchor, ...]
    walls: tuple[Wall, ...]
    contract: str = SCHEMA_VERSION

    @property
    def has_metric_anchor(self) -> bool:
        """True when at least one declared independent metric reference exists."""
        return any(anchor.basis in {"measured", "documented"} for anchor in self.anchors)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _meters(value: object, name: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite metric number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'numeric'}")
    return result


def _point(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain x/y/z in metres")
    return tuple(_meters(item, f"{name}[{i}]", positive=False) for i, item in enumerate(value))


def _sequence(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def load_proposal(raw: Mapping[str, Any]) -> BuildingProposal:
    """Validate the bounded DSH handoff; refuse unknown evidence references."""
    if raw.get("contract") != SCHEMA_VERSION:
        raise ValueError("unexpected BIM proposal contract version")
    project_id = _text(raw.get("project_id"), "project_id")
    name = _text(raw.get("project_name"), "project_name")

    images: list[EvidenceImage] = []
    evidence_ids: set[str] = set()
    for i, obj in enumerate(_sequence(raw.get("images"), "images")):
        item = _mapping(obj, f"images[{i}]")
        ref = _text(item.get("evidence_id"), "evidence_id")
        if ref in evidence_ids:
            raise ValueError("duplicate image evidence_id")
        evidence_ids.add(ref)
        checksum = _text(item.get("sha256"), "sha256").lower()
        if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("sha256 must be 64 lowercase hexadecimal digits")
        images.append(
            EvidenceImage(
                evidence_id=ref,
                path=_text(item.get("path"), "path"),
                sha256=checksum,
                captured_at=item.get("captured_at"),
                provenance=_text(item.get("provenance"), "provenance"),
            )
        )
    if not images:
        raise ValueError("at least one source photo is required")

    anchors: list[MetricAnchor] = []
    for obj in _sequence(raw.get("anchors"), "anchors"):
        item = _mapping(obj, "anchor")
        ref = _text(item.get("evidence_id"), "anchor.evidence_id")
        if ref not in evidence_ids:
            raise ValueError(f"metric anchor has unknown evidence_ref: {ref}")
        basis = _text(item.get("basis"), "anchor.basis")
        if basis not in VALID_BASIS:
            raise ValueError(f"invalid anchor basis: {basis}")
        anchors.append(
            MetricAnchor(
                evidence_id=ref,
                distance_m=_meters(item.get("distance_m"), "anchor.distance_m"),
                basis=basis,
            )
        )

    walls: list[Wall] = []
    seen_ids: set[str] = set()
    for obj in _sequence(raw.get("walls"), "walls"):
        item = _mapping(obj, "wall")
        elem_id = _text(item.get("element_id"), "element_id")
        if elem_id in seen_ids:
            raise ValueError("duplicate BIM element_id")
        seen_ids.add(elem_id)
        start = _point(item.get("start_m"), "start_m")
        end = _point(item.get("end_m"), "end_m")
        if start == end or math.dist(start, end) < 0.001:
            raise ValueError("wall endpoints must be distinct")
        if abs(start[2] - end[2]) > 1e-6:
            raise ValueError("v0.1 wall baseline must be horizontal")
        basis = _text(item.get("basis"), "wall.basis")
        if basis not in VALID_BASIS:
            raise ValueError(f"invalid wall basis: {basis}")
        refs = tuple(_text(ref, "wall.evidence_ref") for ref in _sequence(item.get("evidence_refs"), "evidence_refs"))
        if not refs:
            raise ValueError("wall must cite at least one image evidence ref")
        if any(ref not in evidence_ids for ref in refs):
            raise ValueError("wall cites unknown photo evidence")
        walls.append(
            Wall(
                element_id=elem_id,
                start_m=start,
                end_m=end,
                height_m=_meters(item.get("height_m"), "height_m"),
                thickness_m=_meters(item.get("thickness_m"), "thickness_m"),
                basis=basis,
                evidence_refs=refs,
            )
        )

    if not walls:
        raise ValueError("at least one parametric wall is required")
    return BuildingProposal(
        project_id=project_id,
        project_name=name,
        images=tuple(images),
        anchors=tuple(anchors),
        walls=tuple(walls),
    )


def read_proposal(path: str | Path) -> BuildingProposal:
    """Read a proposal previously emitted by a multimodal-model adapter."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_proposal(_mapping(raw, "proposal"))


def verify_images(proposal: BuildingProposal, evidence_root: Path) -> None:
    """Verify image bytes exist and match source hashes; reject path traversal."""
    root = evidence_root.resolve(strict=True)
    for image in proposal.images:
        path = (root / image.path).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"unsafe evidence path: {image.path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != image.sha256:
            raise ValueError(f"image hash mismatch: {image.evidence_id}")


def release_check(proposal: BuildingProposal, *, allow_approximate: bool = False) -> None:
    """Require a metric anchor before normal IFC export.

    DSH-suggested dimensions can be exported only when explicitly labeled as
    approximate, never silently upgraded to site-survey measurements.
    """
    if not proposal.has_metric_anchor and not allow_approximate:
        raise ValueError(
            "missing independent metric anchor; supply documented/measured "
            "anchor or explicitly opt in to approximate draft IFC"
        )
