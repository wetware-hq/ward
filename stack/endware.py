"""Endware adapters. letters (notes + brief -> letter.md) and figures (results paste -> chart).
Both are run as their own command line / environment in a subprocess and never edited.
Notes and pastes are built ONLY from logged, checked events:
  - a forms answer or decline event that is in the episode log, read back through the harness check;
  - a clinical record whose id an accepted orders tick cited as evidence (checked against the registry).
Every notes line keeps the trace references it came from, so each [Ln] tag in a letter resolves to events."""
import json, os, re, subprocess, sys, tempfile

from stack.paths import SIBLINGS as WORKSPACE
LETTERS = os.path.join(WORKSPACE, "letters", "letters.py")
FIGURES_DIR = os.path.join(WORKSPACE, "figures")
FIGURES_PY = os.path.join(FIGURES_DIR, ".venv", "bin", "python")
TAG = re.compile(r"\[(L\d+(?:,\s*L\d+)*)\]")
DECLINE_TEXT = "chose not to answer"       # a decline is never written as a no


DECLINE_TEXT = "chose not to"          # both LT declined lines; a decline is never a no
from . import locales


def _blocked_artifact(h, bundles, output):
    allb = sorted({x for bd in bundles for x in bd["blocks"]})
    b = next(bd["blocks"][0] for bd in bundles if bd["blocks"])
    return h.block(b, all=allb, output=output, reason=locales.line(b, language=h.language, **{"locale pack": h.pack}))


def _ref(h, ev):
    ep, n = ev.rsplit("#", 1)
    return {"episode": ep, "event": int(n)}


def letter(h, out, patient, episodes, reader, brief, phrases=None, privacy=None, notes=(), audit=False):
    """One harness export (all of the letter's episodes) -> adapter facts -> notes -> one letters build.
    audit=True: a second view of the same export (not a counted call)."""
    from . import adapter
    bundles = [h.export_bundle(e, audit=audit or n > 0) for n, e in enumerate(episodes)]
    if any(bd["blocks"] for bd in bundles):
        return _blocked_artifact(h, bundles, "letters")
    audience = "patient" if brief.strip().endswith("to patient") else "clinician"
    try:
        fs = [f for bd in bundles for f in adapter.facts(bd)]
    except adapter.AdapterRefused as e:
        h._emit("adapter", refused=str(e))
        return {"tool": "refused", "reason": str(e), "exit": 2, "refs": [], "path": None}
    head = {"trace_seq": [r["seq"] for r in h.trace if r.get("op") == "open" and r.get("episode") == episodes[0]][0]}
    fields = {k: [] for k in ("Problems", "Medicines", "Allergies", "Results", "Pending", "Actions")}
    history, question = [], None
    srcs_in = []
    lines_in = adapter.letter_lines(fs, audience, phrases or {}, srcs_in)
    for rid in notes:                         # logged clinician note lines (h.note), cited by trace seq
        r = h.records[rid]
        seq = [x["seq"] for x in h.trace if x["kind"] == "record" and x.get("record") == rid][-1]
        lines_in.append((r["field"], r["text"], [f"trace#{seq}"]))
        srcs_in.append({"from": "clinician_record", "item": None, "event": f"trace#{seq}", "record": rid, "chain": []})
    for (field, text, evs), sr in zip(lines_in, srcs_in):
        refs = [{"trace_seq": int(e.split("#")[1])} if e.startswith("trace#") else _ref(h, e) for e in evs]
        if field == "Question":
            question = (text, refs, sr)
        elif field in fields:
            fields[field].append((text, refs, sr))
        else:
            history.append((text, refs, sr))
    lines, refs, sources = [], [], []
    plain = {"from": "header", "item": None, "event": None, "chain": []}

    def add(t, r, s=plain):
        lines.append(t); refs.append(r); sources.append(s)
    date = h.clock.date().isoformat()
    add(f"Patient: {patient}", [head]); add(f"Date: {date}", [head]); add(f"Recipients: {reader}", [head])
    add(f"Question: {question[0] if question else 'none'}", question[1] if question else [head],
        question[2] if question else plain)
    add("Problems:", [])
    for t, r, sr in fields["Problems"]:
        add(f"- {t}", r, sr)
    # a summary line carries the full source record of every line it was worked out from
    add("History: " + ("; ".join(t.rstrip(".") for t, _, _ in history) if history else "none recorded"),
        [x for _, r, _ in history for x in r] or [head],
        {"from": "summary", "item": None, "event": None, "chain": [sr for _, _, sr in history]} if history else plain)
    for k in ("Medicines", "Allergies", "Results", "Pending", "Actions"):
        add(f"{k}:", [])
        for t, r, sr in fields[k]:
            add(f"- {t}", r, sr)
    res = run_letter_text(h, "\n".join(lines) + "\n", refs, brief, out, privacy, audit=audit, sources=sources)
    res.update(facts=fs, wording=adapter.wording_status())
    return res


