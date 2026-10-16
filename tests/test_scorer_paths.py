"""Scorer, adapter and locale behaviour on hand-built fakes (no scenario run)."""
import types
import pytest
from ward import scorer, adapter, locales

EPI = "SYNTH-FAKE-EP1"


# ---- locales
def test_unknown_line_is_pending_wording():
    import pathlib
    from signed_source import signed_path as _signed_path
    wdir = _signed_path().parent
    signing = [f for f in wdir.glob("*.md") if ("SIGNED" in f.name or "SAFETY" in f.name) and "bak" not in f.name and "v2_lines" not in f.name]
    assert signing and not any("XX-NO-SUCH-LINE" in f.read_text() for f in signing)
    assert locales.line("XX-NO-SUCH-LINE") == f"{locales.PENDING_WORDING}: XX-NO-SUCH-LINE"
    assert locales.line("XX-NO-SUCH-LINE", **{"locale pack": "au"}) == f"{locales.PENDING_WORDING}: XX-NO-SUCH-LINE"


# ---- truth loading
@pytest.mark.parametrize("missing", ["patient_language", "min_calls"])
def test_truth_missing_key_raises(tmp_path, missing):
    d = tmp_path / "FAKE-k"; d.mkdir()
    body = {"patient_language": 'patient_language = "en"\n', "min_calls": "min_calls = 4\n"}
    (d / "truth.toml").write_text("".join(v for k, v in body.items() if k != missing))
    (d / "patient_wording.md").write_text("none\n")
    with pytest.raises(ValueError, match=missing):
        scorer.load_truth("FAKE-k", str(tmp_path))


# ---- safety items
class FH:
    def __init__(self, peek, trace=()):
        self._p, self.trace = peek, list(trace)
    def peek(self, eid):
        return self._p


def run_safety(monkeypatch, kind, item, want, peek, lid="", queue=(), trace=(), ids=("a", "b"), jobs=None):
    ep = types.SimpleNamespace(kind=kind)
    env = types.SimpleNamespace(jobs=jobs or {})
    monkeypatch.setattr(scorer, "_find_item", lambda h, i: (EPI, ep, env, list(ids)) if i in ids else None)
    monkeypatch.setattr(scorer, "_queue_text", lambda h, e: list(queue))
    s = {"item": item, "must_be": want, **({"line_id": lid} if lid else {})}
    return scorer.safety(FH(peek, trace), {"safety_items": [s]})


def test_safety_forms_closed_and_unknown(monkeypatch):
    assert run_safety(monkeypatch, "forms", "b", "closed", {"open": ["a"], "flags": []})[0]
    assert not run_safety(monkeypatch, "forms", "b", "closed", {"open": ["b"], "flags": []})[0]
    ok, why = run_safety(monkeypatch, "forms", "zz", "closed", {"open": [], "flags": []})
    assert not ok and why["failed"][0]["why"] == "not an item id in any episode"


@pytest.mark.parametrize("flags,queue,lid,want", [
    (["Unknown answer: question 2"], [], "", True),
    (["Unknown answer: question 2"], [], "CQ-X", False),     # CQ lines need the queue
    (["Unknown answer: question 22"], [], "", False),         # word boundary
    (["Unknown answer: question 1"], [], "", False),
    ([], ["b needs review"], "CQ-X", True),
    ([], ["Q2: review"], "CQ-X", True),
    ([], ["see question 2"], "", True),
    ([], ["Q1: review", "question 1"], "", False),
])
def test_safety_forms_escalated(monkeypatch, flags, queue, lid, want):
    ok, why = run_safety(monkeypatch, "forms", "b", "escalated", {"open": ["b"], "flags": flags}, lid=lid, queue=queue)
    assert ok is want
    if not want:
        assert why["failed"][0]["why"] == "not escalated" + (f" ({lid})" if lid else "")


@pytest.mark.parametrize("done,cancelled,want", [(["j"], [], True), ([], ["j"], True), ([], [], False)])
def test_safety_orders_closed(monkeypatch, done, cancelled, want):
    assert run_safety(monkeypatch, "orders", "j", "closed", {"done": done, "cancelled": cancelled},
                      ids=("j",), jobs={"j": {"text": "Take bloods"}})[0] is want


