"""Hash-chained, EVM-compatible fleet trace writer: round trip, tamper and determinism.

All data here is synthetic (SYNTH- ids, invented seeds). No real key or salt is used; the test
key and salt are fixed throwaway constants so roots are reproducible. Nothing is printed."""
import base64
import json

import pytest

from ward import tracechain as tc
from ward._keccak import keccak256

# Fixed throwaway secrets for reproducible roots. Not real; never used for a live run.
TEST_KEY_B64 = base64.b64encode(bytes(range(32))).decode()
TEST_SALT_B64 = base64.b64encode(b"synthetic-test-salt-0123456789ab").decode()


def _env(monkeypatch):
    monkeypatch.setenv(tc.SIGNING_KEY_ENV, TEST_KEY_B64)
    monkeypatch.setenv(tc.SALT_ENV, TEST_SALT_B64)


def _events():
    return [
        tc.Event(seed=9001, content={"arm": "neg", "seed": 9001,
                                     "inputs": {"reply": "null"}, "outputs": {"ok": True}},
                 meta={"cost_usd": 0.001, "ts": "ignored"}),
        tc.Event(seed=9001, content={"arm": "neg", "seed": 9001,
                                     "inputs": {"reply": "true"}, "outputs": {"ok": True}}),
        tc.Event(seed=9002, content={"arm": "pos", "seed": 9002,
                                     "inputs": {"reply": "false"}, "outputs": {"ok": False}}),
    ]


def _build(monkeypatch):
    _env(monkeypatch)
    return tc.build_chain(_events(), salt=tc.salt_from_env(),
                          signing_key=tc.signing_key_from_env())


# --------------------------------------------------------------------------- primitives
def test_keccak256_known_vectors():
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"


def test_canonical_rejects_floats_and_timestamps_inside_payload():
    with pytest.raises(ValueError):
        tc.canonical_bytes({"cost": 0.01})
    # bools and ints are fine
    assert tc.canonical_bytes({"b": True, "n": 3, "s": "x"}) == b'{"b":true,"n":3,"s":"x"}'


def test_canonical_sorts_keys():
    assert tc.canonical_bytes({"b": 1, "a": 2}) == tc.canonical_bytes({"a": 2, "b": 1})


def test_blob_record_carries_sidecar_in_hash():
    r = tc.blob_record(b"\x01\x02", dtype="uint8", shape=[2], endianness="little", units="count")
    assert r["__blob__"]["hex"] == "0102" and r["__blob__"]["shape"] == [2]
    # changing the sidecar changes the content digest
    salt = b"x" * 16
    d1 = tc.content_digest(r, salt)
    r2 = tc.blob_record(b"\x01\x02", dtype="int8", shape=[2], endianness="little", units="count")
    assert tc.content_digest(r2, salt) != d1


# --------------------------------------------------------------------------- build / verify
def test_build_then_verify_ok(monkeypatch):
    trace = _build(monkeypatch)
    assert verify_clean(trace, monkeypatch)
    # structure: per-seed roots, a fleet root, proofs on every block
    assert set(trace["header"]["seed_roots"]) == {"9001", "9002"}
    assert trace["header"]["fleet_root"].startswith("0x") and len(trace["header"]["fleet_root"]) == 66
    for b in trace["blocks"]:
        assert "proof" in b and "seed_root" in b


def verify_clean(trace, monkeypatch):
    _env(monkeypatch)
    return tc.verify_chain(trace, salt=tc.salt_from_env()) == []


def test_verify_without_salt_still_checks_chain_roots_proofs_signature(monkeypatch):
    trace = _build(monkeypatch)
    assert tc.verify_chain(trace, salt=None) == []


def test_inclusion_proof_roundtrip(monkeypatch):
    trace = _build(monkeypatch)
    for b in trace["blocks"]:
        leaf = keccak256(keccak256(tc._unhx(b["block_digest"])))
        assert tc.verify_inclusion(leaf, b["proof"], b["seed_root"])


# --------------------------------------------------------------------------- tamper
def test_tamper_one_event_fails_verification(monkeypatch):
    trace = _build(monkeypatch)
    _env(monkeypatch)
    trace["blocks"][2]["content"]["outputs"]["ok"] = True  # flip one output
    problems = tc.verify_chain(trace, salt=tc.salt_from_env())
    assert any("content_digest mismatch" in p for p in problems)
    assert any("block_digest mismatch" in p for p in problems)


