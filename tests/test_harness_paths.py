"""Behaviour of harness refusal paths, trace flags and the blocked layer. Line ids are pinned here, not read
from the harness, so a swapped line is caught."""
import json, os
import pytest
from ward.harness import Harness, COUNTED
from ward import loader, locales

FX = os.path.join(os.path.dirname(__file__), "fixtures")
FORM, SFORM, LIST = (os.path.join(FX, f) for f in ("fake_form.toml", "fake_form_s.toml", "fake_list.toml"))
P, Q, EP, EQ = "SYNTH-FAKEP1", "SYNTH-FAKEP2", "SYNTH-FAKE-EP1", "SYNTH-FAKE-EP2"

# pinned separately from the code: refusal path -> line id
EXPECTED_LINE = {"not_yours": "RF-NOT-YOURS", "agent_grant": "RF-AGENT-REVOKE",
                 "harness_only": "RF-HARNESS-ONLY", "export_real": "RF-EXPORT-REAL"}


def msg(i):
    m = loader.forms()._deps["messages"]
    return m.msg(i)


def hw(form=FORM, kind="forms", **k):
    h = Harness("FAKE", 1, "1930-01-01T08:00", **k)
    h.open_episode(kind, form if kind == "forms" else LIST, EP, P)
    return h


def unchanged(h, handle, fn):
    """Run a refused call; the handle, the episodes and the trace (bar the one call record) must not change."""
    snap = (handle.actor, handle.role, handle.patient, handle.discipline, handle.scope)
    logs = {k: list(e.log) for k, e in h.episodes.items()}
    trace = json.dumps(h.trace)
    r = fn()
    assert not r["accepted"]
    assert (handle.actor, handle.role, handle.patient, handle.discipline, handle.scope) == snap
    assert {k: list(e.log) for k, e in h.episodes.items()} == logs and set(h.episodes) == set(logs)
    assert json.dumps(h.trace[:-1]) == trace
    last = h.trace[-1]
    assert last["kind"] == COUNTED and last["actor"] == snap[0] and last["accepted"] is False
    return r, last


def test_not_yours_unknown_and_foreign_episode():
    h = hw()
    h.open_episode("forms", FORM, EQ, Q)
    pa = h.session(P, "patient", P)
    for ep in (EQ, "SYNTH-NOPE"):
        r, last = unchanged(h, pa, lambda: pa.step(ep, {"type": "approve"}))
        assert r["reason"] == msg(EXPECTED_LINE["not_yours"]) and r["by"] == "harness"


@pytest.mark.parametrize("role", ["patient_agent", "clinician_agent"])
@pytest.mark.parametrize("t", ["grant", "revoke"])
def test_agent_cannot_grant_or_revoke(role, t):
    h = hw()
    ag = h.session("SYNTH-fake-ag", role, P)
    r, _ = unchanged(h, ag, lambda: ag.step(EP, {"type": t}))
    assert r["line_id"] == EXPECTED_LINE["agent_grant"] and r["by"] == "harness"
    assert r["reason"] == locales.line(EXPECTED_LINE["agent_grant"])


def test_patient_grant_not_refused_by_agent_rule():
    h = hw()
    pa = h.session(P, "patient", P)
    r = pa.step(EP, {"type": "grant"})
    assert r.get("line_id") != EXPECTED_LINE["agent_grant"]


def test_non_dict_step_not_agent_rule():
    h = hw()
    ag = h.session("SYNTH-fake-ag", "patient_agent", P)
    r = ag.step(EP, "grant")
    assert r.get("line_id") != EXPECTED_LINE["agent_grant"]


class _OldEnv:
    """An env without call() or export(): the harness must enforce the split and refuse real exports itself."""
    def __init__(self, real):
        self._r, self.log = real, real.log
    def observe(self, *a): return self._r.observe(*a)
    def step(self, *a): return self._r.step(*a)
    def replay(self, *a): return self._r.replay(*a)
    def check(self, *a): return self._r.check(*a)


def old_env(monkeypatch):
    from ward import harness
    real = harness.Episode.env
    monkeypatch.setattr(harness.Episode, "env", lambda self, *a, **k: _OldEnv(real(self, *a, **k)))


