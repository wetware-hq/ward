"""Rulings 12:16/12:17: guardian resubmit only on a live cards grant_state check on the scenario clock (ended grant:
RF-GRANT-ENDED (pending signing), nothing changes); CL-CLOSED names the clinician from the logged-in session only; closing review_trend in
person claims CL-TREND-CLOSED (unsigned); the patient's agent may resend answers unchanged but never change one
(RF-AGENT-ANSWER-CHANGED, unsigned). Unsigned ids carry no text until their rows land."""
import datetime as _dt
from stack import loader, notes
from stack.harness import Harness
from stack.scenarios import CASE, DISC, A, answer
from signed_source import signed_rows as _signed_rows

P, EP, G = "SYNTH-PERSON-C13", "SYNTH-EP-1301", "SYNTH-PERSON-G13"
CARD = CASE("S13_card")


def failed_and_reviewed():
    h = Harness("S13-test", 1313, "1936-03-09T09:00", pack="au", language="en")
    h.open_episode("forms", CASE("paeds_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-13", "clinician", P, discipline=DISC["PAE"])
    assert h.cards_grant(dr, EP, CARD, G)["accepted"]
    dr.step(EP, A("approve"))
    gd = h.session(G, "guardian", P)
    for q, v in (("allergy_any", True), ("allergy_reaction_severe", False), ("takes_blood_thinner", False)):
        gd.step(EP, answer(q, v))
    gd.step(EP, A("submit"))
    dr.step(EP, A("review"))
    return h


def _end(gid, kind):
    c = loader.cards().load(open(CARD, encoding="utf-8").read())
    return [e["at"] for e in c["grant_events"] if e["grant_id"] == gid and e["event"] == kind][0]


def _refused_unchanged(h, who, gid, kind):
    before, n = h.peek(EP), len(h.episodes[EP].log)
    r = h.session(who, "guardian", P).step(EP, A("submit"))
    assert r["accepted"] is False and r["line_id"] == "RF-GRANT-ENDED" and r["ended"] == _end(gid, kind)
    assert r["reason"] == _signed_rows().get("RF-GRANT-ENDED", "")     # unsigned: no text, never invented
    assert h.peek(EP) == before and len(h.episodes[EP].log) == n
    last = [x for x in h.trace if x.get("kind") == "call"][-1]
    assert last["note"]["claim"] == "CL-REFUSED"


def test_revoked_guardian_resubmit_refused_grant_ended():
    _refused_unchanged(failed_and_reviewed(), "SYNTH-PERSON-G13R", "SYNTH-GR-1302", "revoked")


def test_expired_guardian_resubmit_refused_grant_ended_fail_closed():
    _refused_unchanged(failed_and_reviewed(), "SYNTH-PERSON-G13E", "SYNTH-GR-1303", "expired")


def _g13f_resubmit():
    h = failed_and_reviewed()
    r = h.session("SYNTH-PERSON-G13F", "guardian", P).step(EP, A("submit"))
    last = [x for x in h.trace if x.get("kind") == "call"][-1]
    return h, r, last


def test_current_guardian_resubmit_accepted_resubmitted():
    h, r, last = _g13f_resubmit()
    assert r["accepted"], r
    assert notes.env_result(last) == "resubmitted+checked" and last["note"]["claim"] == "CL-RESUBMITTED"
    assert h.peek(EP)["final"]


class _BoxDate(_dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 15)


class _BoxDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 15, 12, 0)

    @classmethod
    def today(cls):
        return cls(2026, 10, 15, 12, 0)


def test_box_clock_does_not_change_the_grant_result(monkeypatch):
    """expires_at is compared with the scenario clock only: a box clock in 2026 (long after 1936-06-30) changes nothing."""
    import time, stack.harness as H
    monkeypatch.setattr(_dt, "date", _BoxDate)
    monkeypatch.setattr(_dt, "datetime", _BoxDateTime)
    monkeypatch.setattr(time, "time", lambda: 1_792_000_000.0)
    for mod in (H, loader.cards()):
        for name, val in (("date", _BoxDate), ("datetime", _BoxDateTime)):
            if isinstance(getattr(mod, name, None), type):
                monkeypatch.setattr(mod, name, val)
    h, r, last = _g13f_resubmit()
    assert r["accepted"] and last["note"]["claim"] == "CL-RESUBMITTED"


def test_guardian_who_stays_pending_until_row_names_guardian():
    _, _, last = _g13f_resubmit()
    row = _signed_rows().get("CL-RESUBMITTED", "")
    t = notes.claim_text("CL-RESUBMITTED", last)
    assert (t is None) if "guardian" not in row else (t is not None and "guardian" in t and "[" not in t)


# ---- S14
def s14_world():
    from stack.scenarios import SCENARIOS
    h = Harness("S14-test", 1414, "1937-04-01T07:00", pack="au", language="en")
    return h


