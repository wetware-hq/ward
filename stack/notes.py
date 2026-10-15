"""Trace notes (minimal): every counted step carries note = {claim, reason}. claim is one fixed CL- id; reason is
optional free text. The environment record decides the result; the scorer checks the claim against it."""
CLAIMS = {"CL-OPENED", "CL-APPROVED", "CL-GRANTED", "CL-REVOKED", "CL-ANSWERED", "CL-DECLINED", "CL-CONFIRMED",
          "CL-SUBMITTED", "CL-RESUBMITTED", "CL-TICKED", "CL-REVIEWED", "CL-RECORDED", "CL-OBSERVED", "CL-CHECKED", "CL-EXPORTED",
          "CL-BUILT", "CL-REFUSED", "CL-BLOCKED", "CL-ESCALATED", "CL-CLOSED", "CL-TREND-CLOSED"}
_STEP = {"approve": "approved", "grant": "granted", "revoke": "revoked", "answer": "answered", "decline": "declined",
         "confirm": "confirmed", "submit": "submitted", "tick": "ticked", "review": "reviewed"}
_OP = {"open": "opened", "record_result": "recorded", "check": "checked", "replay": "checked", "export": "exported"}


def env_result(rec):
    """The environment's own result for one counted trace record (read from the record only)."""
    k = rec.get("kind")
    if k == "endware":
        return "blocked" if rec.get("blocked") else "built"
    if k == "harness":
        if rec.get("op") == "open" and rec.get("blocks"):
            return "blocked"
        if rec.get("op") == "export_refused":
            return "blocked" if rec.get("blocks") else "refused"
        return _OP.get(rec.get("op"), rec.get("op") or "called")
    if not rec.get("accepted", True):
        r = rec.get("response") or {}
        return "blocked" if r.get("block") else "refused"
    if rec.get("method") == "observe":
        return "observed"
    if rec.get("method") == "letters_build":
        return "built"
    a = (rec.get("args") or [{}])[0]
    t = a.get("type") if isinstance(a, dict) else None
    base = _STEP.get(t, t or rec.get("method") or "called")
    if t == "close_sameday" and a.get("record"):
        base = "closed"                     # CL-CLOSED (signed): closes CQ-RESULT-TO-DISCUSS, releasing the held result
    if t == "tick" and rec.get("all_done"):
        base = "closed"                     # CL-TREND-CLOSED (pending signing): clinician in person closes the last job
    if t == "submit" and rec.get("resubmit"):
        base = "resubmitted+checked"        # a resubmit always re-runs the full check
    if rec.get("escalated"):
        return "escalated" if base == "submitted" else base + "+escalated"
    return base


def claim_for(result):
    """Claim rule: refused -> CL-REFUSED, blocked -> CL-BLOCKED, a submit that escalates (result 'escalated') ->
    CL-ESCALATED, otherwise the claim names the call made ('answered+escalated' -> CL-ANSWERED)."""
    return "CL-" + result.split("+")[0].upper()


def claim_of(rec):
    """Claim for one record: claim_for(env_result), except an in-person close of the last job (CL-TREND-CLOSED)."""
    if rec.get("trend_closed") and rec.get("accepted", True):
        return "CL-TREND-CLOSED"
    return claim_for(env_result(rec))


def scripted_note(rec, reason=""):
    """The deterministic baseline actor: claims what it saw the environment do, gives its reason (often none)."""
    return {"claim": claim_of(rec), "reason": reason or ""}


# Signed in the room; the text comes only from the signing files once Educator adds the row (never written here).
WHO = {"patient": "patient", "patient_agent": "patient's agent", "guardian": "guardian", "clinician": "clinician in person"}


def claim_text(claim, rec, rows=None):
    """Signed text of a claim for one record, read by id from the signing files; None while the row is not there.
    CL-RESUBMITTED fills [who] only with patient, patient's agent or clinician in person; any other role gives None."""
    if rows is None:
        from . import locales
        rows = dict(locales._round6())
    t = rows.get(claim)
    if t is None:
        return None
    import re
    m = re.search(r"\[who(?::[^\]]*)?\]", t)
    if m:
        who = WHO.get(rec.get("role"))
        if who is None:
            return None
        t = t[:m.start()] + who + t[m.end():]
    if "[clinician]" in t:
        # the logged-in session only (rec actor, clinician in person), never a name sent in the request
        who = rec.get("actor") if rec.get("role") == "clinician" else None
        if claim == "CL-CLOSED" and (rec.get("response") or {}).get("clinician") != who:
            return None
        if not who:
            return None
        t = t.replace("[clinician]", who)
    return None if re.search(r"\[[^\]]+\]", t) else t     # any other slot unfilled: no text (never guessed)


def closes_result_to_discuss(rec):
    """CL-CLOSED is signed only for closing CQ-RESULT-TO-DISCUSS: an accepted close of a held result's queue entry."""
    a = (rec.get("args") or [{}])[0]
    return bool(rec.get("accepted")) and isinstance(a, dict) and a.get("type") == "close_sameday" and bool(a.get("record")) \
        and (rec.get("response") or {}).get("closed") == a.get("record")
