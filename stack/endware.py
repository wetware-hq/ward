"""Endware adapters. letters (notes + brief -> letter.md) and figures (results paste -> chart).
Both are run as their own command line / environment in a subprocess and never edited.
Notes and pastes are built ONLY from logged, checked events:
  - a forms answer or decline event that is in the episode log, read back through the harness check;
  - a clinical record whose id an accepted orders tick cited as evidence (checked against the registry).
Every notes line keeps the trace references it came from, so each [Ln] tag in a letter resolves to events."""
import json, os, re, subprocess, sys, tempfile

WORKSPACE = os.environ.get("STACK_WORKSPACE", "/workspace")
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


def letter(h, out, patient, episodes, reader, brief, phrases=None, privacy=None, notes=()):
    """One harness export per episode -> adapter facts -> notes -> one letters build."""
    from . import adapter
    bundles = [h.export_bundle(e) for e in episodes]
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
    lines_in = adapter.letter_lines(fs, audience, phrases or {})
    for rid in notes:                         # logged clinician note lines (h.note), cited by trace seq
        r = h.records[rid]
        seq = [x["seq"] for x in h.trace if x["kind"] == "record" and x.get("record") == rid][-1]
        lines_in.append((r["field"], r["text"], [f"trace#{seq}"]))
    for field, text, evs in lines_in:
        refs = [{"trace_seq": int(e.split("#")[1])} if e.startswith("trace#") else _ref(h, e) for e in evs]
        if field == "Question":
            question = (text, refs)
        elif field in fields:
            fields[field].append((text, refs))
        else:
            history.append((text, refs))
    lines, refs = [], []

    def add(t, r):
        lines.append(t); refs.append(r)
    date = h.clock.date().isoformat()
    add(f"Patient: {patient}", [head]); add(f"Date: {date}", [head]); add(f"Recipients: {reader}", [head])
    add(f"Question: {question[0] if question else 'none'}", question[1] if question else [head])
    add("Problems:", [])
    for t, r in fields["Problems"]:
        add(f"- {t}", r)
    add("History: " + ("; ".join(t.rstrip(".") for t, _ in history) if history else "none recorded"),
        [x for _, r in history for x in r] or [head])
    for k in ("Medicines", "Allergies", "Results", "Pending", "Actions"):
        add(f"{k}:", [])
        for t, r in fields[k]:
            add(f"- {t}", r)
    res = run_letter_text(h, "\n".join(lines) + "\n", refs, brief, out, privacy)
    res.update(facts=fs, wording=adapter.wording_status())
    return res


def run_letter_text(h, text, refs, brief, outdir, privacy=None):
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
    h._emit("endware", tool="letters", brief=brief, exit=r.returncode)
    with open(os.path.join(outdir, "notes.refs.json"), "w") as f:
        json.dump({"notes": text.splitlines(), "refs": refs}, f, indent=1)
    return {"tool": "letters", "brief": brief, "exit": r.returncode, "letter": letter, "notes": text, "refs": refs,
            "screen": r.stdout + r.stderr, "path": os.path.join(outdir, "letter.md")}


def letter_tags(letter):
    out = []
    for m in TAG.finditer(letter):
        out += [int(x.strip()[1:]) for x in m.group(1).split(",")]
    return out


_FIG = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from env import Env
a = json.load(sys.stdin)
e = Env()
c = e.clean(text=a["text"], as_at=a["as_at"])
out = {"clean": c}
if c.get("ok"):
    out["rejects"] = e.rejects(c["handle"])
    out["render"] = e.render(c["handle"], out=a["out"])
print(json.dumps(out, default=str))
'''


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
    rows = ["patient,local_label,t,value,unit,device,derivation,status,gap_reason"]
    used = []
    for r in _csv.DictReader(_io.StringIO(design)):
        rows.append(f"{patient},{r['item_id']},{r['recorded_at']},{r['value']},{r['unit']},lab:core,assay,measured,")
        used.append(_ref(h, r["event_id"]))
    text = "\n".join(rows) + "\n"
    os.makedirs(outdir, exist_ok=True)
    payload = json.dumps({"text": text, "as_at": as_at, "out": os.path.join(outdir, "gallery")})
    r = subprocess.run([FIGURES_PY, "-c", _FIG, FIGURES_DIR], input=payload, capture_output=True, text=True, cwd=outdir)
    h._emit("endware", tool="figures", op="clean+render", exit=r.returncode)
    res = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {"error": r.stderr[-400:]}
    files = res.get("render", {}).get("files", []) if isinstance(res.get("render"), dict) else []
    lp = os.path.join(outdir, "gallery", "legends.md")
    legends = open(lp).read() if os.path.exists(lp) else ""
    return {"tool": "figures", "exit": r.returncode, "result": res, "files": files, "legends": legends,
            "paste_rows": len(text.splitlines()) - 1, "refs": used, "path": lp}
