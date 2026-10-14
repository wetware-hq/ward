"""Status wording through the adapter on two real traces (run only when both truth files exist)."""
import re, pytest
from stack import runner, scorer, adapter
from stack.endware import letter

FLAG = re.compile(r" \[flag: [^\]]+\]")
S12 = "S12-patient-declines-safety-question-to-letter-with-privacy-line"
S05 = "S05-mh-screen-by-patient-agent"


KNOWN_RED = {}


def need(sid):
    import os
    t = scorer.load_truth(sid)
    if t is None:
        pytest.skip(scorer.PENDING)
    red = KNOWN_RED.get("S05" if sid == S05 else "")
    if red and os.environ.get("STACK_RUN_TRACES") != "1":
        pytest.skip(f"known red, trace {sid}: " + red)
    return t


def test_s12_declined_safety_question_reaches_letter_as_declined(tmp_path):
    t = need(S12)
    h, art = runner.run(S12, str(tmp_path), t["patient_language"])
    want = adapter.lt("LT-DECLINED-PT-SAFETY", **{"question plain wording": "Do you have any allergies to medicines"})
    assert want in art["letter"]
    assert "This letter includes private details about your health. It's yours to share or keep private." in art["letter"]
    f = [x for x in art["facts"] if x["item_id"] == "allergy_any"][0]
    assert f["status"] == "declined" and f["value"] is None and f["safety"]
    assert any("question 1" in x for x in h.peek("SYNTH-EP-1201")["flags"])    # its alert


def test_s05_self_harm_yes_cut_for_clinician_kept_for_patient_and_queued(tmp_path):
    t = need(S05)
    h, art = runner.run(S05, str(tmp_path), t["patient_language"])
    assert "thoughts of harming yourself" in art["letter"]                     # patient letter: word for word
    c = art["clinician_letter"]
    ev = [x for x in c["facts"] if x["item_id"] == "mh_q2"][0]["event_id"]
    want = adapter.lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": adapter.letter_event_id(ev)})
    assert want in FLAG.sub("", c["letter"]) and "harming" not in c["letter"]
    assert "harming" not in c["notes"]                                         # notes input too
    q = [r for r in h.trace if r.get("op") == "clinician_queue"]
    assert q and q[0]["item"] == 2 and q[0]["event"] == ev and q[0]["date"] == h.clock.date().isoformat()