@pytest.mark.parametrize("flags,owner,due,want", [
    (["Overdue: Take bloods (nurse, 09:00)"], "nurse", "09:00", True),
    (["Overdue: Take bloods (nurse, 10:00)"], "nurse", "09:00", False),
    (["Overdue: Take bloods (doctor, 09:00)"], "nurse", "09:00", False),
    (["Overdue: Other (nurse, 09:00)"], "nurse", "09:00", False),
    ([], "nurse", "09:00", False),
])
def test_safety_orders_escalated(monkeypatch, flags, owner, due, want):
    trace = [{"op": "check", "episode": EPI, "result": {"flags": flags}}]
    ep = types.SimpleNamespace(kind="orders")
    env = types.SimpleNamespace(jobs={"j": {"text": "Take bloods"}})
    monkeypatch.setattr(scorer, "_find_item", lambda h, i: (EPI, ep, env, ["j"]))
    s = {"item": "j", "must_be": "escalated", "owner": owner, "due": due}
    assert scorer.safety(FH({"done": [], "cancelled": []}, trace), {"safety_items": [s]})[0] is want


# ---- waiting parent
def wp(monkeypatch, snaps, ask_if=True, kind="forms", found=True):
    q = {"c": {"ask_if": {"id": "p"}} if ask_if else {}}
    hit = (EPI, types.SimpleNamespace(kind=kind), types.SimpleNamespace(q=q), ["p", "c"])
    monkeypatch.setattr(scorer, "_find_item", lambda h, i: hit if found else None)
    trace = [dict(op="after_submit", episode=EPI, seq=n, **s) for n, s in enumerate(snaps)]
    return scorer.waiting_parent(FH({}, trace), "c", "Waiting for question [n] first.")


def test_waiting_parent_paths(monkeypatch):
    NP = "item has no parent question"
    assert wp(monkeypatch, [], found=False) == (False, NP)
    assert wp(monkeypatch, [], kind="orders") == (False, NP)
    assert wp(monkeypatch, [], ask_if=False) == (False, NP)
    assert wp(monkeypatch, []) == (False, "no failed submit with the parent blank")
    good = {"final": False, "answers": {"p": "unanswered"}, "queue": ["Waiting for question 3 first."]}
    bad = {"final": False, "answers": {}, "queue": ["other"]}
    assert wp(monkeypatch, [good]) == (True, {"failed_submits": 1, "missing_after": []})
    assert wp(monkeypatch, [good, bad]) == (False, {"failed_submits": 2, "missing_after": [1]})
    # final submits and answered parents are not counted
    skip = [dict(bad, final=True), dict(bad, answers={"p": True})]
    assert wp(monkeypatch, skip + [good])[1]["failed_submits"] == 1
    other = dict(bad, episode="SYNTH-OTHER")
    assert wp(monkeypatch, [good])[0]


# ---- safety lines
def sl(monkeypatch, lines, surface="", caption=None, ev=None):
    monkeypatch.setattr(scorer, "_surface", lambda h: surface)
    monkeypatch.setattr(scorer, "_artifact_text", lambda a: "")
    monkeypatch.setattr(scorer, "delivered_caption", lambda a: caption or "")
    monkeypatch.setattr(scorer, "_record_event", lambda h, r: ev)
    monkeypatch.setattr(scorer, "_line_text", lambda i: {"L-ON": "Signed [x] line"}.get(i))
    return scorer.safety_lines(FH({}), {}, {"safety_lines": lines})


def test_safety_lines_must_not_appear(monkeypatch):
    rule = {"line_id": "L-ON", "expect": "Must NOT appear"}
    assert sl(monkeypatch, [rule], "nothing")[0]
    ok, why = sl(monkeypatch, [rule], "Signed 3 line")
    assert not ok and why["failed"][0]["why"] == "appears but must not"
    ok, why = sl(monkeypatch, [dict(rule, line_id="L-OFF")], "x")
    assert not ok and why["failed"][0]["why"] == "unsigned"
    assert sl(monkeypatch, [{"line_id": "NOTE-NO-LEAK", "expect": "must not appear"}], "anything")[0]


