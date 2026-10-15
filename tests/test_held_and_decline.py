"""S14 held results and S15 sensitive decline: the clean run passes each check; each tamper fails it on its own.
S13-S15 truth folders have no patient_wording.md yet, so the truth is read from truth.toml directly here."""
import copy, json, os, tomllib, pytest
from stack import runner, scorer, harness, paths
from stack.harness import Harness
from stack.scenarios import s14, s15, SCENARIOS
from truthgate import missing_truth, truth_path

S14, S15 = "S14-oncology-results-au", "S15-obstetrics-au"


def truth(sid):
    p = truth_path(sid, "truth.toml")
    if not os.path.exists(p):
        missing_truth(sid)
    t = tomllib.load(open(p, "rb"))
    t["wording"] = scorer.parse_wording("")
    return t


def fails(h, art, t, line_id):
    rows = [r for r in t["safety_lines"] if r.get("line_id") == line_id]
    assert rows, line_id
    ok, why = scorer.safety_lines(h, art, dict(t, safety_lines=rows))
    return [] if ok else why["failed"]


def run(sid, fn, tmp_path, **kw):
    seed, start, pack, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    return h, fn(h, str(tmp_path), **kw)


def test_s14_clean_run_holds(tmp_path):
    t = truth(S14)
    h, art = run(S14, s14, tmp_path)
    assert fails(h, art, t, "RESULT-HELD-BY-ENV") == []
    obs = [c for c in h.calls() if c["role"] == "patient"][0]["response"]
    assert obs["result_waiting"] == scorer._line_text("PV-RESULT-WAITING") and "SYNTH-REC-1406" not in json.dumps(obs)
    agent = [c for c in h.calls() if c["args"] and c["args"][0].get("type") == "close_sameday"]
    assert agent[0]["response"]["line_id"] == "RF-RESULT-HELD" and agent[1]["accepted"]
    assert art["tool"] == "figures" and art["points"] == 3                  # clinician figure unaffected


def test_s14_release_before_discussion_fails(tmp_path):
    t = truth(S14)
    h, art = run(S14, s14, tmp_path, tamper="release")
    assert any("no waiting line" in f["why"][0] for f in fails(h, art, t, "RESULT-HELD-BY-ENV"))


def test_s14_agent_close_fails(tmp_path, monkeypatch):
    t = truth(S14)
    monkeypatch.setattr(harness, "CLINICIAN_ROLES", ("clinician", "clinician_agent"))
    h, art = run(S14, s14, tmp_path)
    assert any("not a clinician in person" in w for f in fails(h, art, t, "RESULT-HELD-BY-ENV") for w in f["why"])


def test_s14_value_in_patient_letter_fails(tmp_path):
    t = truth(S14)
    h, art = run(S14, s14, tmp_path)
    value = h.records["SYNTH-REC-1406"]["value"]
    art = dict(art, patient_letter={"letter": f"Your scan: {value}"})
    assert any("patient letter" in w for f in fails(h, art, t, "RESULT-HELD-BY-ENV") for w in f["why"])


def test_s14_value_in_grant_holder_view_fails(tmp_path):
    t = truth(S14)
    h, art = run(S14, s14, tmp_path)
    obs = [c for c in h.trace if c.get("kind") == "call" and c["role"] == "patient"][0]
    leak = dict(copy.deepcopy(obs), role="patient_agent", actor="SYNTH-agent-x",
                response={"result": h.records["SYNTH-REC-1406"]["value"]})
    h.trace.insert(h.trace.index(obs) + 1, leak)
    assert any("value in patient-side output" in w for f in fails(h, art, t, "RESULT-HELD-BY-ENV") for w in f["why"])


def test_s14_held_kind_without_hold_fails(tmp_path, monkeypatch):
    t = truth(S14)
    monkeypatch.setattr(Harness, "_hold", lambda self, rid, p: None)
    h, art = run(S14, s14, tmp_path)
    assert any("no CQ-RESULT-TO-DISCUSS" in w for f in fails(h, art, t, "RESULT-HELD-BY-ENV") for w in f["why"])


