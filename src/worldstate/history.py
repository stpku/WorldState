from __future__ import annotations

from datetime import datetime

from .ids import semantic_id
from .models import Provenance, StateAssertion, StateTransition
from .resolution import REFERENCE_RESOLVER_VERSION

HISTORY_BUILDER_ID = "worldstate.reference-history"


def build_transition(
    from_assertion: StateAssertion | None,
    to_assertion: StateAssertion | None,
    *,
    transition_time: datetime,
    reason: str | None = None,
) -> StateTransition:
    """Create a deterministic transition without mutating either assertion."""
    if from_assertion is None and to_assertion is None:
        raise ValueError("transition requires a from or to assertion")

    anchor = to_assertion if to_assertion is not None else from_assertion
    assert anchor is not None

    if from_assertion is not None and to_assertion is not None:
        if from_assertion.entity != to_assertion.entity:
            raise ValueError("transition assertions must reference the same entity")
        if from_assertion.property_key != to_assertion.property_key:
            raise ValueError("transition assertions must reference the same property_key")

    assertions = tuple(
        assertion
        for assertion in (from_assertion, to_assertion)
        if assertion is not None
    )
    evidence_refs = tuple(
        sorted(
            {
                ref
                for assertion in assertions
                for ref in assertion.provenance.evidence_refs
            }
        )
    )
    source_refs = tuple(
        sorted(
            {
                ref
                for assertion in assertions
                for ref in assertion.provenance.source_refs
            }
        )
    )
    parent_assertion_refs = tuple(
        sorted(
            {assertion.assertion_id for assertion in assertions}
            | {
                ref
                for assertion in assertions
                for ref in assertion.provenance.parent_assertion_refs
            }
        )
    )
    provenance = Provenance(
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        parent_assertion_refs=parent_assertion_refs,
        method="state-transition",
        resolver=f"{HISTORY_BUILDER_ID}@{REFERENCE_RESOLVER_VERSION}",
    )

    payload = {
        "entity": anchor.entity,
        "property_key": anchor.property_key,
        "from_assertion_ref": (
            None if from_assertion is None else from_assertion.assertion_id
        ),
        "to_assertion_ref": None if to_assertion is None else to_assertion.assertion_id,
        "transition_time": transition_time,
        "reason": reason,
        "provenance": provenance,
        "builder": HISTORY_BUILDER_ID,
        "version": REFERENCE_RESOLVER_VERSION,
    }

    return StateTransition(
        transition_id=semantic_id("transition", payload),
        entity=anchor.entity,
        property_key=anchor.property_key,
        from_assertion_ref=(
            None if from_assertion is None else from_assertion.assertion_id
        ),
        to_assertion_ref=None if to_assertion is None else to_assertion.assertion_id,
        transition_time=transition_time,
        reason=reason,
        provenance=provenance,
    )
