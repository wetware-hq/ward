# Migration note: hash-chained, Web3-compatible fleet traces

`ward/tracechain.py` makes a verifiable, EVM-anchorable Merkle chain the **native** form of every
fleet trace. This note says what changes, what to do with existing evidence, and how an on-chain
verifier would check a root. All data is synthetic; this is not approved for real patient data.

## What the chain gives you

* **Canonical JSONL** — one block per line, each line canonical JSON (sorted keys, no whitespace,
  ASCII). First line is the header (roots, proofs, public key, signature); each following line is a
  block.
* **Chain** — each block carries `prev` (previous block's digest for that seed), `index`, `seed`,
  the event `content` (inputs + outputs), a **salted** `content_digest`, and the `block_digest`.
* **Merkle roots** — one root per seed (`seed_roots`) and one `fleet_root` over all seeds. Every
  block carries an `proof` (inclusion proof to its `seed_root`); the header carries a `seed_proofs`
  entry per seed (inclusion proof to the `fleet_root`).
* **Signature** — Ed25519 over the 32-byte `fleet_root`. The public key and signature are in the
  header; the private key is never written.

## Hashing choices (and why)

* **keccak256**, Ethereum's variant (0x01 pad, not NIST SHA3), so a Solidity verifier uses the
  native `keccak256` opcode. Implemented dependency-free in `ward/_keccak.py` (verified against the
  standard empty-string and `"abc"` vectors).
* **Sorted-pair (commutative) internal nodes**: `keccak256(min(a,b) || max(a,b))`. This is the
  OpenZeppelin `MerkleProof.processProof` convention — a proof is just a list of sibling hashes
  with no direction bits, which keeps the Solidity verifier tiny.
* **Double-hashed leaves**: `leaf = keccak256(keccak256(preimage))`. Hashing leaves at a different
  depth from internal nodes is the standard second-preimage defence (a 64-byte internal preimage
  can't be re-read as a leaf).
* **Odd nodes promoted** (carried up unchanged), matching merkletreejs / OZ StandardMerkleTree, so
  proofs stay minimal.
* **Salting**: every `content_digest` is `keccak256(tag || salt || canonical(content))`. Low-entropy
  content (a true/false/null answer) would otherwise be recoverable by enumerating its digest. The
  salt is a per-run secret held off-chain (env `WARD_TRACE_SALT`); only salted digests and roots are
  published. The header publishes a `salt_commitment` (a hash of the salt) so you can later prove
  which salt was used without revealing it.

## Determinism

No floats and no wall-clock timestamps go inside a hashed payload — they ride in each block's
`meta`, which is not hashed. Raw blobs must be wrapped with dtype/shape/endianness/units
(`blob_record`) so the sidecar is hashed with the bytes. Same inputs + same salt + same key →
byte-identical file and root (covered by a determinism test).

## Secrets

* Signing key: env `WARD_TRACE_SIGNING_KEY` (32-byte Ed25519 seed, hex or base64). Store as a
  **masked bot secret**. Never commit it; never write it to a trace; never print it.
* Salt: env `WARD_TRACE_SALT` (≥16 bytes, hex or base64). Also a masked bot secret.
* Generate both with `python3 -m ward.tracechain keygen`.

## Existing (unchained) evidence

**Do not rewrite history.** Pre-existing traces — the flat `fleet_live_58ffa25.json` and its
`SHA256SUMS`, and anything under `truth-backup/` — were written before the chain existed and are
**unchained**. They prove only that the file has not changed since it was written (a SHA256 over the
whole artefact); they cannot prove event order, that nothing was dropped, or who produced them, and
they were never keccak/Merkle/Ed25519 covered.

Leave them exactly as they are. If a chained copy is wanted for verification tooling, build a
*derived* chain from the old file without altering the original:

```
python3 -m ward.tracechain build fleet_live_58ffa25.json fleet_live_58ffa25.chain.jsonl
```

A chain built this way inherits only the integrity the flat file already had; it is not evidence the
original run was chained at emit time. New runs must emit natively via `tracechain.emit(...)`.

## Flat JSON is now a derived view

The legacy flat fleet summary is reconstructed from the chain with `tracechain.fleet_view` (CLI:
`view`). It is a convenience projection for humans and old tooling — the JSONL chain is
authoritative.

## Verify

```
export WARD_TRACE_SALT=...        # masked bot secret; needed to recompute content digests
python3 -m ward.tracechain verify fleet_live_58ffa25.chain.jsonl
# chain links, every content & block digest, both Merkle root levels, every inclusion proof,
# and the Ed25519 signature; exits non-zero on any mismatch.

python3 -m ward.tracechain verify TRACE --no-salt   # chain+roots+proofs+signature without the salt
```

## On-chain anchoring (pluggable hook, no live tx here)

`tracechain.anchor_payload` returns a content-free payload whose `root_bytes32` is the fixed 32-byte
`fleet_root` — exactly what a smart contract stores or an anchor log witnesses. No wallet, funds, or
live transaction are performed; a caller plugs in its own sink.

Recommended target: the GHCR OCI traces registry already wired in ward
(`ghcr.io/wetware-hq/traces`, tagged by ward commit SHA) — a public, immutable, dated anchor with no
new infrastructure. For a true Web3 anchor, write `root_bytes32` to a minimal append-only EVM
contract (one `bytes32` per fleet run). A Sigstore Rekor entry is the third-party-witness alternative.

A Solidity verifier accepts a block because the tree is OZ-compatible:

```solidity
// leaf = keccak256(bytes.concat(keccak256(abi.encode(bytes32 blockDigest))));
// require(MerkleProof.verify(proof, seedRoot, leaf), "bad block");
// then verify seedRoot's inclusion in fleetRoot the same way.
```

## Note on the fleet runner

The trace writer is the native emit path (`tracechain.emit`), and the flat view is derived. Wiring
the live fleet runner to call `emit` per run (instead of dumping flat JSON) is a one-call change;
it is **scaffolded here, not exercised end to end on a live run**, because the live design run is on
hold pending the signed synthetic patient. The next live fleet should call `emit` directly.