def test_harness_only_methods_without_env_call(monkeypatch):
    h = hw(kind="orders")
    old_env(monkeypatch)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    for m in ("reset", "replay", "check", "export"):
        r, last = unchanged(h, dr, lambda: dr.call(EP, m))
        assert r == {"accepted": False, "reason": msg(EXPECTED_LINE["harness_only"]), "by": "harness"}
        assert last["method"] == m
    assert dr.observe(EP).get("accepted", True) is not False


def test_export_nonsynthetic_refused_by_ward_without_env_export(monkeypatch):
    old_env(monkeypatch)
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    r = h.try_export_nonsynthetic("orders", LIST, P)
    assert r == {"accepted": False, "reason": msg(EXPECTED_LINE["export_real"]), "by": "harness"}
    assert h.trace[-1]["adversarial"] is True and h.trace[-1]["note"]["claim"] == "CL-REFUSED"


def test_forms_harness_only_methods_refused():
    h = hw()
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    for m in ("reset", "replay", "export"):
        unchanged(h, dr, lambda: dr.call(EP, m))


def test_export_nonsynthetic_refused_both_kinds():
    for kind, by in (("forms", "middleware"), ("orders", "middleware")):
        h = Harness("FAKE", 1, "1930-01-01T08:00")
        n = len(h.trace)
        r = h.try_export_nonsynthetic(kind, FORM if kind == "forms" else LIST, P)
        assert r["accepted"] is False and r["reason"] and r["by"] == by
        assert len(h.trace) == n + 1 and not h.episodes
        last = h.trace[-1]
        assert last["adversarial"] is True and last["method"] == "export" and last["note"]["claim"] == "CL-REFUSED"
        assert last not in h.counted() and h._adv is False


def test_audit_open_not_counted():
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("forms", FORM, EP, P, audit=True)
    h.open_episode("forms", FORM, EQ, Q)
    ops = [r for r in h.counted() if r.get("op") == "open"]
    assert [r["episode"] for r in ops] == [EQ]
    assert [r.get("audit") for r in h.trace if r.get("op") == "open"] == [True, None]


def test_sensitive_step_flags():
    h = hw(SFORM)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    pa = h.session(P, "patient", P)
    rb = pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
    assert rb["accepted"] and h.trace[-1]["sensitive_step"] is False
    ra = pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    assert ra["accepted"] and h.trace[-1]["sensitive_step"] is True
    h.check(EP)
    assert h.trace[-1]["op"] == "check" and h.trace[-1]["sensitive_step"] is True and "note" in h.trace[-1]
    h.export(EP)
    assert h.trace[-1]["op"] == "export" and h.trace[-1]["sensitive_step"] is True
    # plain form: nothing sensitive anywhere
    g = hw()
    d2 = g.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    d2.step(EP, {"type": "approve"})
    g.session(P, "patient", P).step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    g.check(EP); g.export(EP)
    assert not any(r.get("sensitive_step") for r in g.trace)
    # non-counted ops get no flag; open gets one
    assert "sensitive_step" not in [r for r in h.trace if r.get("op") == "session"][0]
    assert [r for r in h.trace if r.get("op") == "open"][0]["sensitive_step"] is False


def blocked(language="fr", pack="au", needs=("pack",)):
    h = Harness("FAKE", 1, "1930-01-01T08:00", pack=pack, language=language)
    h.open_episode("forms", FORM, EP, P, needs=needs)
    return h


def test_record_result_blocked_paths():
    h = blocked()
    n = len(h.records)
    h.mark_adversarial()
    r = h.record_result("SYNTH-fake-ag", "R1", P, "Hb", "t", 1, "g", role="patient_agent")
    assert r["accepted"] is False and r["block"] == "BK-NO-LANGUAGE" and r["by"] == "locale"
    assert r["reason"] == locales.line("BK-NO-LANGUAGE", language="fr", **{"locale pack": "au"})
    last = h.trace[-1]
    assert last["adversarial"] is True and last["sensitive_step"] is False and h._adv is False
    assert len(h.records) == n and last["note"] and last["accepted"] is False
    r2 = h.record_result("SYNTH-fake-ag", "R2", P, "Hb", "t", 1, "g", role="patient_agent")
    assert "adversarial" not in h.trace[-1] and not r2["accepted"]
    h.record_result("SYNTH-fake-dr", "R3", P, "Hb", "t", 1, "g")
    assert "R3" in h.records and h.trace[-1]["op"] == "record_result"
    # another patient is not blocked
    h.record_result("SYNTH-fake-ag", "R4", Q, "Hb", "t", 1, "g", role="patient_agent")
    assert "R4" in h.records


