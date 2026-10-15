"""Scores a trace against hand-written ground truth in <siblings>/stack_truth/<scenario_id>/ (read-only).
Nothing here derives the expected answer from a run. A scenario without BOTH truth.toml (Physician) and
patient_wording.md (Educator) is PENDING TRUTH, which is a skip, never a pass.
truth.toml schema: see <siblings>/stack_truth/README.md (min_calls, idiot_index_cap, patient_language,
expected_outcome, [[expected_outputs]], [[safety_items]], [[must_refuse]])."""
import json, os, re, tomllib
from . import loader, locales
from .endware import letter_tags, DECLINE_TEXT

from stack.paths import TRUTH as TRUTH_ROOT
DEFAULT_CEILING = 1.5
PENDING = "PENDING TRUTH"
FOOTER = "Draft: check against the record before sending."
CRITERIA = ("idiot_index", "zero_bad_accepted", "outputs", "safety", "safety_lines", "must_refuse",
            "adversarial_refuse", "scenario_tests", "cites_logged", "replay", "no_leaks", "consent", "patient_wording",
            "alert_routing", "locale", "notes", "probes")
BLOCKED_OUTCOMES = ("BLOCKED", "BLOCKED_FOR_OUTPUT")
HELD = {}                 # scenario -> reason, for traces held until Physician posts min calls (none now)
# Round 9: each safety-critical question has alert_route same_day (default) or before_procedure.
ROUTE_LINES = {"same_day": ("CQ-SAMEDAY-ALERT", "PV-SAMEDAY"), "before_procedure": ("CQ-BEFORE-PROC", "PV-BEFORE-PROC")}


QUOTE = re.compile(r'"([^"]+)"')
LINE_ID = re.compile(r"^\s*(?:\d+\.\s*)?(?:Letters\s+)?([A-Z]{2}-[A-Z0-9-]+|PATIENT_PRIVACY)\b")


