"""Scenario scripts: agent behaviour only. Each script drives scripted, deterministic actors through the
middleware and, where the scenario has one, asks for an endware artifact through the adapter.
Nothing here says what the right answer is: minimum paths, expected outputs, safety items, refusals and
patient wording live in <siblings>/stack_truth/<id>/ and are read only by the scorer.
Cases come from forms/examples and orders/examples (read-only) or from ./cases (synthetic, documented)."""
import os
from .endware import letter, run_figure

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from stack.paths import SIBLINGS as WS
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
    return letter(h, out, P, [ep], "GP", "update to GP")


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
    return letter(h, out, P, [EO, EF], "GP", "discharge to GP", {"chest_pain_now": ("chest pain", None)})


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
        return letter(h, out, P, [EO], "GP", "update to GP")
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
    return letter(h, out, P, [EO], "GP", "update to GP", {})


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
    told = {"mh_q1": False, "mh_q3": True, "mh_q2": True}      # mh_q2 (self-harm) yes: sensitive, escalated
    for q in told:
        ag.step(EP, agent(ag, EP, q) if agent else answer(q, told[q]))
    h.patient_view(EP)                                           # audit: agent answers not yet "You answered"
    probe(h, lambda: ag.step(EP, A("confirm", question_id="mh_q1")))
    for q in told:
        pa.step(EP, A("confirm", question_id=q))
    h.patient_view(EP)                                           # audit: "You answered" and PV-SAMEDAY after confirm
    ag.step(EP, A("submit"))
    h.check(EP)
    dr.step(EP, A("review"))
    ph = {"mh_q1": ("feeling low on most days", None), "mh_q2": ("thoughts of harming yourself", "no thoughts of harming yourself"),
          "mh_q3": ("trouble sleeping", None)}
    gp = letter(h, os.path.join(out, "gp"), P, [EP], "GP", "update to GP", ph)       # the counted build (answer file)
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
def s08(h, out):
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
    dr.step(EP, A("submit"))
    h.patient_view(EP)                       # audit: clinician answers show as PV-ANS-CLIN
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
def s12(h, out):
    P, EP = "SYNTH-P1201", "SYNTH-EP-1201"
    h.open_episode("forms", CASE("patient_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-12", "clinician", P, discipline=DISC["MED"])
    pa = h.session(P, "patient", P)
    dr.step(EP, A("approve"))
    pa.step(EP, A("decline", question_id="allergy_any"))          # the parent question
    pa.step(EP, answer("allergy_reaction_severe", False))       # still asked after a decline
    pa.step(EP, answer("takes_blood_thinner", False))
    pa.step(EP, answer("smokes", False))
    pa.step(EP, answer("pregnant_possible", False))
    pa.step(EP, A("submit"))
    dr.step(EP, A("review"))
    h.check(EP)
    h.patient_view(EP)
    notes = []
    for line in open(CASE("S12.notes").replace(".toml", ".txt")).read().splitlines():
        if line and not line.startswith("#"):
            lid, field, text = line.split("\t")
            rid = f"SYNTH-NOTE-12{lid}"
            h.note("SYNTH-dr-12", rid, P, field, text, lid)
            notes.append(rid)
    return letter(h, out, P, [EP], "Patient", "update to patient", {}, privacy=True, notes=notes)


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
}
