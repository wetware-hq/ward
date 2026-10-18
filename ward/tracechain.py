"""Verifiable, Web3-compatible hash-chained trace writer for ward fleet runs.

JSONL is the native, canonical form of every fleet trace: one block per line, each line
canonical JSON. Each block records an event's inputs and outputs, a salted content digest, a
block index, its seed, and the previous block's digest, so the chain can be walked and every
digest recomputed. Block digests roll into a Merkle tree: one root per seed and one root over
the whole fleet. Each block carries an inclusion proof against its seed root, and each seed an
inclusion proof against the fleet root. The 32-byte fleet root is Ed25519-signed and is the
value to anchor on-chain. The old flat fleet JSON is a *derived view* (see ``fleet_view``),
never the source of truth.

Merkle construction (chosen for EVM / Solidity verifiers):
  * Hash: **keccak256** (Ethereum's variant, not NIST SHA3), so a Solidity verifier hashes with
    the native ``keccak256`` opcode. Implemented dependency-free in ``ward._keccak``.
  * Node hashing: **sorted (commutative) pair** ``keccak256(min(a,b) || max(a,b))``. This is the
    OpenZeppelin ``MerkleProof.processProof`` convention: a proof is just a list of sibling
    hashes with no direction bits, which keeps the Solidity verifier tiny and canonical.
  * Leaves are **double-hashed**: ``leaf = keccak256(keccak256(preimage))``. Double hashing with a
    distinct depth for leaves vs internal nodes is the standard second-preimage defence (a
    64-byte internal preimage can never be mistaken for a leaf preimage).
  * Odd nodes are **promoted** (carried up unchanged), matching merkletreejs/OZ StandardMerkleTree
    and keeping proofs minimal.

Determinism: canonical JSON (sorted keys, no whitespace, ASCII). No floats and no wall-clock
timestamps inside a hashed payload; volatile fields ride in each block's ``meta`` (not hashed).
Raw blobs must be wrapped self-describingly (dtype/shape/endianness/units, see ``blob_record``)
so the sidecar is hashed with the bytes.

Secrets: the Ed25519 signing key comes from ``WARD_TRACE_SIGNING_KEY``; the per-run salt from
``WARD_TRACE_SALT``. Neither is ever written to a trace or printed. Only salted digests, roots,
proofs, the public key and the signature are published.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
from typing import Any, Iterable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ward._keccak import keccak256

VERSION = "ward-trace-chain/v2-evm"
SIGNING_KEY_ENV = "WARD_TRACE_SIGNING_KEY"   # base64 or hex of a 32-byte Ed25519 seed
SALT_ENV = "WARD_TRACE_SALT"                 # base64 or hex of the per-run secret salt (>=16 bytes)
GENESIS = "0x" + "00" * 32                   # prev digest of the first block in a seed chain

# Domain-separation tags for the chain digests (kept distinct from Merkle leaf/node hashing).
_CONTENT_TAG = b"ward-trace-content-v2\x00"
_BLOCK_TAG = b"ward-trace-block-v2\x00"
_SALT_COMMIT_TAG = b"ward-trace-salt-commit-v2\x00"


# --------------------------------------------------------------------------- hex helpers
def _hx(b: bytes) -> str:
    return "0x" + b.hex()


def _unhx(s: str) -> bytes:
    return bytes.fromhex(s[2:] if s.startswith("0x") else s)


# --------------------------------------------------------------------------- canonical encode
def _reject_floats(obj: Any, where: str = "payload") -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, float):
        raise ValueError(f"float not allowed in hashed {where}; carry it in block meta instead")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError(f"non-string key in hashed {where}: {k!r}")
            _reject_floats(v, where)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _reject_floats(v, where)
    elif not isinstance(obj, (str, int, type(None))):
        raise ValueError(f"unhashable type {type(obj).__name__} in hashed {where}")


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, ASCII-escaped, floats rejected."""
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def blob_record(raw: bytes, *, dtype: str, shape: Iterable[int], endianness: str, units: str) -> dict:
    """Self-describing wrapper for a raw binary blob: the sidecar is hashed with the bytes."""
    return {
        "__blob__": {
            "hex": raw.hex(),
            "dtype": dtype,
            "shape": list(shape),
            "endianness": endianness,
            "units": units,
        }
    }