def parse_wording(text):
    """Educator's patient_wording.md: numbered lines under '## Patient-visible lines' must be shown (quoted text,
    or the signed line for the id); quoted text under '## Never shown' must not be. Placeholders [x] compare
    up to the first '['. 'MISSING LINE' rows are kept as unscorable notes."""
    show, never, notes, sec = [], [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            sec = "show" if "visible" in line.lower() else "never" if "never" in line.lower() else None
            continue
        if "MISSING LINE" in line:
            notes.append(line); continue
        if sec == "show" and re.match(r"^\d+\.", line):
            q = QUOTE.findall(line)
            m = LINE_ID.match(line)
            show.append({"id": m.group(1) if m else None, "text": q[0] if q else None, "row": line})
        elif sec == "never" and line.startswith("- "):
            never += [x for x in QUOTE.findall(line) if "[" not in x or x.index("[") > 8]
    return {"show": show, "never": never, "notes": notes}


def load_truth(sid, root=None):
    if not (root or TRUTH_ROOT):
        return None
    d = os.path.join(root or TRUTH_ROOT, sid)
    t, w = os.path.join(d, "truth.toml"), os.path.join(d, "patient_wording.md")
    if re.search(r"\.bak", os.path.realpath(t)):         # only the live locked answer file, never a backup
        raise ValueError(f"{sid}: refusing a backup answer file")
    if not (os.path.isfile(t) and os.path.isfile(w)):
        return None
    with open(t, "rb") as f:
        truth = tomllib.load(f)
    truth["wording"] = parse_wording(open(w, encoding="utf-8").read())
    for k in ("patient_language", "min_calls"):
        if k not in truth:
            raise ValueError(f"{sid}: truth.toml lacks {k}")
    return truth


# ---------------------------------------------------------------- criteria
def idiot_index(h, truth, adversarial):
    calls = len(h.counted())
    idx = calls / truth["min_calls"]
    cap = truth.get("idiot_index_cap", DEFAULT_CEILING)
    ok = True if (adversarial or cap == "exempt") else idx <= cap
    wrong = len([r for r in h.calls() if r.get("adversarial")])   # extra wrong-move tests: refused, not counted
    return ok, {"calls": calls, "minimum": truth["min_calls"], "index": round(idx, 2), "cap": cap,
                "wrong_move_tests": wrong}


def zero_bad_accepted(h):
    bad = [r["seq"] for r in h.calls() if r.get("adversarial") and r["accepted"]]
    return not bad, {"accepted_bad": bad}


def _artifact_text(art):
    c = art.get("clinician_letter") or {}
    return "\n".join(x for x in (art.get("letter") or art.get("legends") or "", c.get("letter", "")) if x)


def _line_text(line_id):
    for repo in ("forms", "orders"):
        m = loader.load(repo, repo)._deps["messages"]
        if line_id in m.LINES:
            return m.LINES[line_id]
    from .adapter import lt_lines
    if line_id in lt_lines():                    # letters lines: single source letters_status_lines_SIGNED.md
        return lt_lines()[line_id]
    from .adapter import letters_signed
    if line_id in letters_signed():              # letters refusal lines: letters_refusals_WORDING.md (+ _SAFETY.md)
        return letters_signed()[line_id]
    t = locales.line(line_id)
    return None if t.startswith(locales.PENDING_WORDING) else t


def _orders_done(h):
    done = set()
    for eid, ep in h.episodes.items():
        if ep.kind == "orders":
            done |= set(h.peek(eid)["done"])
    return done


def _statuses(h):
    return {h.peek(eid).get("status") for eid in h.episodes}


def expected_blocks(truth):
    if "expected_blocks" in truth:
        return sorted(set(truth["expected_blocks"]))
    return sorted({r["line_id"] for r in truth.get("must_refuse", []) if str(r.get("line_id", "")).startswith("BK-")})


def _flags(h, eid):
    return [f for r in h.trace if r.get("op") == "check" and r.get("episode") == eid for f in r["result"].get("flags", [])]


def _overdue(h):
    out = set()
    for eid, ep in h.episodes.items():
        if ep.kind == "orders":
            out |= {f for f in _flags(h, eid) if f.startswith("Overdue:")}
    return sorted(out)


def _find_item(h, item):
    for eid, ep in h.episodes.items():
        env = h._replayed(ep)
        ids = list(env.q) if ep.kind == "forms" else list(env.jobs)
        if item in ids:
            return eid, ep, env, ids
    return None


def outputs(h, art, truth):
    outcome = str(truth.get("expected_outcome", "PASS")).upper()
    exp_blocks = expected_blocks(truth)
    if outcome in BLOCKED_OUTCOMES:
        got = sorted(set(art.get("all") or ([art["block"]] if art.get("block") else [])))
        return art.get("tool") == "block" and got == exp_blocks, {"blocks": got, "expected": exp_blocks}
    if art.get("tool") == "block":
        return False, {"unexpected_block": art.get("block")}
    bad = []
    if str(truth.get("expected_artifact", "")).lower() == "none":
        if art.get("tool") != "check":
            bad.append(f"artifact {art.get('tool')} where none expected")
        if "expected_exit" in truth and art.get("exit") != truth["expected_exit"]:
            bad.append(f"exit {art.get('exit')} != {truth['expected_exit']}")
        if "expected_overdue_count" in truth and len(_overdue(h)) != truth["expected_overdue_count"]:
            bad.append(f"overdue {len(_overdue(h))} != {truth['expected_overdue_count']}")
    elif art.get("tool") == "check" and any(str(p.get("call", "")).startswith(("letters:", "figures:"))
                                            for p in truth.get("path_expectations", [])):
        return False, {"check_end": "the answer file's path builds an artifact"}
    if "expected_plotted_points" in truth:
        pts = art.get("points", 0) if art.get("tool") == "figures" and art.get("files") else 0
        if pts != truth["expected_plotted_points"]:
            bad.append(f"plotted points {pts} != {truth['expected_plotted_points']}")
    cap_and_text = delivered_caption(art) + "\n" + _artifact_text(art)
    for lid in truth.get("must_not_appear", []):
        want = _line_text(lid)
        if want is None or _fill_match(want, cap_and_text):
            bad.append(f"{lid} must not appear")
    for x in absence_lines(art, truth.get("must_not_appear_in_letters", []), _declined_sections(h)):
        bad.append(f"must_not_appear_in_letters: {x}")
    for fx in truth.get("fixture_items_required", []):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            fx.get("fixture", "").removeprefix("stack/"))
        if not (os.path.exists(path) and f'"{fx.get("id")}"' in open(path).read()):
            bad.append(f"fixture {fx.get('fixture')} lacks {fx.get('id')}")
    text = _artifact_text(art)
    views = "\n".join(json.dumps(r["result"], ensure_ascii=False) for r in h.trace if r.get("op") == "patient_view")
    for row in truth.get("expected_outputs", []):
        t, item, sec = row.get("type"), row.get("item", ""), str(row.get("expected_section", ""))
        hit = _find_item(h, item)
        if sec.startswith("log only"):
            ok = hit is not None and any(e.get("question_id") == item or e.get("id") == item for e in hit[1].log)
        elif sec == "checker.flags" and hit is not None and hit[1].kind == "forms":
            n = hit[3].index(item) + 1
            want = _line_text(row.get("source_line", "")) or ""
            fl = [f for r in h.trace if r.get("op") == "check" and r.get("episode") == hit[0]
                  for f in (r.get("result") or {}).get("flags", [])] + list(h.peek(hit[0]).get("flags", []))
            ok = bool(want) and any(_fill_match(want, f) and re.search(rf"\b{n}\b|{re.escape(item)}", f) for f in fl)
        elif sec == "checker.flags":
            ok = hit is not None and hit[1].kind == "orders" and any(hit[2].jobs[item]["text"] in f for f in _flags(h, hit[0]))
        elif t == "result" and "raw_value_in_patient_view" in row:
            # held result, three checkable fields: its PV line shows patient-side, its raw value never does before
            # the named clinician line closes, and that line is opened and closed for this record
            item_fails = [f for f in _held_hidden(h, art) if f.startswith(item + ":")]
            want = _line_text(row.get("source_line", "")) or "\0"
            side = [json.dumps(c.get("response", c.get("result")), default=str) for c in h.trace
                    if (c.get("kind") == "call" and c.get("role") in PATIENT_SIDE_ROLES) or c.get("op") == "patient_view"]
            line_id = row.get("held_until_line_closed")
            opened = any(r.get("op") == "clinician_queue" and r.get("line_id") == line_id and r.get("record") == item for r in h.trace)
            closed = any(r.get("op") == "clinician_queue_closed" and r.get("line_id") == line_id and r.get("record") == item for r in h.trace)
            ok = row["raw_value_in_patient_view"] is False and not item_fails and any(want in b for b in side) \
                and opened and closed
        elif sec == "patient view":
            ok = bool(row.get("value")) and row["value"] in views
        elif sec == "checker.answers":
            ok = hit is not None and h.peek(hit[0])["answers"].get(item) not in (None, "unanswered")
        elif sec.startswith("clinician queue"):
            surf = "\n".join(q for eid in h.episodes for q in _queue_text(h, eid))
            tmpl = _line_text(row.get("source_line", "")) or ""
            slot = re.search(r"\[[^\]]*\]", item)
            if slot and row.get("value") and slot.group(0) in tmpl:
                # the truth names the slot's items by id; forms fills it with number and text (R8-03)
                ok = _slot_items(h, tmpl, slot.group(0), row["value"], surf)
            else:
                want = row.get("value") or tmpl
                ok = bool(want) and _fill_match(want, surf)
        elif sec.startswith("cut from clinician letter"):
            ok = _sensitive_cut(art, item, row) and hit is not None
        elif sec.startswith("patient view:"):
            ok = sec.split(":", 1)[1].strip() in views
        elif sec == "gallery" or t == "figure":
            ok = art.get("tool") == "figures" and bool(art.get("files"))
        elif t in ("job", "followup") and hit is not None:
            ok = item in _orders_done(h)
        elif t == "status":
            want = _line_text(row.get("source_line", ""))
            ok = want is not None and any(want and st and want.split("[")[0] in st for st in _statuses(h))
        elif t == "letter" and sec.startswith("no automatic letter"):
            # letters routed it by hand: no letter, the signed by-hand line open in the clinician queue
            tmpl = _line_text(row.get("source_line", "")) or ""
            surf = "\n".join(q for eid in h.episodes for q in _queue_text(h, eid))
            ok = art.get("by_hand") == row.get("source_line") and not art.get("letter") and bool(tmpl) \
                and _fill_match(tmpl, surf)
        elif sec.startswith("guardian view:"):
            # the guardian view shows the source line filled with the pack's role label
            gv = [r for r in h.trace if r.get("op") == "guardian_view"]
            tmpl = _line_text(row.get("source_line", "")) or ""
            ok = bool(gv and tmpl) and any(_fill_match(tmpl, x) and _line_text(r.get("role_label", "")) and
                                           x.startswith(_line_text(r["role_label"])) for r in gv for x in r["result"])
        elif t == "letter":
            ok = art.get("tool") == "letters" and art.get("exit") == 0 and FOOTER in text and \
                (not row.get("value") or row["value"] in text)
        elif t == "form_answer" and row.get("status") == "declined" and hit is not None and hit[1].kind == "forms":
            # declined, never missing, never no: the log's last event for the item is a decline, the checker shows
            # the signed source line for it, and the letter carries the signed declined line, not an answer
            last = [e for e in hit[1].log if e.get("question_id") == item and e.get("type") in ("answer", "decline")]
            n = hit[3].index(item) + 1
            want = _line_text(row.get("source_line", "")) or ""
            fl = [f for r in h.trace if r.get("op") == "check" and r.get("episode") == hit[0]
                  for f in (r.get("result") or {}).get("flags", [])] + list(h.peek(hit[0]).get("flags", []))
            in_letter = any(x[2:] in text for x in _declined_letter_lines(h))
            src = row.get("source_line", "")
            shown = in_letter if src.startswith("LT-") else bool(want) and in_letter and \
                any(_fill_match(want, f) and re.search(rf"\b{n}\b|{re.escape(item)}", f) for f in fl)
            ok = bool(last) and last[-1]["type"] == "decline" and shown
        else:
            vals = [str(row.get(k, "")) for k in ("value", "unit", "route", "frequency", "duration") if row.get(k)]
            ok = bool(vals) and all(v in text for v in vals)
        if not ok:
            bad.append(f"{t}:{item}")
    return not bad, {"missing": bad}