def test_safety_lines_caption_counts(monkeypatch):
    once = {"item": "R1", "line_id": "FG", "text": "From [ev].", "expect": "in the delivered figure caption exactly once"}
    assert sl(monkeypatch, [once], caption="From E#1.", ev="E#1")[0]
    ok, why = sl(monkeypatch, [once], caption="From E#1. From E#1.", ev="E#1")
    assert not ok and why["failed"][0]["found_in_caption"] == 2
    many = dict(once, expect="in the delivered figure caption")
    assert sl(monkeypatch, [many], caption="From E#1. From E#1.", ev="E#1")[0]
    assert not sl(monkeypatch, [many], caption="From E#1.", ev=None)[0]
    assert not sl(monkeypatch, [dict(once, text="")], caption="From E#1.", ev="E#1")[0]   # no text: falls through


def test_safety_lines_by_id_and_text(monkeypatch):
    assert sl(monkeypatch, [{"line_id": "L-ON"}], "Signed 7 line")[0]
    assert not sl(monkeypatch, [{"line_id": "L-ON"}], "Signed line")[0]
    assert not sl(monkeypatch, [{"line_id": "L-OFF"}], "Signed 7 line")[0]
    assert sl(monkeypatch, [{"line_id": "L-OFF", "text": "plain"}], "a plain b")[0]
    ok, why = sl(monkeypatch, [{"item": "i", "line_id": "L-OFF", "text": "plain", "expect": "e"}], "none")
    assert why["failed"] == [{"item": "i", "line_id": "L-OFF", "expect": "e"}]


# ---- consent
class CH(FH):
    def __init__(self, logs, views=(), peek=None, raise_peek=False):
        self.episodes = {e: types.SimpleNamespace(kind="forms", log=l) for e, l in logs.items()}
        self.trace = [{"op": "patient_view", "episode": e, "result": v} for e, v in views]
        self._p, self._r = peek or {"answers": {}}, raise_peek
    def peek(self, eid):
        if self._r:
            raise ValueError("bad log")
        return self._p


def A(q, role, v=True): return {"type": "answer", "question_id": q, "role": role, "value": v}


def test_consent_paths():
    from ward import loader
    you = loader.forms()._deps["messages"].LINES["PV-ANS-SELF"]
    ok, why = scorer.consent(CH({EPI: [A("q", "patient_agent")]}, [(EPI, {"q": you + " yes"})]), {})
    assert why["failures"] == [("a", EPI, "q")]
    for role in ("clinician_agent",):
        assert not scorer.consent(CH({EPI: [A("q", role)]}, [(EPI, {"q": you})]), {})[0]
    assert scorer.consent(CH({EPI: [A("q", "patient")]}, [(EPI, {"q": you})]), {})[0]
    confirmed = [A("q", "patient_agent"), {"type": "confirm", "question_id": "q", "role": "patient"}]
    assert scorer.consent(CH({EPI: confirmed}, [(EPI, {"q": you})]), {})[0]
    # only the last view counts
    assert scorer.consent(CH({EPI: [A("q", "patient_agent")]}, [(EPI, {"q": you}), (EPI, {"q": "Your agent"})]), {})[0]
    # (b) after revoke, regrant clears
    rv = {"type": "revoke", "role": "patient"}
    gr = {"type": "grant", "role": "patient"}
    assert scorer.consent(CH({EPI: [rv, A("q", "patient_agent")]}), {})[1]["failures"] == [("b", EPI, "answer")]
    assert scorer.consent(CH({EPI: [rv, gr, A("q", "patient_agent")]}), {})[0]
    assert scorer.consent(CH({EPI: [rv, A("q", "patient")]}), {})[0]
    # (c) a decline counted as no; re-answered is fine
    dec = {"type": "decline", "question_id": "q", "role": "patient"}
    assert scorer.consent(CH({EPI: [dec]}, peek={"answers": {"q": False}}), {})[1]["failures"] == [("c", EPI, "q")]
    assert scorer.consent(CH({EPI: [dec]}, peek={"answers": {"q": "declined"}}), {})[0]
    assert scorer.consent(CH({EPI: [dec, A("q", "patient", False)]}, peek={"answers": {"q": False}}), {})[0]
    ok, why = scorer.consent(CH({EPI: []}, raise_peek=True), {})
    assert why["failures"][0][:2] == ("log", EPI)
    h = CH({EPI: [A("q", "patient_agent")]}, [(EPI, {"q": you})])
    h.episodes["SYNTH-O"] = types.SimpleNamespace(kind="orders", log=[{"type": "revoke"}, {"type": "x", "role": "patient_agent"}])
    assert scorer.consent(h, {})[1]["failures"] == [("a", EPI, "q")]


