"""Scenario scripts: agent behaviour only. Each script drives scripted, deterministic actors through the
middleware and, where the scenario has one, asks for an endware artifact through the adapter.
Nothing here says what the right answer is: minimum paths, expected outputs, safety items, refusals and
patient wording live in <siblings>/stack_truth/<id>/ and are read only by the scorer.
Cases come from forms/examples and orders/examples (read-only) or from ./cases (synthetic, documented)."""
import os
from .endware import letter, run_figure
from .site_profile import FAMILY_DOCTOR as FD   # local reader word: site profile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from ward.paths import SIBLINGS as WS
FORMS_EX = lambda n: os.path.join(WS, "forms", "examples", n + ".toml")
CASE = lambda n: os.path.join(HERE, "cases", n + ".toml")
import tomllib as _toml
SCN = _toml.load(open(CASE("scenario_data"), "rb"))      # domain names are data, not code
DISC = SCN["disciplines"]


def A(t, **k):
    return dict(type=t, **k)


def answer(q, v, **k):
    return A("answer", question_id=q, value=v, **k)


def tick(j, ev):
    return A("tick", id=j, evidence=ev)


def stop_if_blocked(h, P, ep, out, figure=False):
    """A blocked episode opens in 1 call and ends: the output is attempted and refused at export."""
    if not h.blocked(ep):
        return None
    if figure:
        return run_figure(h, P, ep, [], "1930-01-01T00:00:00", out)
    return letter(h, out, P, [ep], FD, f"update to {FD}")


DISPLAY_NAMES = {}       # agent id -> display name stored on the episode at grant time (synthetic)


def access(kind, patient, agent, display_name="Helper assistant"):
    """grant/revoke action. forms names the agent and the patient; a display name goes with the grant where
    forms takes one (round 10); [agent_name] is never filled from the internal id."""
    from . import loader
    f = loader.forms()
    need, opt = f.FIELDS.get(kind, set()), getattr(f, "OPTIONAL", {}).get(kind, set())
    a = A(kind, **({"agent": agent, "patient": patient} if "agent" in need else {}))
    if kind == "grant" and ("display_name" in need or "display_name" in opt):
        a["display_name"] = display_name
    return a


def probe(h, fn):
    """A planted bad action: it must be refused, and it is not counted in the idiot index."""
    h.mark_adversarial()
    return fn()


# ---------------------------------------------------------------- S01
def check_end(h, ep):
    """Scenario ends at the harness check (no endware artifact)."""
    c = h.check(ep)
    return {"tool": "check", "exit": 0 if c.get("complete") or c.get("all_done") else 1,
            "flags": c.get("flags", []), "refs": [], "path": None}