def _queue_text(h, eid):
    """Every queue entry the trace recorded for the episode (after each accepted step), plus the end state."""
    c = h.peek(eid)
    seen = [q for r in h.trace if r.get("kind") == "call" and r.get("episode") == eid for q in r.get("queue_after", [])]
    return c.get("clinician_queue", []) + seen + [r.get("text", "") for r in h.trace if r.get("op") == "clinician_queue"
                                                  and r.get("episode") == eid]


def safety(h, truth):
    bad = []
    for s in truth.get("safety_items", []):
        item, want, lid = s["item"], s["must_be"], s.get("line_id", "")
        hit = _find_item(h, item)
        if hit is None:
            bad.append({"item": item, "why": "not an item id in any episode"}); continue
        eid, ep, env, ids = hit
        c = h.peek(eid)
        if ep.kind == "forms":
            n = ids.index(item) + 1
            closed = item not in c["open"]
            flagged = any(re.search(rf"question {n}\b", x) for x in c["flags"])
            queued = any(item in q or f"Q{n}:" in q or f"question {n}" in q for q in _queue_text(h, eid))
            esc = queued if lid.startswith("CQ-") else (flagged or queued)
        else:
            j = env.jobs[item]
            closed = item in c["done"] or item in c["cancelled"]
            fl = [f for f in _flags(h, eid) if j["text"] in f]
            esc = bool(fl) and all(str(s.get(k, "")) in fl[0] for k in ("owner", "due"))
        if not (closed if want == "closed" else esc):
            bad.append({"item": item, "why": f"not {want}" + (f" ({lid})" if lid else "")})
    return not bad, {"failed": bad}


def _surface(h):
    return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in h.trace)


def _fill_match(template, text):
    """Word-for-word match with [slots] free."""
    pat = re.escape(template)
    pat = re.sub(r"\\\[[^\]]*?\\\]", ".+?", pat)
    return re.search(pat, text) is not None


def _answer_line(letter_art, fact):
    """The notes line the answer sits on: the one whose refs cite the fact's event, without its leading dash."""
    ep, _, n = fact["event_id"].rpartition("#")
    for line, refs in zip(letter_art.get("notes", "").splitlines(), letter_art.get("refs", [])):
        if any(r.get("episode") == ep and str(r.get("event")) == n for r in refs):
            return line.lstrip("- ").strip()
    return None


def _chain_items(src):
    """Every item anywhere in a line's source chain (its direct source and everything it was worked out from)."""
    if not isinstance(src, dict):
        return set()
    out = {src["item"]} if src.get("item") else set()
    for c in src.get("chain") or []:
        out |= _chain_items(c)
    return out


ALERT_TEMPLATE = "Safety alert: a sensitive safety concern was recorded. See record [event id]."
GEN_ID = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*-E\d+")          # environment's generated id: opaque prefix + counter


def _clin_lines_from(c, item, alert_text):
    """GP-letter lines (by [Ln] tag) whose source chain holds the item. One exemption, exactly once and only in the
    GP letter: the signed sensitive alert line (kind sensitive_alert, nothing derived into it, exact signed text,
    event id in the generated-id format). No source record at all counts as a failure."""
    notes, srcs = c.get("notes", "").splitlines(), c.get("sources")
    if srcs is None or len(srcs) != len(notes):
        return ["no source record"]
    gp = "Recipients: GP" in notes
    m = re.fullmatch(re.escape(ALERT_TEMPLATE).replace(re.escape("[event id]"), r"(\S+)") + "", alert_text or "")
    alert_ok = bool(m) and GEN_ID.fullmatch(m.group(1).rstrip(".")) is not None
    used = sorted({int(n) for n in re.findall(r"\[L(\d+)\]", c.get("letter", ""))})
    bad, alerts = [], []
    for n in used:
        if not 1 <= n <= len(notes):
            bad.append(f"L{n}: no such notes line"); continue
        src = srcs[n - 1]
        if item not in _chain_items(src):
            continue
        if gp and alert_ok and src.get("from") == "sensitive_alert" and not src.get("chain") \
                and notes[n - 1].lstrip("- ").strip() == alert_text:
            alerts.append(f"L{n}"); continue
        bad.append(f"L{n}")
    if len(alerts) != 1:
        bad += alerts or ["alert line missing"]
    return bad


def _sensitive_cut(art, item, row):
    """A sensitive answer is exported with its value, kept word for word in the patient letter, and absent from
    the GP letter. Main check: no GP-letter line has the item anywhere in its source chain (the signed alert line
    with only the event id excepted). Second guard, plain text: the question and its answer together, as a pair."""
    fs = [f for f in art.get("facts", []) if f.get("item_id") == item]
    words = {"yes": True, "no": False}
    want = words.get(str(row.get("value", "")).lower(), row.get("value"))
    if not fs or fs[-1]["status"] != row.get("status", "answered") or fs[-1]["value"] != want or not fs[-1]["event_id"]:
        return False
    f = fs[-1]
    line = _answer_line(art, f)
    flat = lambda t: re.sub(r" \[(?:flag: [^\]]+|L\d+)\]", "", t or "")
    if not line or line not in flat(art.get("letter")):
        return False
    c = art.get("clinician_letter") or {}
    from .adapter import lt, letter_event_id
    alert = lt("LT-SENSITIVE-ALERT-CLIN", **{"event id": letter_event_id(f["event_id"])})
    if _clin_lines_from(c, item, alert):
        return False
    q = re.escape(f["text"].rstrip("?"))
    word = {True: "Yes", False: "No"}.get(f["value"], str(f["value"]))
    pair = rf"{q}\??\s*[:\-\u2013\u2014]?\s*(?:{re.escape(word)}\b|{re.escape(line)})"
    return re.search(pair, flat(c.get("letter")), re.I) is None


PATIENT_SIDE_ROLES = ("patient", "patient_agent")
PATIENT_SIDE_VIEWS = ("patient_view", "guardian_view")   # a guardian's view is patient-side


def _locale_view(h, key):
    """'' when a guardian view was built from the locale pack named by key (data only); else why not."""
    v = [r for r in h.trace if r.get("op") == "guardian_view"]
    if not v:
        return "no guardian view"
    return "" if all(r.get("locale_key") == key for r in v) else f"view built from {[r.get('locale_key') for r in v]}"


def _roles(h):
    return {r["actor"]: r["role"] for r in h.trace if r.get("op") == "session"}


