"""S14: an agent under a provider card (cards' provider_agent role) is refused closing CQ-RESULT-TO-DISCUSS; stack's
agent roles are the roles cards maps to "agent"."""
import ast, os, tempfile
from stack import harness, scenarios
from stack.endware import WORKSPACE


def _cards_agent_roles():
    src = open(os.path.join(WORKSPACE, "cards", "sleeve.py"), encoding="utf-8").read()
    out = set()
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("PATIENT_ROLES", "PROVIDER_ROLES"):
            out |= {k for k, v in ast.literal_eval(n.value).items() if v == "agent"}
    return out


def test_agent_roles_match_cards():
    assert set(harness.AGENT_ROLES) == _cards_agent_roles()


def test_provider_agent_close_refused_and_nothing_changes():
    sid = next(k for k in scenarios.SCENARIOS if k.startswith("S14"))
    seed, start, pack, fn, *_ = scenarios.SCENARIOS[sid]
    h = harness.Harness(sid, seed, start, pack=pack, language="en")
    fn(h, tempfile.mkdtemp())
    p = [r for r in h.trace if r.get("kind") == "call" and r.get("role") == "provider_agent"
         and r.get("method") == "step"]
    assert p and all(not r["accepted"] and r["response"].get("line_id") == "RF-RESULT-HELD" for r in p)
    i = p[0]["seq"]
    assert not any(r.get("op") == "clinician_queue_closed" and r.get("actor") == p[0]["actor"] for r in h.trace)
