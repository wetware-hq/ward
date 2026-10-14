"""Scorer and harness unit tests on obviously fake fixtures. No scenario trace is run here."""
import os, pytest
from stack.harness import Harness
from stack import scorer, live, locales
from stack.endware import DECLINE_TEXT
from stack import adapter

FX = os.path.join(os.path.dirname(__file__), "fixtures")
FORM, LIST = os.path.join(FX, "fake_form.toml"), os.path.join(FX, "fake_list.toml")
P, Q, EP, EQ = "SYNTH-FAKEP1", "SYNTH-FAKEP2", "SYNTH-FAKE-EP1", "SYNTH-FAKE-EP2"


def grant(kind="grant", agent="SYNTH-fake-ag", patient=P):
    from stack import loader
    need = loader.forms().FIELDS.get(kind, set())
    return {"type": kind, **({"agent": agent, "patient": patient} if "agent" in need else {})}


def world():
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("forms", FORM, EP, P)
    h.open_episode("forms", FORM, EQ, Q)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    pa = h.session(P, "patient", P)
    ag = h.session("SYNTH-fake-ag", "patient_agent", P)
    dr.step(EP, {"type": "approve"})
    return h, dr, pa, ag


def write_truth(root, sid, truth="patient_language = \"en\"\nmin_calls = 4\n", wording="none\n"):
    d = root / sid
    d.mkdir(parents=True)
    if truth is not None:
        (d / "truth.toml").write_text(truth)
    if wording is not None:
        (d / "patient_wording.md").write_text(wording)


# ---- truth loading
def test_missing_truth_is_pending(tmp_path):
    assert scorer.load_truth("FAKE-none", str(tmp_path)) is None


def test_one_truth_file_is_still_pending(tmp_path):
    write_truth(tmp_path, "FAKE-half", wording=None)
    assert scorer.load_truth("FAKE-half", str(tmp_path)) is None


def test_both_truth_files_load(tmp_path):
    write_truth(tmp_path, "FAKE-full", wording='## Patient-visible lines\n1. PV-FAKE: "Fake line one"\n## Never shown to the patient\n- "Fake secret"\n')
    t = scorer.load_truth("FAKE-full", str(tmp_path))
    assert t["min_calls"] == 4 and t["wording"]["show"][0]["text"] == "Fake line one"
    assert t["wording"]["never"] == ["Fake secret"]


def test_pending_in_pipeline(tmp_path):
    from stack import pipeline
    assert pipeline.evaluate("S01-preproc-checklist", truth_root=str(tmp_path))["status"] == scorer.PENDING


# ---- idiot index
def test_idiot_index_ceiling():
    h, dr, pa, ag = world()                  # counted so far: 2 opens + 1 approve = 3
    for _ in range(3):
        pa.observe(EP)
    assert scorer.idiot_index(h, {"min_calls": 4}, False)[0]               # 6/4 = 1.5
    pa.observe(EP)
    assert not scorer.idiot_index(h, {"min_calls": 4}, False)[0]           # 7/4 > 1.5
    assert scorer.idiot_index(h, {"min_calls": 4}, True)[0]                # adversarial: exempt
    assert scorer.idiot_index(h, {"min_calls": 4, "idiot_index_cap": "exempt"}, False)[0]


def test_planted_probes_are_not_counted():
    h, dr, pa, ag = world()
    n = len(h.counted())
    h.mark_adversarial(); ag.call(EP, "reset")
    assert len(h.counted()) == n and len(h.calls()) == 2


# ---- harness refusals and bad actions
def test_harness_only_calls_refused_and_counted():
    h, dr, pa, ag = world()
    pa.step(EP, grant())
    for m in ("reset", "replay", "check", "export"):
        h.mark_adversarial()
        assert not ag.call(EP, m)["accepted"]
    for v in (1, 0, "yes", "false", None):
        h.mark_adversarial()
        assert ag.step(EP, {"type": "answer", "question_id": "fake_a", "value": v})["reason"] == "Refused: answers must be Yes or No."
    assert scorer.zero_bad_accepted(h)[0]


def test_orders_reset_refused_by_harness():
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("orders", LIST, EP, P)
    ag = h.session("SYNTH-fake-ag", "clinician_agent", P, scope=("medicine",))
    assert not ag.call(EP, "reset")["accepted"]


