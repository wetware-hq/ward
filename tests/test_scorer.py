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


def test_adapter_fields_and_decline_never_no():
    h = finished_world()
    n0 = len(h.counted())
    fs = adapter.facts(h.export_bundle(EP))
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
    head = adapter.figures_csv(adapter.facts(h.export_bundle(EP)), "au").splitlines()[0]
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
    return h, adapter.facts(h.export_bundle(EP))


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
    texts = " ".join(t for _, t, _ in adapter.letter_lines(adapter.facts(h.export_bundle(EP)), "clinician", {}))
    assert "fake question A" not in texts and "Safety alert: a sensitive" in texts


def test_exact_block_set_and_check_end():
    h, *_ = world()
    t = {"expected_outcome": "BLOCKED", "must_refuse": [{"line_id": "BK-NO-PACK"}, {"line_id": "BK-NO-LEGAL-TERM"}]}
    assert scorer.outputs(h, {"tool": "block", "all": ["BK-NO-LEGAL-TERM", "BK-NO-PACK"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK"]}, t)[0]
    assert not scorer.outputs(h, {"tool": "block", "all": ["BK-NO-PACK", "BK-NO-LEGAL-TERM", "BK-NO-LANGUAGE"]}, t)[0]
    assert scorer.outputs(h, {"tool": "check", "exit": 0}, {"expected_artifact": "none"})[0]
    assert not scorer.outputs(h, {"tool": "check", "exit": 0}, {})[0]
    assert not scorer.outputs(h, {"tool": "check", "exit": 1}, {"expected_artifact": "none"})[0]


def test_wrong_move_tests_counted_separately():
    h, dr, pa, ag = world()
    h.mark_adversarial(); pa.step(EP, {"type": "confirm", "question_id": "fake_a"})
    ok, d = scorer.idiot_index(h, {"min_calls": 3}, False)
    assert d["wrong_move_tests"] == 1 and d["calls"] == 3


def test_signed_lines_not_pending():
    assert not locales.line("BK-NO-PACK", locale="us").startswith(locales.PENDING_WORDING)
    assert not locales.line("RF-AGENT-REVOKE").startswith(locales.PENDING_WORDING)