def test_s15_clean_run_hides_decline(tmp_path):
    t = truth(S15)
    h, art = run(S15, s15, tmp_path)
    assert fails(h, art, t, "DECLINE-HIDDEN-FROM-GRANT-HOLDERS") == []
    assert fails(h, art, t, "GP-LETTER-NO-SOURCE") == []
    gh = [c for c in h.calls() if c["role"] == "patient_agent" and c["method"] == "observe"][0]["response"]
    assert "pregnant" not in json.dumps(gh) and gh.get("flags") == []
    pt = h.peek("SYNTH-EP-1501")
    assert any("question" in f for f in pt["flags"])                       # the treating team still sees it


def test_s15_decline_visible_to_grant_holder_fails(tmp_path):
    t = truth(S15)
    h, art = run(S15, s15, tmp_path, tamper="grant_holder_sees_decline")
    assert fails(h, art, t, "DECLINE-HIDDEN-FROM-GRANT-HOLDERS")


def test_s15_gp_line_from_declined_question_fails(tmp_path):
    t = truth(S15)
    h, art = run(S15, s15, tmp_path)
    c = art["clinician_letter"]
    n = len(c["notes"].splitlines()) + 1
    c["notes"] += "- Pregnancy status not recorded\n"; c["refs"].append([])
    c["sources"].append({"from": "summary", "item": None, "chain": [{"from": "status", "item": "pregnant_possible"}]})
    c["letter"] += f"\n- Pregnancy status not recorded [L{n}]\n"
    assert fails(h, art, t, "GP-LETTER-NO-SOURCE") == [{"line_id": "GP-LETTER-NO-SOURCE", "why": [f"L{n}"]}]


# ---- gate units
def test_held_kinds_from_pack_data(tmp_path):
    assert "imaging report" in harness.held_kinds()
    (tmp_path / "a.toml").write_text('held_result_kinds = ["x"]\n')
    (tmp_path / "b.toml").write_text('held_result_kinds = ["y"]\n')
    (tmp_path / "c.txt").write_text('held_result_kinds = ["z"]\n')
    assert harness.held_kinds(str(tmp_path)) == {"x", "y"}
    assert harness.held_kinds(str(tmp_path / "none")) == set()


def test_gate_view_and_records(tmp_path):
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    P = "SYNTH-FAKEP1"
    h.record_result("SYNTH-lab", "SYNTH-R1", P, "imaging report", "t", "SECRET TEXT", "", kind="imaging report")
    h.record_result("SYNTH-lab", "SYNTH-R2", P, "lab", "t", 5, "u", kind="lab")
    h.record_result("SYNTH-lab", "SYNTH-R3", P, "lab", "t", 6, "u")
    assert h.held_open(P) == ["SYNTH-R1"] and h.held_open("SYNTH-OTHER") == []
    wait = h._line("PV-RESULT-WAITING")
    v = h.gate_view(P, {"a": "x SECRET TEXT", "b": ["SYNTH-R1", "ok"], "c": 3, "d": {"e": "fine"}})
    assert v == {"a": wait, "b": [wait, "ok"], "c": 3, "d": {"e": "fine"}, "result_waiting": wait}
    assert h.gate_view(P, ["SYNTH-R1"]) == [wait]
    assert h.gate_view("SYNTH-OTHER", {"a": "SECRET TEXT"}) == {"a": "SECRET TEXT"}
    assert set(h.visible_records(P, True)) == {"SYNTH-R2", "SYNTH-R3"}
    assert set(h.visible_records(P, False)) == {"SYNTH-R1", "SYNTH-R2", "SYNTH-R3"}
    q = [r for r in h.trace if r.get("op") == "clinician_queue"]
    assert len(q) == 1 and q[0]["record"] == "SYNTH-R1" and "SYNTH-R1" in q[0]["text"]
    h.held["SYNTH-R1"]["open"] = False
    assert h.gate_view(P, {"a": "SECRET TEXT"}) == {"a": "SECRET TEXT"}