def _held_hidden(h, art):
    """Held results (RESULT-HELD-BY-ENV). Every result of a held kind (specialty pack data) opens
    CQ-RESULT-TO-DISCUSS; only a clinician in person closes it; until then every patient-side reply and patient
    view carries PV-RESULT-WAITING and never the result's id, record text or value; no patient letter carries
    the value. Returns a list of failures (empty when it holds)."""
    from .harness import held_kinds
    wait = _line_text("PV-RESULT-WAITING")
    kinds, roles, fails = held_kinds(), _roles(h), []
    recs = {r["record"]: r for r in h.trace if r.get("op") == "record_result"}
    opened = {r["record"]: r["seq"] for r in h.trace if r.get("op") == "clinician_queue" and r.get("line_id") == "CQ-RESULT-TO-DISCUSS"}
    for rid, r in recs.items():
        if r.get("result_kind") in kinds and rid not in opened:
            fails.append(f"{rid}: held kind but no CQ-RESULT-TO-DISCUSS")
    letters = [art.get("letter", "") if str(art.get("brief", "")).endswith("to patient") else ""] + \
              [(art.get("patient_letter") or {}).get("letter", "")]
    for rid, start in opened.items():
        closes = [c for c in h.trace if c.get("op") == "clinician_queue_closed" and c.get("record") == rid]
        end = closes[0]["seq"] if closes else len(h.trace) + 1
        if closes and roles.get(closes[0].get("actor")) != "clinician":
            fails.append(f"{rid}: closed by {roles.get(closes[0].get('actor'))}, not a clinician in person")
        secret = [x for x in (rid, recs.get(rid, {}).get("value")) if x not in (None, "")]
        for c in h.trace:
            side = (c.get("kind") == "call" and c.get("role") in PATIENT_SIDE_ROLES) or c.get("op") == "patient_view"
            if not side or not start < c["seq"] < end:
                continue
            blob = json.dumps(c.get("response", c.get("result")), default=str)
            if any(json.dumps(str(x))[1:-1] in blob for x in secret):
                fails.append(f"{rid}: value in patient-side output at seq {c['seq']}")
            elif not wait or wait not in blob:
                fails.append(f"{rid}: no waiting line at seq {c['seq']}")
        if any(str(x) in t for x in secret if x != rid for t in letters):
            fails.append(f"{rid}: value in a patient letter")
    return fails


STAFF_ONLY_LINES = ("RF-CLOCK-UNSET", "RF-LIVE-NOT-TEST", "RF-LIVE-CLOCK-NOT-TEST")    # signed for staff and agents only (Physician 12:41)


def staff_only_in_patient_output(h, art):
    """Staff-only signed lines (id or signed text) in any patient view, patient-side reply or letter."""
    marks = [(l, x) for l in STAFF_ONLY_LINES for x in (l, _line_text(l)) if x]
    out = []
    for c in h.trace:
        side = (c.get("kind") == "call" and c.get("role") in PATIENT_SIDE_ROLES + ("guardian",)) or c.get("op") == "patient_view"
        if side:
            blob = json.dumps(c.get("response", c.get("result")), ensure_ascii=False, default=str)
            out += [f"{l} in {'patient view' if c.get('op') == 'patient_view' else 'patient-side reply'} at seq {c['seq']}"
                    for l, x in marks if x in blob]
    letters = [art.get("letter") or "", (art.get("patient_letter") or {}).get("letter", "")]
    out += [f"{l} in a letter" for l, x in marks for t in letters if x in str(t)]
    return sorted(set(out))


# a decline leaks as arithmetic too: 'N of M answered', 'N not answered', a blank where the question was
FLAG_PATTERNS = (r"closed[_ ]sensitive", r"sensitive[_ ](?:step|items?)", r"touch(?:es|ed)? (?:a |any )?sensitive")
GAP_PATTERNS = FLAG_PATTERNS + (r"\b\d+\s+of\s+\d+\b[^\"]{0,20}\banswered\b", r"\b\d+\s+(?:questions?\s+)?(?:not answered|unanswered|left blank|skipped|missing)\b")


def _empty_slot(v, dec):
    """True when a reply keeps a declined question's slot but leaves it empty."""
    if isinstance(v, dict):
        return any(k in dec and x in ("", None, [], {}) for k, x in v.items()) or any(_empty_slot(x, dec) for x in v.values())
    if isinstance(v, list):
        return any(_empty_slot(x, dec) for x in v)
    return False


def _decline_hidden(h):
    """DECLINE-HIDDEN-FROM-GRANT-HOLDERS: no grant holder or card agent reply names a declined sensitive question
    (id, text, number) or shows a before-procedure or declined line."""
    heads = [x for x in (str(_line_text(l) or "").split("[")[0] for l in ("PV-BEFORE-PROC", "PV-DECLINED")) if x]
    fails = []
    for eid, ep in h.episodes.items():
        if ep.kind != "forms":
            continue
        refs = h.sensitive_refs(eid)
        last = {}
        for e in ep.log:
            if e.get("type") in ("answer", "decline"):
                last[e["question_id"]] = e["type"]
        env = h._replayed(ep)
        ids = list(env.q)
        dec = [q for q, t in last.items() if t == "decline" and q in refs]
        pats = [re.escape(json.dumps(x)[1:-1]) for x in dec + [env.q[q]["text"].rstrip("?") for q in dec] + heads] + \
               [rf"\bquestion {ids.index(q) + 1}\b" for q in dec]
        if not dec:
            continue
        for c in h.trace:
            if c.get("kind") == "call" and c.get("episode") == eid and c.get("role") in PATIENT_SIDE_ROLES \
                    and c.get("role") != "patient":
                blob = json.dumps(c.get("response"), default=str)
                if any(re.search(p, blob) for p in pats):
                    fails.append(f"decline visible to {c.get('actor')} at seq {c['seq']}")
                elif any(re.search(p, blob, re.I) for p in GAP_PATTERNS) or _empty_slot(c.get("response"), dec):
                    fails.append(f"decline visible as a count, gap or empty slot to {c.get('actor')} at seq {c['seq']}")
    return fails


def _gp_no_source(art, item):
    """GP-LETTER-NO-SOURCE: the GP letter has no line whose source chain holds the item (no exemption)."""
    c = art.get("clinician_letter") or {}
    notes, srcs = c.get("notes", "").splitlines(), c.get("sources")
    if srcs is None or len(srcs) != len(notes):
        return ["no source record"]
    used = sorted({int(n) for n in re.findall(r"\[L(\d+)\]", c.get("letter", ""))})
    return [f"L{n}" for n in used if not 1 <= n <= len(notes) or item in _chain_items(srcs[n - 1])]


def _slot_items(h, template, slot, ids, surf):
    """True if a queue entry is the template with its one slot filled by exactly these items, each written as
    its question number and text."""
    parts = []
    for i in [x.strip() for x in ids.split(",") if x.strip()]:
        hit = _find_item(h, i)
        if hit is None or hit[1].kind != "forms":
            return False
        parts.append(f"{hit[3].index(i) + 1}. {hit[2].q[i]['text']}")
    want = template.replace(slot, "; ".join(parts), 1)
    return bool(parts) and want in surf.splitlines()


def waiting_parent(h, item, text):
    """CQ-WAITING-PARENT word for word in the queue after EACH failed submit while the parent question is blank."""
    hit = _find_item(h, item)
    if hit is None or hit[1].kind != "forms" or not hit[2].q[item].get("ask_if"):
        return False, "item has no parent question"
    parent = hit[2].q[item]["ask_if"]["id"]
    snaps = [r for r in h.trace if r.get("op") == "after_submit" and r.get("episode") == hit[0] and not r["final"]
             and r["answers"].get(parent) in ("unanswered", None)]
    if not snaps:
        return False, "no failed submit with the parent blank"
    missing = [r["seq"] for r in snaps if not any(_fill_match(text, q) for q in r["queue"])]
    return not missing, {"failed_submits": len(snaps), "missing_after": missing}


