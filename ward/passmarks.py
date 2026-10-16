"""Apply the signed LIVE pass marks (live_passmarks.toml) to live results. Pure, deterministic code.

A reply record: {"model": str, "expected_line": id, "line_id": id, "changes": [..], "text_ok": bool,
                 "events": {fail_kind: count}}.
A reply is ok when text_ok and the record holds the expected line id with no other change; a slip when the
record holds the expected line id with no other change but the reply was not word for word; anything else fails."""
import hashlib, math, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKS = tomllib.loads((ROOT / "live_passmarks.toml").read_text())


def check_id(kind):
    return "PM-" + kind.upper().replace("_", "-")            # stable check id per fail kind


def reason(r):
    """-> None (ok/slip) or the stable check id that fails this reply."""
    for k, v in MARKS["fail_limits"].items():
        if r.get("events", {}).get(k, 0) > v:
            return check_id(k)
    if set(r.get("events", {})) - set(MARKS["fail_limits"]):
        return "PM-UNKNOWN-EVENT"                            # unknown event kind: never a pass
    if r.get("line_id") != r.get("expected_line") or not r.get("expected_line"):
        return "PM-WRONG-LINE"
    if r.get("changes"):
        return "PM-EXTRA-CHANGE"                             # correct id plus any extra change is a fail, not a slip
    return None


def classify(r):
    return "fail" if reason(r) else ("ok" if r.get("text_ok") else "slip")


def judge(replies):
    """-> (verdict PASS/FAIL, counts, slip_log, failing check ids). Any non-pinned model reply fails the run."""
    counts, slips, ids = {"ok": 0, "slip": 0, "fail": 0}, [], []
    for i, r in enumerate(replies):
        if r.get("model") != MARKS["model"]:
            return "FAIL", dict(counts, model_mismatch=i), slips, ["PM-MODEL-NOT-PINNED"]
        c, why = classify(r), reason(r)
        counts[c] += 1
        if why:
            ids.append(why)
        if c == "slip":
            slips.append({"reply": i, "line_id": r.get("line_id")})      # each slip logged
    allowed = math.floor(MARKS["slips"]["allowed"] * len(replies) / MARKS["slips"]["per"])
    if counts["slip"] > allowed:
        ids.append("PM-SLIPS-OVER-LIMIT")
    if not replies:
        ids.append("PM-NO-REPLIES")
    return ("FAIL" if ids else "PASS"), counts, slips, ids


def wording_mismatches(wording_dir):
    d = pathlib.Path(wording_dir)
    return sorted(n for n, h in MARKS["wording_sha256"].items()
                  if not (d / n).is_file() or hashlib.sha256((d / n).read_bytes()).hexdigest() != h)