def test_close_and_submit_gate():
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    P, EP = "SYNTH-FAKEP1", "SYNTH-FAKE-EP1"
    h.open_episode("orders", os.path.join(os.path.dirname(__file__), "fixtures", "fake_list.toml"), EP, P)
    h.record_result("SYNTH-lab", "SYNTH-R1", P, "imaging report", "t", "SECRET", "", kind="imaging report")
    dr = h.session("SYNTH-dr", "clinician", P, discipline="medicine")
    for role in ("clinician_agent", "patient", "patient_agent"):
        x = h.session("SYNTH-x", role, P)
        n = len(h.trace)
        r = x.step(EP, {"type": "close_sameday", "record": "SYNTH-R1"})
        assert r["line_id"] == "RF-RESULT-HELD" and r["accepted"] is False and h.held_open(P) == ["SYNTH-R1"] and len(h.trace) == n + 1
    r = dr.step(EP, {"type": "submit"})
    assert r["line_id"] == "RF-RESULT-HELD" and r["accepted"] is False
    assert dr.step(EP, {"type": "close_sameday", "record": "SYNTH-R1"}) == {"accepted": True, "closed": "SYNTH-R1", "queue": "CQ-RESULT-TO-DISCUSS", "clinician": dr.actor}
    assert h.held_open(P) == [] and h.trace[-2]["op"] == "clinician_queue_closed"
    assert dr.step(EP, {"type": "submit"}).get("line_id") != "RF-RESULT-HELD"
    assert dr.step(EP, {"type": "close_sameday", "record": "SYNTH-NOPE"}).get("closed") is None


def test_held_not_in_patient_side_bundle():
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    P, EP = "SYNTH-FAKEP1", "SYNTH-FAKE-EP1"
    h.open_episode("orders", os.path.join(os.path.dirname(__file__), "fixtures", "fake_list.toml"), EP, P)
    h.record_result("SYNTH-lab", "SYNTH-R1", P, "imaging report", "t", "SECRET", "", kind="imaging report")
    pat = h.export_bundle(EP, audit=True, patient_side=True)
    clin = h.export_bundle(EP, audit=True)
    assert "SYNTH-R1" not in pat["records"] and pat["held"] == ["SYNTH-R1"]
    assert "SYNTH-R1" in clin["records"] and clin["held"] == []


def test_adapter_skips_held_ticks_and_declined_sensitive_for_clinicians():
    from stack import adapter
    log = [{"type": "tick", "id": "j", "evidence": "R1", "role": "n", "discipline": None, "timestamp": "T"},
           {"type": "tick", "id": "k", "evidence": "R2", "role": "n", "discipline": None, "timestamp": "T"}]
    b = {"episode_id": "SYNTH-E", "kind": "orders", "blocks": [], "export": {"all_done": True, "log": log},
         "interpreter_events": [], "items": [], "records": {}, "case": None}
    assert [f["record"] for f in adapter.facts(dict(b, held=["R1"]))] == ["R2"]
    assert [f["record"] for f in adapter.facts(b)] == ["R1", "R2"]
    f = {"item_id": "s", "event_id": "E#1", "text": "S?", "sensitive": True, "status": "declined", "value": None,
         "safety": True, "on_behalf": "", "interpreter": False}
    assert adapter.letter_lines([f], "clinician", {}) == []
    assert adapter.letter_lines([f], "patient", {}) != []
    assert adapter.letter_lines([dict(f, status="answered", value=True)], "clinician", {}) != []


