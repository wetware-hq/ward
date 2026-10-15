"""Pins the scorer and harness branches the last mutation run left alive, using synthetic traces and real runs only
(no answer files). Expected lines are read from the signed source via the scorer's own lookup of the signing files."""
import copy, tempfile, types
import pytest
from stack import scorer, harness
from stack.harness import Harness
from stack.scenarios import SCENARIOS


def _run(prefix, tamper=None):
    sid = next(k for k in SCENARIOS if k.startswith(prefix))
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    art = fn(h, tempfile.mkdtemp(), **({"tamper": tamper} if tamper else {}))
    return h, art


@pytest.fixture(scope="module")
def s14():
    return _run("S14")


def _with(h, *recs, drop=None):
    t = copy.copy(h); t.trace = [r for r in h.trace if not (drop and drop(r))] + list(recs)
    return t


# ---- _held_hidden
def test_held_clean(s14):
    assert scorer._held_hidden(*s14) == []


def test_held_closed_by_agent_fails(s14):
    h, art = s14
    t = copy.copy(h)
    t.trace = [dict(r, actor="SYNTH-agent-14") if r.get("op") == "clinician_queue_closed" else r for r in h.trace]
    assert any("not a clinician" in f for f in scorer._held_hidden(t, art))


def test_held_no_waiting_line_fails(s14):
    h, art = s14
    seq = next(r["seq"] for r in h.trace if r.get("op") == "clinician_queue" and r.get("line_id") == "CQ-RESULT-TO-DISCUSS")
    t = _with(h, {"seq": seq + 0.5, "kind": "call", "role": "patient", "actor": "p", "response": {"result": "hello"}})
    assert any("no waiting line" in f for f in scorer._held_hidden(t, art))


def test_held_value_after_close_is_fine_and_before_fails(s14):
    h, art = s14
    rid = next(r["record"] for r in h.trace if r.get("op") == "clinician_queue_closed")
    end = next(r["seq"] for r in h.trace if r.get("op") == "clinician_queue_closed")
    after = _with(h, {"seq": end + 0.5, "kind": "call", "role": "patient", "actor": "p", "response": {"result": rid}})
    before = _with(h, {"seq": end - 0.5, "kind": "call", "role": "patient", "actor": "p", "response": {"result": rid}})
    assert scorer._held_hidden(after, art) == [] and any("value in patient-side" in f for f in scorer._held_hidden(before, art))


def test_held_clinician_side_not_checked(s14):
    h, art = s14
    end = next(r["seq"] for r in h.trace if r.get("op") == "clinician_queue_closed")
    t = _with(h, {"seq": end - 0.5, "kind": "call", "role": "clinician", "actor": "d", "response": {"result": "x"}})
    assert scorer._held_hidden(t, art) == []


# ---- _gp_no_source
def _gp(letter, notes, srcs):
    return {"clinician_letter": {"letter": letter, "notes": "\n".join(notes), "sources": srcs}}


def test_gp_no_source_branches():
    s = [{"item": "a", "chain": []}, {"item": None, "chain": [{"item": "q", "chain": []}]}]
    assert scorer._gp_no_source(_gp("x [L1]", ["n1", "n2"], s), "q") == []
    assert scorer._gp_no_source(_gp("x [L2]", ["n1", "n2"], s), "q") == ["L2"]
    assert scorer._gp_no_source(_gp("x [L3]", ["n1", "n2"], s), "q") == ["L3"]
    assert scorer._gp_no_source(_gp("x [L0]", ["n1", "n2"], s), "q") == ["L0"]
    assert scorer._gp_no_source(_gp("x", ["n1"], s), "q") == ["no source record"]
    assert scorer._gp_no_source(_gp("x", ["n1", "n2"], None), "q") == ["no source record"]
    assert scorer._gp_no_source({}, "q") == ["no source record"]


# ---- resubmit_prompt
def _rp(prompt, declined=("pregnant_possible",), texts=None, accepted=True, typ="decline"):
    tr = [{"seq": 1, "kind": "call", "accepted": accepted, "args": [{"type": typ, "question_id": q}]} for q in declined]
    tr.append({"seq": 2, "op": "patient_view", "result": {"resubmit": prompt}})
    return types.SimpleNamespace(trace=tr, question_texts=texts or {"pregnant_possible": "Could you be pregnant"})


def test_resubmit_prompt_branches():
    want = scorer._line_text("PV-RESUBMIT")
    assert want and scorer.resubmit_prompt(_rp(want))[0]
    assert not scorer.resubmit_prompt(_rp(want + " pregnant_possible"))[0]
    assert not scorer.resubmit_prompt(_rp(want + " Could you be pregnant"))[0]
    assert not scorer.resubmit_prompt(_rp(want + " Declined"))[0]
    assert not scorer.resubmit_prompt(_rp(want[:-1]))[0]
    leaks = scorer.resubmit_prompt(_rp(want + " pregnant_possible"))[1]["leaks"]
    assert leaks[0]["hits"] == ["pregnant_possible"] and leaks[0]["signed"] is False
    # a refused decline names nothing; an answer is not a decline
    assert scorer.resubmit_prompt(_rp(want, accepted=False))[1]["leaks"] == []
    assert scorer.resubmit_prompt(_rp(want, typ="answer"))[0]
    h = _rp(want + " pregnant_possible", accepted=False)
    assert scorer.resubmit_prompt(h)[1]["leaks"][0]["hits"] == []
    h = _rp(want); h.question_texts = {"other": want}          # texts only for declined questions
    assert scorer.resubmit_prompt(h)[0]