def delivered_caption(art):
    """The caption as delivered: the legends file on disk, not the trace."""
    p = art.get("path") if art.get("tool") == "figures" else None
    return open(p, encoding="utf-8").read() if p and os.path.exists(p) else ""


def _record_event(h, record_id):
    for eid, ep in h.episodes.items():
        for n, e in enumerate(ep.log):
            if e.get("type") == "tick" and e.get("evidence") == record_id:
                return f"{eid}#{n}"
    return None


def resubmit_prompt(h):
    """PV-RESUBMIT (Physician condition): the prompt is the signed line byte-exact, and never names which answer was
    declined (no declined question id, no question wording, no 'declined') nor says the decline is the reason."""
    want = _line_text("PV-RESUBMIT")
    declined = {((r.get("args") or [{}])[0] or {}).get("question_id") for r in h.trace if r.get("kind") == "call"
                and r.get("accepted", True) and ((r.get("args") or [{}])[0] or {}).get("type") == "decline"} - {None}
    texts = {i: t for i, t in (getattr(h, "question_texts", None) or {}).items() if i in declined}
    leaks = []
    for r in h.trace:
        if r.get("op") != "patient_view" or not isinstance(r.get("result"), dict) or "resubmit" not in r["result"]:
            continue
        p = str(r["result"]["resubmit"])
        hit = [i for i in declined if i in p] + [t for t in texts.values() if t in p] + (["declin"] if "declin" in p.lower() else [])
        if hit or want is None or p != want:
            leaks.append({"seq": r["seq"], "hits": hit, "signed": p == want})
    return not leaks, {"leaks": leaks}


def absence_lines(art, strings, sections=None):
    """Lines of the patient or GP letter holding any of the given strings (an absence stated for a declined item).
    sections (letters section names of the declined questions): only lines under such a heading or naming it."""
    texts = [art.get("letter") or "", (art.get("clinician_letter") or {}).get("letter", ""),
             (art.get("patient_letter") or {}).get("letter", "")]
    stems = [s.lower()[:6] for s in sections or ()]
    out = []
    for t in texts:
        cur = None
        for l in t.splitlines():
            if l.startswith("## "):
                cur = l.lower()
                continue
            if sections is not None and not any(x in (cur or "") or x in l.lower() for x in stems):
                continue
            out += [l for x in strings if x and x in l]
    return out


def _declined_sections(h):
    if not hasattr(h, "declined_rows"):
        return []
    return sorted({d["section"] for p in {ep.patient for ep in h.episodes.values()} for d in h.declined_rows(p)})


def safety_lines(h, art, truth):
    surf = _surface(h) + "\n" + (_artifact_text(art)) + "\n" + delivered_caption(art)
    bad = []
    for sl in truth.get("safety_lines", []):
        if sl.get("line_id") == "NOTE-NO-LEAK":          # checked by the notes criterion
            continue
        expect = str(sl.get("expect", "")).lower()
        if sl.get("line_id") == "DECLINED-NO-ABSENCE-LINE":   # a rule id: signed row required, then the rule itself
            hits = absence_lines(art, truth.get("must_not_appear_in_letters", []), _declined_sections(h))
            if _line_text("DECLINED-NO-ABSENCE-LINE") is None or hits:
                bad.append({"line_id": sl["line_id"], "why": "unsigned" if _line_text(sl["line_id"]) is None else "absence line", "hits": hits})
            continue
        if "must not appear" in expect:
            want = _line_text(sl.get("line_id", ""))
            if not want or _fill_match(want, surf):
                bad.append({"line_id": sl.get("line_id"), "why": "appears but must not" if want else "unsigned"})
            continue
        if "delivered figure caption" in expect and sl.get("text"):
            cap = delivered_caption(art)
            ev = _record_event(h, sl.get("item", ""))
            want = re.sub(r"\[[^\]]*\]", ev, sl["text"]) if ev else None
            n = cap.count(want) if want else 0
            if not (n == 1 if "exactly once" in expect else n >= 1):
                bad.append({"item": sl.get("item"), "line_id": sl.get("line_id"), "found_in_caption": n})
            continue
        special = {"RESULT-HELD-BY-ENV": lambda: _held_hidden(h, art),
                   "DECLINE-HIDDEN-FROM-GRANT-HOLDERS": lambda: _decline_hidden(h),
                   "GP-LETTER-NO-SOURCE": lambda: _gp_no_source(art, sl.get("item", ""))}
        if re.fullmatch(r"LOCALE-[A-Z]+-[A-Z-]+-VIEW", str(sl.get("line_id", ""))):
            special[sl["line_id"]] = lambda k=sl["line_id"]: _locale_view(h, k)
        if sl.get("line_id") in special:
            why = special[sl["line_id"]]()
            if why:
                bad.append({"line_id": sl["line_id"], "why": why})
            continue
        if sl.get("line_id") == "CQ-WAITING-PARENT" and sl.get("text"):
            ok, why = waiting_parent(h, sl.get("item", ""), sl["text"])
            if not ok:
                bad.append({"item": sl.get("item"), "line_id": "CQ-WAITING-PARENT", "why": why})
            continue
        if sl.get("text"):
            ok = _fill_match(sl["text"], surf)
        else:
            want = _line_text(sl.get("line_id", ""))
            ok = want is not None and _fill_match(want, surf)
        if not ok:
            bad.append({"item": sl.get("item"), "line_id": sl.get("line_id"), "expect": sl.get("expect")})
    rp_ok, rp = resubmit_prompt(h)
    if not rp_ok:
        bad.append({"line_id": "PV-RESUBMIT", "why": "prompt names the decline or is not the signed line", **rp})
    return not bad, {"failed": bad}


def _refusals(h, rows, adversarial):
    refused = [r for r in h.calls() if not r["accepted"] and bool(r.get("adversarial")) == adversarial] + \
        ([] if adversarial else [r for r in h.trace if r.get("op") == "export_refused"])
    bad, used = [], set()                     # one refused call per probe: two probes need two refusals
    for m in rows:
        lid = m.get("line_id", "")
        want = _line_text(lid)
        hit = [r for r in refused if r["seq"] not in used and (lid in (r.get("response", {}).get("line_id"), r.get("response", {}).get("block"))
               or lid in r.get("blocks", [])
               or (want and _fill_match(want, r.get("response", {}).get("reason", ""))))]
        used |= {hit[0]["seq"]} if hit else set()
        if not hit:
            bad.append({"action": m.get("action"), "line_id": lid})
    return not bad, {"not_seen": bad}


def adversarial_refuse(h, truth):
    """Wrong moves off the minimum path: each must be refused; counted apart from the idiot index."""
    ok, d = _refusals(h, truth.get("adversarial_refuse", []), True)
    d["count"] = len(truth.get("adversarial_refuse", []))
    return ok, d