# --------------------------------------------------------------------------- salt / keys
def _decode_secret(s: str, name: str) -> bytes:
    s = s.strip()
    try:
        return bytes.fromhex(s[2:] if s.startswith("0x") else s)
    except ValueError:
        pass
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{name} must be hex or base64") from e


def salt_from_env(env: dict | None = None) -> bytes:
    env = os.environ if env is None else env
    v = env.get(SALT_ENV)
    if not v:
        raise KeyError(f"{SALT_ENV} is not set")
    salt = _decode_secret(v, SALT_ENV)
    if len(salt) < 16:
        raise ValueError(f"{SALT_ENV} must be at least 16 bytes")
    return salt


def signing_key_from_env(env: dict | None = None) -> Ed25519PrivateKey:
    env = os.environ if env is None else env
    v = env.get(SIGNING_KEY_ENV)
    if not v:
        raise KeyError(f"{SIGNING_KEY_ENV} is not set")
    seed = _decode_secret(v, SIGNING_KEY_ENV)
    if len(seed) != 32:
        raise ValueError(f"{SIGNING_KEY_ENV} must decode to a 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(seed)


def salt_commitment(salt: bytes) -> str:
    """Public commitment to the salt: proves which salt was used without revealing it."""
    return _hx(keccak256(_SALT_COMMIT_TAG + salt))


# --------------------------------------------------------------------------- chain digests
def content_digest(content: Any, salt: bytes) -> str:
    return _hx(keccak256(_CONTENT_TAG + salt + canonical_bytes(content)))


def block_digest(seed: Any, index: int, prev: str, cdigest: str) -> str:
    head = {"seed": seed, "index": index, "prev": prev, "content_digest": cdigest}
    return _hx(keccak256(_BLOCK_TAG + canonical_bytes(head)))


# --------------------------------------------------------------------------- Merkle (EVM / OZ-style)
def _leaf_hash(preimage: bytes) -> bytes:
    return keccak256(keccak256(preimage))


def _node_hash(a: bytes, b: bytes) -> bytes:
    return keccak256(a + b) if a <= b else keccak256(b + a)


def _build_tree(leaves: list[bytes]) -> list[list[bytes]]:
    """Return all levels bottom-up; levels[0] == leaves, levels[-1] == [root]. Odd promoted."""
    if not leaves:
        return [[keccak256(b"")]]
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = []
        for i in range(0, len(cur), 2):
            if i + 1 < len(cur):
                nxt.append(_node_hash(cur[i], cur[i + 1]))
            else:
                nxt.append(cur[i])  # promote lone node
        levels.append(nxt)
    return levels


def _proof_for(levels: list[list[bytes]], index: int) -> list[str]:
    """Sibling hashes from leaf to root; promoted lone nodes contribute no sibling."""
    proof = []
    for lvl in levels[:-1]:
        if index % 2 == 0:
            sib = index + 1
            if sib < len(lvl):
                proof.append(_hx(lvl[sib]))
        else:
            proof.append(_hx(lvl[index - 1]))
        index //= 2
    return proof


def verify_inclusion(leaf: bytes, proof: list[str], root: str) -> bool:
    """OpenZeppelin MerkleProof.processProof equivalent: fold with sorted-pair keccak256."""
    h = leaf
    for p in proof:
        h = _node_hash(h, _unhx(p))
    return _hx(h) == root


def merkle_root(leaves: list[bytes]) -> str:
    return _hx(_build_tree(leaves)[-1][0])


# --------------------------------------------------------------------------- build
class Event:
    """One fleet event: a seed, the hashed content (inputs/outputs), and un-hashed meta."""

    __slots__ = ("seed", "content", "meta")

    def __init__(self, seed: Any, content: Any, meta: dict | None = None):
        self.seed = seed
        self.content = content
        self.meta = meta or {}


def build_chain(events: list[Event], *, salt: bytes, signing_key: Ed25519PrivateKey,
                header_extra: dict | None = None) -> dict:
    """Return {'header': ..., 'blocks': [...]} with chain links, Merkle roots, inclusion proofs
    and an Ed25519 signature over the 32-byte fleet root. Pure given (events, salt, key)."""
    blocks: list[dict] = []
    seed_block_digests: dict[Any, list[bytes]] = {}
    seed_block_rows: dict[Any, list[int]] = {}   # seed -> indices into `blocks`
    prev_by_seed: dict[Any, str] = {}
    idx_by_seed: dict[Any, int] = {}

    for ev in events:
        seed = ev.seed
        index = idx_by_seed.get(seed, 0)
        prev = prev_by_seed.get(seed, GENESIS)
        cdig = content_digest(ev.content, salt)
        bdig = block_digest(seed, index, prev, cdig)
        row = {
            "seed": seed,
            "index": index,
            "prev": prev,
            "content": ev.content,
            "content_digest": cdig,
            "block_digest": bdig,
            "meta": ev.meta,          # NOT hashed
        }
        blocks.append(row)
        seed_block_digests.setdefault(seed, []).append(_unhx(bdig))
        seed_block_rows.setdefault(seed, []).append(len(blocks) - 1)
        prev_by_seed[seed] = bdig
        idx_by_seed[seed] = index + 1

    # per-seed Merkle trees over block digests, with per-block inclusion proofs
    seed_roots: dict[str, str] = {}
    seed_leaf_bytes: dict[Any, bytes] = {}
    for seed, digests in seed_block_digests.items():
        leaves = [_leaf_hash(d) for d in digests]
        levels = _build_tree(leaves)
        seed_roots[str(seed)] = _hx(levels[-1][0])
        for pos, row_idx in enumerate(seed_block_rows[seed]):
            blocks[row_idx]["seed_root"] = _hx(levels[-1][0])
            blocks[row_idx]["proof"] = _proof_for(levels, pos)
        # fleet-tree leaf preimage for this seed: canonical (seed, seed_root)
        seed_leaf_bytes[seed] = canonical_bytes({"seed": seed, "root": seed_roots[str(seed)]})

    # fleet Merkle tree over per-seed leaves (seeds sorted by string for determinism)
    ordered_seeds = sorted(seed_block_digests, key=str)
    fleet_leaves = [_leaf_hash(seed_leaf_bytes[s]) for s in ordered_seeds]
    fleet_levels = _build_tree(fleet_leaves)
    fleet_root = _hx(fleet_levels[-1][0])
    seed_proofs = {str(s): _proof_for(fleet_levels, i) for i, s in enumerate(ordered_seeds)}

    sig = signing_key.sign(_unhx(fleet_root))
    pub = signing_key.public_key().public_bytes_raw()

    header = {
        "version": VERSION,
        "algo": {
            "hash": "keccak256",
            "merkle": "sorted-pair, double-hashed leaves, odd-promoted (OZ MerkleProof compatible)",
            "signature": "ed25519-over-fleet-root",
        },
        "block_count": len(blocks),
        "seeds": [str(s) for s in ordered_seeds],
        "seed_roots": seed_roots,
        "seed_proofs": seed_proofs,
        "fleet_root": fleet_root,          # 32-byte value to anchor on-chain
        "salt_commitment": salt_commitment(salt),
        "pubkey": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(sig).decode(),
    }
    if header_extra:
        header["info"] = header_extra
    return {"header": header, "blocks": blocks}


# --------------------------------------------------------------------------- verify
def verify_chain(trace: dict, *, salt: bytes | None) -> list[str]:
    """Walk the chain, recompute every digest, both Merkle root levels, every inclusion proof
    and the signature. Return a list of problems (empty == OK).

    ``salt`` recomputes content digests from content; pass None to skip only that check (chain,
    roots, proofs and signature are still fully verified from the stored content digests)."""
    problems: list[str] = []
    header = trace.get("header") or {}
    blocks = trace.get("blocks") or []

    if header.get("version") != VERSION:
        problems.append(f"header version {header.get('version')!r} != {VERSION!r}")
    if salt is not None and header.get("salt_commitment") != salt_commitment(salt):
        problems.append("salt does not match header salt_commitment")

    seed_block_digests: dict[Any, list[bytes]] = {}
    prev_by_seed: dict[Any, str] = {}
    idx_by_seed: dict[Any, int] = {}

    for n, b in enumerate(blocks):
        seed = b.get("seed")
        where = f"block[{n}] seed={seed} index={b.get('index')}"
        if b.get("index") != idx_by_seed.get(seed, 0):
            problems.append(f"{where}: index should be {idx_by_seed.get(seed, 0)}")
        exp_prev = prev_by_seed.get(seed, GENESIS)
        if b.get("prev") != exp_prev:
            problems.append(f"{where}: prev {b.get('prev')} != expected {exp_prev}")

        if salt is not None:
            cdig = content_digest(b.get("content"), salt)
            if cdig != b.get("content_digest"):
                problems.append(f"{where}: content_digest mismatch (content tampered?)")
        else:
            cdig = b.get("content_digest")

        bdig = block_digest(seed, b.get("index"), b.get("prev"), cdig)
        if bdig != b.get("block_digest"):
            problems.append(f"{where}: block_digest mismatch")

        seed_block_digests.setdefault(seed, []).append(_unhx(b.get("block_digest")))
        prev_by_seed[seed] = b.get("block_digest")
        idx_by_seed[seed] = b.get("index", idx_by_seed.get(seed, 0)) + 1

    # recompute seed roots and check each block's inclusion proof against them
    seed_roots: dict[str, str] = {}
    for seed, digests in seed_block_digests.items():
        leaves = [_leaf_hash(d) for d in digests]
        seed_roots[str(seed)] = merkle_root(leaves)
        if header.get("seed_roots", {}).get(str(seed)) != seed_roots[str(seed)]:
            problems.append(f"seed {seed}: seed_root mismatch")
    for n, b in enumerate(blocks):
        root = header.get("seed_roots", {}).get(str(b.get("seed")))
        leaf = _leaf_hash(_unhx(b.get("block_digest")))
        if root is None or not verify_inclusion(leaf, b.get("proof") or [], root):
            problems.append(f"block[{n}] seed={b.get('seed')}: inclusion proof failed")

    # recompute fleet root and check each seed's inclusion proof against it
    ordered_seeds = sorted(seed_block_digests, key=str)
    fleet_leaves = [_leaf_hash(canonical_bytes({"seed": s, "root": seed_roots[str(s)]}))
                    for s in ordered_seeds]
    fleet_root = merkle_root(fleet_leaves)
    if fleet_root != header.get("fleet_root"):
        problems.append("fleet_root mismatch")
    for s in ordered_seeds:
        leaf = _leaf_hash(canonical_bytes({"seed": s, "root": seed_roots[str(s)]}))
        proof = header.get("seed_proofs", {}).get(str(s))
        if proof is None or not verify_inclusion(leaf, proof, header.get("fleet_root")):
            problems.append(f"seed {s}: fleet-level inclusion proof failed")

    # signature over the fleet root
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(header["pubkey"]))
        pub.verify(base64.b64decode(header["signature"]), _unhx(header["fleet_root"]))
    except Exception as e:  # noqa: BLE001
        problems.append(f"signature verification failed: {type(e).__name__}")

    return problems


