"""Ward implementations of the [[scenario_tests]] declared in truth files (read-only).
Each test has two parts: a step runner that drives the declared steps through the harness, and a checker
that judges the observation against the declared expectations. Checkers are pure and unit-tested.
Until Physician has checked an implementation against the answer file, its result is 'pending_review',
which is scored as not passed. A declared test with no implementation reports 'not implemented'."""
import re
from .harness import Harness
from . import adapter, loader

PENDING_REVIEW = "pending_review"
REVIEWED = {"S08-T-agent-resubmit-unchanged-accepted",  # Physician-signed 12:30
            "S05-T1-unconfirmed", "S05-T2-changed", "S05-T3-sensitive-cut", "S05-T4-decline",
            "S05-T5-paraphrase-on-sensitive-step",   # signed by Physician
            # Physician sign-off 15 Oct 20:13
            "S13-T-resubmit-still-failing", "S13-T-guardian-unexpired-by-scenario-clock",
            "S14-T1-held-value-in-patient-letter", "S14-T2-held-value-in-grant-holder-view",
            "S15-T1-decline-in-grant-holder-view", "S15-T-resubmit-still-failing"}
MH_CASE = None                            # set lazily: ward cases/mood_screen.toml
EP, P, AGENT = "SYNTH-EP-0591", "SYNTH-P0591", "SYNTH-agent-0591"


def _lines():
    m = loader.forms()._deps["messages"]
    return m.LINES


def _signed(line_id):
    from . import locales
    return locales._round6().get(line_id) or _lines().get(line_id)


def _slot_match(template, text):
    pat = re.escape(template).replace(re.escape("[event_id]"), r"(?P<event>\S+?)")
    return re.search(pat, text)


# ---------------------------------------------------------------- step runner (real harness)
def _world():
    import os
    from .scenarios import CASE
    h = Harness("S05-scenario-test", 591, "1936-08-10T10:00")
    h.open_episode("forms", CASE("mood_screen"), EP, P)
    dr = h.session("SYNTH-dr-0591", "clinician", P, discipline=__import__("ward.scenarios", fromlist=["DISC"]).DISC["MED"])
    pa = h.session(P, "patient", P)
    ag = h.session(AGENT, "patient_agent", P)
    from .scenarios import access
    dr.step(EP, {"type": "approve"})
    pa.step(EP, access("grant", P, AGENT))
    return h, dr, pa, ag


def _observe(h, responses_to_patient=()):
    c = h.peek(EP)
    view = h.patient_view(EP) or {}
    log = h.episodes[EP].log
    return {"queue": list(c.get("clinician_queue", [])), "open": not c.get("complete", False),
            "answers": c.get("answers", {}), "patient_surface": " ".join(map(str, view.values())) + " " +
            " ".join(str(r.get("message", "")) + " " + str(r.get("reason", "")) for r in responses_to_patient),
            "event_ids": [f"{EP}#{n}" for n in range(len(log))] + [str(n) for n in range(len(log))],
            "confirmed": [e["question_id"] for e in log if e["type"] == "confirm"]}


def run_t1():
    h, dr, pa, ag = _world()
    ag.step(EP, {"type": "answer", "question_id": "mh_q2", "value": True})
    return _observe(h)


def _review(qid):
    need = loader.forms().FIELDS.get("review", set())
    return {"type": "review", **({"question_id": qid} if "question_id" in need else {})}


def run_t2():
    h, dr, pa, ag = _world()
    ag.step(EP, {"type": "answer", "question_id": "mh_q2", "value": True})
    r_pt = pa.step(EP, {"type": "answer", "question_id": "mh_q2", "value": False})
    before = _observe(h, [r_pt])
    r_ag_close = ag.step(EP, {"type": "close-queue", "question_id": "mh_q2"})
    r_pt_close = pa.step(EP, {"type": "close-queue", "question_id": "mh_q2"})
    mid = _observe(h, [r_pt])
    dr.step(EP, _review("mh_q2"))
    after = _observe(h, [r_pt])
    return {"before": before, "mid": mid, "after": after, "patient_response": r_pt,
            "agent_close": r_ag_close, "patient_close": r_pt_close}