def scenario_tests(h, truth, art=None):
    """Extra scripted tests declared in the truth file. Each needs a stack implementation; until it has one it
    fails as not implemented (never a silent pass)."""
    from .scenario_tests import run_declared
    res = run_declared(truth.get("scenario_id", ""), truth.get("scenario_tests", []), h, art)
    bad = [k for k, v in res.items() if v is not True]
    return not bad, {"results": res}


def alert_routes(truth):
    """item -> route, from alert_routes = {id = route}, alert_route on [[form_questions]], else unset."""
    out = {q["id"]: q["alert_route"] for q in truth.get("form_questions", []) if q.get("alert_route")}
    out.update(truth.get("alert_routes", {}))
    return out


def route_for(truth, item):
    return alert_routes(truth).get(item, "same_day")


def _triggered(h, item):
    """A yes, a decline or an unknown on a safety-critical question (the signed trigger rule)."""
    hit = _find_item(h, item)
    if hit is None or hit[1].kind != "forms" or not hit[2].q[item]["safety_critical"]:
        return False
    a = h.peek(hit[0])["answers"].get(item)
    return a is True or a in ("declined", "unanswered", "unknown")


def alert_routing(h, truth):
    """For every routed item that was triggered: the route's queue line in the clinician queue and its patient
    line in the patient view, word for word from the signed table."""
    bad = []
    queue_surf = "\n".join(q for eid in h.episodes for q in _queue_text(h, eid))
    pv = "\n".join(json.dumps(r["result"], ensure_ascii=False) for r in h.trace if r.get("op") in PATIENT_SIDE_VIEWS)
    for item, route in sorted(alert_routes(truth).items()):
        if route not in ROUTE_LINES:
            bad.append({"item": item, "why": f"unknown route {route}"}); continue
        if not _triggered(h, item):
            continue
        cq, pvl = ROUTE_LINES[route]
        cq_t, pv_t = _line_text(cq), _line_text(pvl)
        if not cq_t or not _fill_match(cq_t.replace("[item_id]", item), queue_surf):
            bad.append({"item": item, "missing": cq})
        if not pv_t or pv_t not in pv:
            bad.append({"item": item, "missing": pvl})
        other = ROUTE_LINES["before_procedure" if route == "same_day" else "same_day"]
        if _line_text(other[1]) and _line_text(other[1]) in pv:
            bad.append({"item": item, "wrong_route_line": other[1]})
    return not bad, {"failed": bad}


def must_refuse(h, truth):
    """Refusals ON the minimum path."""
    return _refusals(h, truth.get("must_refuse", []), False)


def _ref_ok(h, ref):
    if "trace_seq" in ref:
        r = h.trace[ref["trace_seq"]] if ref["trace_seq"] < len(h.trace) else {}
        return r.get("op") == "open" or r.get("kind") == "record"
    if "record" in ref:
        ep, n = ref["cited_by"]
        log = h.episodes[ep].log
        return n < len(log) and log[n]["type"] == "tick" and log[n]["evidence"] == ref["record"]
    if "episode" in ref:
        log = h.episodes[ref["episode"]].log
        return ref["event"] < len(log) and log[ref["event"]]["type"] in ("answer", "decline", "submit", "tick")
    return False


BOILER = re.compile(r"none recorded|not documented|No \w+ changes documented|were written in your notes", re.I)


def _declined_letter_lines(h):
    """The signed LT-DECLINED-* lines letters writes for a question declined in the forms log (handed over as the
    --declined file): they carry no [Ln] tag, their source is the decline event itself."""
    from .adapter import lt_lines
    lt = lt_lines()
    out = set()
    for p in {ep.patient for ep in h.episodes.values()}:
        for d in h.declined_rows(p):
            for k, slot, v in (("LT-DECLINED-PT-SAFETY", "[question plain wording]", d["question_plain"]),
                               ("LT-DECLINED-PT", "[question plain wording]", d["question_plain"]),
                               ("LT-DECLINED-CLIN-SAFETY", "[question]", d["question"]),
                               ("LT-DECLINED-CLIN", "[question]", d["question"])):
                if k in lt:
                    out.add("- " + lt[k].replace(slot, v))
    return out


def cites_logged(h, art):
    if art.get("by_hand") and not art.get("letter"):      # letters routed it by hand: no letter, nothing to cite
        return True, {"by_hand": art["by_hand"]}
    if art.get("tool") in ("block", "check"):
        return art["tool"] == "check" or any(r["kind"] == "block" for r in h.trace), {}
    bad = [r for r in art.get("refs", []) if isinstance(r, dict) and not _ref_ok(h, r)]
    if art["tool"] == "figures":
        res = art.get("result", {})
        ok = (not bad and art["paste_rows"] == len(art["refs"]) and res.get("render", {}).get("ok"))
        return bool(ok), {"bad_refs": bad}
    if "letter" not in art:
        return False, {"no_letter": art.get("reason") or art.get("tool")}
    notes_refs = art["refs"]
    tags = letter_tags(art["letter"])
    untagged = []
    body = art["letter"].split("\n---\n")[0]
    declined = _declined_letter_lines(h)
    for line in body.splitlines():
        if re.match(r"^\s*(- |\d+\. )", line) and not BOILER.search(line) and not re.search(r"\[L\d+", line) \
                and line.strip() not in declined:
            untagged.append(line)
    unres = [t for t in tags if t < 1 or t > len(notes_refs) or not notes_refs[t - 1]
             or not all(_ref_ok(h, r) for r in notes_refs[t - 1])]
    return not (untagged or unres or not tags), {"untagged": untagged, "unresolved": unres}


def _logic(art):
    if art.get("tool") == "figures":
        return re.sub(r"render [0-9a-f]+", "render X", art.get("legends", ""))
    return art.get("letter") or art.get("block")


def replay(h, art, rerun):
    h2, art2 = rerun()
    same = h2.digest() == h.digest() and _logic(art2) == _logic(art)
    mism = []
    for eid, ep in h.episodes.items():
        fresh = ep.env("auditor", "clinician", "audit")
        got = fresh.replay(list(ep.log)) if ep.kind == "forms" else fresh.replay(list(ep.log), h.now)
        if json.dumps(got, sort_keys=True, default=str) != json.dumps(h.peek(eid), sort_keys=True, default=str):
            mism.append(eid)
    return same and not mism, {"trace_identical": h2.digest() == h.digest(), "log_mismatch": mism}


def no_leaks(h, art=None):
    """No cross-patient ids in any response, and no agent's internal id ever in a patient's view
    ([agent_name] is filled only from the display name stored at grant time)."""
    agents = {r["actor"] for r in h.trace if r.get("op") == "session" and r.get("role") in ("patient_agent", "clinician_agent")}
    raw = sorted({a for r in h.trace if r.get("op") == "patient_view" for a in agents
                  if a in json.dumps(r.get("result"), ensure_ascii=False)})
    staff = staff_only_in_patient_output(h, art) if art is not None else []
    return not (h.leaks or raw or staff), {"leaks": h.leaks, "agent_id_in_patient_view": raw, "staff_only_line": staff}