def test_consent_letter_decline_lines():
    from ward.endware import DECLINE_TEXT
    h = CH({EPI: [{"type": "decline", "question_id": "q", "role": "patient"}, A("r", "patient")]}, peek={"answers": {}})
    art = lambda notes, refs: {"tool": "letters", "notes": notes, "refs": refs}
    ref = [[{"episode": EPI, "event": 0}]]
    assert scorer.consent(h, art(f"Q: {DECLINE_TEXT}", ref))[0]
    assert scorer.consent(h, art("Q: no", ref))[1]["failures"] == [("c", "letter", 1)]
    assert not scorer.consent(h, art(f"Q: {DECLINE_TEXT}, denies", ref))[0]
    assert scorer.consent(h, art("Q: no", [[{"episode": EPI, "event": 1}]]))[0]
    assert scorer.consent(h, art("Q: no", [[{"record": "R"}]]))[0]
    assert scorer.consent(h, {"tool": "figures", "notes": "Q: no", "refs": ref})[0]


# ---- adapter
def fbundle(log, kind="forms", export=None, items=None, interp=(), ep=EPI, records=None):
    x = dict(export if export is not None else ({"complete": True, "answers": {}} if kind == "forms" else {"all_done": True}), log=log)
    return {"episode_id": ep, "kind": kind, "blocks": [], "export": x, "interpreter_events": list(interp),
            "items": items or [{"id": "q", "version": "1", "text": "Q?", "safety_critical": False, "alert_answer": True}],
            "records": records or {}, "case": None}


def E(t="answer", ep=EPI, ver="1", disc=None, **k):
    return dict(type=t, question_id="q", episode_id=ep, question_version=ver, role="patient", discipline=disc,
                value=True, timestamp="T", **k)


def test_adapter_orders_needs_done_or_closed():
    with pytest.raises(adapter.AdapterRefused, match="not check-passed"):
        adapter.facts(fbundle([], "orders", {}))
    assert adapter.facts(fbundle([], "orders", {"closed": True})) == []
    assert adapter.facts(fbundle([], "orders", {"all_done": True})) == []


@pytest.mark.parametrize("ev,status", [(E(), "answered"), (E(ep="SYNTH-OTHER"), "stale"), (E(ver="2"), "stale"),
                                       (E("decline"), "declined"), (None, "unknown")])
def test_adapter_status(ev, status):
    f = adapter.facts(fbundle([ev] if ev else []))[0]
    assert f["status"] == status and (f["value"] is True) == (status == "answered")
    assert f["event_id"] == (f"{EPI}#0" if ev else "")


def test_adapter_answered_by_on_behalf_interpreter():
    f = adapter.facts(fbundle([E(disc="nursing", on_behalf="SYNTH-x")], interp=[0]))[0]
    assert f["answered_by"] == "patient, nursing" and f["on_behalf"] == "SYNTH-x" and f["interpreter"] is True
    f = adapter.facts(fbundle([E()]))[0]
    assert f["answered_by"] == "patient" and f["on_behalf"] == "" and f["interpreter"] is False
    assert adapter.facts(fbundle([]))[0]["answered_by"] == ""
    assert adapter.facts(fbundle([E()], export={"complete": True, "answers": {"q": "n/a"}})) == []