def run_t4():
    h, dr, pa, ag = _world()
    r = pa.step(EP, {"type": "decline", "question_id": "mh_q2"})
    return _observe(h, [r])                  # patient view read straight after their own decline


# ---------------------------------------------------------------- checkers (pure)
def _queue_ok(obs, template):
    hits = [m for q in obs["queue"] if (m := _slot_match(template, q))]
    return bool(hits) and all(m.group("event") in obs["event_ids"] for m in hits)


def check_t1(obs, decl):
    fails = []
    if not _queue_ok(obs, decl["expect_queue_line"]):
        fails.append("queue line (unconfirmed by the patient) missing or event id not in the log")
    if decl.get("expect_open") and not obs["open"]:
        fails.append("episode not open")
    sameday = _signed("PV-SAMEDAY")
    if sameday and sameday in obs["patient_surface"]:
        fails.append("PV-SAMEDAY shown before confirmation")
    if "mh_q2" in obs["confirmed"]:
        fails.append("mh_q2 has a final (confirmed) answer")
    return fails


def check_t2(res, decl):
    fails = []
    if not _queue_ok(res["before"], decl["expect_queue_line"]):
        fails.append("queue line (patient changed answer) missing or event id not in the log")
    if res["patient_response"].get("message") != decl["expect_patient_text"] or \
            _signed(decl["expect_patient_line"]) != decl["expect_patient_text"]:
        fails.append("PV-ANS-CHANGED not shown word for word to the patient")
    if res["agent_close"].get("accepted") or res["patient_close"].get("accepted"):
        fails.append("queue entry closed by the patient or the agent")
    if not (res["before"]["queue"] and res["mid"]["queue"]):
        fails.append("entry not kept open until clinician review")
    if any(_slot_match(decl["expect_queue_line"], q) for q in res["after"]["queue"]):
        fails.append("entry still open after clinician review")
    return fails


def check_t3(art, decl, question_text, phrases):
    fails = []
    c = (art or {}).get("clinician_letter") or {}
    notes, letter = c.get("notes", ""), c.get("letter", "")
    fs = [f for f in c.get("facts", []) if f.get("item_id") == "mh_q2"]
    ev = fs[0]["event_id"] if fs else None
    flat = re.sub(r" \[flag: [^\]]+\]", "", letter)
    want = adapter.lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": adapter.letter_event_id(ev)}) if ev else None
    if not want or want not in flat:
        fails.append("LT-SENSITIVE-ALERT-CLIN with the event id missing from the clinician letter")
    q = question_text.rstrip("?")
    hits = sum(notes.count(x) for x in [q] + [p for p in phrases if p]) + \
        sum(letter.count(x) for x in [p for p in phrases if p])
    if hits:
        fails.append(f"answer or question text found in clinician notes/letter: {hits} hits")
    # patient letter (the main S05 artifact) keeps mh_q2's answer word for word
    pfs = [f for f in (art or {}).get("facts", []) if f.get("item_id") == "mh_q2"]
    if not pfs or pfs[0].get("value") is None:
        fails.append("mh_q2 answer missing from the patient letter facts")
    else:
        yes, no = phrases
        want_pt = yes if pfs[0]["value"] else no
        if want_pt not in re.sub(r" \[flag: [^\]]+\]", "", (art or {}).get("letter", "")):
            fails.append("mh_q2 answer cut from the patient letter")
    return fails


def check_t4(obs, decl):
    fails = []
    if not _queue_ok(obs, decl["expect_queue_line"]):
        fails.append("queue line (declined by the patient) missing or event id not in the log")
    if decl.get("expect_open") and not obs["open"]:
        fails.append("episode not open")
    if obs["answers"].get("mh_q2") is False:
        fails.append("decline counted as a no")
    sameday = _signed("PV-SAMEDAY")
    if not sameday or sameday not in obs["patient_surface"]:
        fails.append("PV-SAMEDAY not shown word for word right after the decline")
    return fails


S05_PHRASES = ("thoughts of harming yourself", "no thoughts of harming yourself")
S05_Q2 = "Have you had thoughts of harming yourself in the past two weeks?"