def test_tamper_block_digest_breaks_inclusion(monkeypatch):
    trace = _build(monkeypatch)
    trace["blocks"][0]["block_digest"] = "0x" + "ab" * 32
    problems = tc.verify_chain(trace, salt=None)
    assert problems  # digest/chain/proof all notice


def test_tamper_proof_fails(monkeypatch):
    trace = _build(monkeypatch)
    b = next(b for b in trace["blocks"] if b["proof"])
    b["proof"][0] = "0x" + "ff" * 32
    problems = tc.verify_chain(trace, salt=None)
    assert any("inclusion proof failed" in p for p in problems)


def test_tamper_fleet_root_fails_signature(monkeypatch):
    trace = _build(monkeypatch)
    trace["header"]["fleet_root"] = "0x" + "00" * 32
    problems = tc.verify_chain(trace, salt=None)
    assert any("fleet_root mismatch" in p for p in problems) or \
           any("inclusion proof failed" in p for p in problems)


def test_wrong_salt_detected(monkeypatch):
    trace = _build(monkeypatch)
    problems = tc.verify_chain(trace, salt=b"a-different-salt-xxxxxxxxxxxxxxxx")
    assert any("salt" in p or "content_digest mismatch" in p for p in problems)


# --------------------------------------------------------------------------- determinism
def test_determinism_byte_identical_root_and_file(monkeypatch, tmp_path):
    _env(monkeypatch)
    salt, key = tc.salt_from_env(), tc.signing_key_from_env()
    t1 = tc.build_chain(_events(), salt=salt, signing_key=key)
    t2 = tc.build_chain(_events(), salt=salt, signing_key=key)
    assert t1["header"]["fleet_root"] == t2["header"]["fleet_root"]
    p1, p2 = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    tc.write_trace(t1, p1)
    tc.write_trace(t2, p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_roundtrip_file_io(monkeypatch, tmp_path):
    trace = _build(monkeypatch)
    p = tmp_path / "t.jsonl"
    tc.write_trace(trace, p)
    back = tc.read_trace(p)
    assert back["header"]["fleet_root"] == trace["header"]["fleet_root"]
    assert len(back["blocks"]) == len(trace["blocks"])
    assert tc.verify_chain(back, salt=tc.salt_from_env()) == []


# --------------------------------------------------------------------------- secrets never leak
def test_key_and_salt_never_written_to_trace(monkeypatch, tmp_path):
    trace = _build(monkeypatch)
    p = tmp_path / "t.jsonl"
    tc.write_trace(trace, p)
    text = p.read_text()
    assert TEST_KEY_B64 not in text
    assert TEST_SALT_B64 not in text
    # raw salt bytes (hex) must not appear either
    assert (b"x" * 16).hex() not in text
    assert "synthetic-test-salt" not in text


def test_salt_commitment_present_but_salt_absent(monkeypatch):
    trace = _build(monkeypatch)
    assert trace["header"]["salt_commitment"].startswith("0x")
    # commitment is a hash, not the salt
    assert trace["header"]["salt_commitment"] != TEST_SALT_B64


# --------------------------------------------------------------------------- derived view & anchor
def test_fleet_view_is_derived(monkeypatch):
    trace = _build(monkeypatch)
    view = tc.fleet_view(trace)
    assert view["fleet_root"] == trace["header"]["fleet_root"]
    assert len(view["runs"]) == len(trace["blocks"])
    assert "_derived_from" in view


def test_anchor_payload_is_content_free_32_bytes(monkeypatch):
    trace = _build(monkeypatch)
    anc = tc.anchor_payload(trace)
    assert anc["root_bytes32"] == trace["header"]["fleet_root"]
    assert len(tc._unhx(anc["root_bytes32"])) == 32
    assert "content" not in json.dumps(anc)


# --------------------------------------------------------------------------- env decoding
def test_secret_decode_hex_and_base64():
    assert tc._decode_secret("0x" + "00" * 32, "k") == bytes(32)
    assert tc._decode_secret(base64.b64encode(bytes(32)).decode(), "k") == bytes(32)


def test_signing_key_rejects_wrong_length(monkeypatch):
    monkeypatch.setenv(tc.SIGNING_KEY_ENV, base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        tc.signing_key_from_env()
