# ward

**Overview.** ward is the full-ward integration harness for the wetware clinical tools: it runs synthetic patients through forms and orders, then through letters and figures, and scores every step. Synthetic data only (`SYNTH-` ids, 1930s dates, invented people). Not a medical device.

---

## Clinical abstract

Each wetware tool is checked on its own. Clinical work is not done tool by tool: a questionnaire answer becomes a job on a checklist, then a line in a letter and a point on a chart. Mistakes hide in the hand-offs, for example an assistant's unconfirmed answer reaching a discharge letter, or a patient's sensitive answer appearing in a chart.

ward runs a whole simulated ward. Fifteen scripted scenarios (S01 to S15) play patients, clinicians and their AI assistants, including assistants that try to do things they should not. Every action, allowed or refused, is recorded. Each scenario is then marked against answer files a clinician signed: what had to be refused, what had to appear in the output, and what the patient must be told. When a patient's language or legal arrangements are not supported, the episode is blocked and nothing goes to letters or figures.

What ward is not: it does not treat anyone, give clinical advice or produce letters for real patients. A pass means the tools behaved as signed on invented patients, nothing more.

---

## Engineering specification

### Environment

| Setting | Read by | Meaning |
|---|---|---|
| `WARD_SIBLINGS_DIR` (older: `WARD_WORKSPACE`) | `ward/paths.py` | directory holding the sibling clones and read-only `stack_truth/`, `wording/` (default: parent of this checkout) |
| `WARD_TRUTH` | scorer | scenario answer files (default `$WARD_SIBLINGS_DIR/stack_truth`) |
| `WARD_FIGURES_PYTHON` | bar, endware | interpreter that can import figures' packages |
| `WARD_RUN_TRACES` | tests | `1` runs and scores every trace |
| `WARD_MODEL_API_KEY` | live only | model key; `scripts/bar.sh` unsets it, scripted runs never see it |
| `MUTATE_WORKERS` | mutation scripts | parallel workers |

### Components

- **Middleware:** `forms` (yes/no questionnaires) and `orders` (job checklists), loaded side by side from the siblings directory, `WARD_SIBLINGS_DIR` (default: the directory holding this checkout; read-only; see `ward/loader.py`).
- **Endware:** `letters` (notes → letter.md, run as its CLI) and `figures` (results paste → chart, run in its own venv through `env.Env`). `briefs`, `cards` and `bloc` are not clinical output tools and are not used.
- **Harness** (`ward/harness.py`): owns every episode log; actors get a handle with `observe` and `step` only; `reset`, `replay`, `check` and `export` are harness-only. Every call, accepted or refused, goes to a seeded JSONL trace.
- **Locale layer** (`ward/locales.py`): BK-NO-PACK, BK-NO-LANGUAGE and BK-NO-LEGAL-TERM raised when an episode opens. In a blocked episode the patient and the patient's agent are refused, a clinician may still record answers (interpreter used, except on_behalf answers when no legal term exists), the patient view is hidden and nothing goes to letters or figures.
- **Adapter** (`ward/adapter.py`): one finished, synthetic, check-passed, unblocked export → facts (status, answered_by, on_behalf, interpreter, sensitive, event id) → letters notes and a figures CSV. Pure transform. Status wording from `$WARD_SIBLINGS_DIR/wording/letters_status_lines_SIGNED.md`.
- **Scenarios** (`ward/scenarios.py`): 15 scripted, deterministic traces (agent behaviour only).
- **Scorer** (`ward/scorer.py`): reads `$WARD_SIBLINGS_DIR/stack_truth/<id>/truth.toml` (or `WARD_TRUTH`) and `patient_wording.md` (read-only). Missing either file → PENDING TRUTH (skip). Criteria: idiot index, zero accepted bad actions, outputs, safety items, must-refuse, citations, replay, leaks, consent (P-01 a/b/c), patient wording, locale.
- **Live mode** (`ward/live.py`): S05 and S07, 20 fixed seeds, needs `WARD_MODEL_API_KEY`; without it: WAITING ON KEY. Client: `ward/live_client.py` (OpenRouter), pinned `openai/gpt-4o-mini-2024-07-18`; a reply from any other model fails the run; the key never enters a record.

```bash
python3 -m pytest -q                      # unit tests (traces skip unless WARD_RUN_TRACES=1)
WARD_RUN_TRACES=1 python3 -m pytest -q   # also run and score every trace with truth files
python3 scripts/report.py                 # one table per loop
python3 scripts/mutate.py                 # mutation test of the locale-block guard
python3 scripts/build_s12_notes.py        # rebuild cases/S12.notes.txt from stack_truth
```

## Fresh-clone bar

`scripts/bar.sh SIBLINGS` runs the forms, orders, figures, letters, cards and ward prepush checks with every
setting they read (`scripts/bar.sh SIBLINGS --env` prints them without running anything). SIBLINGS holds the clones
and the read-only folders `stack_truth/`, `cards_truth/`, `cards_wording/` and `wording/`. With those set, letters
deselects none of its 6 `needs_signed` tests and cards none of its 38; unset, both prepush checks fail.

## Live-model status

S05 and S07 were checked with a scripted stand-in, not a real AI model. The scripted runs show the checks catch the mistakes those two scenarios are for. They don't show how a real model behaves. Those tests are still to come.

## Status

Not for use with real patients.
