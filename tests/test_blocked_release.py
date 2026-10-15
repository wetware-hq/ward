"""A BLOCKED_FOR_OUTPUT trace must release nothing: no endware build, no artifact file, block artifact only."""
import os
import pytest
from ward import runner, scorer
from truthgate import missing_truth, truth_path

BLOCKED = ["S03-med-rec-pharmacist", "S04-allied-referral-physio", "S06a-sdm-on-behalf-eu-de", "S10-results-figure"]


@pytest.mark.parametrize("sid", BLOCKED)
def test_blocked_trace_releases_no_output(sid, tmp_path):
    t = scorer.load_truth(sid)
    if t is None:
        missing_truth(sid)
    assert str(t.get("expected_outcome")).upper() == "BLOCKED_FOR_OUTPUT"
    h, art = runner.run(sid, str(tmp_path), t["patient_language"])
    assert art["tool"] == "block" and art.get("path") in (None, "")
    assert not [r for r in h.trace if r["kind"] == "endware"]
    assert not [r for r in h.trace if r.get("op") == "export"]                 # only export_refused
    assert sorted(os.listdir(tmp_path)) == ["trace.jsonl"]
