"""Dev-only planted leak variants (data/dev_leak_variants.toml). Synthetic; for tests and offline LIVE checks."""
import pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = tomllib.loads((ROOT / "data" / "dev_leak_variants.toml").read_text(encoding="utf-8"))
VARIANTS = {v["id"]: v for v in CFG["variant"]}


def trace_row(variant, seq=2):
    """One scored trace row that plants the variant leak."""
    v = variant if isinstance(variant, dict) else VARIANTS[variant]
    kind = v.get("row_kind", "call")
    note = {"claim": "CL-ANSWERED", "reason": v.get("note_reason", "")}
    if v.get("note_detail"):
        note["detail"] = v["note_detail"]
    row = {"kind": kind, "seq": seq, "note": note}
    if v.get("sensitive_step"):
        row["sensitive_step"] = True
    if kind == "harness":
        row["op"] = v.get("harness_op", "check")
    return row


def truth_for(variant):
    v = variant if isinstance(variant, dict) else VARIANTS[variant]
    subs = v.get("leak_substrings")
    return {"note_leak_substrings": list(subs)} if subs else {}