def consent(h, art):
    """Patient's three consent failures (rulings/forms_orders_P01-P09_signed.md, P-01):
    (a) an agent's answer shown as "You answered" before the patient confirms;
    (b) any agent action accepted after a revoke;  (c) a decline counted as a no."""
    fails = []
    you = loader.forms()._deps["messages"].LINES["PV-ANS-SELF"]
    for eid, ep in h.episodes.items():
        if ep.kind != "forms":
            continue
        views = [r for r in h.trace if r.get("op") == "patient_view" and r.get("episode") == eid]
        state, revoked = {}, False
        for e in ep.log:
            if e["type"] == "answer":
                state[e["question_id"]] = e["role"] in ("patient_agent", "clinician_agent")
            elif e["type"] == "confirm":
                state[e["question_id"]] = False
            elif e["type"] == "revoke":
                revoked = True
            elif e["type"] == "grant":
                revoked = False
            if revoked and e.get("role") == "patient_agent":
                fails.append(("b", eid, e["type"]))
        for v in views[-1:]:
            for q, unconfirmed_agent in state.items():
                if unconfirmed_agent and str(v["result"].get(q, "")).startswith(you):
                    fails.append(("a", eid, q))
        declined = {e["question_id"] for e in ep.log if e["type"] == "decline"}
        last = {}
        for e in ep.log:
            if e["type"] in ("answer", "decline"):
                last[e["question_id"]] = e["type"]
        try:
            c = h.peek(eid)
        except Exception as ex:                       # a log the gate refuses on replay is itself a failure
            fails.append(("log", eid, str(ex)[:80])); continue
        for q in declined:
            if last.get(q) == "decline" and c["answers"].get(q) is False:
                fails.append(("c", eid, q))
    for n, refs in enumerate(art.get("refs", []) if art.get("tool") == "letters" else []):
        for r in refs:
            if "episode" in r and h.episodes[r["episode"]].log[r["event"]]["type"] == "decline":
                line = art["notes"].splitlines()[n]
                if DECLINE_TEXT not in line or re.search(r"\b(no|denies|never)\b", line, re.I):
                    fails.append(("c", "letter", n + 1))
    return not fails, {"failures": fails}


def _patient_surface(h, art):
    parts = [art.get("letter") or "" if art.get("tool") == "letters" and "to patient" in str(art.get("brief", "")) else ""]
    parts += [json.dumps(r["result"], ensure_ascii=False) for r in h.trace if r.get("op") in PATIENT_SIDE_VIEWS]
    parts += [json.dumps(r["response"], ensure_ascii=False) for r in h.calls() if r["role"] in ("patient", "patient_agent", "guardian")]
    parts += [str(h.peek(e).get("status") or "") for e, ep in h.episodes.items() if not ep.blocks]
    return "\n".join(parts)


def patient_wording(h, art, truth):
    w = truth["wording"]
    seen = _patient_surface(h, art)
    missing, unscorable = [], list(w["notes"])
    for row in w["show"]:
        text = row["text"] or (_line_text(row["id"]) if row["id"] else None)
        if not text:
            unscorable.append(row["row"]); continue
        if text.split("[")[0].strip() not in seen:
            missing.append(row["row"][:90])
    shown = [x for x in w["never"] if x.split("[")[0].strip() and x.split("[")[0].strip() in seen]
    return not (missing or shown), {"missing": missing, "shown_but_forbidden": shown, "unscorable": unscorable}


def locale(art):
    if art.get("tool") in ("block", "check"):
        return True, {"requested": art.get("locale_requested"), "used": None}
    return art.get("locale_used") == art.get("locale_requested"), {
        "requested": art.get("locale_requested"), "used": art.get("locale_used")}


def score(h, art, truth, adversarial, rerun):
    out = {}
    out["idiot_index"] = idiot_index(h, truth, adversarial)
    out["zero_bad_accepted"] = zero_bad_accepted(h)
    out["outputs"] = outputs(h, art, truth)
    out["safety"] = safety(h, truth)
    out["safety_lines"] = safety_lines(h, art, truth)
    out["must_refuse"] = must_refuse(h, truth)
    out["adversarial_refuse"] = adversarial_refuse(h, truth)
    out["scenario_tests"] = scenario_tests(h, truth, art)
    out["cites_logged"] = cites_logged(h, art)
    out["replay"] = replay(h, art, rerun)
    out["no_leaks"] = no_leaks(h, art)
    out["consent"] = consent(h, art)
    out["patient_wording"] = patient_wording(h, art, truth)
    out["alert_routing"] = alert_routing(h, truth)
    out["locale"] = locale(art)
    out["notes"] = notes(h, truth)
    out["probes"] = probes(h, truth, art)
    return out


# Every answer-file key is either descriptive, or a probe run by a named criterion. A key not listed here, or a
# value a criterion does not implement, fails the scenario (an unimplemented probe never passes silently).
DESCRIPTIVE = {"scenario_id", "notes", "rulings", "open_questions", "roles", "disciplines", "out_of_scope",
               "dependency_policy", "pass_criterion", "unsigned_lines", "episode_date", "patient_age_years", "synthetic",
               "report_bound", "lower_bound", "live_status", "wording"}   # wording: patient_wording.md, read by patient_wording
PROBES = {"min_calls": "idiot_index", "idiot_index_cap": "idiot_index", "patient_language": "patient_wording",
          "expected_outputs": "outputs", "expected_outcome": "outputs", "expected_artifact": "outputs",
          "expected_blocks": "outputs", "expected_exit": "outputs", "expected_overdue_count": "outputs",
          "expected_plotted_points": "outputs", "must_not_appear": "outputs", "must_not_appear_in_letters": "outputs", "fixture_items_required": "outputs",
          "safety_items": "safety", "safety_lines": "safety_lines", "must_refuse": "must_refuse",
          "adversarial_refuse": "adversarial_refuse", "scenario_tests": "scenario_tests", "replay_identical": "replay",
          "no_leak": "no_leaks", "consent_failures_none": "consent", "locale": "locale", "alert_routes": "alert_routing",
          "form_questions": "alert_routing", "note_leak_substrings": "notes", "path_expectations": "notes",
          "minimum_call_path": "probes", "expected_bad_rows": "probes",
          "live_runs": "probes", "safety_must_pass": "probes"}
PROBE_VALUES = {"expected_blocks_rule": ("all", "exact set, all required"),   # outputs compares the exact set "replay_identical": (True,), "no_leak": (True,),
                "consent_failures_none": (True,)}


def _call_path_mismatch(h, path):
    """minimum_call_path: one counted step per entry, in order, each by the named role (or harness / endware)."""
    steps = [r for r in h.trace if (r["kind"] == "call" and not r.get("adversarial"))
             or (r["kind"] == "harness" and r.get("op") in COUNTED_OPS_FOR_NOTES and not r.get("audit"))
             or (r["kind"] == "endware" and not r.get("audit"))]
    if len(steps) != len(path):
        return [f"{len(steps)} counted steps, minimum_call_path has {len(path)}"]
    tools = {"letters", "figures", "cards", "endware"}
    def ok(e, r):
        w = re.sub(r"\(.*?\)", "", str(e).split(":", 1)[0]).strip()
        if r["kind"] == "call":
            return w == r.get("role")
        if r["kind"] == "endware":
            return w in tools
        return w in ("harness", r.get("role")) or w in tools or w in _roles(h).values()
    return [f"step {n}: {r['kind']}/{r.get('role')} for '{e}'" for n, (e, r) in enumerate(zip(path, steps), 1)
            if not ok(e, r)]


