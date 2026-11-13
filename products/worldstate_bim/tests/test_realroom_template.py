"""Capture templates must protect existing evidence and isolate reference data."""
import json
import pytest
from benchmarks.ws_realroom.init_room import initialize


def test_template_has_separate_reference_and_does_not_overwrite(tmp_path):
    target = tmp_path / "room"
    initialize(target, "room-1")
    assert (target / "input/photos").is_dir()
    assert (target / "private-reference/holdout").is_dir()
    assert (target / "private-reference/dimensions.csv").is_file()
    assert json.loads((target / "private-reference/reference.template.json").read_text())["status"] == "NOT_COLLECTED"
    assert json.loads((target / "runs/labor.template.json").read_text())["pairs"] == []
    assert json.loads((target / "input/anchor.json").read_text())["value_m"] is None
    assert "*" in (target / ".gitignore").read_text()
    with pytest.raises(FileExistsError):
        initialize(target, "room-1")
    with pytest.raises(ValueError):
        initialize(tmp_path / "bad", "../bad")
