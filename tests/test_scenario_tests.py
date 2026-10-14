"""S05 scenario-test checkers: each passes on a correct fixture and fails on a broken one.
Declarations are read (read-only) from the S05 answer file. Observations are fake fixtures; no trace is run."""
import copy, os, tomllib, pytest
from stack import scenario_tests as st, adapter, scorer

TRUTH = "/workspace/stack_truth/S05-mh-screen-by-patient-agent/truth.toml"
EP = st.EP


@pytest.fixture(scope="module")
def decl():
    if not os.path.exists(TRUTH):
        pytest.skip(scorer.PENDING)
    return {t["id"]: t for t in tomllib.load(open(TRUTH, "rb"))["scenario_tests"]}


def q(template, ev=f"{EP}#3"):
    return template.replace("[event_id]", ev)


def obs(queue=(), open_=True, answers=None, surface="", confirmed=()):
    return {"queue": list(queue), "open": open_, "answers": answers or {"mh_q2": True}, "patient_surface": surface,
            "event_ids": [f"{EP}#{n}" for n in range(6)], "confirmed": list(confirmed)}


# ---- T1: an agent's unconfirmed yes queues, stays open, no PV-SAMEDAY, no final answer
def test_t1_correct(decl):
    d = decl["S05-T1-unconfirmed"]
    assert st.check_t1(obs([q(d["expect_queue_line"])]), d) == []


@pytest.mark.parametrize("broken", ["no_queue", "bad_event", "closed", "sameday", "confirmed"])
def test_t1_broken(decl, broken):
    d = decl["S05-T1-unconfirmed"]
    o = obs([q(d["expect_queue_line"], f"{EP}#99" if broken == "bad_event" else f"{EP}#3")] if broken != "no_queue" else [],
            open_=broken != "closed", surface=st._signed("PV-SAMEDAY") if broken == "sameday" else "",
            confirmed=["mh_q2"] if broken == "confirmed" else [])
    assert st.check_t1(o, d)


# ---- T2: patient changes the answer; thanked; only a clinician closes the entry
def t2_fixture(d):
    line = q(d["expect_queue_line"])
    return {"before": obs([line]), "mid": obs([line]), "after": obs([]),
            "patient_response": {"accepted": True, "message": d["expect_patient_text"]},
            "agent_close": {"accepted": False}, "patient_close": {"accepted": False}}


def test_t2_correct(decl):
    d = decl["S05-T2-changed"]
    assert st.check_t2(t2_fixture(d), d) == []


@pytest.mark.parametrize("broken", ["no_line", "no_thanks", "agent_closes", "patient_closes", "closed_early", "never_closed"])
def test_t2_broken(decl, broken):
    d = decl["S05-T2-changed"]
    r = copy.deepcopy(t2_fixture(d))
    if broken == "no_line": r["before"]["queue"] = []
    if broken == "no_thanks": r["patient_response"] = {"accepted": True}
    if broken == "agent_closes": r["agent_close"] = {"accepted": True}
    if broken == "patient_closes": r["patient_close"] = {"accepted": True}
    if broken == "closed_early": r["mid"]["queue"] = []
    if broken == "never_closed": r["after"] = r["before"]
    assert st.check_t2(r, d)


# ---- T3: sensitive answer cut from the clinician letter, alert with event id present
def t3_art(ev=f"{EP}#5", leak=None):
    alert = adapter.lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": adapter.letter_event_id(ev)})
    return {"clinician_letter": {"notes": f"Problems:\n- {alert}\n" + (leak or ""),
                                 "letter": f"- {alert} [L6]\n", "facts": [{"item_id": "mh_q2", "event_id": ev}]}}


def test_t3_correct(decl):
    assert st.check_t3(t3_art(), decl["S05-T3-sensitive-cut"], st.S05_Q2, st.S05_PHRASES) == []


@pytest.mark.parametrize("broken", ["answer_in_notes", "question_in_notes", "answer_in_letter", "no_alert"])
def test_t3_broken(decl, broken):
    a = t3_art(leak="- thoughts of harming yourself\n" if broken == "answer_in_notes" else
               f"- {st.S05_Q2}\n" if broken == "question_in_notes" else None)
    if broken == "answer_in_letter":
        a["clinician_letter"]["letter"] += "- no thoughts of harming yourself [L7]\n"
    if broken == "no_alert":
        a["clinician_letter"]["letter"] = "- nothing [L6]\n"
    assert st.check_t3(a, decl["S05-T3-sensitive-cut"], st.S05_Q2, st.S05_PHRASES)


# ---- T4: a decline queues, stays open, never a no
def test_t4_correct(decl):
    d = decl["S05-T4-decline"]
    assert st.check_t4(obs([q(d["expect_queue_line"])], answers={"mh_q2": "declined"}), d) == []


@pytest.mark.parametrize("broken", ["no_queue", "closed", "as_no"])
def test_t4_broken(decl, broken):
    d = decl["S05-T4-decline"]
    o = obs([q(d["expect_queue_line"])] if broken != "no_queue" else [], open_=broken != "closed",
            answers={"mh_q2": False if broken == "as_no" else "declined"})
    assert st.check_t4(o, d)


# ---- scoring: passing checks stay pending_review until Physician has checked them
def test_passing_check_is_pending_review_and_not_scored(monkeypatch, decl):
    d = decl["S05-T3-sensitive-cut"]
    res = st.run_declared("S05", [d], None, t3_art())
    assert res == {d["id"]: st.PENDING_REVIEW}
    ok, _ = scorer.scenario_tests(None, {"scenario_tests": [d]}, t3_art())
    assert not ok
    monkeypatch.setattr(st, "REVIEWED", {d["id"]})
    assert scorer.scenario_tests(None, {"scenario_tests": [d]}, t3_art())[0]
