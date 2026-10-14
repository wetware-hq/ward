"""The harness: owns every episode log, opens sessions, and is the only party that may reset, replay,
check or export. Actors (people and agents) get a Handle that exposes observe and step only.
Every call, accepted or refused, is written to the trace. No model is called anywhere."""
import datetime, hashlib, json, os, random, re
from . import loader, locales

SYNTH_ID = re.compile(r"SYNTH-[A-Za-z0-9-]+")
COUNTED = "call"          # trace kind of an actor call
COUNTED_OPS = {"open", "check", "export", "export_refused", "replay", "record_result"}   # harness ops that count (truth: "harness: reset/check/...")
AGENT_ROLES = ("patient_agent", "clinician_agent")
CLINICIAN_ROLES = ("clinician",)          # who may still act in a blocked episode


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
        self.scenario_id, self.seed, self.pack, self.language = scenario_id, seed, pack, language
        self.rng = random.Random(seed)
        self.clock = datetime.datetime.fromisoformat(start) + datetime.timedelta(minutes=self.rng.randrange(0, 30))
        self.trace, self.episodes, self.records, self.artifacts = [], {}, {}, []
        self.leaks, self.now, self._adv = [], None, False
        self._emit("meta", scenario=scenario_id, seed=seed, start=self.clock.isoformat(timespec="minutes"),
                   pack=pack, language=language)

    # ---- trace ----
    def _emit(self, kind, **f):
        from . import notes
        if "note" not in f and (kind == "endware" or (kind == "harness" and f.get("op") in COUNTED_OPS)):
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
    def open_episode(self, kind, case, episode_id, patient, needs=()):
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
                           for b in ep.blocks])
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
                   method="export", args=[{"synthetic": False}], adversarial=True, accepted=r["accepted"], response=r)
        return r

    def blocked(self, episode_id):
        return list(self.episodes[episode_id].blocks)

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

    def record_result(self, actor, record_id, patient, label, t, value, unit):
        """Harness call that records a lab result (counted). It reaches a figure only once an orders tick cites
        its record id as evidence."""
        self.records[record_id] = dict(actor=actor, patient=patient, field="result", text=f"{label}|{t}|{value}|{unit}")
        return self._emit("harness", op="record_result", actor=actor, record=record_id, patient=patient,
                          label=label, t=t, value=value, unit=unit)

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

    def export_bundle(self, episode_id):
        """One harness export (counted) plus what the adapter needs to stay a pure transform: the case items,
        the records cited by ticks, which events were recorded with an interpreter, the pack and the language."""
        ep = self.episodes[episode_id]
        blocked = list(ep.blocks)
        x = None if blocked else self.export(episode_id)
        if blocked:
            self._emit("harness", op="export_refused", episode=episode_id, blocks=blocked)   # counted (truth path)
        env = self._replayed(ep)
        items = ([dict(q) for q in env.schema["question"]] if ep.kind == "forms" else [dict(j) for j in env.lst["job"]])
        interp = sorted(i for r in self.calls() if r.get("episode") == episode_id and r.get("interpreter_used")
                        for i in r.get("events", []))
        return {"episode_id": episode_id, "kind": ep.kind, "patient": ep.patient, "blocks": blocked, "export": x,
                "items": items, "records": {k: v for k, v in self.records.items() if v["patient"] == ep.patient},
                "interpreter_events": interp, "pack": self.pack, "language": self.language,
                "case": ep.case if isinstance(ep.case, str) else None}

    def peek(self, episode_id):
        """Scorer read: rebuilds state from the log without writing to the trace."""
        ep = self.episodes[episode_id]
        e = self._replayed(ep)
        return e.check() if ep.kind == "forms" else e.check(self.now)

    def patient_view(self, episode_id):
        ep = self.episodes[episode_id]
        if ep.blocks:                        # hidden for a blocked episode
            self._emit("harness", op="patient_view", episode=episode_id, result={}, hidden=list(ep.blocks))
            return None
        v = self._replayed(ep).patient_view()
        self._emit("harness", op="patient_view", episode=episode_id, result=v)
        return v

    def export(self, episode_id):
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
        self._emit("harness", op="export", episode=episode_id)
        return x

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
        if ep is None or ep.patient != h.patient:
            # harness binding: a handle reaches only its own patient's episodes, same line either way
            return self._out(h, rec, {"accepted": False, "reason": self._line("RF-NOT-YOURS"), "by": "harness"})
        if method == "step" and h.role in AGENT_ROLES and isinstance(args[0], dict) and args[0].get("type") in ("grant", "revoke"):
            return self._out(h, rec, {"accepted": False, "by": "harness", "line_id": "RF-AGENT-REVOKE",
                                      "reason": locales.line("RF-AGENT-REVOKE")})   # PENDING WORDING
        if ep.blocks:
            # locale layer, blocked episode: the patient and the patient's agent are refused; a clinician may
            # still record answers in their own session (interpreter used), except on_behalf answers when no
            # signed decision-maker term exists. Nothing goes to letters or figures (export refuses).
            on_behalf = method == "step" and isinstance(args[0], dict) and "on_behalf" in args[0]
            b = ("BK-NO-LEGAL-TERM" if on_behalf and "BK-NO-LEGAL-TERM" in ep.blocks
                 else ep.blocks[0] if h.role not in CLINICIAN_ROLES else None)
            if b:
                return self._out(h, rec, {"accepted": False, "block": b, "by": "locale",
                                          "reason": locales.line(b, language=self.language, **{"locale pack": self.pack})})
            rec.update(interpreter_used=True, blocked_for_output=list(ep.blocks))
            mod = loader.forms() if ep.kind == "forms" else loader.orders()
            t = args[0].get("type") if method == "step" and isinstance(args[0], dict) else None
            if t and "interpreter" in getattr(mod, "OPTIONAL", {}).get(t, set()):
                args = [dict(args[0], interpreter=True)]     # middleware field, where it exists (round 8)
        env = self._replayed(ep, h.actor, h.role, h.discipline, h.scope)
        before = len(env.log)
        q0 = len(self.peek(episode_id).get("clinician_queue", []) or []) if method == "step" else 0
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
            q1 = len(self.peek(episode_id).get("clinician_queue", []) or [])
            if q1 > q0 or self._would_escalate(ep, env, new):
                rec["escalated"] = True
            out = self._out(h, rec, r)
            self._escalate_sensitive(ep, env, new, rec["events"])
            if any(e["type"] == "submit" for e in new):      # queue snapshot after every submit
                c = self.peek(episode_id)
                self._emit("harness", op="after_submit", episode=episode_id, final=bool(r.get("final")),
                           queue=list(c.get("clinician_queue", [])), answers=c.get("answers", {}))
            return out
        return self._out(h, rec, r)

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
        accepted = r.get("accepted", True) if isinstance(r, dict) else True
        seen = set(SYNTH_ID.findall(json.dumps(r)))
        own = {h.patient} | {e for e, ep in self.episodes.items() if ep.patient == h.patient}
        foreign = sorted(i for i in seen if i in self._all_ids() and i not in own)
        if foreign:
            self.leaks.append(dict(actor=h.actor, ids=foreign))
        if self._adv:
            rec["adversarial"], self._adv = True, False
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
        rec["sensitive_step"] = bool(ev & refs or any(f'"{x}"' in blob or (("#" in x) and x in blob) for x in refs))
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
                or r["kind"] == "endware"]

    def write(self, path):
        with open(path, "w") as f:
            f.write(self.trace_jsonl())
