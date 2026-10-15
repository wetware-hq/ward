"""Pure scenario-test checkers (check_t1/t2/t4), driven with synthetic observations so every branch is pinned
without the answer files. Templates and patient lines are read from the signed source."""
import copy
import pytest
from stack import scenario_tests as st
from signed_source import signed_rows as _signed_rows

SIGNED = _signed_rows()
TPL = SIGNED["CQ-RESULT-TO-DISCUSS"]                # a signed queue line with one [event_id] slot
LINE = TPL.replace("[event_id]", "SYNTH-EV-1")
OTHER = TPL.replace("[event_id]", "SYNTH-EV-9")      # slot filled with an id that is not in the log
SAMEDAY = st._signed("PV-SAMEDAY")
DECL = {"expect_queue_line": TPL, "expect_open": True}


def obs(**kw):
    o = {"queue": [LINE], "event_ids": ["SYNTH-EV-1"], "open": True, "patient_surface": "", "confirmed": [],
         "answers": {"mh_q2": "declined"}}
    o.update(kw)
    return o


# ---- t1
def test_t1_clean():
    assert st.check_t1(obs(), DECL) == []


@pytest.mark.parametrize("kw,frag", [
    ({"queue": []}, "queue line"), ({"queue": [OTHER]}, "queue line"), ({"queue": [LINE, OTHER]}, "queue line"),
    ({"open": False}, "not open"), ({"patient_surface": "x " + SAMEDAY}, "PV-SAMEDAY"),
    ({"confirmed": ["mh_q2"]}, "mh_q2")])
def test_t1_each_fault(kw, frag):
    f = st.check_t1(obs(**kw), DECL)
    assert len(f) == 1 and frag in f[0]


def test_t1_open_not_expected():
    assert st.check_t1(obs(open=False), {"expect_queue_line": TPL}) == []


def test_t1_queue_line_mismatch_not_matched():
    assert st._queue_ok(obs(queue=["unrelated"]), TPL) is False


# ---- t2
PV_CHANGED = st._signed("PV-ANS-CHANGED")
D2 = {"expect_queue_line": TPL, "expect_patient_text": PV_CHANGED, "expect_patient_line": "PV-ANS-CHANGED"}


def res(**kw):
    r = {"before": obs(), "mid": obs(), "after": obs(queue=[]), "patient_response": {"message": PV_CHANGED},
         "agent_close": {"accepted": False}, "patient_close": {"accepted": False}}
    r.update(kw)
    return r


def test_t2_clean():
    assert PV_CHANGED
    assert st.check_t2(res(), D2) == []


@pytest.mark.parametrize("kw,frag", [
    ({"before": obs(queue=[OTHER])}, "queue line"),
    ({"patient_response": {"message": "x"}}, "word for word"),
    ({"agent_close": {"accepted": True}}, "closed by"), ({"patient_close": {"accepted": True}}, "closed by"),
    ({"mid": obs(queue=[])}, "kept open"), ({"after": obs()}, "still open")])
def test_t2_each_fault(kw, frag):
    f = st.check_t2(res(**kw), D2)
    assert len(f) == 1 and frag in f[0], f


def test_t2_before_empty_fails_twice():
    f = st.check_t2(res(before=obs(queue=[])), D2)
    assert any("queue line" in x for x in f) and any("kept open" in x for x in f)


def test_t2_declared_text_must_be_the_signed_line():
    f = st.check_t2(res(patient_response={"message": "x"}), dict(D2, expect_patient_text="x"))
    assert len(f) == 1 and "word for word" in f[0]


# ---- t4
def test_t4_clean():
    assert st.check_t4(obs(patient_surface=SAMEDAY), DECL) == []


@pytest.mark.parametrize("kw,frag", [
    ({"queue": [OTHER]}, "queue line"), ({"open": False}, "not open"),
    ({"answers": {"mh_q2": False}}, "counted as a no"), ({"patient_surface": ""}, "PV-SAMEDAY")])
def test_t4_each_fault(kw, frag):
    o = obs(patient_surface=SAMEDAY); o.update(kw)
    f = st.check_t4(o, DECL)
    assert len(f) == 1 and frag in f[0], f


def test_t4_unanswered_or_true_is_not_a_no():
    for v in (None, True, "declined", 0):
        o = obs(patient_surface=SAMEDAY, answers={"mh_q2": v})
        assert st.check_t4(o, DECL) == ([] if v is not False else ["decline counted as a no"])


def test_t4_open_not_expected():
    assert st.check_t4(obs(patient_surface=SAMEDAY, open=False), {"expect_queue_line": TPL}) == []