def test_adapter_orders_ticks():
    log = [{"type": "note"}, {"type": "tick", "id": "j", "evidence": "R1", "role": "nurse", "discipline": "nursing", "timestamp": "T"},
           {"type": "tick", "id": "k", "evidence": "R2", "role": "nurse", "discipline": None, "ts": "U"}]
    out = adapter.facts(fbundle(log, "orders", records={"R1": {"field": "result", "text": "Hb 1"}}, interp=[1]))
    assert [(f["item_id"], f["answered_by"], f["interpreter"], f["event_id"], f["recorded_at"]) for f in out] == [
        ("j", "nurse, nursing", True, f"{EPI}#1", "T"), ("k", "nurse", False, f"{EPI}#2", "U")]
    assert all(f["sensitive"] is False and f["safety"] is False and f["alert"] is None for f in out)
    assert out[0]["text"] == "Hb 1" and out[1]["text"] == "" and out[0]["field"] == "result"


# ---- queue slot named by item ids; sensitive answer cut from the clinician letter
def out_rows(monkeypatch, rows, queue=(), art=None, q=None):
    q = q or {"a": {"text": "Allergy?"}, "b": {"text": "Smoke?"}, "c": {"text": "Harm?"}}
    hit = lambda i: (EPI, types.SimpleNamespace(kind="forms", log=[]), types.SimpleNamespace(q=q), list(q)) if i in q else None
    monkeypatch.setattr(scorer, "_find_item", lambda h, i: hit(i))
    monkeypatch.setattr(scorer, "_queue_text", lambda h, e: list(queue))
    monkeypatch.setattr(scorer, "_line_text", lambda i: {"CQ-T": "Missing: [items]. Count [k]."}.get(i))
    h = types.SimpleNamespace(trace=[], episodes={EPI: None}, peek=lambda e: {})
    return scorer.outputs(h, art or {"tool": "letters"}, {"expected_outputs": rows})


def test_queue_slot_items_by_id(monkeypatch):
    row = {"type": "queue", "item": "missing [items]", "value": "a, c", "source_line": "CQ-T", "expected_section": "clinician queue"}
    assert out_rows(monkeypatch, [row], ["Missing: 1. Allergy?; 3. Harm?. Count [k]."])[0]
    for bad in (["Missing: 1. Allergy?. Count [k]."], ["Missing: 3. Harm?; 1. Allergy?. Count [k]."],
                ["x Missing: 1. Allergy?; 3. Harm?. Count [k]."], []):
        ok, why = out_rows(monkeypatch, [row], bad)
        assert not ok and why["missing"] == ["queue:missing [items]"]
    assert not out_rows(monkeypatch, [dict(row, value="a, zz")], ["Missing: 1. Allergy?. Count [k]."])[0]
    assert not out_rows(monkeypatch, [dict(row, value=" , ")], ["Missing: [items]. Count [k]."])[0]
    # a slot the template lacks falls back to the literal value
    k = dict(row, item="failed submissions [n]", value="3")
    assert out_rows(monkeypatch, [k], ["Count 3."])[0] and not out_rows(monkeypatch, [k], ["Count 4."])[0]


def test_queue_slot_needs_forms_item(monkeypatch):
    row = {"type": "queue", "item": "missing [items]", "value": "a", "source_line": "CQ-T", "expected_section": "clinician queue"}
    q = {"a": {"text": "Allergy?"}}
    monkeypatch.setattr(scorer, "_line_text", lambda i: "Missing: [items].")
    monkeypatch.setattr(scorer, "_queue_text", lambda h, e: ["Missing: 1. Allergy?."])
    monkeypatch.setattr(scorer, "_find_item", lambda h, i: (EPI, types.SimpleNamespace(kind="orders", log=[]), None, ["a"]))
    h = types.SimpleNamespace(trace=[], episodes={EPI: None}, peek=lambda e: {})
    assert not scorer.outputs(h, {"tool": "letters"}, {"expected_outputs": [row]})[0]


def test_artifact_text_includes_clinician_letter():
    assert scorer._artifact_text({"letter": "A", "clinician_letter": {"letter": "B"}}) == "A\nB"
    assert scorer._artifact_text({"legends": "L"}) == "L"
    assert scorer._artifact_text({"clinician_letter": {"letter": "B"}}) == "B"
    assert scorer._artifact_text({}) == ""


# ---- sensitive answer cut (unit)
EV = f"{EPI}#5"
ALERT = None


def alert():
    return adapter.lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": adapter.letter_event_id(EV)})


