"""The harness: owns every episode log, opens sessions, and is the only party that may reset, replay,
check or export. Actors (people and agents) get a Handle that exposes observe and step only.
Every call, accepted or refused, is written to the trace. No model is called anywhere."""
import datetime, hashlib, json, os, random, re
from . import loader, locales
import tomllib as _toml
# person id -> cards grant id, per scenario (data: cases/scenario_data.toml [person_grants.*])
PERSON_GRANTS = {k: v for d in _toml.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "cases", "scenario_data.toml"), "rb")).get("person_grants", {}).values() for k, v in d.items()}

SYNTH_ID = re.compile(r"SYNTH-[A-Za-z0-9-]+")
COUNTED = "call"          # trace kind of an actor call
COUNTED_OPS = {"open", "check", "export", "export_refused", "replay", "record_result"}   # harness ops that count (truth: "harness: reset/check/...")
AGENT_ROLES = ("patient_agent", "clinician_agent")
CLINICIAN_ROLES = ("clinician",)          # who may still act in a blocked episode
# job ids that are a trend review (data: cases/scenario_data.toml [claims] trend_review_jobs)
TREND_REVIEW_JOBS = frozenset(_toml.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "cases", "scenario_data.toml"), "rb")).get("claims", {}).get("trend_review_jobs", []))
PATIENT_SIDE = ("patient", "patient_agent", "guardian")   # every patient-side reader: the patient, grant holders, card agents
SPECIALTY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "specialty")


def held_kinds(directory=None):
    """Result kinds held for discussion: specialty pack data only (packs/specialty/*.toml, held_result_kinds)."""
    import tomllib
    d = directory or SPECIALTY_DIR
    out = set()
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".toml"):
            with open(os.path.join(d, f), "rb") as fh:
                out |= set(tomllib.load(fh).get("held_result_kinds", []))
    return out


class Blocked(Exception):
    pass


def ts_key(kind):
    """forms uses 'timestamp'; orders used 'ts' and moves to 'timestamp' in round 8. Read from the live code."""
    if kind == "forms":
        return "timestamp"
    import inspect
    return "ts" if '"ts"' in inspect.getsource(loader.orders().OrdersEnv.step) else "timestamp"


def _jsonable(x):
    return json.loads(json.dumps(x, default=str, ensure_ascii=False))


class Episode:
    def __init__(self, kind, case, episode_id, patient):
        self.kind, self.case, self.episode_id, self.patient = kind, case, episode_id, patient
        self.blocks = []                    # locale blocks raised at open
        self.log = []                       # authoritative append-only event log, owned by the harness

    def env(self, actor, role, discipline=None, scope=()):
        mod = loader.forms() if self.kind == "forms" else loader.orders()
        e = mod.FormEnv() if self.kind == "forms" else mod.OrdersEnv()
        e.reset(self.case, actor, role, self.episode_id, discipline, scope)
        return e


class Handle:
    """What an actor holds. Bound to one actor, one role and one patient. Only observe and step."""

    def __init__(self, h, actor, role, patient, discipline=None, scope=()):
        self._h, self.actor, self.role, self.patient = h, actor, role, patient
        self.discipline, self.scope = discipline, tuple(scope)

    def observe(self, episode_id, *a, note=None):
        return self._h._call(self, episode_id, "observe", list(a), note=note)

    def step(self, episode_id, action, note=None):
        """note: {"claim": CL-id, "reason": text} or a reason string; claim omitted -> the scripted actor's own."""
        return self._h._call(self, episode_id, "step", [action], note=note)

    def call(self, episode_id, method, *a):
        """Any other method name (reset, replay, check, export ...) is attempted and refused."""
        return self._h._call(self, episode_id, method, list(a))