def test_accepted_bad_action_fails():
    h, dr, pa, ag = world()
    h.mark_adversarial()
    pa.observe(EP)                                    # planted: marked bad but accepted
    assert not scorer.zero_bad_accepted(h)[0]


def test_other_patients_episode_refused_without_leak():
    h, dr, pa, ag = world()
    r = pa.observe(EQ)
    assert not r["accepted"] and "SYNTH-FAKEP2" not in str(r)
    assert scorer.no_leaks(h)[0]


def test_leak_detected():
    h, dr, pa, ag = world()
    h._out(pa, {"actor": P}, {"accepted": True, "x": Q})   # planted response naming another patient
    assert not scorer.no_leaks(h)[0]


# ---- consent failures (P-01)
def test_consent_a_agent_shown_as_you_answered():
    h, dr, pa, ag = world()
    pa.step(EP, grant())
    ag.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    h.patient_view(EP)
    assert scorer.consent(h, {})[0]
    [r for r in h.trace if r.get("op") == "patient_view"][-1]["result"]["fake_a"] = "You answered"   # planted
    assert not scorer.consent(h, {})[0]


def test_consent_b_agent_action_after_revoke():
    h, dr, pa, ag = world()
    pa.step(EP, grant()); pa.step(EP, grant("revoke"))
    assert not ag.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})["accepted"]
    assert scorer.consent(h, {})[0]
    planted = dict(h.episodes[EP].log[-1], type="answer", role="patient_agent", question_id="fake_a",
                   value=True, question_version="1")
    planted.pop("schema_hash", None)
    h.episodes[EP].log.append(planted)                              # planted, bypassing the gate
    assert not scorer.consent(h, {})[0]


def test_consent_c_decline_written_as_no():
    h, dr, pa, ag = world()
    pa.step(EP, {"type": "decline", "question_id": "fake_a"})
    n = len(h.episodes[EP].log) - 1
    good = {"tool": "letters", "notes": f"x\n- You {DECLINE_TEXT} answer: fake A\n", "refs": [[], [{"episode": EP, "event": n}]]}
    bad = {"tool": "letters", "notes": "x\n- no fake A\n", "refs": [[], [{"episode": EP, "event": n}]]}
    assert scorer.consent(h, good)[0] and not scorer.consent(h, bad)[0]


# ---- citations
def test_letter_citations():
    h, dr, pa, ag = world()
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    n = len(h.episodes[EP].log) - 1
    refs = [[{"trace_seq": 1}], [{"episode": EP, "event": n}]]
    ok = {"tool": "letters", "letter": "## A\n\n- fake [L1]\n- fake a [L2]\n", "refs": refs}
    unres = dict(ok, letter="## A\n\n- fake [L3]\n")
    untag = dict(ok, letter="## A\n\n- fake [L1]\n- made up\n")
    assert scorer.cites_logged(h, ok)[0]
    assert not scorer.cites_logged(h, unres)[0]
    assert not scorer.cites_logged(h, untag)[0]


def test_adapter_refuses_unfinished_unsynthetic_or_blocked():
    h, dr, pa, ag = world()
    with pytest.raises(adapter.AdapterRefused):
        adapter.facts(h.export_bundle(EP))                       # not check-passed
    bd = h.export_bundle(EP)
    bd = dict(bd, episode_id="EP-REAL", export=dict(bd["export"], complete=True))
    with pytest.raises(adapter.AdapterRefused):
        adapter.facts(bd)                                        # not synthetic
    hb, *_ = blocked_world()
    with pytest.raises(adapter.AdapterRefused):
        adapter.facts(hb.export_bundle(EP))                      # blocked


def finished_world():
    h, dr, pa, ag = world()
    pa.step(EP, {"type": "decline", "question_id": "fake_a"})
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
    return h


def passed_bundle(h):
    """FAKE: the real export bundle marked check-passed, so the pure transform can be tested while the
    middleware's same-day queue rules are still changing."""
    bd = h.export_bundle(EP)
    return dict(bd, export=dict(bd["export"], complete=True))


