"""Export adapter (cleared design). Input: one finished episode export bundle from the harness (one harness
export call). It must be synthetic, check-passed and not blocked, else it is refused. The transform is pure:
no environment calls. Outputs:
  (a) facts for a letters notes file, one per checked event, each citing its event id;
  (b) a figures CSV: episode,item_id,value,unit,recorded_at,event_id,status,answered_by,on_behalf,interpreter,sensitive
Every fact and row carries status (answered|declined|unknown|stale), answered_by (role, discipline), on_behalf,
interpreter and sensitive. A declined or unknown answer is never written as a no and never dropped; its safety
alert carries through. Letter status wording comes from /workspace/wording/letters_status_lines_DRAFT.md and
is read from letters_status_lines_SIGNED.md (PENDING WORDING if only the draft exists). letters has no input for these fields (gap), so they reach it as notes lines."""
import csv, io, os, re, tomllib

WORKSPACE = os.environ.get("STACK_WORKSPACE", "/workspace")
LT_SIGNED_FILE = os.path.join(WORKSPACE, "wording", "letters_status_lines_SIGNED.md")
LT_DRAFT_FILE = os.path.join(WORKSPACE, "wording", "letters_status_lines_DRAFT.md")
LT_SIGNED = os.path.exists(LT_SIGNED_FILE)   # PENDING WORDING unless the signed table exists
LT_FILE = LT_SIGNED_FILE if LT_SIGNED else LT_DRAFT_FILE
PENDING_WORDING = "PENDING WORDING"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_COLS = ["episode", "item_id", "value", "unit", "recorded_at", "event_id", "status", "answered_by",
            "on_behalf", "interpreter", "sensitive"]


class AdapterRefused(Exception):
    pass


def lt_lines():
    rows = re.findall(r"^\|\s*(LT-[A-Z-]+)\s*\|[^|]*\|[^|]*\|\s*(.+?)\s*\|\s*$", open(LT_FILE, encoding="utf-8").read(), re.M)
    return dict(rows)


def lt(line_id, **f):
    t = lt_lines()[line_id]
    for k, v in f.items():
        t = t.replace(f"[{k}]", str(v))
    return t


def sensitive_ids(case_path):
    """forms questions have no 'sensitive' field (gap); a stack sidecar <case>.sensitive.toml lists them."""
    if not case_path:
        return set()
    side = case_path.replace(".toml", ".sensitive.toml")
    if not os.path.exists(side):
        side = os.path.join(HERE, "cases", os.path.basename(case_path).replace(".toml", ".sensitive.toml"))
    if not os.path.exists(side):
        return set()
    with open(side, "rb") as f:
        return set(tomllib.load(f).get("sensitive", []))


def _event_id(ep, n):
    return f"{ep}#{n}"


def facts(bundle):
    """Pure transform: bundle -> list of facts. Refuses unless synthetic, check-passed and unblocked."""
    ep = bundle["episode_id"]
    if bundle["blocks"]:
        raise AdapterRefused(bundle["blocks"][0])
    if not (isinstance(ep, str) and ep.startswith("SYNTH-")):
        raise AdapterRefused("not synthetic")
    x = bundle["export"]
    if bundle["kind"] == "forms" and not x.get("complete"):
        raise AdapterRefused("not check-passed")
    if bundle["kind"] == "orders" and not (x.get("all_done") or x.get("closed")):
        raise AdapterRefused("not check-passed")
    log, interp, out = x["log"], set(bundle["interpreter_events"]), []
    if bundle["kind"] == "forms":
        sens = sensitive_ids(bundle["case"])
        for q in bundle["items"]:
            i = q["id"]
            ans = x["answers"].get(i)
            if ans == "n/a":
                continue                                  # skipped by its stated condition, not unknown
            hits = [(n, e) for n, e in enumerate(log) if e.get("question_id") == i and e["type"] in ("answer", "decline")]
            n, e = hits[-1] if hits else (None, None)
            stale = e is not None and (e.get("episode_id") != ep or e.get("question_version") != q["version"])
            status = ("stale" if stale else "declined" if e and e["type"] == "decline"
                      else "answered" if e else "unknown")
            out.append({"episode": ep, "item_id": i, "text": q["text"], "value": e["value"] if status == "answered" else None,
                        "unit": "", "recorded_at": e["timestamp"] if e else "", "event_id": _event_id(ep, n) if e else "",
                        "status": status, "answered_by": f"{e['role']}, {e['discipline']}" if e and e["discipline"] else (e["role"] if e else ""),
                        "on_behalf": (e or {}).get("on_behalf") or "", "interpreter": n in interp,
                        "sensitive": i in sens, "safety": q["safety_critical"], "alert": q["alert_answer"]})
    else:
        for n, e in enumerate(log):
            if e["type"] != "tick":
                continue
            r = bundle["records"].get(e["evidence"], {})
            out.append({"episode": ep, "item_id": e["id"], "record": e["evidence"], "field": r.get("field", ""),
                        "text": r.get("text", ""), "value": r.get("text", ""), "unit": "", "recorded_at": e["ts"],
                        "event_id": _event_id(ep, n), "status": "answered",
                        "answered_by": f"{e['role']}, {e['discipline']}" if e["discipline"] else e["role"],
                        "on_behalf": "", "interpreter": n in interp, "sensitive": False, "safety": False, "alert": None})
    return out


