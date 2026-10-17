# Stability bar extensions (ward checkout)

Entries here describe what an optional check proves and what it does **not** prove. They are not signed unless noted elsewhere.

## ward-evidence (`evidence/`)

**Proves:** internal integrity of one fleet run’s evidence — every recorded model call carries the parameters actually sent (with explicit nulls), the raw reply, and reasoning explicitly disabled; leaves are content-addressed and roll up to a Merkle root so tampering, reordering, or dropping a block is detected by `verify`.

**Does not prove:** any external anchoring or publication; that model outputs are true, safe, or clinically correct; or that consent was valid in the real world (only that export rules were applied against the repo’s withdrawn list).
