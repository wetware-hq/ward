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
            "alert_routing", "locale", "notes")
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
    d = os.path.join(root or TRUTH_ROOT, sid)
    t, w = os.path.join(d, "truth.toml"), os.path.join(d, "patient_wording.md")
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
        elif sec.startswith("patient view:"):
            ok = sec.split(":", 1)[1].strip() in views
        elif sec == "gallery" or t == "figure":
            ok = art.get("tool") == "figures" and bool(art.get("files"))
        elif t in ("job", "followup") and hit is not None:
            ok = item in _orders_done(h)
        elif t == "status":
            want = _line_text(row.get("source_line", ""))
            ok = want is not None and any(want and st and want.split("[")[0] in st for st in _statuses(h))
        elif t == "letter":
            ok = art.get("tool") == "letters" and art.get("exit") == 0 and FOOTER in text and \
                (not row.get("value") or row["value"] in text)
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


def safety_lines(h, art, truth):
    surf = _surface(h) + "\n" + (_artifact_text(art)) + "\n" + delivered_caption(art)
    bad = []
    for sl in truth.get("safety_lines", []):
        if sl.get("line_id") == "NOTE-NO-LEAK":          # checked by the notes criterion
            continue
        expect = str(sl.get("expect", "")).lower()
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
    return not bad, {"failed": bad}


def _refusals(h, rows, adversarial):
    refused = [r for r in h.calls() if not r["accepted"] and bool(r.get("adversarial")) == adversarial] + \
        ([] if adversarial else [r for r in h.trace if r.get("op") == "export_refused"])
    bad = []
    for m in rows:
        lid = m.get("line_id", "")
        want = _line_text(lid)
        hit = [r for r in refused if lid in (r.get("response", {}).get("line_id"), r.get("response", {}).get("block"))
               or lid in r.get("blocks", [])
               or (want and r.get("response", {}).get("reason", "").startswith(want.split("[")[0].rstrip()))]
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
    pv = "\n".join(json.dumps(r["result"], ensure_ascii=False) for r in h.trace if r.get("op") == "patient_view")
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


def cites_logged(h, art):
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
    for line in body.splitlines():
        if re.match(r"^\s*(- |\d+\. )", line) and not BOILER.search(line) and not re.search(r"\[L\d+", line):
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


def no_leaks(h):
    """No cross-patient ids in any response, and no agent's internal id ever in a patient's view
    ([agent_name] is filled only from the display name stored at grant time)."""
    agents = {r["actor"] for r in h.trace if r.get("op") == "session" and r.get("role") in ("patient_agent", "clinician_agent")}
    raw = sorted({a for r in h.trace if r.get("op") == "patient_view" for a in agents
                  if a in json.dumps(r.get("result"), ensure_ascii=False)})
    return not (h.leaks or raw), {"leaks": h.leaks, "agent_id_in_patient_view": raw}


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
    parts += [json.dumps(r["result"], ensure_ascii=False) for r in h.trace if r.get("op") == "patient_view"]
    parts += [json.dumps(r["response"], ensure_ascii=False) for r in h.calls() if r["role"] in ("patient", "patient_agent")]
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
    out["no_leaks"] = no_leaks(h)
    out["consent"] = consent(h, art)
    out["patient_wording"] = patient_wording(h, art, truth)
    out["alert_routing"] = alert_routing(h, truth)
    out["locale"] = locale(art)
    out["notes"] = notes(h, truth)
    return out


def _env_base(x):
    """'answered+escalated:CQ-SAMEDAY-ALERT' -> 'answered+escalated'; 'built (FG-ROW-OMITTED x1)' -> 'built'."""
    x = str(x).split()[0] if str(x).strip() else ""
    return re.sub(r":.*?(?=\+[a-z]|$)", "", x)


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
        elif claim != N.claim_for(N.env_result(r)):
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
        for p, r in zip(pe, steps):
            n = r.get("note") or {}
            got = N.env_result(r)
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