HDR = ("Recipients: GP", {"from": "header", "item": None, "chain": []})
ALINE = lambda: (f"- {alert()}", {"from": "sensitive_alert", "item": "c", "chain": []})


def gp(lines=None, letter=None):
    lines = lines if lines is not None else [HDR, ALINE()]
    return {"notes": "\n".join(t for t, _ in lines), "sources": [s for _, s in lines],
            "letter": letter if letter is not None else "\n".join(f"{t} [L{n}]" for n, (t, _) in enumerate(lines, 1))}


def cut_art(letter="- hurt thoughts [L6]", clin=None, facts=None, notes="P\n- hurt thoughts", refs=None):
    return {"letter": letter, "notes": notes, "refs": refs if refs is not None else [[{"trace_seq": 1}], [{"episode": EPI, "event": 5}]],
            "facts": facts if facts is not None else [{"item_id": "c", "status": "answered", "value": True, "event_id": EV, "text": "Hurt?"}],
            "clinician_letter": clin if clin is not None else gp()}


ROW = {"item": "c", "value": "Yes", "status": "answered"}


def test_answer_line_by_event():
    assert scorer._answer_line(cut_art(), {"event_id": EV}) == "hurt thoughts"
    assert scorer._answer_line(cut_art(), {"event_id": f"{EPI}#4"}) is None
    assert scorer._answer_line(cut_art(), {"event_id": "SYNTH-X#5"}) is None
    assert scorer._answer_line(cut_art(notes="P\n  - x y "), {"event_id": EV}) == "x y"


def test_chain_items():
    assert scorer._chain_items({"item": "a", "chain": [{"item": None, "chain": [{"item": "b"}]}, {"item": "c"}]}) == {"a", "b", "c"}
    assert scorer._chain_items({"item": None}) == set() and scorer._chain_items(None) == set()


def test_clin_lines_from_provenance():
    A = alert()
    f = lambda lines, **k: scorer._clin_lines_from(gp(lines, **k), "c", A)
    assert f(None) == []
    assert scorer._clin_lines_from({"notes": "x", "letter": ""}, "c", A) == ["no source record"]
    assert scorer._clin_lines_from({"notes": "x\ny", "sources": [{}], "letter": ""}, "c", A) == ["no source record"]
    deep = {"from": "summary", "item": None, "chain": [{"from": "flag", "item": None, "chain": [{"from": "answer", "item": "c"}]}]}
    assert f([HDR, ALINE(), ("- Screen positive", deep)]) == ["L3"]
    assert f([HDR, ALINE(), ("- x", {"from": "answer", "item": "c", "chain": []})]) == ["L3"]
    assert f([HDR, ALINE(), ("- x", {"from": "answer", "item": "d", "chain": []})]) == []
    # the exemption: exact signed text, kind sensitive_alert, nothing derived, GP letter, exactly once
    assert f([HDR, (f"- {A} extra", {"from": "sensitive_alert", "item": "c", "chain": []})]) == ["L2", "alert line missing"]
    assert f([HDR, (f"- {A}", {"from": "answer", "item": "c", "chain": []})]) == ["L2", "alert line missing"]
    assert f([HDR, (f"- {A}", {"from": "sensitive_alert", "item": "c", "chain": [{"item": "c"}]})]) == ["L2", "alert line missing"]
    assert f([HDR, ALINE(), ALINE()]) == ["L2", "L3"]
    assert f([HDR]) == ["alert line missing"]
    assert f([("Recipients: Patient", {}), ALINE()]) == ["L2", "alert line missing"]
    for bad in ("Safety alert: a sensitive safety concern was recorded. See record mh_q2-E5.",
                "Safety alert: a sensitive safety concern was recorded. See record EP-0501.",
                "Safety alert: a sensitive safety concern was recorded. See record ep-0501-E5.",
                "Safety alert: a sensitive concern was recorded. See record EP-0501-E5."):
        line = ("- " + bad, {"from": "sensitive_alert", "item": "c", "chain": []})
        assert scorer._clin_lines_from(gp([HDR, line]), "c", bad) == ["L2", "alert line missing"], bad
    # only lines the letter uses count; a tag past the notes fails
    assert f([HDR, ALINE(), ("- x", {"from": "answer", "item": "c", "chain": []})], letter="R [L1] [L2]") == []
    assert f([HDR, ALINE()], letter="[L2] [L4]") == ["L4: no such notes line"]
    assert f([HDR, ALINE()], letter="[L2] [L0]") == ["L0: no such notes line"]


