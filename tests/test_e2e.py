"""One test per scenario trace. PENDING TRUTH (skip) until both truth files exist.
Traces run by default. The ones in KNOWN_RED wait on forms, letters or truth changes outside this repo and are
skipped with their reason; STACK_RUN_TRACES=1 runs them too."""
import os, pytest
from stack.scenarios import SCENARIOS
from stack import pipeline, scorer

RUN_ALL = os.environ.get("STACK_RUN_TRACES") == "1"
KNOWN_RED = {
    "S12-patient-declines-safety-question-to-letter-with-privacy-line": "waits on letters (privacy line, PRIVACY_BLOCKED refusals) and Physician's C15/allergy_any ruling; declined route scored in test_trace_negatives",
}


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_trace(sid, tmp_path):
    if scorer.load_truth(sid) is None:
        pytest.skip(scorer.PENDING)
    if sid in KNOWN_RED and not RUN_ALL:
        pytest.skip(f"known red, trace {sid}: " + KNOWN_RED[sid])
    r = pipeline.evaluate(sid, str(tmp_path))
    failed = {k: d for k, (ok, d) in r["criteria"].items() if not ok}
    assert not failed, failed


def test_fifteen_scenarios():
    assert len(SCENARIOS) == 15 and all(s.startswith("S") for s in SCENARIOS)