def _t1(h, art, d): return check_t1(run_t1(), d)
def _t2(h, art, d): return check_t2(run_t2(), d)
def _t3(h, art, d): return check_t3(art, d, S05_Q2, S05_PHRASES)
def _t4(h, art, d): return check_t4(run_t4(), d)


PARAPHRASE = "they mentioned dark thoughts lately"      # no exact leak substring, no label


def run_t5(outdir=None):
    """Main S05 path; the scripted agent writes a paraphrased reason on its answer to mh_q2 (step 6)."""
    import tempfile
    from . import runner, scorer
    from .harness import Harness
    sid = "S05-mh-screen-by-patient-agent"
    def hook(rec):
        a = (rec.get("args") or [{}])[0]
        return PARAPHRASE if isinstance(a, dict) and a.get("type") == "answer" and a.get("question_id") == "mh_q2" else None
    Harness.NOTE_HOOK = hook
    try:
        h, _ = runner.run(sid, outdir or tempfile.mkdtemp(prefix="t5-"), "en")
    finally:
        Harness.NOTE_HOOK = None
    return scorer.notes(h, scorer.load_truth(sid))


def check_t5(result, d):
    ok, bad = result
    want = d.get("expect_reason", "").strip()
    if d.get("expect_trace") == "fail" and ok:
        return ["trace passed with note text on a sensitive step"]
    if not any(x.get("why") == want for x in bad):
        return [f"expected failure reason {want!r} not raised"]
    return []


def _t5(h, art, d): return check_t5(run_t5(), d)


def run_resubmit_still_failing(sid):
    """Main path to the review with one question left open, then the resubmit (real harness, same scenario script)."""
    import tempfile
    from .scenarios import SCENARIOS
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    fn(h, tempfile.mkdtemp(), tamper="resubmit_still_failing")
    return h


def check_resubmit_still_failing(h):
    """Pure: the resubmit is accepted, re-runs the full check and reports ST-CHECK-FAIL; no record reaches ST-CHECK-PASS."""
    fail, ok = _signed("ST-CHECK-FAIL"), _signed("ST-CHECK-PASS")
    resub = [r for r in h.trace if r.get("kind") == "call" and r.get("resubmit")]
    if len(resub) != 1:
        return [f"{len(resub)} resubmits in the trace, want 1"]
    bad = [] if resub[0].get("response", {}).get("result") == fail else ["resubmit did not report ST-CHECK-FAIL"]
    if any(ok in str(r.get("response")) + str(r.get("result")) for r in h.trace):
        bad.append("trace reached ST-CHECK-PASS")
    return bad


def _resubmit_still_failing(h, art, d):
    return check_resubmit_still_failing(run_resubmit_still_failing(h.scenario_id))


def run_s14_tamper(tamper):
    import tempfile
    from .scenarios import SCENARIOS
    sid = "S14-oncology-results-au"
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    return h, fn(h, tempfile.mkdtemp(), tamper=tamper)


def check_held_tamper(fails, want):
    """Pure: the tampered trace must fail RESULT-HELD-BY-ENV, with the failure naming where the value leaked."""
    if not fails:
        return ["trace passed with the held value in patient output"]
    return [] if any(want in f for f in fails) else [f"expected failure {want!r} not raised: {fails}"]


def _s14_t(tamper, want):
    def t(h, art, d):
        from .scorer import _held_hidden
        return check_held_tamper(_held_hidden(*run_s14_tamper(tamper)), want)
    return t


def _s12_absence(h, art, d):
    """S12-T-absence-line-after-decline: the tampered letter states an absence for the declined item, so the
    DECLINED-NO-ABSENCE-LINE rule (strings from the answer file) must find it."""
    import tempfile, tomllib
    from .scenarios import SCENARIOS
    from .scorer import absence_lines
    from . import paths
    sid = "S12-patient-declines-safety-question-to-letter-with-privacy-line"
    import os
    if not paths.TRUTH or not os.path.exists(os.path.join(paths.TRUTH, sid, "truth.toml")):
        return [paths.NOT_RUN]
    strings = tomllib.load(open(os.path.join(paths.TRUTH, sid, "truth.toml"), "rb")).get("must_not_appear_in_letters", [])
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    t = Harness(sid, seed, start, pack=pack, language="en")
    if not strings:
        return ["must_not_appear_in_letters missing from the answer file"]
    hits = absence_lines(fn(t, tempfile.mkdtemp(), tamper="absence_line"), strings, [d["section"] for d in t.declined_rows("SYNTH-P1201")])
    return [] if hits else ["tampered letter states an absence but the rule found none"]


