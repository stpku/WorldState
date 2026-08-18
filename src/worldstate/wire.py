"""Canonical provider-wire projections for WorldState public semantics.

The wire contract is consumer-neutral. It preserves enough WorldState state,
validity, provenance, uncertainty, and scope information for downstream systems
to make their own task-relative decisions without importing the Python runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from .models import (
    Conflict,
    EntityRef,
    JSONValue,
    Provenance,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    Uncertainty,
    Unknown,
    Validity,
    WorldStateSnapshot,
)

WIRE_CONTRACT_VERSION = "0.1"
STATE_QUERY_RESULT_CONTRACT_ID = "worldstate.state-query-result"
SNAPSHOT_CONTRACT_ID = "worldstate.snapshot"


def _time(value: datetime) -> str:
    """Render UTC datetimes as RFC 3339 while preserving microsecond precision."""
    return value.isoformat().replace("+00:00", "Z")


def _json(value: JSONValue) -> object:
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def entity_ref_payload(entity: EntityRef) -> dict[str, object]:
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "namespace": entity.namespace,
    }


def spatial_scope_payload(scope: SpatialScope | None) -> dict[str, object] | None:
    if scope is None:
        return None
    return {
        "kind": scope.kind,
        "reference": scope.reference,
        "bbox": None if scope.bbox is None else list(scope.bbox),
        "metadata": _json(scope.metadata),
    }


def validity_payload(validity: Validity) -> dict[str, object]:
    return {
        "resolved_at": _time(validity.resolved_at),
        "valid_from": None if validity.valid_from is None else _time(validity.valid_from),
        "valid_until": None if validity.valid_until is None else _time(validity.valid_until),
        "superseded_by": validity.superseded_by,
    }


def provenance_payload(provenance: Provenance) -> dict[str, object]:
    return {
        "evidence_refs": list(provenance.evidence_refs),
        "source_refs": list(provenance.source_refs),
        "parent_assertion_refs": list(provenance.parent_assertion_refs),
        "method": provenance.method,
        "resolver": provenance.resolver,
    }


def uncertainty_payload(uncertainty: Uncertainty | None) -> dict[str, object] | None:
    if uncertainty is None:
        return None
    return {
        "confidence": uncertainty.confidence,
        "method": uncertainty.method,
        "reason": uncertainty.reason,
        "metadata": _json(uncertainty.metadata),
    }


def state_query_result_payload(result: StateQueryResult) -> dict[str, object]:
    """Serialize one already-resolved WorldState outcome without reinterpretation."""
    base: dict[str, object] = {
        "contract": STATE_QUERY_RESULT_CONTRACT_ID,
        "contract_version": WIRE_CONTRACT_VERSION,
    }

    if isinstance(result, StateAssertion):
        base.update(
            {
                "kind": "assertion",
                "assertion_id": result.assertion_id,
                "entity": entity_ref_payload(result.entity),
                "property_key": result.property_key,
                "value": _json(result.value),
                "epistemic_mode": result.epistemic_mode.value,
                "validity": validity_payload(result.validity),
                "provenance": provenance_payload(result.provenance),
                "version": result.version,
                "uncertainty": uncertainty_payload(result.uncertainty),
                "spatial_scope": spatial_scope_payload(result.spatial_scope),
            }
        )
        return base

    if isinstance(result, Unknown):
        base.update(
            {
                "kind": "unknown",
                "unknown_id": result.unknown_id,
                "reason": result.reason.value,
                "as_of": _time(result.as_of),
                "entity": None if result.entity is None else entity_ref_payload(result.entity),
                "property_key": result.property_key,
                "missing": list(result.missing),
                "metadata": _json(result.metadata),
            }
        )
        return base

    if isinstance(result, Conflict):
        base.update(
            {
                "kind": "conflict",
                "conflict_id": result.conflict_id,
                "entity": entity_ref_payload(result.entity),
                "property_key": result.property_key,
                "candidate_refs": list(result.candidate_refs),
                "evidence_refs": list(result.evidence_refs),
                "reason": result.reason,
                "as_of": _time(result.as_of),
                "metadata": _json(result.metadata),
            }
        )
        return base

    raise TypeError(f"unsupported WorldState query result: {type(result).__name__}")


def snapshot_payload(snapshot: WorldStateSnapshot) -> dict[str, object]:
    """Serialize a complete immutable snapshot using canonical result ordering."""
    return {
        "contract": SNAPSHOT_CONTRACT_ID,
        "contract_version": WIRE_CONTRACT_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "as_of": _time(snapshot.as_of),
        "created_at": _time(snapshot.created_at),
        "version": snapshot.version,
        "scope": spatial_scope_payload(snapshot.scope),
        "assertions": [state_query_result_payload(item) for item in snapshot.assertions],
        "unknowns": [state_query_result_payload(item) for item in snapshot.unknowns],
        "conflicts": [state_query_result_payload(item) for item in snapshot.conflicts],
        "source_versions": dict(snapshot.source_versions),
    }