def test_gate_grant_holder_units(tmp_path):
    import shutil
    from stack import locales
    form = tmp_path / "f.toml"
    shutil.copy(os.path.join(os.path.dirname(__file__), "fixtures", "fake_form.toml"), form)
    (tmp_path / "f.sensitive.toml").write_text('sensitive = ["fake_b"]\n')
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    P, EP = "SYNTH-FAKEP1", "SYNTH-FAKE-EP1"
    h.open_episode("forms", str(form), EP, P)
    h.session("SYNTH-dr", "clinician", P, discipline="medicine").step(EP, {"type": "approve"})
    pa = h.session(P, "patient", P)
    obj = {"fake_b": "x", "k": ["question 2 alert", "question 12", "fine"], "t": "Is this fake question B", "o": 1}
    assert h.gate_grant_holder(P, obj) == obj                             # nothing declined yet
    pa.step(EP, {"type": "decline", "question_id": "fake_a"})               # declined but not sensitive
    assert h.gate_grant_holder(P, obj) == obj
    pa.step(EP, {"type": "decline", "question_id": "fake_b"})
    bp = locales.line("PV-BEFORE-PROC").split("[")[0] + "x"
    out = h.gate_grant_holder(P, dict(obj, b=bp, l=[bp, "ok"]))
    assert out == {"k": ["question 12", "fine"], "o": 1, "l": ["ok"]}
    assert h.declined_sensitive(P) == ({"fake_b"}, {"Is this fake question B?"}, {2})
    assert h.declined_sensitive("SYNTH-OTHER") == (set(), set(), set())
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})   # answered after all: shown
    assert h.gate_grant_holder(P, obj) == obj


def test_line_fill():
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    assert h._line_fill("XX-NOPE") == "ERR:xx-nope"
    assert "SYNTH-R9" in h._line_fill("CQ-RESULT-TO-DISCUSS", event_id="SYNTH-R9")


def _fake_held_h(trace):
    from types import SimpleNamespace
    return SimpleNamespace(trace=[dict(t, seq=i) for i, t in enumerate(trace)])


def test_held_hidden_unit_roles_and_unicode():
    from stack import scorer, locales
    wait = locales.line("PV-RESULT-WAITING")
    base = [{"op": "session", "actor": "SYNTH-dr", "role": "clinician"},
            {"op": "session", "actor": "SYNTH-pa", "role": "patient"},
            {"op": "record_result", "record": "SYNTH-R9", "result_kind": "imaging report", "value": "Café nodule"},
            {"op": "clinician_queue", "line_id": "CQ-RESULT-TO-DISCUSS", "record": "SYNTH-R9"}]
    clin = {"kind": "call", "role": "clinician", "response": {"v": "Café nodule"}}
    assert scorer._held_hidden(_fake_held_h(base + [clin]), {}) == []           # clinician sees the value
    leak = {"kind": "call", "role": "patient", "response": {"v": "Café nodule", "w": wait}}
    assert scorer._held_hidden(_fake_held_h(base + [leak]), {})                   # non-ASCII value still caught
    ok = {"kind": "call", "role": "patient", "response": {"w": wait}}
    assert scorer._held_hidden(_fake_held_h(base + [ok]), {}) == []
    sess = {"op": "session", "actor": "SYNTH-pa2", "role": "patient"}           # not a call: no waiting line needed
    assert scorer._held_hidden(_fake_held_h(base + [sess]), {}) == []


def test_gp_no_source_needs_a_source_record():
    from stack import scorer
    assert scorer._gp_no_source({"clinician_letter": {"notes": "a\nb"}}, "x") == ["no source record"]
    assert scorer._gp_no_source({"clinician_letter": {"notes": "a\nb", "sources": [[]]}}, "x") == ["no source record"]


