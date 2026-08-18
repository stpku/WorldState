from datetime import datetime, timedelta, timezone

import pytest

from worldstate import canonical_json, semantic_id


def test_mapping_order_does_not_change_semantic_id() -> None:
    left = {"entity": "thing-1", "value": {"b": 2, "a": 1}}
    right = {"value": {"a": 1, "b": 2}, "entity": "thing-1"}

    assert canonical_json(left) == canonical_json(right)
    assert semantic_id("state", left) == semantic_id("state", right)


def test_equivalent_timezone_instants_canonicalize_identically() -> None:
    utc = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    plus_eight = datetime(
        2026,
        8,
        18,
        20,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert canonical_json({"at": utc}) == canonical_json({"at": plus_eight})


def test_semantic_id_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        semantic_id("state", {"at": datetime(2026, 8, 18, 12, 0)})


def test_semantic_id_rejects_non_finite_float() -> None:
    with pytest.raises(ValueError, match="NaN or infinite"):
        semantic_id("state", {"value": float("nan")})