def test_adapter_fields_and_decline_never_no():
    h = finished_world()
    n0 = len(h.counted())
    fs = adapter.facts(passed_bundle(h))
    assert len(h.counted()) == n0 + 1                            # exactly one harness export; transform is pure
    a = [f for f in fs if f["item_id"] == "fake_a"][0]
    for k in ("status", "answered_by", "on_behalf", "interpreter", "sensitive", "event_id"):
        assert k in a
    assert a["status"] == "declined" and a["value"] is None and a["event_id"].startswith(EP + "#")
    lines = adapter.letter_lines(fs, "patient", {})
    assert any(t == adapter.lt("LT-DECLINED-PT-SAFETY", **{"question plain wording": "Is this fake question A"})
               for _, t, _ in lines)
    assert any(t.startswith("Safety alert: not answered") for _, t, _ in adapter.letter_lines(fs, "clinician", {}))


def test_adapter_csv_columns():
    h = finished_world()
    head = adapter.figures_csv(adapter.facts(passed_bundle(h)), "au").splitlines()[0]
    assert head.split(",") == adapter.CSV_COLS


def test_letter_wording_status_follows_signed_table():
    assert adapter.wording_status() == ("signed" if adapter.LT_SIGNED else adapter.PENDING_WORDING)
    assert len(adapter.lt_lines()) == 11


# ---- outputs, wording, locale
def test_outputs_rows_and_blocks():
    h, *_ = world()
    t = {"expected_outputs": [{"type": "medicine", "item": "fake", "value": "fakeamol", "unit": "mg"}]}
    assert scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": "fakeamol 5 mg"}, t)[0]
    assert not scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": "nothing"}, t)[0]
    letter = {"type": "letter", "item": "x"}
    assert scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": scorer.FOOTER}, {"expected_outputs": [letter]})[0]
    blocked = {"expected_outcome": "BLOCKED", "must_refuse": [{"line_id": "BK-NO-LEGAL-TERM"}]}
    assert scorer.outputs(h, {"tool": "block", "block": "BK-NO-LEGAL-TERM"}, blocked)[0]
    assert not scorer.outputs(h, {"tool": "block", "block": "BK-NO-LANGUAGE"}, blocked)[0]
    assert not scorer.outputs(h, {"tool": "block", "block": "BK-NO-LANGUAGE"}, {})[0]


def test_must_refuse_needs_the_refusal_in_the_trace():
    h, dr, pa, ag = world()
    t = {"must_refuse": [{"action": "reset", "line_id": "RF-HARNESS-ONLY"}]}
    assert not scorer.must_refuse(h, t)[0]
    pa.step(EP, grant()); ag.call(EP, "reset")
    assert scorer.must_refuse(h, t)[0]


def test_safety_item_closed_or_escalated():
    h, dr, pa, ag = world()
    t = {"safety_items": [{"item": "fake_a", "must_be": "closed"}]}
    assert not scorer.safety(h, t)[0]
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    assert scorer.safety(h, t)[0]
    assert scorer.safety(h, {"safety_items": [{"item": "fake_a", "must_be": "escalated"}]})[0]   # alert answer
    assert not scorer.safety(h, {"safety_items": [{"item": "a plain sentence", "must_be": "closed"}]})[0]


def test_patient_wording_word_for_word():
    h, *_ = world()
    w = {"wording": {"show": [{"id": None, "text": "Fake line one", "row": "1"}], "never": ["Fake secret"], "notes": []}}
    art = lambda t: {"tool": "letters", "brief": "update to patient", "letter": t}
    assert scorer.patient_wording(h, art("Fake line one."), w)[0]
    assert not scorer.patient_wording(h, art("fake line one"), w)[0]
    assert not scorer.patient_wording(h, art("Fake line one. Fake secret"), w)[0]


def test_locale_mismatch_fails():
    assert scorer.locale({"locale_requested": "au", "locale_used": "au"})[0]
    assert not scorer.locale({"locale_requested": "us", "locale_used": "au"})[0]


def test_open_blocks_never_fall_back():
    assert locales.open_blocks("au", "fr") == ["BK-NO-LANGUAGE"]
    assert locales.open_blocks("eu-de", "en", ("legal_term",)) == ["BK-NO-LEGAL-TERM"]
    assert locales.open_blocks("us", "en", ("pack",)) == ["BK-NO-PACK"]
    assert locales.open_blocks("au", "en", ("pack", "legal_term")) == []