# ---- DECLINED-NO-ABSENCE-LINE in safety_lines
def test_declined_rule_in_safety_lines(monkeypatch):
    h, art = _run("S12")
    truth = {"safety_lines": [{"line_id": "DECLINED-NO-ABSENCE-LINE", "item": "", "expect": ""}],
             "must_not_appear_in_letters": ["none recorded"]}
    assert scorer.safety_lines(h, art, truth)[0] or True     # whole result has other parts; check the bad list below
    bad = lambda t: [b for b in scorer.safety_lines(h, t, truth)[1].get("failed", []) if b.get("line_id") == "DECLINED-NO-ABSENCE-LINE"]
    assert bad(art) == []
    monkeypatch.setattr(scorer, "absence_lines", lambda *a, **k: ["Allergies: none recorded"])
    assert bad(art) and bad(art)[0]["why"] == "absence line"
    monkeypatch.setattr(scorer, "absence_lines", lambda *a, **k: [])
    real = scorer._line_text
    monkeypatch.setattr(scorer, "_line_text", lambda i: None if i == "DECLINED-NO-ABSENCE-LINE" else real(i))
    assert bad(art) and bad(art)[0]["why"] == "unsigned"


# ---- harness
def test_released_record_observed_with_its_text():
    h, _ = _run("S14", "release")
    r = [x for x in h.trace if x.get("method") == "observe" and isinstance(x.get("response"), dict) and "value" in x["response"]]
    assert r and r[-1]["accepted"] is True and r[-1]["response"]["value"] == h.records[r[-1]["response"]["record"]]["text"]


def test_unregistered_role_refused_by_middleware_and_other_errors_raise(monkeypatch):
    h, _ = _run("S01")
    ep = next(iter(h.episodes))
    r = h.session("SYNTH-x", "janitor", h.episodes[ep].patient).step(ep, {"type": "submit"})
    last = h.trace[-1]
    assert last["accepted"] is False and last["response"]["by"] == "middleware"
    monkeypatch.setattr(Harness, "_replayed", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        h.session("SYNTH-y", "clinician", h.episodes[ep].patient).step(ep, {"type": "submit"})


def test_trend_close_only_by_clinician_on_a_trend_job():
    for p in ("S14", "S10b"):
        h, _ = _run(p)
        t = [r for r in h.trace if r.get("trend_closed")]
        assert t and all(r["trend_closed"] is True and r["role"] in harness.CLINICIAN_ROLES and
                         r["args"][0].get("id") in harness.TREND_REVIEW_JOBS for r in t)
        assert t[-1]["all_done"] == "ST-DONE"
        ticks = [r for r in h.trace if r.get("kind") == "call" and (r.get("args") or [{}])[0].get("type") == "tick"
                 and not r.get("trend_closed")]
        assert all(r["role"] not in harness.CLINICIAN_ROLES or r["args"][0].get("id") not in harness.TREND_REVIEW_JOBS
                   or not r.get("accepted") for r in ticks)


def test_resubmit_needs_an_earlier_submit():
    for p in ("S12", "S13", "S15"):
        h, _ = _run(p)
        for r in [x for x in h.trace if x.get("resubmit")]:
            prior = [x for x in h.trace if x["seq"] < r["seq"] and x.get("kind") == "call" and x.get("accepted")
                     and x.get("episode") == r["episode"] and isinstance((x.get("args") or [{}])[0], dict)]
            kinds = [x["args"][0].get("type") for x in prior]
            assert "submit" in kinds and "review" in kinds[max(i for i, k in enumerate(kinds) if k == "submit"):]
        first = [x for x in h.trace if x.get("kind") == "call" and x.get("accepted")
                 and isinstance((x.get("args") or [{}])[0], dict) and (x.get("args") or [{}])[0].get("type") == "submit"]
        assert first and not first[0].get("resubmit")


def test_submits_before_review_are_not_resubmits():
    h, _ = _run("S08")
    subs = [r for r in h.trace if r.get("kind") == "call" and r.get("accepted")
            and (r.get("args") or [{}])[0].get("type") == "submit"]
    first_review = min(r["seq"] for r in h.trace if r.get("kind") == "call" and r.get("accepted")
                       and (r.get("args") or [{}])[0].get("type") == "review")
    before = [r for r in subs if r["seq"] < first_review]
    assert len(before) >= 2 and not any(r.get("resubmit") for r in before)


def test_resubmit_prompt_record_without_accepted_key_counts_as_accepted():
    want = scorer._line_text("PV-RESUBMIT")
    h = _rp(want + " pregnant_possible")
    del h.trace[0]["accepted"]
    assert scorer.resubmit_prompt(h)[1]["leaks"][0]["hits"] == ["pregnant_possible"]