def _held(h):
    P4, EO = "SYNTH-P1401", "SYNTH-EP-1401"
    h.open_episode("orders", CASE("onc_results"), EO, P4)
    dr = h.session("SYNTH-dr-14", "clinician", P4, discipline=DISC["ONC"])
    dr.step(EO, A("approve"))
    from stack.scenarios import SCN
    kind, text = SCN["results"]["S14"]["imaging"]
    h.record_result("SYNTH-dr-14", "SYNTH-REC-1406", P4, kind, "1937-04-28T08:00:00", text, "", kind=kind)
    return P4, EO, dr


def test_agent_under_clinician_name_cannot_close_held_and_no_cl_closed():
    h = s14_world(); P4, EO, dr = _held(h)
    ag = h.session("SYNTH-agent-14", "clinician_agent", P4, scope=(DISC["ONC"],))
    r = ag.step(EO, A("close_sameday", record="SYNTH-REC-1406", clinician="SYNTH-dr-14"))
    assert r["accepted"] is False and r["reason"] == _signed_rows()["RF-RESULT-HELD"]
    assert h.held_open(P4) == ["SYNTH-REC-1406"]
    assert not any((x.get("note") or {}).get("claim") == "CL-CLOSED" for x in h.trace)


def test_cl_closed_names_session_clinician_never_request():
    h = s14_world(); P4, EO, dr = _held(h)
    dr.step(EO, A("close_sameday", record="SYNTH-REC-1406", clinician="SYNTH-someone-else"))
    last = [x for x in h.trace if x.get("kind") == "call"][-1]
    assert last["note"]["claim"] == "CL-CLOSED" and last["response"]["queue"] == "CQ-RESULT-TO-DISCUSS"
    t = notes.claim_text("CL-CLOSED", last)
    assert t is not None and "SYNTH-dr-14" in t and "SYNTH-someone-else" not in t


def test_trend_closed_claim_is_unsigned_and_has_no_text():
    assert "CL-TREND-CLOSED" in notes.CLAIMS
    t = notes.claim_text("CL-TREND-CLOSED", {"role": "clinician", "actor": "SYNTH-dr-14", "args": [{"clinician": "SYNTH-x"}]})
    assert (t is None) if "CL-TREND-CLOSED" not in _signed_rows() else ("SYNTH-dr-14" in t and "SYNTH-x" not in t)
    assert notes.claim_text("CL-TREND-CLOSED", {"role": "clinician_agent", "actor": "SYNTH-agent-14"}) is None


# ---- S08
def s08_passed():
    P8, E8 = "SYNTH-P0801", "SYNTH-EP-0801"
    h = Harness("S08-test", 808, "1937-02-15T07:30", pack="au", language="en")
    h.open_episode("forms", CASE("patient_history"), E8, P8, needs=("pack",))
    dr = h.session("SYNTH-dr-08", "clinician", P8, discipline=DISC["MED"])
    pa = h.session(P8, "patient", P8)
    from stack.scenarios import access
    dr.step(E8, A("approve"))
    pa.step(E8, access("grant", P8, "SYNTH-agent-08"))
    ag = h.session("SYNTH-agent-08", "patient_agent", P8)
    ag.step(E8, A("submit"))
    for q, v in [("allergy_any", True), ("allergy_reaction_severe", False), ("takes_blood_thinner", False),
                 ("smokes", False), ("pregnant_possible", False)]:
        dr.step(E8, answer(q, v))
    dr.step(E8, A("review"))
    return h, E8, ag


def test_agent_changing_an_answer_after_submit_is_refused_unchanged():
    h, E8, ag = s08_passed()
    before, n = h.peek(E8), len(h.episodes[E8].log)
    r = ag.step(E8, answer("smokes", True))
    assert r["accepted"] is False and r["line_id"] == "RF-AGENT-ANSWER-CHANGED"
    assert r["reason"] == _signed_rows().get("RF-AGENT-ANSWER-CHANGED", "")     # unsigned: no text, never invented
    assert h.peek(E8) == before and len(h.episodes[E8].log) == n


def test_agent_resending_answers_unchanged_then_resubmit_accepted():
    h, E8, ag = s08_passed()
    assert ag.step(E8, answer("smokes", False))["accepted"]
    r = ag.step(E8, A("submit"))
    last = [x for x in h.trace if x.get("kind") == "call"][-1]
    assert r.get("accepted", True) and last["note"]["claim"] == "CL-RESUBMITTED"


def test_box_clock_patch_is_restored_after_the_test():
    """The patch above is scoped to its own test (pytest monkeypatch): the real clock is back for everything after."""
    import time, stack.harness as H
    assert _dt.date is not _BoxDate and _dt.datetime is not _BoxDateTime
    assert H.datetime is _dt and loader.cards().__dict__.get("date") is not _BoxDate
    assert abs(time.time() - _dt.datetime.now().timestamp()) < 5 and time.time() != 1_792_000_000.0


def test_guardian_ended_probes_only_in_s13():
    """The G13R/G13E guardians belong to S13's child; no other scenario probes with them."""
    import inspect
    from stack import scenarios as S
    for fn in (S.s12, S.s15):
        assert "G13R" not in inspect.getsource(fn) and "G13E" not in inspect.getsource(fn)
    assert "G13E" in inspect.getsource(S.s13)