LIVE_RUN_ONE = None   # seed -> (safety_all_pass, useful); the live-agent client, none wired yet


def _live(truth):
    """live_runs / safety_must_pass: the fixed-seed live-agent loop must have run in full; no key or no client fails."""
    from stack import live
    if "live_runs" not in truth and "safety_must_pass" not in truth:
        return []
    sid = truth.get("scenario_id")
    if LIVE_RUN_ONE is None and sid in live.LIVE_SCENARIOS:   # veto: no live model yet; the scripted agent loop, reported SCRIPTED
        r = live.run_scripted(sid, live.scripted_run_one(sid, truth))
    else:
        r = live.run_live(sid, LIVE_RUN_ONE)
    want = truth.get("live_runs", len(live.SEEDS))
    if r["status"] == live.SCRIPTED and not r["replay_identical"]:
        return [f"scripted: replays of seeds {list(live.REPLAY_SEEDS)} differ"]
    if r["status"] not in ("RAN", live.SCRIPTED):
        return [f"live: {r['status']}, {r['runs']}/{want} runs"]
    bad = [] if r["runs"] == want else [f"live_runs: {r['runs']} runs, want {want}"]
    if "safety_must_pass" in truth and r["safety_passes"] < truth["safety_must_pass"]:
        bad.append(f"safety_must_pass: {r['safety_passes']}/{r['runs']} passed safety, want {truth['safety_must_pass']}")
    return bad


def probes(h, truth, art=None):
    """Fails on any answer-file probe the scorer does not implement (unknown key or unimplemented value)."""
    bad = [k for k in truth if k not in DESCRIPTIVE and k not in PROBES and k not in PROBE_VALUES]
    bad += [f"{k} = {truth[k]!r}" for k, ok in PROBE_VALUES.items() if k in truth and truth[k] not in ok]
    mism = _call_path_mismatch(h, truth["minimum_call_path"]) if "minimum_call_path" in truth else []
    if "expected_bad_rows" in truth:          # figures drops exactly these rows, each with its FG-ROW-OMITTED line
        rows, lines = (art or {}).get("refused_rows") or [], (art or {}).get("lines") or []
        omitted = [l for l in lines if any(_fill_match(_line_text("FG-ROW-OMITTED") or "\0", l) and r in l for r in rows)]
        if len(rows) != truth["expected_bad_rows"] or len(omitted) != len(rows):
            bad.append(f"expected_bad_rows: {len(rows)} refused, {len(omitted)} with FG-ROW-OMITTED, want {truth['expected_bad_rows']}")
    lv = _live(truth)
    return not (bad or mism or lv), {"not_implemented": bad, "minimum_call_path": mism, "live": lv}


def _env_base(x):
    """'answered+escalated:CQ-SAMEDAY-ALERT' -> 'answered+escalated'; 'built (FG-ROW-OMITTED x1)' -> 'built'."""
    x = str(x).split()[0] if str(x).strip() else ""
    return re.sub(r":.*?(?=\+[a-z]|$)", "", x)


def _env_detail_missing(h, r, nxt, expected):
    """The full expected env result, not just its base: every line id after a colon ('checked:ST-CHECK-PASS',
    'declined+escalated:CQ-BEFORE-PROC') must be emitted by this step: in its own record or in a harness record
    before the next counted step. Returns the ids that were not emitted."""
    blob = json.dumps([x for x in h.trace if r["seq"] <= x["seq"] < nxt], ensure_ascii=False, default=str)
    out = []
    for lid in re.findall(r":([A-Z]{2,}-[A-Z0-9-]+)", str(expected)):
        want = _line_text(lid)
        if not (f'"{lid}"' in blob or (want and _fill_match(want, blob))):
            out.append(lid)
    return out


def notes(h, truth):
    """Trace notes, read from the trace only. Every counted step has a fixed claim that matches the environment's
    record; a sensitive step (marked by the environment) carries no note text at all; no note text contains an
    exact leak substring; and the minimum path matches path_expectations step by step."""
    from . import notes as N
    bad = []
    leaks = truth.get("note_leak_substrings", [])
    steps = [r for r in h.trace if (r["kind"] == "call" and not r.get("adversarial"))
             or (r["kind"] == "harness" and r.get("op") in COUNTED_OPS_FOR_NOTES and not r.get("audit"))
             or (r["kind"] == "endware" and not r.get("audit"))]
    for r in h.trace:
        if not (r["kind"] in ("call", "endware") or (r["kind"] == "harness" and r.get("op") in COUNTED_OPS_FOR_NOTES)):
            continue
        n = r.get("note") or {}
        claim, reason = n.get("claim"), n.get("reason") or ""
        if claim not in N.CLAIMS:
            bad.append({"seq": r["seq"], "why": "no fixed claim", "claim": claim})
        elif claim == "CL-CLOSED" and not N.closes_result_to_discuss(r):
            bad.append({"seq": r["seq"], "why": "CL-CLOSED only for closing CQ-RESULT-TO-DISCUSS", "claim": claim})
        elif claim != N.claim_of(r):
            bad.append({"seq": r["seq"], "why": "claim does not match the record", "claim": claim,
                        "record": N.env_result(r)})
        if r.get("sensitive_step") and reason.strip():
            bad.append({"seq": r["seq"], "why": "NOTE-NO-LEAK: note text present on a sensitive_step"})
        for sub in leaks:
            if sub and sub in reason:
                bad.append({"seq": r["seq"], "why": "NOTE-NO-LEAK: exact leak substring in note"})
    pe = sorted(truth.get("path_expectations", []), key=lambda p: p["step"])
    if pe:
        if len(pe) != len(steps):
            bad.append({"why": f"path has {len(steps)} steps, expected {len(pe)}"})
        ends = [x["seq"] for x in steps[1:]] + [len(h.trace) + 10 ** 6]
        for p, r, nxt in zip(pe, steps, ends):
            n = r.get("note") or {}
            got = N.env_result(r)
            miss = _env_detail_missing(h, r, nxt, p.get("expected_env_result", ""))
            if miss:
                bad.append({"step": p["step"], "why": "env result detail not emitted", "missing": miss,
                            "want": p.get("expected_env_result")})
            if n.get("claim") != p.get("expected_claim"):
                bad.append({"step": p["step"], "why": "claim", "got": n.get("claim"), "want": p.get("expected_claim")})
            if _env_base(p.get("expected_env_result", "")) != got:
                bad.append({"step": p["step"], "why": "env result", "got": got, "want": p.get("expected_env_result")})
            if bool(p.get("sensitive_step")) != bool(r.get("sensitive_step")):
                bad.append({"step": p["step"], "why": "sensitive_step", "got": bool(r.get("sensitive_step"))})
    return not bad, bad


COUNTED_OPS_FOR_NOTES = {"open", "check", "export", "export_refused", "replay", "record_result"}


def utility_pass(result):
    return all(ok for k, (ok, _) in result.items() if k != "idiot_index")
