"""Room ruling: each tamper below must make its trace fail on its own (the untampered run passes that check)."""
from ward.site_profile import FAMILY_DOCTOR  # site profile
import copy, re, pytest
from ward import runner, scorer
from truthgate import missing_truth, truth_path

S08, S05 = "S08-three-fails-escalation", "S05-mh-screen-by-patient-agent"


def run(sid, tmp_path):
    t = scorer.load_truth(sid)
    if t is None:
        missing_truth(sid)
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


def s05_red(h, t, a):
    """S05 criteria that fail for this artifact (outputs and the T3 scenario test)."""
    red = [] if scorer.outputs(h, a, t)[0] else ["outputs"]
    if scorer.scenario_tests(h, t, a)[1]["results"]["S05-T3-sensitive-cut"] is not True:
        red.append("T3")
    return red


def test_s05_negatives_each_fail_alone(tmp_path):
    t, h, art = run(S05, tmp_path)
    assert s05_red(h, t, art) == []                                # clean run: the mh_q2 row and T3 pass
    q = [f for f in art["facts"] if f["item_id"] == "mh_q2"][0]["text"]
    yes = copy.deepcopy(art); yes["clinician_letter"]["letter"] += f"\n- {q} Yes\n"
    def gp_line(a, text, src):
        c = a["clinician_letter"]
        n = len(c["notes"].splitlines()) + 1
        c["notes"] += f"- {text}\n"; c["refs"].append([]); c["sources"].append(src)
        c["letter"] += f"\n- {text} [L{n}]\n"
        return a
    flag = {"from": "flag", "item": "mh_q2", "event": None, "chain": []}
    derived = gp_line(copy.deepcopy(art), "Screen positive", {"from": "summary", "item": None, "event": None,
                      "chain": [{"from": "summary", "item": None, "event": None, "chain": [flag]}]})
    direct = gp_line(copy.deepcopy(art), "Mood screen reviewed", dict(flag, **{"from": "answer"}))
    unrelated = gp_line(copy.deepcopy(art), "Sleep noted", dict(flag, item="mh_q3"))
    word = copy.deepcopy(art); word["letter"] = word["letter"].replace("thoughts of harming yourself", "thoughts of hurting yourself")
    drop = copy.deepcopy(art); drop["facts"] = [f for f in drop["facts"] if f["item_id"] != "mh_q2"]
    assert "outputs" in s05_red(h, t, yes)
    assert "outputs" in s05_red(h, t, derived)                     # mh_q2 two steps down its source chain
    assert "outputs" in s05_red(h, t, direct)
    assert s05_red(h, t, unrelated) == []
    nosrc = copy.deepcopy(art); del nosrc["clinician_letter"]["sources"]
    assert "outputs" in s05_red(h, t, nosrc)
    assert "outputs" in s05_red(h, t, word) and "T3" in s05_red(h, t, word)
    assert "outputs" in s05_red(h, t, drop)


def test_s05_alert_exemption_tampers_each_fail_alone(tmp_path):
    t, h, art = run(S05, tmp_path)
    assert s05_red(h, t, art) == []
    c0 = art["clinician_letter"]
    n = [i for i, s in enumerate(c0["sources"]) if s["from"] == "sensitive_alert"][0]
    alert = c0["notes"].splitlines()[n].lstrip("- ")

    def add(a, text, src):
        c = a["clinician_letter"]; k = len(c["notes"].splitlines()) + 1
        c["notes"] += f"- {text}\n"; c["refs"].append([]); c["sources"].append(src)
        c["letter"] += f"\n- {text} [L{k}]\n"
        return a

    def retext(a, new):
        c = a["clinician_letter"]; lines = c["notes"].splitlines()
        c["letter"] = c["letter"].replace(lines[n].lstrip("- "), new)
        lines[n] = "- " + new; c["notes"] = "\n".join(lines) + "\n"
        return a
    src = dict(c0["sources"][n])
    other = add(copy.deepcopy(art), "Mood screen: flagged for review", src)                 # another mh_q2 line as the alert
    extra = retext(copy.deepcopy(art), alert.rstrip(".") + " urgently today.")              # signed text plus words
    twice = add(copy.deepcopy(art), alert, src)                                            # the alert twice
    bad_id = retext(copy.deepcopy(art), re.sub(r"See record \S+\.$", "See record mh_q2-E5.", alert))
    for a in (other, extra, twice, bad_id):
        assert "outputs" in s05_red(h, t, a)


def test_s05_bare_yes_elsewhere_does_not_trigger(tmp_path):
    t, h, art = run(S05, tmp_path)
    a = copy.deepcopy(art); a["clinician_letter"]["letter"] += f"\nYes, the {FAMILY_DOCTOR} has the plan. Questions answered: Yes\n"
    assert scorer.outputs(h, a, t)[0]


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