def test_blocked_line_choice():
    # on_behalf with no legal term -> BK-NO-LEGAL-TERM; else BK-NO-LANGUAGE wins over others
    h = blocked(language="fr", pack="us", needs=("pack", "legal_term"))
    assert h.blocked(EP)[0] == "BK-NO-PACK" and "BK-NO-LANGUAGE" in h.blocked(EP)
    pa = h.session(P, "patient", P)
    r, _ = unchanged(h, pa, lambda: pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False}))
    assert r["block"] == "BK-NO-LANGUAGE"
    if "BK-NO-LEGAL-TERM" in h.blocked(EP):
        r, _ = unchanged(h, pa, lambda: pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False,
                                                      "on_behalf": "x"}))
        assert r["block"] == "BK-NO-LEGAL-TERM"
        r, _ = unchanged(h, pa, lambda: pa.observe(EP, "on_behalf"))
        assert r["block"] == "BK-NO-LANGUAGE"
    g = blocked(language="en", pack="us", needs=("pack",))
    pg = g.session(P, "patient", P)
    r, _ = unchanged(g, pg, lambda: pg.step(EP, {"type": "approve"}))
    assert r["block"] == "BK-NO-PACK" and r["reason"] == locales.line("BK-NO-PACK", language="en", **{"locale pack": "us"})


def test_blocked_clinician_interpreter():
    h = blocked()
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    r = dr.step(EP, {"type": "approve"})
    assert r["accepted"]
    last = h.trace[-1]
    assert last["interpreter_used"] is True and last["blocked_for_output"] == ["BK-NO-LANGUAGE"]
    h2 = hw()
    h2.session("SYNTH-fake-dr", "clinician", P, discipline="medicine").step(EP, {"type": "approve"})
    assert "interpreter_used" not in h2.trace[-1]


def test_blocked_patient_view_keeps_only_alert_lines():
    h = blocked()
    v = h.patient_view(EP)
    heads = [locales.line(l).split("[")[0] for l in ("PV-SAMEDAY", "PV-BEFORE-PROC")]
    def strings(x):
        if isinstance(x, str): yield x
        elif isinstance(x, dict):
            for y in x.values(): yield from strings(y)
        elif isinstance(x, list):
            for y in x: yield from strings(y)
    assert all(any(s.startswith(hd) for hd in heads if hd) for s in strings(v))
    last = h.trace[-1]
    assert last["op"] == "patient_view" and last["hidden"] == ["BK-NO-LANGUAGE"] and last["result"] == v
    g = hw()
    assert g.patient_view(EP) and "hidden" not in g.trace[-1]


def test_out_leaks_adversarial_and_note_hook(monkeypatch):
    h = hw()
    h.open_episode("forms", FORM, EQ, Q)
    pa = h.session(P, "patient", P)
    pa.observe(EP)
    assert h.leaks == []
    h.mark_adversarial()
    pa.step(EQ, {"type": "approve"})
    assert h.trace[-1]["adversarial"] is True and h._adv is False
    pa.observe(EP)
    assert "adversarial" not in h.trace[-1]
    seen = []
    monkeypatch.setattr(Harness, "NOTE_HOOK", lambda rec: seen.append(rec) or "hooked")
    pa.observe(EP)
    assert h.trace[-1]["note"]["reason"] == "hooked" and seen[-1]["accepted"] in (True, False)
    pa.observe(EP, note="mine")
    assert h.trace[-1]["note"]["reason"] == "mine" and len(seen) == 1
    pa.step(EP, {"type": "approve"}, note={"claim": "CL-X", "reason": "r"})
    assert h.trace[-1]["note"] == {"claim": "CL-X", "reason": "r"}