# --------------------------------------------------------------------------- io (JSONL is canonical)
def _dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_trace(trace: dict, path: str | pathlib.Path) -> None:
    """Write the canonical JSONL: first line the header, one block per line. Deterministic."""
    path = pathlib.Path(path)
    with path.open("w", encoding="utf-8") as f:
        f.write(_dump({"type": "header", **trace["header"]}) + "\n")
        for b in trace["blocks"]:
            f.write(_dump({"type": "block", **b}) + "\n")


def read_trace(path: str | pathlib.Path) -> dict:
    header, blocks = None, []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        t = obj.pop("type", None)
        if t == "header":
            header = obj
        elif t == "block":
            blocks.append(obj)
        else:
            raise ValueError(f"unknown record type {t!r}")
    return {"header": header, "blocks": blocks}


# --------------------------------------------------------------------------- derived flat view
def fleet_view(trace: dict) -> dict:
    """Reconstruct the legacy flat fleet summary from the canonical chain. Derived, not source:
    a convenience projection for humans and old tooling; the JSONL chain is authoritative."""
    h = trace["header"]
    runs = []
    for b in trace["blocks"]:
        c = b.get("content", {})
        runs.append({**{"arm": c.get("arm"), "scenario": c.get("scenario"), "seed": c.get("seed")},
                     **(c.get("inputs") or {}), **(c.get("outputs") or {}), **(b.get("meta") or {})})
    info = h.get("info") or {}
    return {
        "label": info.get("source_label"),
        "ward_commit": info.get("ward_commit"),
        "pinned_model": info.get("pinned_model"),
        "fleet_root": h.get("fleet_root"),
        "block_count": h.get("block_count"),
        "runs": runs,
        "_derived_from": "canonical JSONL chain; this flat view is not the source of truth",
    }


