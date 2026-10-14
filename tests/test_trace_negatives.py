"""Room ruling: each tamper below must make its trace fail on its own (the untampered run passes that check)."""
import copy, pytest
from stack import runner, scorer

S08, S05 = "S08-three-fails-escalation", "S05-mh-screen-by-patient-agent"


def run(sid, tmp_path):
    t = scorer.load_truth(sid)
    if t is None:
        pytest.skip(scorer.PENDING)
    h, art = runner.run(sid, str(tmp_path), t["patient_language"])
    return t, h, art


def s08_outputs(monkeypatch, h, art, t, f):
    real = scorer._queue_text
    monkeypatch.setattr(scorer, "_queue_text", lambda hh, e: [f(x) for x in real(hh, e)])
    return scorer.outputs(h, art, t)


def test_s08_queue_line_wrong_id_or_text_fails(tmp_path, monkeypatch):
    t, h, art = run(S08, tmp_path)
    assert s08_outputs(monkeypatch, h, art, t, lambda x: x)[0]
    eid, ep, env, ids = scorer._find_item(h, "takes_blood_thinner")
    n = ids.index("takes_blood_thinner") + 1
    good = f"{n}. {env.q['takes_blood_thinner']['text']}"
    other = [i for i in ids if i not in ("takes_blood_thinner", "allergy_any", "smokes", "pregnant_possible")][0]
    wrong_id = f"{ids.index(other) + 1}. {env.q[other]['text']}"
    wrong_text = f"{n}. {env.q['takes_blood_thinner']['text'].replace('blood', 'water')}"
    for bad in (wrong_id, wrong_text):
        ok, why = s08_outputs(monkeypatch, h, art, t, lambda x: x.replace(good, bad))
        assert not ok and why["missing"] == ["queue:missing [items]"], bad


def test_s05_one_word_changed_in_patient_letter_fails(tmp_path):
    t, h, art = run(S05, tmp_path)
    t3 = lambda a: scorer.scenario_tests(h, t, a)[1]["results"]["S05-T3-sensitive-cut"]
    assert t3(art) is True
    a = copy.deepcopy(art)
    a["letter"] = a["letter"].replace("thoughts of harming yourself", "thoughts of hurting yourself")
    assert t3(a) == ["mh_q2 answer cut from the patient letter"]


S12 = "S12-patient-declines-safety-question-to-letter-with-privacy-line"


def test_s12_declined_route_against_own_truth(tmp_path):
    """Declined route only (CQ-BEFORE-PROC to the clinician, PV-BEFORE-PROC to the patient), from S12's truth rows.
    The whole trace stays skipped until letters lands; this part does not wait on letters."""
    t, h, art = run(S12, tmp_path)
    ids = ("CQ-BEFORE-PROC", "PV-BEFORE-PROC")
    rows = [r for r in t["safety_lines"] if r.get("line_id") in ids]
    assert {r["line_id"] for r in rows} == set(ids)
    assert scorer.safety_lines(h, {}, dict(t, safety_lines=rows)) == (True, {"failed": []})
    items = [s for s in t["safety_items"] if s.get("line_id") == "CQ-BEFORE-PROC"]
    assert items and scorer.safety(h, dict(t, safety_items=items))[0]
    views = "\n".join(str(r["result"]) for r in h.trace if r.get("op") == "patient_view")
    pv = [r for r in rows if r["line_id"] == "PV-BEFORE-PROC"][0]["text"]
    assert pv in views
    # tamper: the decline wording swapped for a plain no must fail
    cq = [r for r in rows if r["line_id"] == "CQ-BEFORE-PROC"]
    bad = [dict(r, text=r["text"].replace("declined by the patient", "answered no")) for r in cq]
    assert not scorer.safety_lines(h, {}, dict(t, safety_lines=bad))[0]