def _declined_form(tmp_path):
    import shutil
    form = tmp_path / "f.toml"
    shutil.copy(os.path.join(os.path.dirname(__file__), "fixtures", "fake_form.toml"), form)
    (tmp_path / "f.sensitive.toml").write_text('sensitive = ["fake_b"]\n')
    h = Harness("FAKE", 1, "1937-01-01T08:00")
    P, EP = "SYNTH-FAKEP1", "SYNTH-FAKE-EP1"
    h.open_episode("forms", str(form), EP, P)
    h.session("SYNTH-dr", "clinician", P, discipline="medicine").step(EP, {"type": "approve"})
    return h, P, EP


def test_grant_holder_gate_spares_patient_and_clinician(tmp_path):
    h, P, EP = _declined_form(tmp_path)
    pa = h.session(P, "patient", P)
    pa.step(EP, {"type": "decline", "question_id": "fake_b"})
    for role, kept in (("patient", True), ("clinician", True), ("patient_agent", False)):
        s = h.session("SYNTH-x" + role, role, P, **({"discipline": "medicine"} if role == "clinician" else {}))
        h._out(s, {"episode": EP}, {"q": "fake_b"})
        assert ("q" in h.trace[-1]["response"]) is kept, role


def test_decline_hidden_counts_only_declined_sensitive(tmp_path):
    from stack import scorer
    h, P, EP = _declined_form(tmp_path)
    pa = h.session(P, "patient", P)
    pa.step(EP, {"type": "decline", "question_id": "fake_a"})                 # declined, not sensitive
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})  # sensitive, answered
    ag = h.session("SYNTH-ag", "patient_agent", P)
    h._out(ag, {"episode": EP, "role": "patient_agent", "actor": "SYNTH-ag"}, {"q": "fake_a fake_b"})
    call = h.trace[-1]
    assert call["role"] == "patient_agent" and scorer._decline_hidden(h) == []
    pa.step(EP, {"type": "decline", "question_id": "fake_b"})
    h.trace.append(dict(call, response={"q": "fake_b"}, seq=len(h.trace)))
    assert scorer._decline_hidden(h)


def test_s15_agent_answers_after_decline_refused_and_decline_stands(tmp_path):
    t = truth(S15)
    h, art = run(S15, s15, tmp_path)
    refused = [c for c in h.calls() if c.get("adversarial") and c["role"] == "clinician_agent"]
    assert len(refused) == 2 and all(c["accepted"] is False for c in refused)
    assert h.peek("SYNTH-EP-1501")["answers"]["pregnant_possible"] == "declined"
    assert scorer.adversarial_refuse(h, {"adversarial_refuse": [r for r in t.get("adversarial_refuse", [])
                                                                 if r.get("line_id") == "RF-CLIN-AGENT"]})[0]


def test_s15_agent_overwrite_tamper_fails(tmp_path):
    t = truth(S15)
    h, art = run(S15, s15, tmp_path, tamper="agent_overwrites_decline")
    rows = [r for r in t.get("adversarial_refuse", []) if r.get("line_id") == "RF-CLIN-AGENT"]
    assert len(rows) == 2 and not scorer.adversarial_refuse(h, {"adversarial_refuse": rows})[0]


def test_s15_t1_runs_the_grant_holder_check(tmp_path):
    from stack import scenario_tests as st
    h, art = run(S15, s15, tmp_path)
    assert st.IMPLEMENTED["S15-T1-decline-in-grant-holder-view"](h, art, {}) == []
    h2, _ = run(S15, s15, tmp_path / "t", tamper="grant_holder_sees_decline")
    assert st.IMPLEMENTED["S15-T1-decline-in-grant-holder-view"](h2, None, {})


def _interp_missing(art):
    """FG-INTERP-WITHHELD (signed source, byte-exact) must be in a figure artifact's legends."""
    import re
    raw = open(os.path.join(paths.SIBLINGS, "wording", "forms_orders_lines_SIGNED.md"), "rb").read().decode("utf-8")
    want = re.search(r"^\| FG-INTERP-WITHHELD \| (.*) \|$", raw, re.M).group(1)
    return want not in str(art.get("legends", "")) + str(art.get("result", ""))


