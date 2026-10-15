"""Guard (ruling 12:19): RF-REVOKED fires only for an assistant grant that was actively revoked. A grant holder who
is not an assistant (guardian, decision-maker) or an expired grant gets RF-GRANT-ENDED instead."""
import json, tempfile, pytest
from stack import loader
from stack.harness import Harness
from stack.scenarios import SCENARIOS
from signed_source import signed_rows as _signed_rows

ASSISTANTS = ("patient_agent", "clinician_agent")


def _is_revoked_line(resp):
    head = _signed_rows()["RF-REVOKED"].split("[date]")[0]
    return resp.get("line_id") == "RF-REVOKED" or str(resp.get("reason", "")).startswith(head)


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_rf_revoked_only_after_an_assistant_revoke(sid):
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    fn(h, tempfile.mkdtemp())
    calls = [r for r in h.trace if r.get("kind") == "call"]
    for i, r in enumerate(calls):
        if r.get("accepted") or not _is_revoked_line(r.get("response") or {}):
            continue
        assert r["role"] in ASSISTANTS, r
        revoked = [c for c in calls[:i] if c.get("accepted") and isinstance((c.get("args") or [{}])[0], dict)
                   and c["args"][0].get("type") == "revoke" and c["args"][0].get("agent") == r["actor"]]
        assert revoked, f"RF-REVOKED without an active revoke of {r['actor']}"


def test_expired_guardian_never_gets_rf_revoked():
    from test_rulings_1216 import failed_and_reviewed, P, EP
    h = failed_and_reviewed()
    r = h.session("SYNTH-PERSON-G13E", "guardian", P).step(EP, {"type": "submit"})
    assert not _is_revoked_line(r) and r["line_id"] == "RF-GRANT-ENDED"


def test_cards_expired_grant_is_not_rf_revoked():
    from stack.scenarios import CASE
    c = loader.cards()
    card = c.load(open(CASE("S13_card"), encoding="utf-8").read())
    env = c.Env(now="1936-03-09") if hasattr(c, "Env") else None
    assert env is not None
    s = c.Session(env, "decision_maker", "SYNTH-AG-1303", grant_id="SYNTH-GR-1303")
    with pytest.raises(c.Refused) as e:
        s.open(text=open(CASE("S13_card"), encoding="utf-8").read())
    assert e.value.args[0] != "RF-REVOKED"
