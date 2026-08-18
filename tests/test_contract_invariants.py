from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from worldstate import (
    Conflict,
    EntityRef,
    EpistemicMode,
    Provenance,
    Source,
    StateAssertion,
    TemporalScope,
    Uncertainty,
    Unknown,
    UnknownReason,
    Validity,
    WorldStateSnapshot,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def provenance() -> Provenance:
    return Provenance(
        evidence_refs=("ev_1",),
        source_refs=("source_1",),
        method="direct-observation",
    )


def test_temporal_scope_rejects_reverse_interval() -> None:
    with pytest.raises(ValueError, match="end must not be earlier"):
        TemporalScope(
            start=datetime(2026, 8, 19, tzinfo=UTC),
            end=datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_temporal_scope_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TemporalScope(start=datetime(2026, 8, 18))


def test_uncertainty_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        Uncertainty(confidence=1.01)


def test_provenance_requires_evidence_or_parent_assertion() -> None:
    with pytest.raises(ValueError, match="provenance requires"):
        Provenance(evidence_refs=(), source_refs=(), method="unsupported")


def test_metadata_is_recursively_frozen() -> None:
    source = Source(
        source_id="source_1",
        source_type="example",
        metadata={"outer": {"inner": [1, 2]}},
    )

    with pytest.raises(TypeError):
        source.metadata["new"] = "value"  # type: ignore[index]

    nested = source.metadata["outer"]
    assert nested["inner"] == (1, 2)  # type: ignore[index]
    with pytest.raises(TypeError):
        nested["inner"] = (3,)  # type: ignore[index]


def test_epistemic_mode_is_preserved_on_assertion() -> None:
    entity = EntityRef("thing-1")
    validity = Validity(resolved_at=NOW)

    for mode in EpistemicMode:
        assertion = StateAssertion(
            assertion_id=f"state_{mode.value}",
            entity=entity,
            property_key="status",
            value="ok",
            epistemic_mode=mode,
            validity=validity,
            provenance=provenance(),
            version="0.1",
        )
        assert assertion.epistemic_mode is mode


def test_unknown_and_conflict_are_distinct_first_class_results() -> None:
    entity = EntityRef("thing-1")
    unknown = Unknown(
        unknown_id="unknown_1",
        reason=UnknownReason.NO_EVIDENCE,
        as_of=NOW,
        entity=entity,
        property_key="status",
    )
    conflict = Conflict(
        conflict_id="conflict_1",
        entity=entity,
        property_key="status",
        candidate_refs=("claim_a", "claim_b"),
        evidence_refs=("ev_a", "ev_b"),
        reason="incompatible values",
        as_of=NOW,
    )

    assert not isinstance(unknown, StateAssertion)
    assert not isinstance(conflict, Unknown)
    assert unknown.reason is UnknownReason.NO_EVIDENCE


def test_snapshot_and_source_versions_are_immutable() -> None:
    snapshot = WorldStateSnapshot(
        snapshot_id="snap_1",
        as_of=NOW,
        created_at=NOW,
        version="0.1",
        source_versions={"b": "2", "a": "1"},
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.version = "0.2"  # type: ignore[misc]

    with pytest.raises(TypeError):
        snapshot.source_versions["c"] = "3"  # type: ignore[index]

    assert tuple(snapshot.source_versions) == ("a", "b")