def letter_event_id(event_id):
    """letters refuses notes holding a second SYNTH- identifier (gap), so an event id is written in letters as
    <episode without SYNTH->-E<n>, e.g. SYNTH-EP-0501#7 -> EP-0501-E7. The mapping is one to one."""
    ep, n = event_id.rsplit("#", 1)
    return f"{ep.removeprefix('SYNTH-')}-E{n}"


def letter_lines(fs, audience, phrases):
    """Facts -> (field, text, event ids) for the notes file. audience: 'patient' or 'clinician'.
    phrases: item_id -> (text if yes, text if no) for answered questions (scenario wording, not status wording)."""
    from .harness import AGENT_ROLES  # noqa: F401
    rel = __import__("stack.loader", fromlist=["forms"]).forms()._deps["messages"].RELATIONSHIP
    out = []
    for f in fs:
        ev = [f["event_id"]] if f["event_id"] else []
        if "record" in f:
            out.append((f["field"], f["text"], ev)); continue
        q = f["text"].rstrip("?")
        if f["sensitive"] and audience != "patient":
            # leak guard: a sensitive answer's text never goes into clinician notes; the alert line and the
            # event id stand in its place, whatever the status
            out.append(("Problems", lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": letter_event_id(f["event_id"]) if f["event_id"] else "none"}), ev))
            continue
        if f["status"] in ("declined", "unknown", "stale"):
            st = "unknown" if f["status"] == "stale" else f["status"]
            key = f"LT-{st.upper()}-{'PT' if audience == 'patient' else 'CLIN'}"
            if f["safety"] and key + "-SAFETY" in lt_lines():
                key += "-SAFETY"
            out.append(("Problems", lt(key, question=q, **{"question plain wording": q}), ev))
        else:
            yes, no = phrases.get(f["item_id"], (None, None))
            t = yes if f["value"] else no
            if t:
                out.append(("Problems", t, ev))
        if f["on_behalf"]:
            r = rel[f["on_behalf"]]
            if audience == "patient":
                out.append(("History", lt("LT-ONBEHALF-PT", **{"relationship, patient term": r[0]}), ev))
            else:
                out.append(("History", lt("LT-ONBEHALF-CLIN", **{"relationship, clinician term": r[1],
                                                                  "discipline": f["answered_by"].split(", ")[-1]}), ev))
        if f["interpreter"] and audience != "patient":
            out.append(("History", lt("LT-INTERP-CLIN"), ev))
    return out


def figures_csv(fs, pack):
    """Design CSV. Unit comes from the locale pack's unit list where it names the unit (gap: packs have no units
    file today, so the core list is used and the pack is recorded)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, CSV_COLS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for f in fs:
        row = dict(f)
        if "record" in f and f["field"] == "result":
            label, t, v, unit = f["text"].split("|")
            row.update(item_id=label, value=v, unit=unit, recorded_at=t)
        w.writerow(row)
    return buf.getvalue()


def wording_status():
    return "signed" if LT_SIGNED else PENDING_WORDING
