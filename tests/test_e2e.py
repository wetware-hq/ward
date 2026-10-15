"""One test per scenario trace. No answer-file setting: skipped as RUN-TRACES-NOT-RUN. Setting present: a missing
answer file fails.
Traces run by default. The ones in KNOWN_RED wait on forms, letters or truth changes outside this repo and are
skipped with their reason; WARD_RUN_TRACES=1 runs them too."""
import os, pytest
from ward.scenarios import SCENARIOS
from ward import pipeline, scorer
from truthgate import missing_truth, truth_path

RUN_ALL = os.environ.get("WARD_RUN_TRACES") == "1"
KNOWN_RED = {}   # S12 passes since the letters wiring and Physician review (15 Oct 21:48)


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_trace(sid, tmp_path):
    if scorer.load_truth(sid) is None:
        missing_truth(sid)
    if sid in KNOWN_RED and not RUN_ALL:
        pytest.skip(f"known red, trace {sid}: " + KNOWN_RED[sid])
    r = pipeline.evaluate(sid, str(tmp_path))
    failed = {k: d for k, (ok, d) in r["criteria"].items() if not ok}
    assert not failed, failed


def test_every_scenario_has_an_answer_file_folder():
    assert SCENARIOS and all(s.startswith("S") and os.path.isdir(truth_path(s)) for s in SCENARIOS)
