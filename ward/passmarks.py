"""Apply the signed LIVE pass marks (live_passmarks.toml) to live results. Pure, deterministic code.

A reply record: {"model": str, "expected_line": id, "line_id": id, "changes": [..], "text_ok": bool,
                 "events": {fail_kind: count}}.
A reply is ok when text_ok and the record holds the expected line id with no other change; a slip when the
record holds the expected line id with no other change but the reply was not word for word; anything else fails."""
import hashlib, math, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKS = tomllib.loads((ROOT / "live_passmarks.toml").read_text())


def classify(r):
    if any(r.get("events", {}).get(k, 0) > v for k, v in MARKS["fail_limits"].items()):
        return "fail"
    if set(r.get("events", {})) - set(MARKS["fail_limits"]):
        return "fail"                                        # unknown event kind: never a pass
    clean = r.get("line_id") == r.get("expected_line") and r.get("expected_line") and not r.get("changes")
    if not clean:
        return "fail"                                        # correct id plus any extra change is a fail, not a slip
    return "ok" if r.get("text_ok") else "slip"


def judge(replies):
    """-> (verdict PASS/FAIL, counts, slip_log). Any non-pinned model reply fails the run."""
    counts, slips = {"ok": 0, "slip": 0, "fail": 0}, []
    for i, r in enumerate(replies):
        if r.get("model") != MARKS["model"]:
            return "FAIL", dict(counts, model_mismatch=i), slips
        c = classify(r)
        counts[c] += 1
        if c == "slip":
            slips.append({"reply": i, "line_id": r.get("line_id")})      # each slip logged
    allowed = math.floor(MARKS["slips"]["allowed"] * len(replies) / MARKS["slips"]["per"])
    ok = counts["fail"] == 0 and counts["slip"] <= allowed and replies != []
    return ("PASS" if ok else "FAIL"), counts, slips


def wording_mismatches(wording_dir):
    d = pathlib.Path(wording_dir)
    return sorted(n for n, h in MARKS["wording_sha256"].items()
                  if not (d / n).is_file() or hashlib.sha256((d / n).read_bytes()).hexdigest() != h)
