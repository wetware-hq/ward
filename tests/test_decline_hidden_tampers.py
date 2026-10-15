"""S15-T1: a decline injected into a grant holder's reply fails, as text, id, count, gap or empty slot."""
import copy, tempfile
import pytest
from ward import scorer
from ward.harness import Harness
from ward.scenarios import SCENARIOS

SID = "S15-obstetrics-au"


@pytest.fixture(scope="module")
def run():
    seed, start, pack, fn, *_ = SCENARIOS[SID]
    h = Harness(SID, seed, start, pack=pack, language="en")
    fn(h, tempfile.mkdtemp())
    return h


def _inject(h, resp):
    t = copy.copy(h); t.trace = list(h.trace)
    ep = next(e for e, x in h.episodes.items() if x.kind == "forms")
    t.trace.append({"seq": 9999, "kind": "call", "actor": "SYNTH-agent-15g", "role": "patient_agent", "episode": ep,
                    "method": "observe", "accepted": True, "response": resp})
    return t


def test_clean(run):
    assert scorer._decline_hidden(run) == []


@pytest.mark.parametrize("resp", [
    {"result": "pregnant_possible: declined"},                 # the id
    {"result": "2 of 3 answered"}, {"result": "3 of 4 questions answered"},
    {"result": "1 not answered"}, {"result": "1 question unanswered"},
    {"answers": {"pregnant_possible": ""}}, {"answers": {"pregnant_possible": None}}])
def test_each_tamper_fails(run, resp):
    assert scorer._decline_hidden(_inject(run, resp))


@pytest.mark.parametrize("resp", [{"closed_sensitive": True}, {"result": "resubmit touches sensitive items"},
                                  {"result": "this step was a sensitive step"}, {"note": "closed sensitive"}])
def test_flag_copied_to_grant_holder_fails(run, resp):
    assert scorer._decline_hidden(_inject(run, resp))


def test_flag_staff_side_only(run):
    import json
    res = [r for r in run.trace if r.get("resubmit")]
    assert res and all(r["closed_sensitive"] is True for r in res)       # the resubmit re-ran the check over pregnant_possible
    side = [r for r in run.trace if r.get("op") in ("patient_view", "guardian_view")
            or (r.get("kind") == "call" and r.get("role") in ("patient", "patient_agent", "guardian"))]
    blob = json.dumps([r.get("response", r.get("result")) for r in side], default=str)
    assert "closed_sensitive" not in blob and "sensitive" not in blob.lower()


def test_declined_line_head_in_grant_holder_reply_fails(run):
    head = scorer._line_text("PV-DECLINED").split("[")[0]
    assert head and scorer._decline_hidden(_inject(run, {"result": head}))