class Harness:
    NOTE_HOOK = None      # tests only: callable(record) -> reason text for a scripted actor's note, or None
    def __init__(self, scenario_id, seed, start="1937-03-01T08:00", pack="au", language="en"):
        self.scenario_id, self.seed, self.pack, self.language = scenario_id, seed, pack, locales.lang_code(language)
        self.rng = random.Random(seed)
        self.clock = datetime.datetime.fromisoformat(start)      # fixture clock: never moved by the seed
        self.order_seed, self.independent = None, {}
        self.trace, self.episodes, self.records, self.artifacts = [], {}, {}, []
        self.person_grants = {}
        self.patient_cards = {}      # patient -> card a clinician read for this episode (cards grant_state source)
        self.leaks, self.now, self._adv = [], None, False
        self.held = {}                      # record id -> {"patient", "open"}: results held for discussion
        self._emit("meta", scenario=scenario_id, seed=seed, start=self.clock.isoformat(timespec="minutes"),
                   pack=pack, language=language)

    # ---- trace ----
    def _emit(self, kind, **f):
        from . import notes
        if kind == "endware" or (kind == "harness" and f.get("op") in COUNTED_OPS):
            if "sensitive_step" not in f:   # the environment decides: inputs/results name a sensitive item or its event
                eps = [f["episode"]] if f.get("episode") in self.episodes else \
                      [r.get("episode") for r in self.trace if r.get("op") == "export" and r.get("episode") in self.episodes][-1:]
                refs = set().union(*[self.sensitive_refs(e) for e in eps]) if eps else set()
                blob = json.dumps(_jsonable(f), default=str)
                f["sensitive_step"] = bool(refs) and (kind == "endware" or (f.get("op") == "export" and any("#" in x for x in refs)) or any(f'"{x}"' in blob or ("#" in x and x in blob) for x in refs))
            if "note" not in f:
                f["note"] = notes.scripted_note(dict(kind=kind, **f))      # the harness actor's own note
        rec = _jsonable(dict(seq=len(self.trace), kind=kind, **f))
        self.trace.append(rec)
        return rec

    def tick(self, minutes=1):
        self.clock += datetime.timedelta(minutes=minutes)
        return self.clock.isoformat(timespec="minutes")

    def trace_jsonl(self):
        return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in self.trace)

    def digest(self):
        return hashlib.sha256(self.trace_jsonl().encode()).hexdigest()

    # ---- harness-only operations ----
    def open_episode(self, kind, case, episode_id, patient, needs=(), audit=False):
        """Opens an episode (truth: "harness: reset"). The locale layer runs here, before any question is
        shown: missing pack (if the episode leads to endware wording, needs 'pack'), missing patient
        language, missing decision-maker term (needs 'legal_term'). A blocked episode opens in 1 call and ends."""
        ep = Episode(kind, case, episode_id, patient)
        ep.blocks = locales.open_blocks(self.pack, self.language, needs)
        env = ep.env("harness", "clinician", "harness")
        if hasattr(env, "open_episode"):     # forms (in progress): synthetic flag set only by the harness, first event
            env.open_episode(True, self.clock.isoformat(timespec="minutes"))
            ep.log.extend(env.log)
        self.episodes[episode_id] = ep
        self._emit("harness", op="open", episode=episode_id, env=kind, patient=patient,
                   case=os.path.basename(case) if isinstance(case, str) else case.get("form_id") or case.get("list_id"),
                   blocks=[{"block": b, "line": locales.line(b, language=self.language, **{"locale pack": self.pack})}
                           for b in ep.blocks], **({"audit": True} if audit else {}))
        return episode_id

    def try_export_nonsynthetic(self, kind, case, patient):
        """Harness-only wrong move: build a scratch episode whose synthetic flag is false (the data itself stays
        synthetic) and attempt an export. It must be refused with RF-EXPORT-REAL. Logged as one planted call,
        so it is never counted in the idiot index; the scratch episode is never added to the run."""
        self._adv = False                    # this method logs its own planted call
        scratch_id = "SCRATCH-NONSYNTH-" + str(len(self.trace))
        ep = Episode(kind, case, scratch_id, patient)
        env = ep.env("harness", "clinician", "harness")
        reason = None
        if hasattr(env, "open_episode") and hasattr(env, "export"):
            env.open_episode(False, self.clock.isoformat(timespec="minutes"))
            try:
                env.export()
                reason = None                                  # accepted: a failure the scorer will catch
            except Exception as e:                             # forms refuses by its own synthetic flag
                reason = str(e)
        else:
            reason = self._line("RF-EXPORT-REAL")               # orders has no synthetic flag yet: stack refuses
        r = {"accepted": reason is None, "reason": reason or "", "by": "middleware" if hasattr(env, "export") else "harness"}
        self._emit(COUNTED, actor="harness", role="harness", discipline=None, patient=patient, episode=scratch_id,
                   method="export", args=[{"synthetic": False}], adversarial=True, accepted=r["accepted"], response=r,
                   note={"claim": "CL-EXPORTED" if r["accepted"] else "CL-REFUSED", "reason": ""})
        return r

    def blocked(self, episode_id):
        return list(self.episodes[episode_id].blocks)

    def cards_grant(self, h, episode_id, card_path, person):
        """A clinician records a person's access from the record: the person's cards grant (scenario data maps person
        id -> grant id) must be current by cards' own grant_state at scenario time, on the card for this episode.
        Counted as one 'grant' step. Nothing is written to the card."""
        cards = loader.cards()
        rec = dict(actor=h.actor, role=h.role, discipline=h.discipline, patient=h.patient, episode=episode_id,
                   method="cards_grant", args=[{"type": "grant", "person": person}])
        gid = PERSON_GRANTS.get(person)
        refuse = {"accepted": False, "reason": self._line("RF-NOT-YOURS"), "by": "harness"}
        if h.role not in CLINICIAN_ROLES or gid is None:
            return self._out(h, rec, refuse)
        card = cards.load(open(card_path, encoding="utf-8").read())
        if card["header"]["episode_id"] == episode_id:
            self.patient_cards[h.patient] = card
        g = card["grants"].get(gid) or {}
        if card["header"]["episode_id"] != episode_id or not g.get("rel") or \
                cards.grant_state(card, gid, self.clock.date().isoformat()) != "current":
            return self._out(h, rec, refuse)
        self.person_grants[(h.patient, person)] = {"card": card, "grant_id": gid, "rel": g["rel"]}
        return self._out(h, rec, {"accepted": True, "rel": g["rel"]})

    def _person_access(self, h):
        """A person acting for a patient (guardian): (state, end date) from cards' grant_state on the scenario clock,
        read live on every call. Never the box clock, never a role name on the request."""
        pg = self.person_grants.get((h.patient, h.actor))
        card = pg["card"] if pg else self.patient_cards.get(h.patient)
        gid = pg["grant_id"] if pg else PERSON_GRANTS.get(h.actor)
        if card is None or gid not in card["grants"] or not card["grants"][gid].get("rel"):
            return "none", None
        now = self.clock.date().isoformat()
        st = loader.cards().grant_state(card, gid, now)
        ends = [e["at"] for e in card["grant_events"] if e["grant_id"] == gid and e["event"] == st and e["at"] <= now]
        return st, (ends[-1] if ends else None)

    @staticmethod
    def _line_or_unsigned(line_id):
        """Signed text by id, or no text at all while the row is unsigned (never invented)."""
        m = loader.forms()._deps["messages"]
        return m.msg(line_id) if line_id in m.LINES else ""

    def session(self, actor, role, patient, discipline=None, scope=()):
        self._emit("harness", op="session", actor=actor, role=role, patient=patient, discipline=discipline,
                   scope=list(scope))
        return Handle(self, actor, role, patient, discipline, scope)

    def record(self, actor, record_id, patient, field, text):
        """A clinical record entered by a clinician (result, medicine, plan). Records reach an artifact only
        after an orders tick cites them as evidence (the orders gate checks the id against its registry)."""
        self.records[record_id] = dict(actor=actor, patient=patient, field=field, text=text)
        return self._emit("record", actor=actor, record=record_id, patient=patient, field=field, text=text,
                          ts=self.tick(0))

    def record_result(self, actor, record_id, patient, label, t, value, unit, role="clinician", kind=None):
        """Harness call that records a lab result (counted). It reaches a figure only once an orders tick cites
        its record id as evidence. In a blocked episode only a clinician may record (interpreter used)."""
        blocks = [b for ep in self.episodes.values() if ep.patient == patient for b in ep.blocks]
        if blocks and role not in CLINICIAN_ROLES:
            r = {"accepted": False, "block": blocks[0], "by": "locale",
                 "reason": locales.line(blocks[0], language=self.language, **{"locale pack": self.pack})}
            adv, self._adv = self._adv, False
            from . import notes
            rec = dict(actor=actor, role=role, discipline=None, patient=patient, episode=None, method="record_result",
                       args=[{"record": record_id}], accepted=False, response=r, sensitive_step=False)
            if adv:
                rec["adversarial"] = True
            rec["note"] = notes.scripted_note(dict(rec, kind=COUNTED))
            self._emit(COUNTED, **rec)
            return r
        self.records[record_id] = dict(actor=actor, patient=patient, field="result", text=f"{label}|{t}|{value}|{unit}",
                                       value=value)
        rec = self._emit("harness", op="record_result", actor=actor, record=record_id, patient=patient,
                         label=label, t=t, value=value, unit=unit, **({"result_kind": kind} if kind else {}))
        if kind is not None and kind in held_kinds():
            self._hold(record_id, patient)
        return rec

    # ---- held-result gate (one generic gate for every patient-side view) ----
    def _hold(self, record_id, patient):
        self.held[record_id] = {"patient": patient, "open": True}
        self._emit("harness", op="clinician_queue", record=record_id, line_id="CQ-RESULT-TO-DISCUSS",
                   text=self._line_fill("CQ-RESULT-TO-DISCUSS", event_id=record_id))

    def held_open(self, patient):
        return sorted(r for r, x in self.held.items() if x["open"] and x["patient"] == patient)

    def _close_held(self, h, record_id):
        """The existing queue-close call (step close_sameday) closes CQ-RESULT-TO-DISCUSS; only a clinician
        acting in person may. Anyone else is refused with RF-RESULT-HELD and nothing changes."""
        if h.role not in CLINICIAN_ROLES:
            return {"accepted": False, "by": "harness", "line_id": "RF-RESULT-HELD", "reason": self._line("RF-RESULT-HELD")}
        self.held[record_id]["open"] = False
        self._emit("harness", op="clinician_queue_closed", record=record_id, line_id="CQ-RESULT-TO-DISCUSS", actor=h.actor)
        # the clinician named in CL-CLOSED is the logged-in session, never a name sent in the request
        return {"accepted": True, "closed": record_id, "queue": "CQ-RESULT-TO-DISCUSS", "clinician": h.actor}

    def _held_strings(self, patient):
        out = []
        for rid in self.held_open(patient):
            r = self.records.get(rid, {})
            out += [rid, r.get("text", "")] + ([str(r["value"])] if str(r.get("value", "")).strip() else [])
        return [x for x in out if x]

    def declined_rows(self, patient):
        """Questions the patient declined (last event a decline), as letters' --declined rows: item, section (data:
        scenario_data [letter_sections]), safety, sensitive (stack sidecar), question, question_plain (the form text).
        'lines' is added per letter by the caller from its own line sources."""
        from .adapter import sensitive_ids
        secs = _toml.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases",
                                            "scenario_data.toml"), "rb")).get("letter_sections", {})
        out = []
        for ep in self.episodes.values():
            if ep.patient != patient or ep.kind != "forms":
                continue
            last = {}
            for e in ep.log:
                if e.get("type") in ("answer", "decline"):
                    last[e["question_id"]] = e["type"]
            env, sens = self._replayed(ep), sensitive_ids(ep.case) if isinstance(ep.case, str) else set()
            for q, t in last.items():
                if t == "decline" and q in secs:
                    txt = env.q[q]["text"]
                    out.append({"item": q, "section": secs[q], "safety": bool(env.q[q].get("safety_critical")),
                                "sensitive": q in sens, "question": txt, "question_plain": txt})
        return out

    def declined_sensitive(self, patient):
        """(question ids, question texts, question numbers) of sensitive questions the patient declined (last event a decline)."""
        ids, texts, nums = set(), set(), set()
        for ep in self.episodes.values():
            if ep.patient != patient or ep.kind != "forms":
                continue
            refs = self.sensitive_refs(ep.episode_id)
            last = {}
            for e in ep.log:
                if e.get("type") in ("answer", "decline"):
                    last[e["question_id"]] = e["type"]
            env = self._replayed(ep)
            for q, t in last.items():
                if t == "decline" and q in refs:
                    ids.add(q); texts.add(env.q[q]["text"]); nums.add(list(env.q).index(q) + 1)
        return ids, texts, nums

    def gate_grant_holder(self, patient, obj):
        """Grant holders and card agents see nothing derived from a declined sensitive question: no key, line,
        count or marker (the before-procedure line included)."""
        ids, texts, nums = self.declined_sensitive(patient)
        if not ids:
            return obj
        num = re.compile(r"\bquestion (?:%s)\b" % "|".join(str(n) for n in sorted(nums)))
        heads = [h for h in (locales.line(l).split("[")[0] for l in ("PV-BEFORE-PROC", "PV-DECLINED")) if h]
        bad = list(ids) + [t.rstrip("?") for t in texts]

        def hit(v):
            return isinstance(v, str) and (any(b in v for b in bad) or any(v.startswith(x) for x in heads)
                                           or num.search(v) is not None)

        def walk(v):
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items() if k not in ids and not hit(x)}
            if isinstance(v, list):
                return [walk(x) for x in v if not hit(x)]
            return v
        return walk(obj)

    def gate_view(self, patient, obj):
        """Patient-side copy of obj: every string naming a held, undiscussed result (its id, record text or raw
        value) becomes PV-RESULT-WAITING. Clinician views never pass through here."""
        bad = self._held_strings(patient)
        if not bad:
            return obj
        wait = self._line("PV-RESULT-WAITING")

        def walk(v):
            if isinstance(v, str):
                return wait if any(b in v for b in bad) else v
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x) for x in v]
            return v
        out = walk(obj)
        return dict(out, result_waiting=wait) if isinstance(out, dict) else out

    def visible_records(self, patient, patient_side):
        recs = {k: v for k, v in self.records.items() if v["patient"] == patient}
        if patient_side:
            recs = {k: v for k, v in recs.items() if k not in self.held_open(patient)}
        return recs

    def _line_fill(self, line_id, **f):
        m = loader.forms()._deps["messages"]
        return m.msg(line_id, **f) if line_id in m.LINES else "ERR:" + line_id.lower()

    def note(self, actor, record_id, patient, field, text, line):
        """A clinician note line from the scenario's synthetic notes file, logged before it can reach a letter."""
        self.records[record_id] = dict(actor=actor, patient=patient, field=field, text=text, note_line=line)
        return self._emit("record", actor=actor, record=record_id, patient=patient, field=field, text=text,
                          note_line=line)

    def set_now(self, now):
        self.now = now
        self._emit("harness", op="clock", now=now)

    def _replayed(self, ep, actor="harness", role="clinician", discipline="harness", scope=()):
        e = ep.env(actor, role, discipline, scope)
        if ep.kind == "forms":
            e.replay(ep.log)
        else:
            e.replay(ep.log, self.now)
        return e

    def check(self, episode_id, audit=False):
        """audit=True: a read by the scorer, written to the trace but not counted."""
        ep = self.episodes[episode_id]
        e = self._replayed(ep)
        c = e.check() if ep.kind == "forms" else e.check(self.now)
        self._emit("harness", op="check", episode=episode_id, result=c, **({"audit": True} if audit else {}))
        return c

    def export_bundle(self, episode_id, audit=False, patient_side=False):
        """One harness export (counted) plus what the adapter needs to stay a pure transform: the case items,
        the records cited by ticks, which events were recorded with an interpreter, the pack and the language."""
        ep = self.episodes[episode_id]
        blocked = list(ep.blocks)
        x = None if blocked else self.export(episode_id, audit=audit)
        if blocked:
            self._emit("harness", op="export_refused", episode=episode_id, blocks=blocked, audit=audit)   # counted (truth path)
        env = self._replayed(ep)
        items = ([dict(q) for q in env.schema["question"]] if ep.kind == "forms" else [dict(j) for j in env.lst["job"]])
        interp = sorted(i for r in self.calls() if r.get("episode") == episode_id and r.get("interpreter_used")
                        for i in r.get("events", []))
        return {"episode_id": episode_id, "kind": ep.kind, "patient": ep.patient, "blocks": blocked, "export": x,
                "items": items, "records": self.visible_records(ep.patient, patient_side),
                "interpreter_events": interp, "pack": self.pack, "language": self.language,
                "held": self.held_open(ep.patient) if patient_side else [],
                "case": ep.case if isinstance(ep.case, str) else None}

    def peek(self, episode_id):
        """Scorer read: rebuilds state from the log without writing to the trace."""
        ep = self.episodes[episode_id]
        e = self._replayed(ep)
        return e.check() if ep.kind == "forms" else e.check(self.now)

    @property
    def question_texts(self):
        """{question id: plain wording} for every forms episode (scorer read; nothing written to the trace)."""
        out = {}
        for ep in self.episodes.values():
            if ep.kind == "forms":
                out.update({i: q["text"] for i, q in self._replayed(ep).q.items()})
        return out

    def patient_view(self, episode_id):
        ep = self.episodes[episode_id]
        if ep.blocks:                        # blocked: only the safety alert lines show (a block never stops a safety alert)
            full = self._replayed(ep).patient_view()
            heads = [locales.line(l).split("[")[0] for l in ("PV-SAMEDAY", "PV-BEFORE-PROC")]
            keep = {}
            def walk(v):
                if isinstance(v, str):
                    return v if any(hd and v.startswith(hd) for hd in heads) else None
                if isinstance(v, dict):
                    d = {k: walk(x) for k, x in v.items()}
                    return {k: x for k, x in d.items() if x not in (None, {}, [])}
                if isinstance(v, list):
                    return [x for x in (walk(y) for y in v) if x not in (None, {}, [])]
                return None
            keep = walk(full) or {}
            self._emit("harness", op="patient_view", episode=episode_id, result=keep, hidden=list(ep.blocks))
            return keep
        v = self.gate_view(ep.patient, self._replayed(ep).patient_view())
        self._emit("harness", op="patient_view", episode=episode_id, result=v)
        return v

    def export(self, episode_id, audit=False):
        """Harness-only export. forms has export(); orders has none yet (gap), so its check stands in.
        A blocked episode is never exported: nothing goes to letters or figures."""
        ep = self.episodes[episode_id]
        if ep.blocks:
            self._emit("harness", op="export_refused", episode=episode_id, blocks=list(ep.blocks))
            raise Blocked(ep.blocks[0])
        e = self._replayed(ep)
        x = e.export() if hasattr(e, "export") else dict(e.check(self.now), log=list(ep.log))
        if "log" not in x:
            x = dict(x, log=list(ep.log))
        self._emit("harness", op="export", episode=episode_id, audit=audit)   # audit: same export call, other episode
        return x

    def ordered(self, group, fns):
        """Seeded reordering hook. Only steps the answer file marks independent (truth 'independent_steps':
        {group: [...]}) may be shuffled, and only when an order seed is set. Generated ids and timestamps may
        change with the seed; the fixture clock and due times never do. The order used is logged."""
        order = list(range(len(fns)))
        if self.order_seed is not None and group in self.independent:
            random.Random(f"{self.order_seed}:{self.scenario_id}:{group}").shuffle(order)
        self._emit("harness", op="order", group=group, order=order, seed=self.order_seed,
                   independent=group in self.independent)
        return [fns[i]() for i in order]

    def mark_adversarial(self):
        """The next actor call is a planted bad action; it must be refused."""
        self._adv = True

    def block(self, block_id, **f):
        """End the trace with a block (no wording fallback). Emitted by id while the line is DRAFT."""
        self._emit("block", block=block_id, **f)
        return {"tool": "block", "block": block_id, "all": f.get("all") or [block_id], "exit": 0, "refs": [], "path": None}

    # ---- actor calls ----
    def _call(self, h, episode_id, method, args, note=None):
        ep = self.episodes.get(episode_id)
        rec = dict(actor=h.actor, role=h.role, discipline=h.discipline, patient=h.patient, episode=episode_id,
                   method=method, args=args)
        rec["_note"] = note
        if ep is not None and h.role == "guardian":
            st, end = self._person_access(h)
            if st in ("revoked", "expired"):      # a grant holder's grant ended: RF-GRANT-ENDED (pending signing)
                return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "RF-GRANT-ENDED", "ended": end,
                                          "reason": self._line_or_unsigned("RF-GRANT-ENDED")})
            if st != "current":
                return self._out(h, rec, {"accepted": False, "reason": self._line("RF-NOT-YOURS"), "by": "harness"})
        if ep is None or ep.patient != h.patient:
            # harness binding: a handle reaches only its own patient's episodes, same line either way
            return self._out(h, rec, {"accepted": False, "reason": self._line("RF-NOT-YOURS"), "by": "harness"})
        t0 = args[0].get("type") if method == "step" and args and isinstance(args[0], dict) else None
        if method == "observe" and args and isinstance(args[0], dict) and args[0].get("record") in self.held:
            rid = args[0]["record"]           # a request for one held result's raw value
            if self.held[rid]["open"] and h.role in PATIENT_SIDE:
                return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "PV-RESULT-WAITING",
                                          "reason": self._line("PV-RESULT-WAITING")})
            return self._out(h, rec, {"accepted": True, "record": rid, "value": (self.records.get(rid) or {}).get("text")})
        if t0 == "answer" and h.role == "patient_agent" and ep.kind == "forms" and self.peek(episode_id).get("submissions"):
            cur = self.peek(episode_id).get("answers", {})
            q = args[0].get("question_id")
            if q in cur and cur[q] != args[0].get("value"):   # resend unchanged: fine; any change: refused
                return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "RF-AGENT-ANSWER-CHANGED",
                                          "reason": self._line_or_unsigned("RF-AGENT-ANSWER-CHANGED")})
        if t0 == "close_sameday" and args[0].get("record") in self.held:
            return self._out(h, rec, self._close_held(h, args[0]["record"]))
        if t0 == "submit" and self.held_open(ep.patient):
            # CQ-RESULT-TO-DISCUSS open: the episode cannot pass until a clinician records the discussion
            return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "RF-RESULT-HELD",
                                      "reason": self._line("RF-RESULT-HELD")})
        if method == "step" and h.role in AGENT_ROLES and isinstance(args[0], dict) and args[0].get("type") in ("grant", "revoke"):
            return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "RF-AGENT-REVOKE",
                                      "reason": locales.line("RF-AGENT-REVOKE")})   # PENDING WORDING
        if ep.blocks:
            # locale layer, blocked episode: the patient and the patient's agent are refused; a clinician may
            # still record answers in their own session (interpreter used), except on_behalf answers when no
            # signed decision-maker term exists. Nothing goes to letters or figures (export refuses).
            on_behalf = method == "step" and isinstance(args[0], dict) and "on_behalf" in args[0]
            b = ("BK-NO-LEGAL-TERM" if on_behalf and "BK-NO-LEGAL-TERM" in ep.blocks
                 else ("BK-NO-LANGUAGE" if "BK-NO-LANGUAGE" in ep.blocks else ep.blocks[0])
                 if h.role not in CLINICIAN_ROLES else None)
            if b:
                return self._out(h, rec, {"accepted": False, "block": b, "by": "locale",
                                          "reason": locales.line(b, language=self.language, **{"locale pack": self.pack})})
            rec.update(interpreter_used=True, blocked_for_output=list(ep.blocks))
            mod = loader.forms() if ep.kind == "forms" else loader.orders()
            t = args[0].get("type") if method == "step" and isinstance(args[0], dict) else None
            if t and "interpreter" in getattr(mod, "OPTIONAL", {}).get(t, set()):
                args = [dict(args[0], interpreter=True)]     # middleware field, where it exists (round 8)
        try:
            env = self._replayed(ep, h.actor, h.role, h.discipline, h.scope)
        except Exception as e:               # the env refuses the session itself (e.g. an unregistered role)
            if type(e).__name__ != "Invalid":
                raise
            return self._out(h, rec, {"accepted": False, "reason": str(e), "by": "middleware"})
        before = len(env.log)
        if method == "step" and isinstance(args[0], dict) and args[0].get("type") == "review":
            refs0 = self.sensitive_refs(episode_id)      # a review that closes a sensitive item's entry is sensitive
            pre = " ".join(self.peek(episode_id).get("clinician_queue", []) or [])
            rec["_closed_sensitive"] = any(x in pre for x in refs0 if "#" not in x) or any(
                f"event {x.rsplit('#', 1)[1]}" in pre for x in refs0 if "#" in x)
        can_escalate = method == "step" and isinstance(args[0], dict) and args[0].get("type") in ("answer", "decline", "submit")
        q0 = self._alerts(episode_id) if can_escalate else set()
        if method == "step" and isinstance(args[0], dict):
            a = dict(args[0])
            a.setdefault(ts_key(ep.kind), self.tick())
            args = [a]
            rec["args"] = args
        if hasattr(env, "call"):
            r = env.call(method, *args)
        elif method in ("observe", "step"):
            r = getattr(env, method)(*args)       # orders: no call() yet (gap G3); harness enforces the split
        else:
            r = {"accepted": False, "reason": self._line("RF-HARNESS-ONLY"), "by": "harness"}
        if not isinstance(r, dict):
            r = {"accepted": True, "value": r}
        new = env.log[before:]
        if method == "step" and r.get("accepted") and h.role == "patient" and locales.signed("PV-ANS-CHANGED"):
            # the patient changed an answer their agent gave: thank them (only once the line is signed)
            for e in new:
                prev = [x for x in ep.log if x.get("question_id") == e.get("question_id") and x["type"] == "answer"]
                if e["type"] == "answer" and prev and prev[-1].get("role") == "patient_agent" and prev[-1]["value"] != e["value"]:
                    r = dict(r, message=locales.line("PV-ANS-CHANGED"))
        if method == "step" and r.get("accepted"):
            ep.log.extend(new)
            rec["events"] = [len(ep.log) - len(new) + i for i in range(len(new))]
            rec["queue_after"] = list(self.peek(episode_id).get("clinician_queue", []) or [])   # env record, for the scorer
            if t0 == "tick" and h.role in CLINICIAN_ROLES and args[0].get("id") in TREND_REVIEW_JOBS:
                rec["trend_closed"] = True        # Physician 12:30: a clinician closing the trend review, every scenario
                if not self.peek(episode_id).get("open"):
                    rec["all_done"] = "ST-DONE"   # and it finished every job: env result closed:ST-DONE (S14)   # in person, closes the last open job: CL-TREND-CLOSED (pending signing)
            if can_escalate and (self._alerts(episode_id) - q0 or self._would_escalate(ep, env, new)):
                rec["escalated"] = True
            out = self._out(h, rec, r)
            self._escalate_sensitive(ep, env, new, rec["events"])
            if any(e["type"] == "submit" for e in new):      # queue snapshot after every submit
                c = self.peek(episode_id)
                self._emit("harness", op="after_submit", episode=episode_id, final=bool(r.get("final")),
                           queue=list(c.get("clinician_queue", [])), answers=c.get("answers", {}))
            return out
        return self._out(h, rec, r)

    ESCALATION_LINES = ("CQ-SAMEDAY-ALERT", "CQ-BEFORE-PROC", "CQ-THREE-FAILS")

    def _alerts(self, episode_id):
        """Queue entries that are escalations (signed CQ lines, matched by their fixed text before any slot)."""
        try:
            q = self.peek(episode_id).get("clinician_queue", []) or []
        except Exception:
            return set()
        heads = [locales.line(l).split("[")[0] for l in self.ESCALATION_LINES]
        return {x for x in q if any(hd and x.startswith(hd) for hd in heads)}

    def _would_escalate(self, ep, env, new):
        if ep.kind != "forms" or not isinstance(ep.case, str):
            return False
        from .adapter import sensitive_ids
        sens = sensitive_ids(ep.case)
        return any(e["type"] == "answer" and (q := env.q.get(e.get("question_id"))) and q["id"] in sens
                   and q["safety_critical"] and e["value"] == q["alert_answer"] for e in new)

    def sensitive_refs(self, episode_id):
        """Sensitive question ids of an episode and event ids of their answers. The environment decides, not the agent:
        a forms question with sensitive=true, or (gap) the stack sidecar."""
        ep = self.episodes.get(episode_id)
        if not ep or ep.kind != "forms" or not isinstance(ep.case, str):
            return set()
        from .adapter import sensitive_ids
        sens = set(sensitive_ids(ep.case))
        try:
            env = self._replayed(ep, "SYNTH-harness", "clinician", None, ())
            sens |= {k for k, q in env.q.items() if q.get("sensitive")}
        except Exception:
            pass
        evs = {f"{episode_id}#{n}" for n, e in enumerate(ep.log) if e.get("question_id") in sens}
        return sens | evs

    def _escalate_sensitive(self, ep, env, new, idx):
        """A sensitive safety question answered with its alert answer goes to the clinician queue the same day
        (item number plus text). forms has no sensitive field (gap), so the stack sidecar names the items."""
        if ep.kind != "forms" or not isinstance(ep.case, str):
            return
        from .adapter import sensitive_ids
        sens = sensitive_ids(ep.case)
        ids = list(env.q)
        for e, n in zip(new, idx):
            q = env.q.get(e.get("question_id"))
            if e["type"] == "answer" and q and q["id"] in sens and q["safety_critical"] and e["value"] == q["alert_answer"]:
                self._emit("harness", op="clinician_queue", episode=ep.episode_id, item=ids.index(q["id"]) + 1,
                           text=q["text"], event=f"{ep.episode_id}#{n}", date=e["timestamp"][:10])

    def _out(self, h, rec, r):
        r = _jsonable(r)
        if h.role in PATIENT_SIDE:
            r = self.gate_view(h.patient, r)
        if h.role in PATIENT_SIDE and h.role != "patient":
            r = self.gate_grant_holder(h.patient, r)
        accepted = r.get("accepted", True) if isinstance(r, dict) else True
        seen = set(SYNTH_ID.findall(json.dumps(r)))
        own = {h.patient} | {e for e, ep in self.episodes.items() if ep.patient == h.patient}
        foreign = sorted(i for i in seen if i in self._all_ids() and i not in own)
        if foreign:
            self.leaks.append(dict(actor=h.actor, ids=foreign))
        if self._adv:
            rec["adversarial"], self._adv = True, False
        a0 = (rec.get("args") or [{}])[0]
        if accepted and isinstance(a0, dict) and a0.get("type") == "submit":
            kinds = [((t.get("args") or [{}])[0] or {}).get("type") for t in self.trace
                     if t.get("kind") == COUNTED and t.get("accepted") and t.get("episode") == rec.get("episode")
                     and isinstance((t.get("args") or [{}])[0], dict)]
            last = max((n for n, k in enumerate(kinds) if k == "submit"), default=None)
            if last is not None and "review" in kinds[last:]:
                rec["resubmit"] = True   # a submit after a clinician review of a failed form (ruling 11:52)
                # the resubmit re-runs the full check over every answer, so it touches any sensitive item the form holds
                rec["_closed_sensitive"] = rec.get("_closed_sensitive") or bool(self.sensitive_refs(rec["episode"]))
        from . import notes
        note = rec.pop("_note", None)
        if isinstance(note, str) or note is None:
            note = {"reason": note or ""}
        if Harness.NOTE_HOOK and not note.get("reason"):
            note["reason"] = Harness.NOTE_HOOK(dict(rec, accepted=accepted, response=r)) or ""
        full = dict(rec, kind=COUNTED, accepted=accepted, response=r)
        refs = self.sensitive_refs(rec["episode"]) if rec.get("episode") in self.episodes else set()
        blob = json.dumps(_jsonable([rec.get("args"), r, rec.get("events")]))
        ev = {f"{rec['episode']}#{n}" for n in rec.get("events") or []}
        rec["sensitive_step"] = bool(ev & refs or any(f'"{x}"' in blob or (("#" in x) and x in blob) for x in refs)
                                     or bool(rec.pop("_closed_sensitive", False)))
        rec["note"] = {"claim": note.get("claim") or notes.scripted_note(full)["claim"], "reason": note.get("reason", "")}
        self._emit(COUNTED, **rec, accepted=accepted, response=r)
        return r

    def _all_ids(self):
        return {ep.patient for ep in self.episodes.values()} | set(self.episodes)

    @staticmethod
    def _line(line_id):
        m = loader.forms()._deps["messages"]
        return m.msg(line_id) if line_id in m.LINES else "ERR:" + line_id.lower()

    # ---- derived facts used by endware ----
    def ticked_evidence(self, patient):
        """Record ids cited by accepted orders ticks for this patient, with the event that cited them."""
        out = {}
        for eid, ep in self.episodes.items():
            if ep.kind == "orders" and ep.patient == patient:
                for n, e in enumerate(ep.log):
                    if e["type"] == "tick":
                        out[e["evidence"]] = (eid, n)
        return out

    def calls(self):
        """Actor calls only (accepted or refused)."""
        return [r for r in self.trace if r["kind"] == COUNTED]

    def counted(self):
        """Calls counted by the idiot index: actor calls that are not planted probes, harness reset/check/
        export/replay, and endware builds (1 per letter, 1 per figure). The adapter transform is not a call."""
        return [r for r in self.trace if (r["kind"] == COUNTED and not r.get("adversarial"))
                or (r["kind"] == "harness" and r.get("op") in COUNTED_OPS and not r.get("audit"))
                or (r["kind"] == "endware" and not r.get("audit"))]

    def write(self, path):
        with open(path, "w") as f:
            f.write(self.trace_jsonl())