# --------------------------------------------------------------------------- off-box anchor hook
def anchor_payload(trace: dict) -> dict:
    """Content-free payload to anchor off-box. ``root_bytes32`` is the fixed-size 32-byte value a
    smart contract would store / an anchor log would witness. Pluggable: no live chain tx, no
    wallet, no funds here — a caller plugs in its own anchor sink (EVM contract, Rekor, OCI tag).

    Recommended target: the GHCR OCI traces registry already wired in ward
    (ghcr.io/wetware-hq/traces), tagged by the ward commit SHA — a public, immutable, dated anchor
    with no new infrastructure. For a true Web3 anchor, write ``root_bytes32`` to a minimal
    append-only EVM contract (one ``bytes32`` event per fleet run); a Sigstore Rekor entry is the
    third-party-witness alternative."""
    h = trace["header"]
    return {
        "version": h["version"],
        "root_bytes32": h["fleet_root"],   # 0x-prefixed 32-byte keccak256 root
        "salt_commitment": h["salt_commitment"],
        "pubkey": h["pubkey"],
        "signature": h["signature"],
    }


# --------------------------------------------------------------------------- fleet runner hook / adapter
def emit(events: list[Event], out_path: str | pathlib.Path, *, salt: bytes | None = None,
         signing_key: Ed25519PrivateKey | None = None, header_extra: dict | None = None) -> dict:
    """One-call native emit for a fleet runner: build the chain and write canonical JSONL.

    A fleet runner builds an ``Event`` per run as it goes and calls this instead of dumping a flat
    JSON. Keys/salt default to the environment vars. Returns the in-memory trace."""
    salt = salt_from_env() if salt is None else salt
    signing_key = signing_key_from_env() if signing_key is None else signing_key
    trace = build_chain(events, salt=salt, signing_key=signing_key, header_extra=header_extra)
    write_trace(trace, out_path)
    return trace