def test_out_records_foreign_id_leak():
    h = hw()
    h.open_episode("forms", FORM, EQ, Q)
    pa = h.session(P, "patient", P)
    h._out(pa, dict(actor=P, role="patient", episode=EP, args=[]), {"accepted": True, "v": f"{Q} {EQ} {P} SYNTH-unknown"})
    assert h.leaks == [{"actor": P, "ids": sorted([Q, EQ])}]
    h._out(pa, dict(actor=P, role="patient", episode=EP, args=[]), {"accepted": True, "v": f"{P} {EP}"})
    assert len(h.leaks) == 1


# ---- trace flags, escalation and review
def sens_form(tmp_path, safety=True):
    import shutil
    f = tmp_path / "f.toml"
    shutil.copy(FORM, f)
    (tmp_path / "f.sensitive.toml").write_text('sensitive = ["fake_a"]\n')
    return str(f)


def calls(h):
    return [r for r in h.trace if r["kind"] == COUNTED]


def started(form):
    h = hw(form)
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    return h, dr, h.session(P, "patient", P)


def test_escalated_only_on_alerting_answer(tmp_path):
    for form in (FORM, sens_form(tmp_path)):
        h, dr, pa = started(form)
        assert "escalated" not in calls(h)[-1]                        # approve cannot escalate
        pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})
        assert "escalated" not in calls(h)[-1]                        # alert answer, not safety-critical
        pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
        assert "escalated" not in calls(h)[-1]
        pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
        assert calls(h)[-1]["escalated"] is True
        assert calls(h)[-1]["queue_after"] == h.peek(EP)["clinician_queue"] != []
        r = pa.step(EP, {"type": "bogus"})
        assert not r["accepted"] and "queue_after" not in calls(h)[-1] and "events" not in calls(h)[-1]


def test_sensitive_alert_goes_to_queue_and_review_is_sensitive(tmp_path):
    h, dr, pa = started(sens_form(tmp_path))
    n0 = len(h.episodes[EP].log)
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    q = [r for r in h.trace if r.get("op") == "clinician_queue"]
    assert len(q) == 1 and q[0]["item"] == 1 and q[0]["event"] == f"{EP}#{n0}" and q[0]["text"] == "Is this fake question A?"
    assert calls(h)[-1]["sensitive_step"] is True and calls(h)[-1]["events"] == [n0]
    dr.step(EP, {"type": "review"})
    assert calls(h)[-1]["sensitive_step"] is True and "_closed_sensitive" not in calls(h)[-1]
    # same review on the plain form (nothing sensitive) is not flagged
    g, d2, p2 = started(FORM)
    p2.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    assert not [r for r in g.trace if r.get("op") == "clinician_queue"]
    d2.step(EP, {"type": "review"})
    assert calls(g)[-1]["sensitive_step"] is False


def test_review_with_nothing_queued_not_sensitive(tmp_path):
    h, dr, pa = started(sens_form(tmp_path))
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})
    dr.step(EP, {"type": "review"})
    assert calls(h)[-1]["sensitive_step"] is False


def test_emit_sensitive_for_endware_and_export(tmp_path):
    h, dr, pa = started(sens_form(tmp_path))
    h.export(EP)
    assert h.trace[-1]["sensitive_step"] is False                 # no sensitive event yet
    h._emit("endware", tool="letters")
    assert h.trace[-1]["sensitive_step"] is True                  # endware on an episode with sensitive items
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    h.export(EP)
    assert h.trace[-1]["sensitive_step"] is True
    h._emit("endware", tool="figures", sensitive_step=False)
    assert h.trace[-1]["sensitive_step"] is False                 # an explicit value is kept
    g = hw()
    g._emit("endware", tool="letters")
    assert g.trace[-1]["sensitive_step"] is False                 # no export yet: nothing to inherit
    g.export(EP)
    g._emit("endware", tool="letters")
    assert g.trace[-1]["sensitive_step"] is False
    assert "sensitive_step" not in g._emit("harness", op="clock")


