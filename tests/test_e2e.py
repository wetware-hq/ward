"""One test per scenario trace. PENDING TRUTH (skip) until both truth files exist.
Traces are opt-in (STACK_RUN_TRACES=1): truth files are still under review and the export adapter is on
hold, so trace results are reported by scripts/report.py and do not gate the unit suite."""
import os, pytest
from stack.scenarios import SCENARIOS
from stack import pipeline, scorer

RUN = os.environ.get("STACK_RUN_TRACES") == "1"


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_trace(sid, tmp_path):
    if scorer.load_truth(sid) is None:
        pytest.skip(scorer.PENDING)
    if not RUN:
        pytest.skip("trace run is opt-in: STACK_RUN_TRACES=1")
    r = pipeline.evaluate(sid, str(tmp_path))
    failed = {k: d for k, (ok, d) in r["criteria"].items() if not ok}
    assert not failed, failed


def test_fifteen_scenarios():
    assert len(SCENARIOS) == 15 and all(s.startswith("S") for s in SCENARIOS)
