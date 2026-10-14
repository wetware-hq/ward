"""Trace notes (minimal): every counted step carries note = {claim, reason}. claim is one fixed CL- id; reason is
optional free text. The environment record decides the result; the scorer checks the claim against it."""
CLAIMS = {"CL-OPENED", "CL-APPROVED", "CL-GRANTED", "CL-REVOKED", "CL-ANSWERED", "CL-DECLINED", "CL-CONFIRMED",
          "CL-SUBMITTED", "CL-TICKED", "CL-REVIEWED", "CL-RECORDED", "CL-OBSERVED", "CL-CHECKED", "CL-EXPORTED",
          "CL-BUILT", "CL-REFUSED", "CL-BLOCKED", "CL-ESCALATED"}
_STEP = {"approve": "approved", "grant": "granted", "revoke": "revoked", "answer": "answered", "decline": "declined",
         "confirm": "confirmed", "submit": "submitted", "tick": "ticked", "review": "reviewed"}
_OP = {"open": "opened", "record_result": "recorded", "check": "checked", "replay": "checked", "export": "exported"}


def env_result(rec):
    """The environment's own result for one counted trace record (read from the record only)."""
    k = rec.get("kind")
    if k == "endware":
        return "built"
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
    a = (rec.get("args") or [{}])[0]
    t = a.get("type") if isinstance(a, dict) else None
    base = _STEP.get(t, t or rec.get("method") or "called")
    if rec.get("escalated"):
        return "escalated" if base == "submitted" else base + "+escalated"
    return base


def claim_for(result):
    """Claim rule: refused -> CL-REFUSED, blocked -> CL-BLOCKED, a submit that escalates (result 'escalated') ->
    CL-ESCALATED, otherwise the claim names the call made ('answered+escalated' -> CL-ANSWERED)."""
    return "CL-" + result.split("+")[0].upper()


def scripted_note(rec, reason=""):
    """The deterministic baseline actor: claims what it saw the environment do, gives its reason (often none)."""
    return {"claim": claim_for(env_result(rec)), "reason": reason or ""}