def test_endware_inherits_last_exported_episode(tmp_path):
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    h.open_episode("forms", sens_form(tmp_path), EP, P)
    h.open_episode("forms", FORM, EQ, P)
    h.export(EP); h.export(EQ)
    h._emit("endware", tool="letters")
    assert h.trace[-1]["sensitive_step"] is False
    h.export(EP)
    h._emit("endware", tool="letters")
    assert h.trace[-1]["sensitive_step"] is True
    h._emit("harness", op="export", episode="SYNTH-GONE")
    h._emit("endware", tool="letters")
    assert h.trace[-1]["sensitive_step"] is True


def test_export_counted_unless_audit():
    h = hw()
    h.export(EP)
    assert h.trace[-1]["audit"] is False and h.trace[-1] in h.counted()
    h.export(EP, audit=True)
    assert h.trace[-1] not in h.counted()


def test_open_with_dict_case_names_it():
    import tomllib
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    for kind, f, want in (("forms", FORM, "FAKE-form"), ("orders", LIST, "FAKE-list")):
        h.open_episode(kind, tomllib.load(open(f, "rb")), "SYNTH-E-" + kind, P)
        assert h.trace[-1]["case"] == want
    h.open_episode("forms", FORM, EP, P)
    assert h.trace[-1]["case"] == "fake_form.toml"


def test_blocked_clinician_answer_marked_interpreter_but_approve_not():
    h = blocked()
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    assert "interpreter" not in calls(h)[-1]["args"][0]
    dr.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    assert calls(h)[-1]["args"][0]["interpreter"] is True
    g = hw()
    d = g.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    d.step(EP, {"type": "approve"}); d.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    assert "interpreter" not in calls(g)[-1]["args"][0]


def test_patient_changing_agent_answer_is_thanked():
    h, dr, pa = started(FORM)
    ag = h.session("SYNTH-fake-ag", "patient_agent", P)
    pa.step(EP, {"type": "grant"} if "agent" not in loader.forms().FIELDS.get("grant", set())
            else {"type": "grant", "agent": "SYNTH-fake-ag", "patient": P})
    assert ag.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})["accepted"]
    same = pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})
    assert "message" not in same                                   # same value: nothing changed
    ag.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})
    changed = pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
    assert locales.signed("PV-ANS-CHANGED") and changed.get("message") == locales.line("PV-ANS-CHANGED")
    again = pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})
    assert "message" not in again                                  # last answer was the patient's own
    ag.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    assert "message" not in dr.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})   # not the patient


class _Bare:
    """Env with observe returning a non-dict and nothing else."""
    def __init__(self, real): self._r, self.log = real, real.log
    def observe(self, *a): return ["plain"]
    def replay(self, *a): return self._r.replay(*a)
    def check(self, *a): return self._r.check(*a)


def test_non_dict_results_wrapped(monkeypatch):
    from ward import harness
    h = hw(kind="orders")
    real = harness.Episode.env
    monkeypatch.setattr(harness.Episode, "env", lambda self, *a, **k: _Bare(real(self, *a, **k)))
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    assert dr.observe(EP) == {"accepted": True, "value": ["plain"]}
    assert calls(h)[-1]["accepted"] is True
    r = h._out(dr, dict(actor="x", episode=EP, args=[]), ["raw"])
    assert r == ["raw"] and calls(h)[-1]["accepted"] is True


def test_export_nonsynthetic_flag_combinations(monkeypatch):
    from ward import harness
    real = harness.Episode.env
    class OnlyOpen(_OldEnv):
        def open_episode(self, *a): pass
    class OnlyExport(_OldEnv):
        def export(self): return {}
    for cls, by in ((OnlyOpen, "harness"), (OnlyExport, "middleware")):
        monkeypatch.setattr(harness.Episode, "env", lambda self, *a, cls=cls, **k: cls(real(self, *a, **k)))
        r = Harness("FAKE", 1, "1930-01-01T08:00").try_export_nonsynthetic("orders", LIST, P)
        assert r == {"accepted": False, "reason": msg(EXPECTED_LINE["export_real"]), "by": by}
    class Accepts(_OldEnv):
        def open_episode(self, *a): pass
        def export(self): return {}
    monkeypatch.setattr(harness.Episode, "env", lambda self, *a, **k: Accepts(real(self, *a, **k)))
    h = Harness("FAKE", 1, "1930-01-01T08:00")
    r = h.try_export_nonsynthetic("orders", LIST, P)
    assert r == {"accepted": True, "reason": "", "by": "middleware"} and h.trace[-1]["note"]["claim"] == "CL-EXPORTED"
    assert h.trace[-1]["args"] == [{"synthetic": False}]


