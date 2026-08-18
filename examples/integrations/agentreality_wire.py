from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from worldstate import Conflict, JSONValue, StateAssertion, StateQueryResult, Unknown

# Point-in-time compatibility target observed in AgentReality on 2026-08-18:
# packages/adapter-worldstate/src/index.ts
AGENTREALITY_WORLDSTATE_PROJECTION_REVISION = (
    "sha256:fa45027763922e4cb0498bcccf3bb1825ee7889803b49da518059a38fb7627cb"
)


def project_query_result_for_agentreality(result: StateQueryResult) -> dict[str, Any]:
    """Build the minimal wire projection currently consumed by AgentReality.

    This is an M4 compatibility fixture, not a production adapter. The consuming
    AgentReality project owns its adapter and grounding policy. WorldState owns
    only the already-resolved truth outcome carried by this projection.
    """
    if isinstance(result, StateAssertion):
        validity: dict[str, str] = {
            "resolvedAt": _iso_utc(result.validity.resolved_at),
        }
        if result.validity.valid_from is not None:
            validity["validFrom"] = _iso_utc(result.validity.valid_from)
        if result.validity.valid_until is not None:
            validity["validUntil"] = _iso_utc(result.validity.valid_until)
        if result.validity.superseded_by is not None:
            validity["supersededBy"] = result.validity.superseded_by

        return {
            "kind": "assertion",
            "assertionId": result.assertion_id,
            "entityId": result.entity.entity_id,
            "propertyKey": result.property_key,
            "value": _thaw_json(result.value),
            "epistemicMode": result.epistemic_mode.value,
            "validity": validity,
            "version": result.version,
            "evidenceRefs": [
                _worldstate_ref("evidence", ref)
                for ref in result.provenance.evidence_refs
            ],
            "sourceRefs": [
                _worldstate_ref("source", ref)
                for ref in result.provenance.source_refs
            ],
        }

    if isinstance(result, Unknown):
        projected: dict[str, Any] = {
            "kind": "unknown",
            "unknownId": result.unknown_id,
            "reason": result.reason.value,
            "asOf": _iso_utc(result.as_of),
        }
        if result.missing:
            projected["missing"] = list(result.missing)
        return projected

    if isinstance(result, Conflict):
        return {
            "kind": "conflict",
            "conflictId": result.conflict_id,
            "reason": result.reason,
            "asOf": _iso_utc(result.as_of),
            "candidateRefs": list(result.candidate_refs),
            "evidenceRefs": [
                _worldstate_ref("evidence", ref) for ref in result.evidence_refs
            ],
        }

    raise TypeError(f"unsupported WorldState query result: {type(result).__name__}")


def snapshot_ref(snapshot_id: str) -> str:
    """Return the optional snapshot reference accepted by AgentReality adapter."""
    return _worldstate_ref("snapshot", snapshot_id)


def _worldstate_ref(kind: str, ref: str) -> str:
    if "://" in ref:
        return ref
    return f"worldstate://{kind}/{ref}"


def _iso_utc(value: datetime) -> str:
    # Core contracts already enforce UTC. Render the interoperable RFC 3339 Z form.
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _thaw_json(value: JSONValue) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