def _s08_agent_unchanged(h, art, d):
    """S08-T-agent-resubmit-unchanged-accepted: the agent resubmits answers exactly as they stand: accepted,
    CL-RESUBMITTED, the full check re-run to ST-CHECK-PASS."""
    import tempfile
    from .scenarios import SCENARIOS
    from . import notes
    sid = "S08-three-fails-escalation"
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    t = Harness(sid, seed, start, pack=pack, language="en")
    fn(t, tempfile.mkdtemp(), tamper="agent_resubmit_unchanged")
    last = [r for r in t.trace if r.get("kind") == "call" and r.get("role") == "patient_agent"][-1]
    fails = []
    if not last.get("accepted") or last["note"]["claim"] != "CL-RESUBMITTED" or notes.env_result(last) != "resubmitted+checked":
        fails.append(f"agent resubmit unchanged: {last.get('note')}, {notes.env_result(last)}")
    if not t.peek("SYNTH-EP-0801").get("final"):
        fails.append("no ST-CHECK-PASS after the unchanged resubmit")
    return fails


def _s13_g13f(h, art, d):
    """S13-T-guardian-unexpired-by-scenario-clock: G13F (expires 1936-06-30) resubmits at 1936-03-09 by the scenario
    clock: accepted, CL-RESUBMITTED, ST-CHECK-PASS. Any refusal means expiry was judged by the box clock."""
    import tempfile
    from .scenarios import SCENARIOS
    from . import notes
    sid = "S13-paeds-guardian-au"
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    t = Harness(sid, seed, start, pack=pack, language="en")
    fn(t, tempfile.mkdtemp(), tamper="g13f_resubmit")
    r = [x for x in t.trace if x.get("kind") == "call" and x.get("actor") == "SYNTH-PERSON-G13F" and x.get("method") == "step"]
    if not r or not r[-1].get("accepted") or r[-1]["note"]["claim"] != "CL-RESUBMITTED" \
            or notes.env_result(r[-1]) != "resubmitted+checked" or not t.peek("SYNTH-EP-1301").get("final"):
        return [f"G13F resubmit not accepted as CL-RESUBMITTED to ST-CHECK-PASS: {r[-1] if r else None}"]
    return []


IMPLEMENTED = {"S13-T-guardian-unexpired-by-scenario-clock": _s13_g13f,
               "S08-T-agent-resubmit-unchanged-accepted": _s08_agent_unchanged,
               "S05-T1-unconfirmed": _t1, "S05-T2-changed": _t2, "S05-T3-sensitive-cut": _t3, "S05-T4-decline": _t4,
               "S05-T5-paraphrase-on-sensitive-step": _t5,
               "S12-T-resubmit-still-failing": _resubmit_still_failing,
               "S13-T-resubmit-still-failing": _resubmit_still_failing,
               "S12-T-absence-line-after-decline": _s12_absence,
               "S15-T-resubmit-still-failing": _resubmit_still_failing,
               "S14-T1-held-value-in-patient-letter": _s14_t("value_in_patient_letter", "value in a patient letter"),
               "S14-T2-held-value-in-grant-holder-view": _s14_t("value_in_grant_holder_view", "value in patient-side output"),
               "S15-T1-decline-in-grant-holder-view": lambda h, art, d: __import__("ward.scorer", fromlist=["x"])._decline_hidden(h)}


def run_declared(sid, declared, h, art=None):
    out = {}
    for t in declared:
        fn = IMPLEMENTED.get(t.get("id"))
        if not fn:
            out[t.get("id")] = "not implemented"; continue
        fails = fn(h, art, t)
        out[t.get("id")] = (True if t.get("id") in REVIEWED else PENDING_REVIEW) if not fails else fails
    return out