def test_interp_withheld_on_both_patient_and_clinician_figures(tmp_path):
    from stack.endware import run_figure
    seed, start, pack, *_ = SCENARIOS["S10b-results-figure-au"]
    from stack.scenarios import s10b
    h = Harness("S10b-results-figure-au", seed, start, pack=pack, language="en")
    s10b(h, str(tmp_path / "base"))
    ep = next(e for e, x in h.episodes.items() if x.kind == "orders")
    P = h.episodes[ep].patient
    recs = ["SYNTH-REC-1001", "SYNTH-REC-1002", "SYNTH-REC-1003"]
    arts = {aud: run_figure(h, P, ep, recs, "1937-10-16T08:00:00", str(tmp_path / aud), audience=aud)
            for aud in ("patient", "clinician")}
    for aud, art in arts.items():
        assert art.get("exit") == 0 and not _interp_missing(art), aud
    cut = dict(arts["patient"], legends="", result="")
    assert _interp_missing(cut)                                   # the check fails when the line is missing


# ---------- ruling 11:52 / PV-RESUBMIT: review never finalises; resubmit by patient or clinician in person ----------
from signed_source import signed_rows as _signed_rows
from stack import notes as _notes
from stack.scenarios import s12
S12 = "S12-patient-declines-safety-question-to-letter-with-privacy-line"


def _resubmit_flow(h, ep):
    calls = [r for r in h.trace if r.get("kind") == "call" and r.get("episode") == ep]
    kinds = [((r.get("args") or [{}])[0] or {}).get("type") for r in calls]
    rv = kinds.index("review")
    after = calls[rv + 1:]
    agent = [r for r in after if r["role"] == "clinician_agent" and kinds[calls.index(r)] == "submit"]
    resub = [r for r in after if r["role"] == "patient" and kinds[calls.index(r)] == "submit"]
    return agent, resub


@pytest.mark.parametrize("sid,fn,ep", [(S15, s15, "SYNTH-EP-1501"), (S12, s12, "SYNTH-EP-1201")])
def test_resubmit_after_review_is_the_only_source_of_check_pass(tmp_path, sid, fn, ep):
    h, art = run(sid, fn, tmp_path)
    signed = _signed_rows()
    agent, resub = _resubmit_flow(h, ep)
    assert agent and all(not r["accepted"] and r["response"]["reason"] == signed["RF-CLIN-AGENT"] for r in agent)
    assert len(resub) == 1 and resub[0]["resubmit"] and _notes.env_result(resub[0]) == "resubmitted+checked"
    assert resub[0]["note"]["claim"] == "CL-RESUBMITTED" and resub[0]["response"]["result"] == signed["ST-CHECK-PASS"]
    rv_seq = [r for r in h.trace if r.get("kind") == "call" and ((r.get("args") or [{}])[0] or {}).get("type") == "review"][0]["seq"]
    before = [r for r in h.trace if r.get("op") == "check" and r["seq"] < resub[0]["seq"] and r["seq"] > rv_seq]
    assert all(r["result"]["checked"] != signed["ST-CHECK-PASS"] for r in before)
    views = [r for r in h.trace if r.get("op") == "patient_view" and rv_seq < r["seq"] < resub[0]["seq"]]
    assert views and all(v["result"].get("resubmit") == signed["PV-RESUBMIT"] for v in views)
    assert scorer.resubmit_prompt(h)[0]


def test_s15_resubmit_prompt_naming_the_decline_fails(tmp_path):
    for tamper in ("resubmit_prompt_names_question", "resubmit_prompt_quotes_question", "resubmit_prompt_says_declined"):
        h, art = run(S15, s15, tmp_path / tamper, tamper=tamper)
        ok, why = scorer.resubmit_prompt(h)
        assert not ok and why["leaks"], tamper


