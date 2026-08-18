from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from .ids import semantic_id
from .models import (
    Conflict,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    Unknown,
    WorldStateSnapshot,
)
from .resolution import REFERENCE_RESOLVER_VERSION


def build_snapshot(
    results: Iterable[StateQueryResult],
    *,
    as_of: datetime,
    scope: SpatialScope | None = None,
    source_versions: Mapping[str, str] | None = None,
    created_at: datetime | None = None,
    version: str = REFERENCE_RESOLVER_VERSION,
) -> WorldStateSnapshot:
    """Build an immutable replay-stable snapshot from explicit query outcomes.

    The reference builder defaults ``created_at`` to ``as_of`` so repeated replay
    of the same semantic inputs does not acquire a wall-clock dependency.
    """
    assertions: list[StateAssertion] = []
    unknowns: list[Unknown] = []
    conflicts: list[Conflict] = []

    for result in results:
        if isinstance(result, StateAssertion):
            assertions.append(result)
        elif isinstance(result, Unknown):
            unknowns.append(result)
        elif isinstance(result, Conflict):
            conflicts.append(result)
        else:
            raise TypeError(f"unsupported snapshot result: {type(result).__name__}")

    canonical_assertions = tuple(sorted(assertions, key=lambda item: item.assertion_id))
    canonical_unknowns = tuple(sorted(unknowns, key=lambda item: item.unknown_id))
    canonical_conflicts = tuple(sorted(conflicts, key=lambda item: item.conflict_id))
    canonical_source_versions = dict(sorted((source_versions or {}).items()))
    snapshot_created_at = as_of if created_at is None else created_at

    payload = {
        "as_of": as_of,
        "created_at": snapshot_created_at,
        "scope": scope,
        "assertion_refs": tuple(item.assertion_id for item in canonical_assertions),
        "unknown_refs": tuple(item.unknown_id for item in canonical_unknowns),
        "conflict_refs": tuple(item.conflict_id for item in canonical_conflicts),
        "source_versions": canonical_source_versions,
        "version": version,
    }

    return WorldStateSnapshot(
        snapshot_id=semantic_id("snap", payload),
        as_of=as_of,
        created_at=snapshot_created_at,
        version=version,
        scope=scope,
        assertions=canonical_assertions,
        unknowns=canonical_unknowns,
        conflicts=canonical_conflicts,
        source_versions=canonical_source_versions,
    )