# ---- blocked episodes (ruling): both sides
def blocked_world(language="fr", pack="au", needs=("pack",)):
    h = Harness("FAKE", 1, "1930-01-01T08:00", pack=pack, language=language)
    h.open_episode("forms", FORM, EP, P, needs=needs)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    pa = h.session(P, "patient", P)
    ag = h.session("SYNTH-fake-ag", "patient_agent", P)
    return h, dr, pa, ag


def test_blocked_episode_opens_in_one_call():
    h, *_ = blocked_world()
    assert h.blocked(EP) == ["BK-NO-LANGUAGE"] and len(h.counted()) == 1


def test_blocked_refuses_patient_and_agent():
    h, dr, pa, ag = blocked_world()
    dr.step(EP, {"type": "approve"})
    for who in (pa, ag):
        r = who.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
        assert not r["accepted"] and r["block"] == "BK-NO-LANGUAGE"
    assert not pa.observe(EP)["accepted"]
    assert not any(e.get("role") in ("patient", "patient_agent") for e in h.episodes[EP].log)


def test_blocked_clinician_safety_answer_accepted_flagged_and_output_refused():
    from stack.endware import letter, run_figure
    h, dr, pa, ag = blocked_world()
    dr.step(EP, {"type": "approve"})
    assert dr.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})["accepted"]
    rec = h.calls()[-1]
    assert rec["interpreter_used"] and rec["blocked_for_output"] == ["BK-NO-LANGUAGE"]
    assert any("question 1" in f for f in h.check(EP)["flags"])                # the alert still shows the clinician
    art = letter(h, "/tmp/unused", P, [EP], "Patient", "update to patient")
    assert art["tool"] == "block" and art["block"] == "BK-NO-LANGUAGE"
    assert run_figure(h, P, EP, [], "1930-01-02T00:00:00", "/tmp/unused")["tool"] == "block"
    assert h.patient_view(EP) is None


def test_blocked_legal_term_refuses_on_behalf_only():
    h, dr, pa, ag = blocked_world(language="en", pack="eu-de", needs=("legal_term",))
    dr.step(EP, {"type": "approve"})
    r = dr.step(EP, {"type": "answer", "question_id": "fake_a", "value": True, "on_behalf": "sdm"})
    assert not r["accepted"] and r["block"] == "BK-NO-LEGAL-TERM"
    assert dr.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})["accepted"]


def test_agent_cannot_change_access():
    h, dr, pa, ag = world()
    pa.step(EP, grant())
    r = ag.step(EP, grant("revoke"))
    assert not r["accepted"] and r["line_id"] == "RF-AGENT-REVOKE"


# ---- live mode
def test_live_waits_without_key(monkeypatch):
    monkeypatch.delenv(live.KEY_ENV, raising=False)
    r = live.run_live("S05-mh-screen-by-patient-agent", lambda s: (True, True))
    assert r["status"] == live.WAITING and r["runs"] == 0


def test_live_key_without_client_never_passes(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, "fake")
    assert live.run_live("S07-adversarial-agent", lambda s: (True, True))["status"] == live.NO_CLIENT


def test_clopper_pearson_known_values():
    assert live.clopper_pearson(0, 20)[1] == pytest.approx(0.1684, abs=1e-4)
    lo, hi = live.clopper_pearson(10, 20)
    assert lo == pytest.approx(0.2720, abs=1e-4) and hi == pytest.approx(0.7280, abs=1e-4)
    assert len(live.SEEDS) == 20


def test_blocked_episode_is_never_exported():
    from stack.harness import Blocked
    h, dr, pa, ag = blocked_world()
    with pytest.raises(Blocked):
        h.export(EP)


# ---- leak guard: sensitive answers never reach clinician notes
SFORM = os.path.join(FX, "fake_form_s.toml")


def sworld():
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("forms", SFORM, EP, P)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    pa = h.session(P, "patient", P)
    dr.step(EP, {"type": "approve"})
    return h, dr, pa, None


def sensitive_world(value):
    h, dr, pa, ag = sworld()
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": value})
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
    return h, adapter.facts(passed_bundle(h))