def test_resubmit_prompt_unit():
    pv = _signed_rows()["PV-RESUBMIT"]
    def h(prompt, declined=("q_x",), texts=("Is it so?",)):
        tr = [{"kind": "call", "seq": 0, "episode": "E", "args": [{"type": "decline", "question_id": d}], "accepted": True}
              for d in declined]
        tr.append({"kind": "harness", "op": "patient_view", "seq": 9, "episode": "E", "result": {"resubmit": prompt}})
        return type("H", (), {"trace": tr, "question_texts": {"q_x": texts[0]}})()
    assert scorer.resubmit_prompt(h(pv))[0]
    for bad in (pv + " q_x", pv + " Is it so?", pv.replace("again.", "again, declined."), pv[:-1]):
        assert not scorer.resubmit_prompt(h(bad))[0], bad


@pytest.mark.parametrize("sid,fn", [(S15, s15), (S12, s12)])
def test_resubmit_still_failing_never_reaches_check_pass(tmp_path, sid, fn):
    from stack import scenario_tests as st
    assert st.check_resubmit_still_failing(st.run_resubmit_still_failing(sid)) == []
    h, _ = run(sid, fn, tmp_path)                   # the clean run passes, so the checker must reject it
    assert st.check_resubmit_still_failing(h) == ["resubmit did not report ST-CHECK-FAIL", "trace reached ST-CHECK-PASS"]


# ---------- S14 code faults: env result of the discussion record, missing probes ----------
def test_s14_discussion_record_is_cl_closed_not_close_sameday():
    rec = {"kind": "call", "accepted": True, "method": "step", "args": [{"type": "close_sameday", "record": "SYNTH-REC-1406"}]}
    assert _notes.env_result(rec) == "closed" and _notes.claim_for(_notes.env_result(rec)) == "CL-CLOSED" in _notes.CLAIMS


def _adv(h, line_id):
    return [r for r in h.calls() if r.get("adversarial") and not r["accepted"]
            and (r["response"].get("line_id") == line_id or r["response"].get("reason") == _signed_rows()[line_id])]


def test_s14_probes_are_refused_with_their_signed_lines(tmp_path):
    h, art = run(S14, s14, tmp_path)
    ex = _adv(h, "RF-EXPORT-REAL")
    assert len(ex) == 1 and ex[0]["args"] == [{"synthetic": False}] and ex[0]["episode"].startswith("SCRATCH-NONSYNTH-")
    assert len(_adv(h, "PV-RESULT-WAITING")) == 1
    held = _adv(h, "RF-RESULT-HELD")
    assert {r["role"] for r in held} == {"clinician_agent", "patient_agent", "provider_agent"}


def test_s14_raw_value_request_after_release_is_not_refused(tmp_path):
    h, art = run(S14, s14, tmp_path, tamper="release")
    assert _adv(h, "PV-RESULT-WAITING") == []


@pytest.mark.parametrize("tid,tamper,want", [
    ("S14-T1-held-value-in-patient-letter", "value_in_patient_letter", "value in a patient letter"),
    ("S14-T2-held-value-in-grant-holder-view", "value_in_grant_holder_view", "value in patient-side output")])
def test_s14_t1_t2_fail_on_tamper_and_not_on_the_clean_run(tid, tamper, want):
    from stack import scenario_tests as st
    from stack.scorer import _held_hidden
    assert st.IMPLEMENTED[tid](None, None, {}) == []                       # the tampered run fails as declared
    assert any(want in f for f in _held_hidden(*st.run_s14_tamper(tamper)))
    assert _held_hidden(*st.run_s14_tamper(None)) == []                     # the clean run holds
    assert st.check_held_tamper([], want) == ["trace passed with the held value in patient output"]


