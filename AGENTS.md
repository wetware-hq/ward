---
schema: wetware.agent.v1
resource: ward
version: 0.1.0
capabilities: [integration-harness, scenario-scoring, live-model-check]
inputs:
  siblings: {type: directory, env: WARD_SIBLINGS_DIR, constraint: "forms, orders, letters, figures clones; stack_truth/ and wording/ read-only"}
  truth: {type: toml, env: WARD_TRUTH, constraint: "signed answer files; read-only"}
  session: {type: object, fields: [actor, role, patient, discipline, scope]}
outputs:
  trace: {type: jsonl, constraint: "seeded; every call, accepted or refused"}
  score: {type: table, values: [PASS, FAIL, PENDING TRUTH, WAITING ON KEY]}
  endware: {type: [letter.md, csv], constraint: "only from a finished, synthetic, check-passed, unblocked export"}
---

# Agent contract

Normative rules for agents that operate or modify ward. Wording uses RFC 2119: **MUST**, **MUST NOT**, **SHOULD**. Not approved for real patient data.

## Data handling

1. All data **MUST** be synthetic: `SYNTH-` ids, 1930s dates, invented people.
2. If real patient data appears, the agent **MUST** stop, **MUST NOT** repeat or process it, and **MUST** tell the user to report a privacy incident.
3. `stack_truth/`, `wording/` and any held-out answer folders **MUST NOT** be written, and held-out folders **MUST NOT** be opened.

## Operating the environment

1. An actor **MUST** act only through its harness handle: `observe(episode_id, ...)` and `step(episode_id, action)`. `reset`, `replay`, `check` and `export` are harness-only.
2. A refusal is final for that action. The agent **MUST NOT** retry it under another role, actor, scope or wording.
3. In a locale-blocked episode (BK-NO-PACK, BK-NO-LANGUAGE, BK-NO-LEGAL-TERM) the agent **MUST NOT** try to reach letters or figures.
4. Live mode runs S05 and S07 only, seeds 9001-9020, model pinned in `ward/live_client.py`. The key **MUST** come from `WARD_MODEL_API_KEY` at send time and **MUST NOT** be printed, logged or written to a result. Scripted runs and `scripts/bar.sh` **MUST** run with no model key set.
5. A missing truth file **MUST** score PENDING TRUTH, and a missing key WAITING ON KEY; neither is a pass.

## Changing code

- `python3 -m pytest -q` **MUST** exit 0 before every commit; `scripts/bar.sh SIBLINGS` **MUST** exit 0 before a push.
- Changes to guards in `safety_functions.toml` **MUST** be followed by `python3 scripts/mutate.py`, which **MUST** kill every mutant, and a fresh `mutation.stamp`.
- The README Live-model status line **MUST** match the Physician-signed line in `STABILITY_BAR.md` word for word. An agent **MUST NOT** edit it to claim live sign-off.
- Scoring **MUST** stay deterministic code against signed truth files; it **MUST NOT** depend on a model's judgement.
- The adapter **MUST** stay a pure transform; status wording **MUST** come from the signed wording file.

## Out of scope

- Real patients, hosted services, clinical advice
- Writing answer files or signing wording
