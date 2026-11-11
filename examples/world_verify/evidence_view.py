"""Read-only WorldState evidence views for two illustrative WORLD / VERIFY stories.

All input claims below are synthetic teaching data, NOT field measurements,
historical reconstructions, or a live integration with either public website.
This consumer intentionally relies on public WorldState contracts only.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from worldstate import (
    Claim,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    state_query_result_payload,
)

AT = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
CONTRACT = "world-verify.evidence-view"
CONTRACT_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class Story:
    """Presentation metadata owned by this demo consumer, not WorldState Core."""

    key: str
    title: str
    entity: EntityRef
    questions: tuple[str, ...]
    limitation: str


STORIES = {
    "pku_scale": Story(
        key="pku_scale",
        title="From Room 517 to Earth: why image alignment cannot prove scale",
        entity=EntityRef(
            "illustrative-campus-building",
            entity_type="illustrative-building",
            namespace="world-verify-demo",
        ),
        questions=("projection_alignment", "absolute_height_m"),
        limitation=(
            "Image reprojection similarity alone does not identify an absolute "
            "physical scale. No verified height measurement is included."
        ),
    ),
    "campus_reconstruction": Story(
        key="campus_reconstruction",
        title="Campus reconstruction: appearance is not geometry",
        entity=EntityRef(
            "illustrative-campus-reconstruction",
            entity_type="illustrative-model",
            namespace="world-verify-demo",
        ),
        questions=(
            "appearance_similarity",
            "candidate_roof_orientation",
            "geometry_verified",
        ),
        limitation=(
            "The two roof-orientation claims are incompatible simulated "
            "candidates, not observations of the actual building. Visual "
            "similarity is not proof of geometric correctness."
        ),
    ),
}


def _add_simulated_claim(
    provider: InMemoryWorldState,
    story: Story,
    property_key: str,
    value: str,
    candidate: str,
) -> None:
    """Register one explicitly synthetic simulated claim and its own evidence."""

    evidence_id = f"{story.key}:{candidate}:{property_key}:evidence"
    source = Source(
        source_id=f"{story.key}:{candidate}:source",
        source_type="synthetic-teaching-case",
        version="0.1",
        metadata={"synthetic": True, "not_a_real_world_measurement": True},
    )
    provider.add_evidence(
        Evidence(
            evidence_id=evidence_id,
            source=source,
            recorded_at=AT,
            metadata={"synthetic": True},
        )
    )
    provider.add_claim(
        Claim(
            claim_id=f"{story.key}:{candidate}:{property_key}:claim",
            entity=story.entity,
            property_key=property_key,
            value=value,
            epistemic_mode=EpistemicMode.SIMULATED,
            provenance=Provenance(
                evidence_refs=(evidence_id,),
                source_refs=(source.source_id,),
                method="synthetic-teaching-example",
            ),
            created_at=AT,
        )
    )


def build_story_provider(story_key: str) -> tuple[Story, InMemoryWorldState]:
    """Build a deterministic teaching provider for one of the two stories."""

    if story_key not in STORIES:
        raise ValueError(f"unknown story: {story_key}")
    story = STORIES[story_key]
    provider = InMemoryWorldState()

    if story_key == "pku_scale":
        _add_simulated_claim(
            provider, story, "projection_alignment", "similar", "reprojection"
        )
        # Intentionally no absolute_height_m evidence: Unknown must survive.
    elif story_key == "campus_reconstruction":
        _add_simulated_claim(
            provider, story, "appearance_similarity", "visually-similar", "render"
        )
        _add_simulated_claim(
            provider, story, "candidate_roof_orientation", "north-south", "model-a"
        )
        _add_simulated_claim(
            provider, story, "candidate_roof_orientation", "east-west", "model-b"
        )
        # Intentionally no geometry_verified evidence: Unknown must survive.

    return story, provider


def evidence_view(story_key: str) -> dict[str, object]:
    """Project provider results into a publication-only JSON view.

    The `outcome` field uses the unchanged public WorldState result wire.
    This consumer does not infer state, decide if geometry is correct, or
    turn an Unknown/Conflict into a successful real-world assertion.
    """

    story, provider = build_story_provider(story_key)
    facts: list[dict[str, object]] = []

    for property_key in story.questions:
        result = provider.query_state(story.entity, property_key, AT)
        state_ref = (
            getattr(result, "assertion_id", None)
            or getattr(result, "conflict_id", None)
            or getattr(result, "unknown_id")
        )
        evidence = provider.get_evidence(state_ref)
        facts.append(
            {
                "property_key": property_key,
                "outcome": state_query_result_payload(result),
                "evidence": [
                    {
                        "evidence_id": item.evidence_id,
                        "source_id": item.source.source_id,
                        "source_type": item.source.source_type,
                        "synthetic": item.source.metadata.get("synthetic", False),
                        "recorded_at": item.recorded_at.isoformat().replace(
                            "+00:00", "Z"
                        ),
                    }
                    for item in evidence
                ],
            }
        )

    return {
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "story": story.key,
        "title": story.title,
        "as_of": AT.isoformat().replace("+00:00", "Z"),
        "demo_data": "synthetic-not-a-field-observation",
        "limitation": story.limitation,
        "facts": facts,
    }


def main(argv: Iterable[str] | None = None) -> int:
    """Print deterministic JSON suitable for a future static demo adapter."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", choices=tuple(STORIES), default="pku_scale")
    args = parser.parse_args(argv)
    print(json.dumps(evidence_view(args.story), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