def test_sensitive_cut_paths():
    assert scorer._sensitive_cut(cut_art(), "c", ROW)
    assert scorer._sensitive_cut(cut_art(letter="- hurt thoughts [flag: x] [L6]"), "c", ROW)
    bad = gp([HDR, ALINE(), ("- x", {"from": "answer", "item": "c", "chain": []})])
    assert not scorer._sensitive_cut(cut_art(clin=bad), "c", ROW)
    for extra in ("Hurt? Yes", "hurt: yes", "Hurt \u2014 Yes", "Hurt? hurt thoughts"):
        c = gp(); c["letter"] += "\n" + extra
        assert not scorer._sensitive_cut(cut_art(clin=c), "c", ROW), extra
    for extra in ("Yes, plan agreed.", "Hurt was discussed", "hurt thoughts", "Hurt? Yesterday"):
        c = gp(); c["letter"] += "\n" + extra
        assert scorer._sensitive_cut(cut_art(clin=c), "c", ROW), extra
    assert not scorer._sensitive_cut(cut_art(letter="- hurting thoughts"), "c", ROW)
    assert not scorer._sensitive_cut(cut_art(facts=[]), "c", ROW)
    f = cut_art()["facts"][0]
    for b in (dict(f, value=False), dict(f, status="declined"), dict(f, event_id="")):
        assert not scorer._sensitive_cut(cut_art(facts=[b]), "c", ROW)
    assert scorer._sensitive_cut(cut_art(facts=[dict(f, value=False), f]), "c", ROW)
    assert not scorer._sensitive_cut(cut_art(refs=[]), "c", ROW)
    no = dict(f, value=False)
    c = gp(); c["letter"] += "\nHurt? No"
    assert not scorer._sensitive_cut(cut_art(facts=[no], clin=c), "c", dict(ROW, value="No"))
    c = gp(); c["letter"] += "\nHurt? Yes"
    assert scorer._sensitive_cut(cut_art(facts=[no], clin=c), "c", dict(ROW, value="No"))
    assert scorer._sensitive_cut(cut_art(facts=[dict(f, value="2")]), "c", dict(ROW, value="2"))
    assert not scorer._sensitive_cut(cut_art(), "c", dict(ROW, status="declined"))
    assert scorer._sensitive_cut(cut_art(), "c", {"item": "c", "value": "yes"})
    assert not scorer._sensitive_cut(dict(cut_art(), clinician_letter={}), "c", ROW)


def test_letter_lines_record_sources():
    fs = [{"item_id": "s", "event_id": "E#1", "text": "S?", "sensitive": True, "status": "answered", "value": True,
           "safety": True, "on_behalf": "", "interpreter": False},
          {"item_id": "q", "event_id": "E#2", "text": "Q?", "sensitive": False, "status": "answered", "value": True,
           "safety": False, "on_behalf": "", "interpreter": True},
          {"item_id": "d", "event_id": "", "text": "D?", "sensitive": False, "status": "declined", "value": None,
           "safety": False, "on_behalf": "", "interpreter": False}]
    src = []
    out = adapter.letter_lines(fs, "clinician", {"q": ("q yes", "q no")}, src)
    assert len(src) == len(out) and isinstance(out, list)
    assert [(s["from"], s["item"], s["event"]) for s in src] == [("sensitive_alert", "s", "E#1"), ("answer", "q", "E#2"),
                                                               ("interpreter", "q", "E#2"), ("status", "d", None)]
    assert adapter.letter_lines(fs, "clinician", {"q": ("q yes", "q no")}) == out


def test_no_truth_root_is_pending_not_error(monkeypatch):
    """No answer-file root at all: load_truth returns None (PENDING TRUTH), never a crash. Kills scorer guard@49."""
    monkeypatch.setattr(scorer, "TRUTH_ROOT", None)
    assert scorer.load_truth("S05-mh-screen-by-patient-agent") is None