def from_fleet_json(fleet: dict) -> list[Event]:
    """Adapt a legacy flat fleet JSON ('runs' list) into per-event blocks. Used to chain existing
    evidence for verification; new runs should emit natively via ``emit``."""
    events: list[Event] = []
    for r in fleet.get("runs") or []:
        meta = {k: r[k] for k in r if isinstance(r.get(k), float)}
        content = {
            "arm": r.get("arm"),
            "scenario": r.get("scenario"),
            "seed": r.get("seed"),
            "inputs": {
                "raw_replies": r.get("raw_replies"),
                "mh_q3_replies": r.get("mh_q3_replies"),
                "reply_models": r.get("reply_models"),
                "model_calls": r.get("model_calls"),
            },
            "outputs": {
                "check_ids": r.get("check_ids"),
                "target": r.get("target"),
                "caught": r.get("caught"),
                "scorer_safety_ok": r.get("scorer_safety_ok"),
                "error": r.get("error"),
                "records": r.get("records"),
            },
        }
        events.append(Event(seed=r.get("seed"), content=content, meta=meta))
    return events


# --------------------------------------------------------------------------- CLI
def _cli_keygen(args) -> int:
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes_raw()
    pub = key.public_key().public_bytes_raw()
    print(f"{SIGNING_KEY_ENV} (store as a masked bot secret, base64): {base64.b64encode(seed).decode()}")
    print(f"public key (base64, safe to publish):                     {base64.b64encode(pub).decode()}")
    print("salt (store as a second masked bot secret, base64):       "
          + base64.b64encode(os.urandom(32)).decode() + f"  -> {SALT_ENV}")
    return 0