def test_s15_planted_gp_line_from_declined_sensitive_question_fails_for_now(tmp_path):
    """letters has no refusal yet for a GP-letter line sourced from a declined sensitive question (its
    SENSITIVE_REFUSED is about items not on the sensitive list). Until letters adds it, this probe must fail:
    flip the assertions when letters refuses it with letters:SENSITIVE_REFUSED."""
    h, art = run(S15, s15, tmp_path)
    p = [r for r in h.calls() if r.get("method") == "letters_build" and r.get("adversarial")]
    assert len(p) == 1 and p[0]["args"][0]["source_item"] == "pregnant_possible"
    row = {"action": "gp-update letter includes a line sourced from pregnant_possible", "role": "harness",
           "line_id": "letters:SENSITIVE_REFUSED", "logged_as_answer": False}
    ok, d = scorer.adversarial_refuse(h, {"adversarial_refuse": [row]})
    assert not ok and d["not_seen"] == [{"action": row["action"], "line_id": row["line_id"]}]


# ---------- room 12:07: CL-RESUBMITTED [who], CL-CLOSED only for CQ-RESULT-TO-DISCUSS, absence rule ----------
def test_cl_resubmitted_who_is_only_patient_patients_agent_guardian_or_clinician_in_person():
    rows = {"CL-RESUBMITTED": "X [who: a, b] Y"}   # test row only: the real text is read from the signing files
    got = {r: _notes.claim_text("CL-RESUBMITTED", {"role": r}, rows) for r in
           ("patient", "patient_agent", "clinician", "clinician_agent", "guardian", "harness")}
    assert got == {"patient": "X patient Y", "patient_agent": "X patient's agent Y", "clinician": "X clinician in person Y",
                   "clinician_agent": None, "guardian": "X guardian Y", "harness": None}
    assert _notes.claim_text("CL-RESUBMITTED", {"role": "patient"}, {}) is None      # unsigned row: no text


def test_claim_text_reads_the_signing_files_only():
    assert _notes.claim_text("CL-CONFIRMED", {"role": "patient"}) == _signed_rows()["CL-CONFIRMED"]
    t = _signed_rows()["CL-RESUBMITTED"]
    i, j = t.index("[who"), t.index("]", t.index("[who")) + 1
    assert _notes.claim_text("CL-RESUBMITTED", {"role": "patient_agent"}) == t[:i] + "patient's agent" + t[j:]
    assert _notes.claim_text("CL-CLOSED", {"role": "clinician"}) is None      # [clinician] fill source not ruled


def test_cl_closed_is_flagged_on_any_entry_but_cq_result_to_discuss(tmp_path):
    h, art = run(S14, s14, tmp_path)
    close = [r for r in h.calls() if r.get("accepted") and ((r.get("args") or [{}])[0] or {}).get("type") == "close_sameday"][0]
    assert _notes.closes_result_to_discuss(close)
    for r in [x for x in h.calls() if x is not close and x.get("note")]:
        r["note"] = dict(r["note"], claim="CL-CLOSED")
    flagged = {b["seq"] for b in _notes_bad(h) if b.get("why") == "CL-CLOSED only for closing CQ-RESULT-TO-DISCUSS"}
    assert flagged == {x["seq"] for x in h.calls() if x is not close and x.get("note") and x["kind"] == "call"}
    close["note"] = dict(close["note"], claim="CL-CLOSED")
    assert close["seq"] not in {b["seq"] for b in _notes_bad(h) if b.get("why", "").startswith("CL-CLOSED")}


def _notes_bad(h):
    ok, bad = scorer.notes(h, {"path_expectations": [], "minimum_call_path": []})
    return [b for b in (bad if isinstance(bad, list) else []) if isinstance(b, dict)]


def test_absence_lines_rule():
    art = {"letter": "## Allergies\n- No allergies were written in your notes.", "clinician_letter": {"letter": "History: none recorded"}}
    assert scorer.absence_lines(art, ["none recorded", "No allergies were written in your notes"]) == [
        "- No allergies were written in your notes.", "History: none recorded"]
    assert scorer.absence_lines({"letter": "fine"}, ["none recorded"]) == []
