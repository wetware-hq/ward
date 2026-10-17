# Stability bar extensions (ward checkout)

Entries here describe what an optional check proves and what it does **not** prove. They are not signed unless noted elsewhere.

## ward-evidence (`evidence/`)

**Proves:** internal integrity of one fleet run’s evidence — every recorded model call carries the parameters actually sent (with explicit nulls), the raw reply, and reasoning explicitly disabled; leaves are content-addressed and roll up to a Merkle root so tampering, reordering, or dropping a block is detected by `verify`.

**Does not prove:** any external anchoring or publication; that model outputs are true, safe, or clinically correct; or that consent was valid in the real world (only that export rules were applied against the repo’s withdrawn list).

## lab/tool compliance (`ward/compliance.py`, `data/compliance_prompts.toml`)

**Proves:** lab resource and tool decisions accept only structured `yes` / `no` / `abstain` model input (reasoning off, schema-constrained); abstain routes to a labelled human surface and is never coerced to deny; malformed replies fail the call.

**Does not prove:** that the model’s yes/no is correct, that humans act on abstain labels, or regulatory compliance outside this harness.

## jurisdiction scan (`jurisdiction_scan.toml`)

**Log (2026-10-17):** Squash merge `c8f6c457` permanently carries the Cursor Agent `Co-authored-by` trailer address (`cursoragent@cursor.com`) in git history. That address is a service/bot mailbox, not a person. History is deliberately not rewritten. The forward-only fix is an explicit cited allowlist in `data/commit_message_bot_allowlist.toml` used only when scanning commit messages; tracked file contents still fail on that address. Any other email in a commit message still fails.

**commit_base:** `d70b159` — only commits after this point are scanned; allowlisted bot addresses apply only to the email check in commit bodies.