def run_letter_text(h, text, refs, brief, outdir, privacy=None, audit=False, sources=None):
    os.makedirs(outdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "notes.txt")
        with open(p, "w") as f:
            f.write(text)
        cmd = [sys.executable, LETTERS, p, "--brief", brief, "--out", outdir]
        if privacy is not None:
            cmd += ["--privacy", "true" if privacy else "false"]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(LETTERS))
    letter = open(os.path.join(outdir, "letter.md")).read() if r.returncode == 0 else ""
    h._emit("endware", tool="letters", brief=brief, exit=r.returncode, **({"audit": True} if audit else {}))
    with open(os.path.join(outdir, "notes.refs.json"), "w") as f:
        json.dump({"notes": text.splitlines(), "refs": refs, **({"sources": sources} if sources is not None else {})}, f, indent=1)
    return {"tool": "letters", "brief": brief, "exit": r.returncode, "letter": letter, "notes": text, "refs": refs,
            **({"sources": sources} if sources is not None else {}),
            "screen": r.stdout + r.stderr, "path": os.path.join(outdir, "letter.md")}


def letter_tags(letter):
    out = []
    for m in TAG.finditer(letter):
        out += [int(x.strip()[1:]) for x in m.group(1).split(",")]
    return out


_FIG = r'''
import json, sys, os
sys.path.insert(0, sys.argv[1])
import figures
a = json.load(sys.stdin)
try:
    d, checks = figures.build(a["text"], a["out"] + ".html", as_at=a["as_at"])
    files = sorted(os.path.join(d, f) for f in os.listdir(d))
    pts = sum(len(r) for _, runs, _ in checks for r in runs)
    print(json.dumps({"render": {"ok": True, "files": files}, "points": pts}))
except figures.RowsRefused as e:
    print(json.dumps({"refused": e.lines}))
'''


FIGURES_RUN = subprocess.run          # tests may replace this with a stub; traces use the real figures


def run_figure(h, patient, episode_id, record_ids, as_at, outdir):
    """One harness export -> adapter facts -> design CSV -> figures paste -> one figures build.
    figures reads its own columns (patient,local_label,t,value,unit,...), not the design CSV (gap), so the
    design CSV is mapped column by column; rows not named in record_ids are not charted."""
    from . import adapter
    import csv as _csv, io as _io
    bd = h.export_bundle(episode_id)
    if bd["blocks"]:
        return _blocked_artifact(h, [bd], "figures")
    try:
        fs = adapter.facts(bd)
    except adapter.AdapterRefused as e:
        h._emit("adapter", refused=str(e))
        return {"tool": "refused", "reason": str(e), "exit": 2, "refs": [], "path": None}
    design = adapter.figures_csv([f for f in fs if f.get("record") in record_ids], h.pack)
    rows = ["patient,local_label,t,value,unit,device,derivation,status,gap_reason,event_id"]
    used = []
    fig_pid = "SYNTH-" + (re.sub(r"\D", "", patient) or "0")   # gap: figures only accepts SYNTH-<digits> patient ids
    for r in _csv.DictReader(_io.StringIO(design)):   # every row passes straight through; figures does the row check
        rows.append(f"{fig_pid},{r['item_id']},{r['recorded_at']},{r['value']},{r['unit']},lab:core,assay,measured,,{r['event_id']}")
        used.append(_ref(h, r["event_id"]))
    text = "\n".join(rows) + "\n"
    os.makedirs(outdir, exist_ok=True)
    payload = json.dumps({"text": text, "as_at": as_at, "out": os.path.join(outdir, "gallery")})
    r = FIGURES_RUN([FIGURES_PY, "-c", _FIG, FIGURES_DIR], input=payload, capture_output=True, text=True, cwd=outdir)
    h._emit("endware", tool="figures", op="build", exit=r.returncode)
    res = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {"error": r.stderr[-400:]}
    if "refused" in res:                       # figures made no figure: its own FG-REFUSE-DATA lines
        return {"tool": "refused", "reason": "FG-REFUSE-DATA", "lines": res["refused"], "exit": 2, "refs": [], "path": None}
    files = res.get("render", {}).get("files", []) if isinstance(res.get("render"), dict) else []
    lp = os.path.join(outdir, "gallery", "legends.md")
    legends = open(lp).read() if os.path.exists(lp) else ""
    pre, post = locales.line("FG-ROW-OMITTED", event_id="\x00").split("\x00")
    lines = [l for l in legends.splitlines() if l.startswith(pre) and l.endswith(post)]
    omitted = [l[len(pre):len(l) - len(post)] for l in lines]
    return {"tool": "figures", "exit": r.returncode, "result": res, "files": files, "legends": legends,
            "paste_rows": len(text.splitlines()) - 1, "refs": used, "path": lp, "lines": lines,
            "refused_rows": omitted, "points": res.get("points", 0),
            "charted_rows": [f"{u['episode']}#{u['event']}" for u in used if f"{u['episode']}#{u['event']}" not in omitted]}