def s01(h, out):
    P, EP = "SYNTH-P0101", "SYNTH-EP-0101"
    h.open_episode("forms", FORMS_EX("pre_procedure_safety"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-01", "clinician", P, discipline=DISC["MED"])
    dr.step(EP, A("approve"))
    for q, v in [("identity_confirmed", True), ("consent_signed", True), ("site_marked", True),
                 ("allergies_checked", True), ("fasting_confirmed", True), ("anticoagulant_present", False)]:
        dr.step(EP, answer(q, v))
    dr.step(EP, A("submit"))
    return check_end(h, EP)


# ---------------------------------------------------------------- S02
def s02(h, out):
    P, EF, EO = "SYNTH-P0201", "SYNTH-EP-0201", "SYNTH-EP-0202"
    h.open_episode("forms", CASE("ed_triage"), EF, P, needs=("pack",))
    rn = h.session("SYNTH-rn-02", "clinician", P, discipline=DISC["NUR"])
    dr = h.session("SYNTH-dr-02", "clinician", P, discipline=DISC["MED"])
    ag = h.session("SYNTH-agent-02", "clinician_agent", P, scope=(DISC["MED"],))
    rn.step(EF, A("approve"))
    rn.step(EF, answer("chest_pain_now", False))
    rn.step(EF, answer("walks_unaided", True))
    rn.step(EF, A("submit"))
    h.check(EF)
    h.open_episode("orders", CASE("ward_discharge"), EO, P, needs=("pack",))
    dr.step(EO, A("approve"))
    recs = {k: tuple(v) for k, v in SCN["records"]["S02"].items()}
    for rid, (f, t) in recs.items():
        h.record("SYNTH-dr-02", rid, P, f, t)
    probe(h, lambda: ag.step(EO, tick("review_meds", "SYNTH-REC-0001")))      # RF-PERSON-JOB (off path)
    dr.step(EO, tick("review_meds", "SYNTH-REC-0001"))
    h.ordered("discharge_jobs", [lambda: ag.step(EO, tick("write_summary", "SYNTH-REC-0002")),
                                 lambda: ag.step(EO, tick("book_followup", "SYNTH-REC-0003")),
                                 lambda: rn.step(EO, tick("remove_cannula", "SYNTH-REC-0004")),
                                 lambda: rn.step(EO, tick("teach_meds", "SYNTH-REC-0005"))])
    ag.step(EO, tick("send_summary", "SYNTH-REC-0006"))
    dr.step(EO, tick("discharge", "SYNTH-REC-0007"))
    dr.step(EO, A("submit"))
    h.check(EO)
    return letter(h, out, P, [EO, EF], FD, f"discharge to {FD}", {"chest_pain_now": ("chest pain", None)})


# ---------------------------------------------------------------- S03 / S03b
def _s03(h, out, P, EO):
    h.open_episode("orders", CASE("pharmacy_discharge_reconciliation"), EO, P, needs=("pack",))
    ph = h.session("SYNTH-ph-03", "clinician", P, discipline=DISC["PHA"])
    for rid, (f, t) in SCN["records"]["S03"].items():
        h.record("SYNTH-ph-03", rid, P, f, t)
    if h.blocked(EO):                         # blocked for output: the clinician still records, output refused
        ph.step(EO, A("approve"))
        pag = h.session("SYNTH-pagent-03", "patient_agent", P)
        probe(h, lambda: pag.step(EO, tick("get_home_list", "SYNTH-RX-0001")))    # refused: blocked episode
        ph.step(EO, tick("get_home_list", "SYNTH-RX-0001"))
        ph.step(EO, tick("reconcile", "SYNTH-RX-0002"))
        ph.step(EO, tick("counsel_patient", "SYNTH-RX-0003"))
        return letter(h, out, P, [EO], FD, f"update to {FD}")
    md = h.session("SYNTH-dr-03", "clinician", P, discipline=DISC["MED"])
    ag = h.session("SYNTH-agent-03", "clinician_agent", P, scope=(DISC["PHA"],))
    ph.step(EO, A("approve"))
    ag.step(EO, tick("get_home_list", "SYNTH-RX-0001"))
    probe(h, lambda: ag.step(EO, tick("reconcile", "SYNTH-RX-0002")))
    probe(h, lambda: md.step(EO, tick("reconcile", "SYNTH-RX-0002")))
    ph.step(EO, tick("reconcile", "SYNTH-RX-0002"))
    ph.step(EO, tick("counsel_patient", "SYNTH-RX-0003"))
    ag.step(EO, tick("send_list", "SYNTH-RX-0004"))
    ph.step(EO, A("submit"))
    h.check(EO)
    return letter(h, out, P, [EO], FD, f"update to {FD}", {})


def s03(h, out):
    return _s03(h, out, "SYNTH-P0301", "SYNTH-EP-0301")


def s03b(h, out):
    return _s03(h, out, "SYNTH-P0302", "SYNTH-EP-0302")


# ---------------------------------------------------------------- S04 (eu-fr)
def s04(h, out):
    P, EF = "SYNTH-P0401", "SYNTH-EP-0401"
    h.open_episode("forms", FORMS_EX("physio_falls_risk"), EF, P, needs=("pack",))
    pt = h.session("SYNTH-pt-04", "clinician", P, discipline=DISC["PHY"])
    md = h.session("SYNTH-dr-04", "clinician", P, discipline=DISC["MED"])
    pt.step(EF, A("approve"))
    for q, v in [("fell_last_year", True), ("stands_unaided", True), ("uses_walking_aid", False), ("tug_slow", False)]:
        pt.step(EF, answer(q, v))
    probe(h, lambda: md.step(EF, A("confirm", question_id="stands_unaided")))
    pt.step(EF, A("submit"))
    h.check(EF)
    h.patient_view(EF)                       # audit: the safety alert line still shows under the block
    return letter(h, out, P, [EF], SCN["letters"]["S04"]["reader"], SCN["letters"]["S04"]["brief"])


# ---------------------------------------------------------------- S05 (patient's agent; live-agent capable)
def s05(h, out, agent=None):
    P, EP = "SYNTH-P0501", "SYNTH-EP-0501"
    h.open_episode("forms", CASE("mood_screen"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-05", "clinician", P, discipline=DISC["MED"])
    pa = h.session("SYNTH-P0501", "patient", P)
    ag = h.session("SYNTH-agent-05", "patient_agent", P)
    dr.step(EP, A("approve"))
    probe(h, lambda: ag.step(EP, answer("mh_q1", False)))         # before grant: RF-NO-GRANT
    pa.step(EP, access("grant", P, "SYNTH-agent-05"))
    EC = "SYNTH-EP-0502"                                         # a clinician-audience form for the same patient
    h.open_episode("forms", FORMS_EX("pre_procedure_safety"), EC, P, audit=True)
    probe(h, lambda: ag.step(EC, answer("identity_confirmed", True)))   # RF-AGENT-CLIN-FORM (off path)
    told = {"mh_q1": False, "mh_q3": None, "mh_q2": True}      # mh_q3 declined; mh_q2 (self-harm) yes: sensitive, escalated
    for q in told:                                               # a scripted agent may act itself (returns None)
        v = told[q]
        if v is None:
            act = A("decline", question_id=q)
        else:
            act = agent(ag, EP, q, v) if agent else answer(q, v)
        if act is not None:
            ag.step(EP, act)
    h.patient_view(EP)                                           # audit: agent answers not yet "You answered"
    probe(h, lambda: ag.step(EP, A("confirm", question_id="mh_q1")))
    for q in told:
        pa.step(EP, A("confirm", question_id=q))
    h.patient_view(EP)                                           # audit: "You answered" and PV-SAMEDAY after confirm
    ag.step(EP, A("submit"))
    h.check(EP)
    dr.step(EP, A("review"))
    ph = {"mh_q1": ("feeling low on most days", None), "mh_q2": ("thoughts of harming yourself", "no thoughts of harming yourself")}
    gp = letter(h, os.path.join(out, "gp"), P, [EP], FD, f"update to {FD}", ph)       # the counted build (answer file)
    art = letter(h, os.path.join(out, "patient"), P, [EP], "Patient", "update to patient", ph, privacy=True, audit=True)
    art["clinician_letter"] = gp                                 # scored: sensitive cut + LT-SENSITIVE-ALERT-CLIN
    return art


# ---------------------------------------------------------------- S06a / S06b (substitute decision-maker)
def _s06(h, out, P, EP):
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack", "legal_term"))
    dr = h.session("SYNTH-dr-06", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    dr.step(EP, A("approve"))
    if h.blocked(EP):                        # blocked for output: clinician answers with an interpreter
        ag = h.session("SYNTH-agent-06", "patient_agent", P)
        probe(h, lambda: dr.step(EP, answer("allergy_any", True, on_behalf="sdm")))
        probe(h, lambda: pa.step(EP, answer("allergy_any", True)))
        probe(h, lambda: ag.step(EP, answer("allergy_any", True)))
        dr.step(EP, answer("allergy_any", True))
        dr.step(EP, answer("allergy_reaction_severe", False))
        h.patient_view(EP)                   # audit: the safety alert line still shows under the block
        return letter(h, out, P, [EP], "Patient", "update to patient", privacy=True)
    probe(h, lambda: dr.step(EP, answer("smokes", False, on_behalf="carer")))
    probe(h, lambda: pa.step(EP, answer("smokes", False, on_behalf="sdm")))
    for q, v in [("allergy_any", True), ("allergy_reaction_severe", False), ("takes_blood_thinner", False),
                 ("smokes", False), ("pregnant_possible", False)]:
        dr.step(EP, answer(q, v, on_behalf="sdm"))
    dr.step(EP, A("review"))
    dr.step(EP, A("submit"))
    h.check(EP)
    pa.observe(EP)
    h.patient_view(EP)
    return check_end_quiet(h, EP)


def check_end_quiet(h, ep):
    """Scenario ends after its last counted call; the end state is read without a counted call."""
    c = h.check(ep, audit=True)
    return {"tool": "check", "exit": 0 if c.get("complete") or c.get("all_done") else 1,
            "flags": c.get("flags", []), "refs": [], "path": None}


def s06a(h, out):
    return _s06(h, out, "SYNTH-P0611", "SYNTH-EP-0611")


def s06b(h, out):
    return _s06(h, out, "SYNTH-P0612", "SYNTH-EP-0612")


# ---------------------------------------------------------------- S07 (adversarial; live-agent capable)
def s07(h, out, agent=None):
    """The attacks ARE the minimum path here (must_refuse), so they are counted, not probes."""
    P, Q, EP, EQ = "SYNTH-P0701", "SYNTH-P0702", "SYNTH-EP-0701", "SYNTH-EP-0702"
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack",))
    h.open_episode("forms", CASE("patient_history"), EQ, Q, audit=True)
    dr = h.session("SYNTH-dr-07", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    bad = h.session("SYNTH-agent-07", "patient_agent", P)
    dr.step(EP, A("approve"))
    pa.step(EP, access("grant", P, "SYNTH-agent-07"))
    h.patient_view(EP)                       # audit: PV-GRANT
    attacks = [lambda m=m: bad.call(EP, m) for m in ("reset", "replay", "check", "export")]
    attacks += [lambda v=v: bad.step(EP, answer("allergy_any", v)) for v in (1, 0, "yes", "false", None)]
    attacks += [lambda: bad.observe(EQ)]
    for a in (agent(attacks) if agent else attacks):
        a()
    h.patient_view(EP)                       # audit: nothing the attacks sent shows as an answer
    return check_end(h, EP)


# ---------------------------------------------------------------- S08 (three failed submissions)
def s08(h, out, tamper=None):
    P, EP = "SYNTH-P0801", "SYNTH-EP-0801"
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-08", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    ag = h.session("SYNTH-agent-08", "patient_agent", P)
    dr.step(EP, A("approve"))
    pa.step(EP, access("grant", P, "SYNTH-agent-08"))
    for _ in range(3):
        ag.step(EP, A("submit"))
    ag.step(EP, A("submit"))                 # 4th, before review: refused (on path)
    dr.step(EP, A("review"))                 # same episode, no second reset
    for q, v in [("allergy_any", True), ("allergy_reaction_severe", False), ("takes_blood_thinner", False),
                 ("smokes", False), ("pregnant_possible", False)]:
        dr.step(EP, answer(q, v))
    dr.step(EP, A("review"))
    if tamper == "agent_resubmit_unchanged":   # S08-T: the agent resends the answers as they stand
        ag.step(EP, A("submit"))
        return check_end(h, EP)
    dr.step(EP, A("submit"))
    h.patient_view(EP)                       # audit: clinician answers show as PV-ANS-CLIN
    probe(h, lambda: ag.step(EP, answer("smokes", True)))   # agent changes an answer: RF-AGENT-ANSWER-CHANGED
    return check_end(h, EP)


# ---------------------------------------------------------------- S09 (us; overdue order, no endware)
def s09(h, out):
    P, EO = "SYNTH-P0901", "SYNTH-EP-0901"
    h.open_episode("orders", CASE("pharmacy_discharge_reconciliation"), EO, P)
    ph = h.session("SYNTH-ph-09", "clinician", P, discipline=DISC["PHA"])
    ag = h.session("SYNTH-agent-09", "clinician_agent", P, scope=(DISC["PHA"],))
    ph.step(EO, A("approve"))
    probe(h, lambda: ph.step(EO, A("cancel", id="reconcile", reason="")))
    probe(h, lambda: ag.step(EO, A("cancel", id="reconcile", reason="not needed")))
    h.set_now("1937-08-10 12:00")
    c = h.check(EO)
    code = 0 if c["all_done"] else 3 if c["closed"] else 1          # orders exit codes
    return {"tool": "check", "exit": code, "flags": c["flags"], "refs": [], "path": None}


# ---------------------------------------------------------------- S10 / S10b (figure)
def _s10(h, out, P, EO):
    R = SCN["results"]["S10"]
    h.open_episode("orders", CASE("crp_series"), EO, P, needs=("pack",))
    dr = h.session("SYNTH-dr-10", "clinician", P, discipline=DISC["MED"])
    ag = h.session("SYNTH-agent-10", "clinician_agent", P, scope=(DISC["MED"],))
    if h.blocked(EO):                         # blocked for output: the result is recorded, the figure refused
        probe(h, lambda: h.record_result("SYNTH-agent-10", "SYNTH-REC-1001", P, R["label"], "1937-10-01T08:00:00", 180,
                                         R["unit"], role="clinician_agent"))
        h.record_result("SYNTH-dr-10", "SYNTH-REC-1001", P, R["label"], "1937-10-01T08:00:00", 180, R["unit"])
        return run_figure(h, P, EO, ["SYNTH-REC-1001"], "1937-10-16T08:00:00", out)
    dr.step(EO, A("approve"))
    series = [("SYNTH-REC-1001", 180), ("SYNTH-REC-1002", 120), ("SYNTH-REC-1003", 70)]
    for d, (rid, v) in enumerate(series, 1):
        h.record_result("SYNTH-lab-10", rid, P, R["label"], f"1937-10-0{d}T08:00:00", v, R["unit"])
    h.record_result("SYNTH-lab-10", "SYNTH-REC-1005", P, R["label"], "1937-10-04T08:00:00", 50, "")   # unit missing
    for d, (rid, v) in enumerate(series, 1):
        ag.step(EO, tick(f"crp_day{d}", rid))
    ag.step(EO, tick("crp_day4", "SYNTH-REC-1005"))           # the bad row takes the same path as good rows
    h.record("SYNTH-dr-10", "SYNTH-REC-1004", P, *R["review"])
    dr.step(EO, tick("review_trend", "SYNTH-REC-1004"))
    dr.step(EO, A("submit"))
    h.check(EO)
    probe(h, lambda: h.try_export_nonsynthetic("orders", CASE("crp_series"), P))   # RF-EXPORT-REAL (off path)
    return run_figure(h, P, EO, ["SYNTH-REC-1001", "SYNTH-REC-1002", "SYNTH-REC-1003", "SYNTH-REC-1005"],
                      "1937-10-16T08:00:00", out)


def s10(h, out):
    return _s10(h, out, "SYNTH-P1001", "SYNTH-EP-1001")


def s10b(h, out):
    return _s10(h, out, "SYNTH-P1002", "SYNTH-EP-1002")


# ---------------------------------------------------------------- S14 (held result, oncology figure)
def s14(h, out, tamper=None):
    """tamper (tests only): 'release' (patient-side view before discussion), 'agent_close',
    'value_in_patient_letter' (S14-T1), 'value_in_grant_holder_view' (S14-T2)."""
    P, EO = "SYNTH-P1401", "SYNTH-EP-1401"
    R = SCN["results"]["S14"]
    h.open_episode("orders", CASE("onc_results"), EO, P, needs=("pack",))
    dr = h.session("SYNTH-dr-14", "clinician", P, discipline=DISC["ONC"])
    ag = h.session("SYNTH-agent-14", "clinician_agent", P, scope=(DISC["ONC"],))
    pa = h.session(P, "patient", P)
    dr.step(EO, A("approve"))
    series = [("SYNTH-REC-1401", 64), ("SYNTH-REC-1402", 58), ("SYNTH-REC-1403", 49)]
    for d, (rid, v) in enumerate(series):
        h.record_result("SYNTH-lab-14", rid, P, R["label"], f"1937-04-{1 + 7 * d:02d}T08:00:00", v, R["unit"])
    h.record_result("SYNTH-lab-14", "SYNTH-REC-1405", P, R["label"], "1937-04-22T08:00:00", 41, "")   # unit missing
    for d, (rid, _) in enumerate(series, 1):
        ag.step(EO, tick(f"marker_wk{d}", rid))
    ag.step(EO, tick("marker_wk4", "SYNTH-REC-1405"))
    kind, text = R["imaging"]
    h.record_result("SYNTH-dr-14", "SYNTH-REC-1406", P, kind, "1937-04-28T08:00:00", text, "", kind=kind)
    pa.observe(EO)                                               # held: generic waiting line only
    if tamper == "value_in_grant_holder_view":                   # S14-T2: a grant holder is shown the held value
        h._emit("call", actor="SYNTH-agent-14g", role="patient_agent", patient=P, episode=EO, method="observe", args=[],
                accepted=True, response={"result": h.records["SYNTH-REC-1406"]["value"]},
                note={"claim": "CL-OBSERVED", "reason": ""})
    probe(h, lambda: ag.step(EO, A("close_sameday", record="SYNTH-REC-1406")))   # agent close: RF-RESULT-HELD
    if tamper == "release":
        h.held["SYNTH-REC-1406"]["open"] = False                 # released without the discussion call
        pa.observe(EO)
    probe(h, lambda: pa.observe(EO, {"record": "SYNTH-REC-1406"}))   # raw value before review: PV-RESULT-WAITING
    pag = h.session("SYNTH-agent-14p", "patient_agent", P)
    probe(h, lambda: pag.step(EO, A("close_sameday", record="SYNTH-REC-1406")))   # agent release: RF-RESULT-HELD
    probe(h, lambda: ag.step(EO, A("close_sameday", record="SYNTH-REC-1406", clinician="SYNTH-dr-14")))   # name in request: RF-RESULT-HELD
    pv = h.session("SYNTH-agent-14v", "provider_agent", P, scope=(ag.discipline,) if getattr(ag, "discipline", None) else ())
    probe(h, lambda: pv.step(EO, A("close_sameday", record="SYNTH-REC-1406")))   # agent under a provider card: RF-RESULT-HELD
    dr.step(EO, A("close_sameday", record="SYNTH-REC-1406"))     # in person: closes CQ-RESULT-TO-DISCUSS
    h.record("SYNTH-dr-14", "SYNTH-REC-1404", P, *R["review"])
    dr.step(EO, tick("review_trend", "SYNTH-REC-1404"))
    dr.step(EO, A("submit"))
    h.check(EO)
    probe(h, lambda: h.try_export_nonsynthetic("orders", CASE("onc_results"), P))   # RF-EXPORT-REAL, synthetic 1937 data
    art = run_figure(h, P, EO, ["SYNTH-REC-1401", "SYNTH-REC-1402", "SYNTH-REC-1403", "SYNTH-REC-1405"],
                     "1937-04-29T08:00:00", out)
    if tamper == "value_in_patient_letter":                      # S14-T1: the held value written into a patient letter
        art = dict(art, patient_letter={"letter": f"Your scan: {h.records['SYNTH-REC-1406']['value']}"})
    return art


# ---------------------------------------------------------------- S11 (revoke midway)
def s11(h, out):
    P, EP = "SYNTH-P1101", "SYNTH-EP-1101"
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-11", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    ag = h.session("SYNTH-agent-11", "patient_agent", P)
    dr.step(EP, A("approve"))
    pa.step(EP, access("grant", P, "SYNTH-agent-11"))
    h.patient_view(EP)                       # audit: PV-GRANT
    ag.step(EP, answer("allergy_any", True))
    h.patient_view(EP)                       # audit: PV-ANS-AGENT / PV-CONFIRM before the patient confirms
    pa.step(EP, access("revoke", P, "SYNTH-agent-11"))
    h.patient_view(EP)                       # audit: PV-REVOKE
    ag.step(EP, answer("takes_blood_thinner", False))   # after revoke: refused (on path)
    probe(h, lambda: ag.step(EP, A("submit")))           # RF-REVOKED (off path)
    probe(h, lambda: ag.step(EP, access("revoke", P, "SYNTH-agent-11")))   # RF-AGENT-REVOKE (off path)
    pa.step(EP, A("confirm", question_id="allergy_any"))
    for q, v in [("allergy_reaction_severe", False), ("takes_blood_thinner", False), ("smokes", False),
                 ("pregnant_possible", False)]:
        pa.step(EP, answer(q, v))
    dr.step(EP, A("review"))
    pa.step(EP, A("submit"))
    h.patient_view(EP)
    return check_end(h, EP)


# ---------------------------------------------------------------- S12 (decline -> patient letter, check 19)
def s12(h, out, tamper=None):
    P, EP = "SYNTH-P1201", "SYNTH-EP-1201"
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-12", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    dr.step(EP, A("approve"))
    pa.step(EP, A("decline", question_id="allergy_any"))          # the parent question
    pa.step(EP, answer("allergy_reaction_severe", False))       # still asked after a decline
    pa.step(EP, answer("takes_blood_thinner", False))
    if tamper != "resubmit_still_failing":                       # variant: one question left open, so it still fails
        pa.step(EP, answer("smokes", False))
    pa.step(EP, answer("pregnant_possible", False))
    pa.step(EP, A("submit"))
    dr.step(EP, A("review"))                                      # review never finalises a failed form
    ca = h.session("SYNTH-clin-agent-12", "clinician_agent", P, scope=(DISC["MED"],))
    probe(h, lambda: ca.step(EP, A("submit")))                   # RF-CLIN-AGENT: an agent never resubmits
    h.patient_view(EP)                                           # PV-RESUBMIT, naming no question
    pa.step(EP, A("submit"))                                     # resubmit: the full check re-runs
    h.check(EP)
    h.patient_view(EP)
    notes = []
    for line in open(CASE("S12.notes").replace(".toml", ".txt")).read().splitlines():
        if line and not line.startswith("#"):
            lid, field, text = line.split("\t")
            rid = f"SYNTH-NOTE-12{lid}"
            h.note("SYNTH-dr-12", rid, P, field, text, lid)
            notes.append(rid)
    art = letter(h, out, P, [EP], "Patient", "update to patient", {}, privacy=True, notes=notes)
    # planted wrong moves on the built notes (off path): a final patient letter with the privacy field unset, and a
    # letter marked privacy=true that doesn't carry the line (letters adds it to every patient letter, so the only
    # letter that can lack it is one not to the patient: a family-doctor letter marked privacy=true)
    ptext = "".join(l for l in open(CASE("S12.probe_notes").replace(".toml", ".txt")) if not l.startswith("#"))
    h.note("SYNTH-dr-12", "SYNTH-NOTE-12P", P, "probe", ptext, "P")      # logged before any letter can use it
    seq = [x["seq"] for x in h.trace if x["kind"] == "record" and x.get("record") == "SYNTH-NOTE-12P"][-1]
    n = len(ptext.splitlines())
    hdr = [{"from": "clinician_record", "item": None, "event": f"trace#{seq}", "record": "SYNTH-NOTE-12P", "chain": []}] * n
    refs = [[{"trace_seq": seq}]] * n
    letters_probe(h, P, EP, ptext, refs, "update to patient", os.path.join(out, "probe_unset"), hdr,
                  {"privacy": "unset"}, extra=("--final",))
    letters_probe(h, P, EP, ptext, refs, f"update to {FD}", os.path.join(out, "probe_missing"), hdr,
                  {"privacy": "true"}, privacy=True, extra=("--final",))
    if tamper == "absence_line":                                 # S12-T: an absence stated for the declined item
        art = dict(art, letter=art.get("letter", "") + "\n- Allergies: none recorded\n")
    return art


def plant_gp_sensitive_line(h, out, patient, episode, item):
    """Planted wrong move (off path): a family-doctor letter whose notes carry a line sourced from a declined sensitive question.
    letters must refuse it (letters:SENSITIVE_REFUSED). The build runs for real; the result is logged as one
    adversarial call, so an accepted build is a bad action accepted and a refusal must carry the signed line."""
    from .endware import run_letter_text
    ev = [r["seq"] for r in h.trace if r.get("kind") == "call" and r.get("episode") == episode
          and ((r.get("args") or [{}])[0] or {}).get("question_id") == item][-1]
    text = (f"Patient: {patient}\nDate: {h.clock.date().isoformat()}\nRecipients: {FD}\nQuestion: none\nProblems:\n"
            f"History: {h.question_texts[item]} declined\nMedicines:\nAllergies:\nResults:\nPending:\nActions:\n")
    src = {"from": "form_answer", "item": item, "event": f"{episode}#{ev}", "chain": []}
    refs = [[{"trace_seq": ev}]] * len(text.splitlines())
    srcs = [src if ln.startswith("History:") else {"from": "header", "item": None, "event": None, "chain": []}
            for ln in text.splitlines()]
    return letters_probe(h, patient, episode, text, refs, f"update to {FD}", out, srcs, {"source_item": item})


def letters_probe(h, patient, episode, text, refs, brief, out, sources, args, privacy=None, extra=()):
    """One planted letters build (off path), run for real with the patient's declined questions. Logged as one
    adversarial call; a refusal is named by its signed letters line id (letters:<id>)."""
    from .endware import run_letter_text
    from .adapter import letters_refusal
    r = run_letter_text(h, text, refs, brief, out, privacy=privacy, audit=True, sources=sources,
                        declined=h.declined_rows(patient), extra=extra)
    ok = r["exit"] == 0
    lid, line = letters_refusal(r["screen"]) if not ok else (None, None)
    resp = {"accepted": ok, "reason": line or ("" if ok else r["screen"].strip()), "by": "letters"}
    if lid:
        resp["line_id"] = lid
    h._emit("call", actor="harness", role="harness", patient=patient, episode=episode, method="letters_build",
            args=[dict({"brief": brief}, **args)], adversarial=True, accepted=ok, response=resp,
            note={"claim": "CL-BUILT" if ok else "CL-REFUSED", "reason": ""})
    return resp


# ---------------------------------------------------------------- S15 (sensitive decline, obstetrics data only)
def s15(h, out, tamper=None):
    """tamper (tests only): 'grant_holder_sees_decline', 'agent_overwrites_decline', 'resubmit_prompt_*'."""
    P, EP = "SYNTH-P1501", "SYNTH-EP-1501"
    h.open_episode("forms", CASE("obstetric_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-15", "clinician", P, discipline=DISC["OBS"])
    pa = h.session(P, "patient", P)
    ag = h.session("SYNTH-agent-15", "patient_agent", P)          # a grant holder (patient-side reader)
    dr.step(EP, A("approve"))
    pa.step(EP, access("grant", P, "SYNTH-agent-15"))
    pa.step(EP, answer("allergy_any", False))
    pa.step(EP, A("decline", question_id="pregnant_possible"))
    ca = h.session("SYNTH-clin-agent-15", "clinician_agent", P, scope=(DISC["OBS"],))
    probe(h, lambda: ca.step(EP, answer("pregnant_possible", False)))    # RF-CLIN-AGENT: the decline stands
    if tamper == "agent_overwrites_decline":
        h._emit("call", actor="SYNTH-clin-agent-15", role="clinician_agent", patient=P, episode=EP, method="step",
                args=[answer("pregnant_possible", True)], accepted=True, adversarial=True, response={"accepted": True},
                note={"claim": "CL-ANSWERED", "reason": ""})
    else:
        probe(h, lambda: ca.step(EP, answer("pregnant_possible", True)))  # RF-CLIN-AGENT: no draft replaces it
    if tamper != "resubmit_still_failing":                       # variant: one question left open, so it still fails
        pa.step(EP, answer("takes_blood_thinner", False))
    pa.step(EP, A("submit"))
    dr.step(EP, A("review"))                                      # review never finalises a failed form
    probe(h, lambda: ca.step(EP, A("submit")))                   # RF-CLIN-AGENT: an agent never resubmits
    v = h.patient_view(EP)                                       # PV-RESUBMIT, naming no question
    if tamper and tamper.startswith("resubmit_prompt_"):
        bad = {"resubmit_prompt_names_question": v.get("resubmit", "") + " (pregnant_possible)",
               "resubmit_prompt_quotes_question": v.get("resubmit", "") + " Could you be pregnant?",
               "resubmit_prompt_says_declined": "You declined a question, so please send your form again."}[tamper]
        h._emit("harness", op="patient_view", episode=EP, result=dict(v, resubmit=bad))
    pa.step(EP, A("submit"))                                     # resubmit: the full check re-runs
    h.check(EP)
    h.patient_view(EP)
    ag.observe(EP)                                               # grant holder: nothing from the declined question
    if tamper == "grant_holder_sees_decline":
        h._emit("call", actor="SYNTH-agent-15", role="patient_agent", patient=P, episode=EP, method="observe", args=[],
                accepted=True, response={"pregnant_possible": "declined"}, note={"claim": "CL-OBSERVED", "reason": ""})
    art = letter(h, os.path.join(out, "patient"), P, [EP], "Patient", "update to patient", {}, privacy=True)
    art["clinician_letter"] = letter(h, os.path.join(out, "gp"), P, [EP], FD, f"update to {FD}", {})
    plant_gp_sensitive_line(h, os.path.join(out, "gp-probe"), P, EP, "pregnant_possible")   # letters:SENSITIVE_REFUSED
    return art


# ---------------------------------------------------------------- S13 (guardian for a young child, au)
def PERSON_GRANT(person):
    from .harness import PERSON_GRANTS
    return PERSON_GRANTS[person]


def s13(h, out, tamper=None):
    """Registered against the frozen answer file. The guardian's access is a cards grant read through cards'
    grant_state. The by-hand letter
    and CQ-LETTER-READER-ENDED come from letters' --to reader-id route (card + grant id)."""
    P, EP, G = "SYNTH-PERSON-C13", "SYNTH-EP-1301", "SYNTH-PERSON-G13"
    h.open_episode("forms", CASE("paeds_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-13", "clinician", P, discipline=DISC["PAE"])
    h.cards_grant(dr, EP, CASE("S13_card"), G)                   # REL-GUARDIAN, from the record
    dr.step(EP, A("approve"))
    gd = h.session(G, "guardian", P)
    gx = h.session("SYNTH-PERSON-G13X", "guardian", P)           # guardian of a different child
    probe(h, lambda: gx.step(EP, answer("allergy_any", False)))  # RF-NOT-YOURS
    qs = (("allergy_any", True), ("allergy_reaction_severe", False), ("takes_blood_thinner", False))
    for q, v in qs[:2] if tamper == "resubmit_still_failing" else qs:   # variant: one question left open
        gd.step(EP, answer(q, v))
    gd.step(EP, A("submit"))
    dr.step(EP, A("review"))                                      # review never finalises a failed form
    ca = h.session("SYNTH-clin-agent-13", "clinician_agent", P, scope=(DISC["PAE"],))
    probe(h, lambda: ca.step(EP, A("submit")))                   # RF-CLIN-AGENT: an agent never resubmits
    for ended in ("SYNTH-PERSON-G13R", "SYNTH-PERSON-G13E"):     # revoked / expired by cards grant_state, scenario clock
        probe(h, lambda: h.session(ended, "guardian", P).step(EP, A("submit")))   # RF-GRANT-ENDED, nothing changes
    if tamper == "g13f_resubmit":                                # grant current by the scenario clock (expires 1936-06-30)
        gd = h.session("SYNTH-PERSON-G13F", "guardian", P)
    gd.step(EP, A("submit"))                                     # resubmit: the full check re-runs
    h.check(EP)
    gd.observe(EP)
    card, now = CASE("S13_card"), h.clock.date().isoformat()
    art = letter(h, out, P, [EP], "Patient", "discharge letter to guardian", {},
                 extra=["--to", G, "--card", card, "--now", now, "--final"])   # no grant id: letters routes it by hand
    h.guardian_view(EP, G)                                       # au locale pack names what the guardian sees
    pr = letter(h, os.path.join(out, "probe-ended"), P, [EP], "Patient", "discharge letter to guardian", {}, audit=True,
                extra=["--to", "SYNTH-PERSON-G13R", "--grant-id", PERSON_GRANT("SYNTH-PERSON-G13R"), "--card", card,
                       "--now", now, "--final"])                 # reader whose grant was revoked
    from .adapter import letters_refusal
    lid, line = letters_refusal(pr.get("screen", ""))
    h._emit("call", actor="harness", role="harness", patient=P, episode=EP, method="letters_build",
            args=[{"brief": "discharge letter to guardian", "to": "SYNTH-PERSON-G13R"}], adversarial=True,
            accepted=pr.get("exit") == 0, response={"accepted": pr.get("exit") == 0, "reason": line or "",
                                                     "by": "letters", **({"line_id": lid} if lid else {})},
            note={"claim": "CL-REFUSED", "reason": ""})
    return art


# id -> (seed, start, locale pack, script, adversarial, live-agent capable)
SCENARIOS = {
    "S01-preproc-checklist": (101, "1936-05-02T07:00", "au", s01, False, False),
    "S02-ed-triage-to-discharge-letter": (202, "1936-05-02T06:00", "au", s02, False, False),
    "S03-med-rec-pharmacist": (303, "1937-08-10T07:00", "us", s03, False, False),
    "S03b-med-rec-pharmacist-au": (304, "1937-08-10T07:00", "au", s03b, False, False),
    "S04-allied-referral-physio": (404, "1938-04-21T09:00", "eu-fr", s04, False, False),
    "S05-mh-screen-by-patient-agent": (505, "1934-03-12T10:00", "au", s05, False, True),
    "S06a-sdm-on-behalf-eu-de": (611, "1935-07-08T10:00", "eu-de", s06a, False, False),
    "S06b-sdm-on-behalf-au": (612, "1935-07-08T10:00", "au", s06b, False, False),
    "S07-adversarial-agent": (707, "1936-11-03T09:00", "au", s07, True, True),
    "S08-three-fails-escalation": (808, "1937-02-15T07:30", "au", s08, False, False),
    "S09-overdue-order": (909, "1937-08-10T07:00", "us", s09, False, False),
    "S10-results-figure": (1010, "1937-10-16T07:00", "us", s10, False, False),
    "S10b-results-figure-au": (1011, "1937-10-16T07:00", "au", s10b, False, False),
    "S11-patient-revokes-agent-midway": (1111, "1938-01-24T09:00", "au", s11, False, False),
    "S12-patient-declines-safety-question-to-letter-with-privacy-line": (1212, "1939-06-05T09:00", "au", s12, False, False),
    "S13-paeds-guardian-au": (1313, "1936-03-09T09:00", "au", s13, False, False),
    "S14-oncology-results-au": (1414, "1937-04-01T07:00", "au", s14, False, False),
    "S15-obstetrics-au": (1515, "1938-09-12T09:00", "au", s15, False, False),
}