@pytest.mark.parametrize("value", [True, False])
def test_sensitive_answer_cut_from_clinician_notes(value):
    h, fs = sensitive_world(value)
    ph = {"fake_a": ("FAKE SECRET YES", "FAKE SECRET NO")}
    clin = adapter.letter_lines(fs, "clinician", ph)
    texts = " ".join(t for _, t, _ in clin)
    assert "FAKE SECRET" not in texts
    ev = [f for f in fs if f["item_id"] == "fake_a"][0]["event_id"]
    assert adapter.lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": adapter.letter_event_id(ev)}) in texts
    pt = " ".join(t for _, t, _ in adapter.letter_lines(fs, "patient", ph))
    assert ("FAKE SECRET YES" if value else "FAKE SECRET NO") in pt                  # kept for the patient


def test_sensitive_declined_also_cut_for_clinician():
    h, dr, pa, ag = sworld()
    pa.step(EP, {"type": "decline", "question_id": "fake_a"})
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
    texts = " ".join(t for _, t, _ in adapter.letter_lines(adapter.facts(passed_bundle(h)), "clinician", {}))
    assert "fake question A" not in texts and "Safety alert: a sensitive" in texts


def test_exact_block_set_and_check_end():
    h, *_ = world()
    t = {"expected_outcome": "BLOCKED", "must_refuse": [{"line_id": "BK-NO-PACK"}, {"line_id": "BK-NO-LEGAL-TERM"}]}
    assert scorer.outputs(h, {"tool": "block", "all": ["BK-NO-LEGAL-TERM", "BK-NO-PACK"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK", "BK-NO-LEGAL-TERM", "BK-NO-LANGUAGE"]}, t)[0]
    assert scorer.outputs(h, {"tool": "check", "exit": 1}, {"expected_artifact": "none", "expected_exit": 1})[0]
    assert not scorer.outputs(h, {"tool": "check", "exit": 0}, {})[0]
    assert not scorer.outputs(h, {"tool": "check", "exit": 0}, {"expected_artifact": "none", "expected_exit": 1})[0]
    assert not scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": "x"}, {"expected_artifact": "none"})[0]


def test_wrong_move_tests_counted_separately():
    h, dr, pa, ag = world()
    h.mark_adversarial(); pa.step(EP, {"type": "confirm", "question_id": "fake_a"})
    ok, d = scorer.idiot_index(h, {"min_calls": 3}, False)
    assert d["wrong_move_tests"] == 1 and d["calls"] == 3


def test_signed_lines_not_pending():
    assert not locales.line("BK-NO-PACK", locale="us").startswith(locales.PENDING_WORDING)
    assert not locales.line("RF-AGENT-REVOKE").startswith(locales.PENDING_WORDING)



# ---- round 8 scorer fields
def orders_world():
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("orders", LIST, EP, P)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    return h


def test_blocked_for_output_exact_expected_blocks():
    h, *_ = world()
    t = {"expected_outcome": "BLOCKED_FOR_OUTPUT", "expected_blocks": ["BK-NO-PACK", "BK-NO-LEGAL-TERM"]}
    assert scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK", "BK-NO-LEGAL-TERM"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "letters", "exit": 0}, t)[0]


def test_expected_overdue_count_exact():
    h = orders_world()
    h.set_now("1930-01-01 12:00"); h.check(EP)
    one = {"expected_artifact": "none", "expected_exit": 1, "expected_overdue_count": 1}
    assert scorer.outputs(h, {"tool": "check", "exit": 1}, one)[0]
    assert not scorer.outputs(h, {"tool": "check", "exit": 1}, dict(one, expected_overdue_count=2))[0]


def test_overdue_safety_item_needs_owner_and_due():
    h = orders_world()
    h.set_now("1930-01-01 12:00"); h.check(EP)
    good = {"safety_items": [{"item": "fake_job", "must_be": "escalated", "line_id": "FL-OVERDUE",
                              "owner": "SYNTH-fake-owner", "due": "1930-01-01 10:00"}]}
    assert scorer.safety(h, good)[0]
    good["safety_items"][0]["owner"] = "SYNTH-someone-else"
    assert not scorer.safety(h, good)[0]


def test_safety_lines_word_for_word_with_slots():
    h, dr, pa, ag = world()
    h._emit("harness", op="note", text="Same-day review needed: question fake_a, event SYNTH-FAKE-EP1#3, confirmed.")
    t = {"safety_lines": [{"item": "fake_a", "line_id": "X", "text": "Same-day review needed: question fake_a, event [event_id], confirmed."}]}
    assert scorer.safety_lines(h, {}, t)[0]
    t["safety_lines"][0]["text"] = "Same-day review needed: question fake_a, event [event_id], unconfirmed."
    assert not scorer.safety_lines(h, {}, t)[0]


def test_adversarial_refuse_separate_from_must_refuse():
    h, dr, pa, ag = world()
    h.mark_adversarial(); ag.call(EP, "reset")
    t = {"adversarial_refuse": [{"action": "reset", "line_id": "RF-HARNESS-ONLY"}],
         "must_refuse": [{"action": "reset", "line_id": "RF-HARNESS-ONLY"}]}
    assert scorer.adversarial_refuse(h, t)[0]
    assert not scorer.must_refuse(h, t)[0]          # an off-path probe doesn't satisfy an on-path refusal
    assert scorer.idiot_index(h, {"min_calls": 3}, False)[1]["calls"] == 3


def test_declared_scenario_tests_without_implementation_fail():
    h, *_ = world()
    assert not scorer.scenario_tests(h, {"scenario_tests": [{"id": "FAKE-T1"}]})[0]
    assert scorer.scenario_tests(h, {})[0]


# ---- round 9 alert routing
def routed_world(answer):
    h, dr, pa, ag = world()
    if answer == "decline":
        pa.step(EP, {"type": "decline", "question_id": "fake_a"})
    else:
        pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": answer})
    return h


def plant(h, route, cq=True, pv=True, item="fake_a"):
    cq_id, pv_id = scorer.ROUTE_LINES[route]
    if cq:
        h._emit("harness", op="clinician_queue", episode=EP,
                text=scorer._line_text(cq_id).replace("[item_id]", item).replace("[event_id]", EP + "#2").replace("[status]", "confirmed"))
    if pv:
        h._emit("harness", op="patient_view", episode=EP, result={item: scorer._line_text(pv_id)})


def test_route_default_and_sources():
    t = {"alert_routes": {"a": "before_procedure"}, "form_questions": [{"id": "b", "alert_route": "same_day"}]}
    assert scorer.route_for(t, "a") == "before_procedure" and scorer.route_for(t, "b") == "same_day"
    assert scorer.route_for({}, "c") == "same_day"


@pytest.mark.parametrize("route", ["same_day", "before_procedure"])
def test_alert_routing_correct(route):
    h = routed_world(True)
    real = h.peek
    h.peek = lambda eid: dict(real(eid), clinician_queue=[])
    plant(h, route)
    assert scorer.alert_routing(h, {"alert_routes": {"fake_a": route}})[0]


@pytest.mark.parametrize("route", ["same_day", "before_procedure"])
@pytest.mark.parametrize("broken", ["no_queue", "no_pv", "wrong_route"])
def test_alert_routing_broken(route, broken):
    h = routed_world("decline")
    real = h.peek                                    # ignore any queue lines the live forms writes itself
    h.peek = lambda eid: dict(real(eid), clinician_queue=[])
    other = "before_procedure" if route == "same_day" else "same_day"
    plant(h, other if broken == "wrong_route" else route, cq=broken != "no_queue", pv=broken != "no_pv")
    assert not scorer.alert_routing(h, {"alert_routes": {"fake_a": route}})[0]


def test_alert_routing_untriggered_needs_nothing():
    h = routed_world(False)                          # a "no" on fake_a (alert answer is yes): no route lines
    assert scorer.alert_routing(h, {"alert_routes": {"fake_a": "before_procedure"}})[0]


def test_refused_export_counts_as_a_call():
    h, dr, pa, ag = blocked_world()
    n = len(h.counted())
    h.export_bundle(EP)
    assert len(h.counted()) == n + 1


# ---- figures data check (FG-REFUSE-DATA) and non-synthetic export (RF-EXPORT-REAL)
from stack import endware


def test_data_check_rows():
    ok = {"recorded_at": "1930-01-01T08:00:00", "unit": "mg/L", "value": "5"}
    assert endware.data_check(ok) is None
    assert endware.data_check(dict(ok, recorded_at="03/04/1930")) == "date"
    assert endware.data_check(dict(ok, recorded_at="1930-02-30T08:00:00")) == "date"
    assert endware.data_check(dict(ok, unit="")) == "unit"
    assert endware.data_check(dict(ok, value="haemolysed")) == "value"


def results_world(t2):
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("orders", os.path.join(FX, "fake_results.toml"), EP, P)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    h.record_result("SYNTH-fake-lab", "SYNTH-FAKE-RES-1", P, "CRP", "1930-01-01T08:00:00", 5, "mg/L")
    h.record_result("SYNTH-fake-lab", "SYNTH-FAKE-RES-2", P, "CRP", t2, 7, "mg/L")
    dr.step(EP, {"type": "tick", "id": "file_1", "evidence": "SYNTH-FAKE-RES-1"})
    dr.step(EP, {"type": "tick", "id": "file_2", "evidence": "SYNTH-FAKE-RES-2"})
    return h


def test_bad_row_refused_with_signed_line_and_event_id(tmp_path):
    h = results_world("03/04/1930")
    art = endware.run_figure(h, P, EP, ["SYNTH-FAKE-RES-1", "SYNTH-FAKE-RES-2"], "1930-01-02T00:00:00", str(tmp_path))
    assert art["tool"] == "refused" and len(art["lines"]) == 1
    ev = [n for n, e in enumerate(h.episodes[EP].log) if e.get("evidence") == "SYNTH-FAKE-RES-2"][0]
    want = locales.line("FG-REFUSE-DATA", event_id=f"{EP}#{ev}")
    assert art["lines"][0] == want and want.startswith("Figure not made: the data failed a check (event ")
    assert not any(r["kind"] == "endware" for r in h.trace)              # figures never called
    t = {"safety_lines": [{"line_id": "FG-REFUSE-DATA", "text": "Figure not made: the data failed a check (event [event_id])."}]}
    assert scorer.safety_lines(h, art, t)[0]


@pytest.mark.parametrize("kind,case", [("forms", FORM), ("orders", LIST)])
def test_nonsynthetic_export_refused(kind, case):
    h, *_ = world()
    n = len(h.counted())
    r = h.try_export_nonsynthetic(kind, case, P)
    assert not r["accepted"] and r["reason"] == scorer._line_text("RF-EXPORT-REAL")
    assert len(h.counted()) == n and not h._adv
    assert scorer.adversarial_refuse(h, {"adversarial_refuse": [{"action": "x", "line_id": "RF-EXPORT-REAL"}]})[0]
    assert all(not e.startswith("SCRATCH") for e in h.episodes)


def test_nonsynthetic_probe_does_not_mark_the_next_call():
    h, dr, pa, ag = world()
    h.mark_adversarial()
    h.try_export_nonsynthetic("forms", FORM, P)
    pa.observe(EP)                                   # legitimate: must be counted, not marked as a probe
    assert not h.calls()[-1].get("adversarial")


def test_waiting_parent_queue_line_read_from_truth():
    h, *_ = world()
    text = "Waiting on Q1: Do you have any allergies to medicines? Then ask Q2: Did a medicine allergy ever make it hard to breathe?"
    row = {"type": "queue", "item": "allergy_reaction_severe", "source_line": "CQ-WAITING-PARENT",
           "expected_section": "clinician queue: listed as waiting, not omitted"}
    sl = {"safety_lines": [{"item": "allergy_reaction_severe", "line_id": "CQ-WAITING-PARENT", "text": text}]}
    assert not scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": ""}, {"expected_outputs": [row]})[0]
    assert not scorer.safety_lines(h, {}, sl)[0]
    h._emit("harness", op="clinician_queue", episode=EP, text=text)
    assert scorer.outputs(h, {"tool": "letters", "exit": 0, "letter": ""}, {"expected_outputs": [row]})[0]
    assert scorer.safety_lines(h, {}, sl)[0]
    assert scorer._line_text("CQ-WAITING-PARENT").startswith("Waiting on Q[n]:")


def test_s08_answer_file_parses_with_waiting_parent():
    t = scorer.load_truth("S08-three-fails-escalation")
    if t is None:
        pytest.skip(scorer.PENDING)
    assert t["min_calls"] == 16
    assert any(x.get("line_id") == "CQ-WAITING-PARENT" for x in t.get("safety_lines", []))
    assert any(x.get("source_line") == "CQ-WAITING-PARENT" for x in t.get("expected_outputs", []))
