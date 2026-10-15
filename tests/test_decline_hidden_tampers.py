"""S15-T1: a decline injected into a grant holder's reply fails, as text, id, count, gap or empty slot."""
import copy, tempfile
import pytest
from stack import scorer
from stack.harness import Harness
from stack.scenarios import SCENARIOS

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
