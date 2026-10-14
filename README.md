# stack

Full-stack integration harness for the wetware clinical tools. Synthetic data only (`SYNTH-` ids, 1930s dates, invented people). Not a medical device.

- **Middleware:** `forms` (yes/no questionnaires) and `orders` (job checklists), loaded side by side from `/workspace` (read-only; see `stack/loader.py`).
- **Endware:** `letters` (notes → letter.md, run as its CLI) and `figures` (results paste → chart, run in its own venv through `env.Env`). `briefs`, `cards` and `bloc` are not clinical output tools and are not used.
- **Harness** (`stack/harness.py`): owns every episode log; actors get a handle with `observe` and `step` only; `reset`, `replay`, `check` and `export` are harness-only. Every call, accepted or refused, goes to a seeded JSONL trace.
- **Locale layer** (`stack/locales.py`): BK-NO-PACK, BK-NO-LANGUAGE and BK-NO-LEGAL-TERM raised when an episode opens. In a blocked episode the patient and the patient's agent are refused, a clinician may still record answers (interpreter used, except on_behalf answers when no legal term exists), the patient view is hidden and nothing goes to letters or figures.
- **Adapter** (`stack/adapter.py`): one finished, synthetic, check-passed, unblocked export → facts (status, answered_by, on_behalf, interpreter, sensitive, event id) → letters notes and a figures CSV. Pure transform. Status wording from `/workspace/wording/letters_status_lines_SIGNED.md`.
- **Scenarios** (`stack/scenarios.py`): 15 scripted, deterministic traces (agent behaviour only).
- **Scorer** (`stack/scorer.py`): reads `/workspace/stack_truth/<id>/truth.toml` and `patient_wording.md` (read-only). Missing either file → PENDING TRUTH (skip). Criteria: idiot index, zero accepted bad actions, outputs, safety items, must-refuse, citations, replay, leaks, consent (P-01 a/b/c), patient wording, locale.
- **Live mode** (`stack/live.py`): S05 and S07, 20 fixed seeds, needs `STACK_MODEL_API_KEY`; without it: WAITING ON KEY.

```bash
python3 -m pytest -q                      # unit tests (traces skip unless STACK_RUN_TRACES=1)
STACK_RUN_TRACES=1 python3 -m pytest -q   # also run and score every trace with truth files
python3 scripts/report.py                 # one table per loop
python3 scripts/mutate.py                 # mutation test of the locale-block guard
python3 scripts/build_s12_notes.py        # rebuild cases/S12.notes.txt from stack_truth
```