def _cli_build(args) -> int:
    fleet = json.loads(pathlib.Path(args.fleet_json).read_text(encoding="utf-8"))
    trace = emit(from_fleet_json(fleet), args.out,
                 header_extra={"source_label": fleet.get("label"),
                               "ward_commit": fleet.get("ward_commit"),
                               "pinned_model": fleet.get("pinned_model")})
    print(f"wrote {args.out}: {trace['header']['block_count']} blocks, "
          f"fleet_root={trace['header']['fleet_root']}")
    return 0


def _cli_view(args) -> int:
    trace = read_trace(args.trace)
    print(json.dumps(fleet_view(trace), indent=2))
    return 0


def _cli_verify(args) -> int:
    trace = read_trace(args.trace)
    salt = None
    if not args.no_salt:
        try:
            salt = salt_from_env()
        except KeyError:
            print(f"error: {SALT_ENV} not set; pass --no-salt to verify chain/roots/proofs/signature only")
            return 2
    problems = verify_chain(trace, salt=salt)
    if problems:
        print(f"VERIFY FAIL: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    scope = "chain+roots+proofs+signature" if salt is None else "content+chain+roots+proofs+signature"
    print(f"VERIFY OK: {len(trace['blocks'])} blocks, fleet_root={trace['header']['fleet_root']} ({scope})")
    return 0


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python3 -m ward.tracechain",
                                description="Verifiable, EVM-compatible hash-chained ward fleet traces.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("keygen", help="generate an Ed25519 signing key + salt and print setup hints")
    pk.set_defaults(func=_cli_keygen)

    pb = sub.add_parser("build", help="build a canonical JSONL chain from a legacy flat fleet JSON")
    pb.add_argument("fleet_json")
    pb.add_argument("out")
    pb.set_defaults(func=_cli_build)

    pw = sub.add_parser("view", help="print the derived flat view of a canonical JSONL chain")
    pw.add_argument("trace")
    pw.set_defaults(func=_cli_view)

    pv = sub.add_parser("verify", help="verify a canonical JSONL chain end to end (incl. inclusion proofs)")
    pv.add_argument("trace")
    pv.add_argument("--no-salt", action="store_true",
                    help=f"skip content recomputation ({SALT_ENV} not needed)")
    pv.set_defaults(func=_cli_verify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