def test_blocked_view_equals_filtered_full_view():
    h = blocked()
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    dr.step(EP, {"type": "approve"})
    assert h.patient_view(EP) == {}
    dr.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    full = h._replayed(h.episodes[EP]).patient_view()
    v = h.patient_view(EP)
    keep = {k: x for k, x in full.items() if isinstance(x, str) and x.startswith(locales.line("PV-SAMEDAY").split("[")[0])}
    assert keep and v == keep


def test_blocked_view_walks_nested(monkeypatch):
    from ward import harness
    sd = locales.line("PV-SAMEDAY").split("[")[0] + "x"
    full = {"a": "other", "b": {"c": sd, "d": "no", "e": {}}, "f": [sd, "no", [], {"g": "no"}, 3], "h": 3, "i": {"j": "no"}}
    class V(_OldEnv):
        def patient_view(self): return full
    real = harness.Episode.env
    h = blocked()
    monkeypatch.setattr(harness.Episode, "env", lambda self, *a, **k: V(real(self, *a, **k)))
    assert h.patient_view(EP) == {"b": {"c": sd}, "f": [sd]}


def test_emit_sensitive_matching_is_exact(tmp_path):
    h, dr, pa = started(sens_form(tmp_path))
    pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": True})      # event, not sensitive
    plain = len(h.episodes[EP].log) - 1
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    sens = len(h.episodes[EP].log) - 1
    chk = lambda res: h._emit("harness", op="check", episode=EP, result=res)["sensitive_step"]
    assert chk({"open": ["fake_a"]}) is True                     # quoted id
    assert chk({"t": "zfake_az"}) is False                       # a substring of something else
    assert chk({"t": f"see {EP}#{sens} now"}) is True             # unquoted event id
    assert chk({"t": f"see {EP}#{plain} now"}) is False
    o = lambda r: (h._out(pa, dict(actor=P, episode=EP, args=[]), r), calls(h)[-1]["sensitive_step"])[1]
    assert o({"accepted": True, "t": "zfake_az"}) is False
    assert o({"accepted": True, "t": f"see {EP}#{sens} now"}) is True
    assert o({"accepted": True, "t": ["fake_a"]}) is True


def test_review_sensitive_by_question_or_event_alone(tmp_path, monkeypatch):
    h, dr, pa = started(sens_form(tmp_path))
    pa.step(EP, {"type": "answer", "question_id": "fake_a", "value": False})
    n = len(h.episodes[EP].log) - 1
    real = Harness.peek
    for queue, want in ((["about fake_a only"], True), ([f"event {n} only"], True), (["event 99"], False), ([], False)):
        monkeypatch.setattr(Harness, "peek", lambda self, e, q=queue: dict(real(self, e), clinician_queue=q))
        dr.step(EP, {"type": "review"})
        assert calls(h)[-1]["sensitive_step"] is want, queue


def test_blocked_clinician_non_dict_step_refused_cleanly():
    h = blocked()
    dr = h.session("SYNTH-fake-dr", "clinician", P, discipline="medicine")
    r = dr.step(EP, "approve")
    assert r["accepted"] is False


def test_patient_answer_to_other_question_not_thanked():
    h, dr, pa = started(FORM)
    ag = h.session("SYNTH-fake-ag", "patient_agent", P)
    pa.step(EP, {"type": "grant"} if "agent" not in loader.forms().FIELDS.get("grant", set())
            else {"type": "grant", "agent": "SYNTH-fake-ag", "patient": P})
    ag.step(EP, {"type": "answer", "question_id": "fake_a", "value": True})
    assert "message" not in pa.step(EP, {"type": "answer", "question_id": "fake_b", "value": False})
