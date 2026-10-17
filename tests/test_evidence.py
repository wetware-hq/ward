"""ward-evidence crate and live_client model_call emission."""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

from ward import live
from ward import live_client as lc

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"


def _resolve_cargo() -> str:
    env = os.environ.get("CARGO")
    if env:
        return env
    found = shutil.which("cargo")
    if found:
        return found
    home = pathlib.Path.home() / ".cargo" / "bin" / "cargo"
    if home.is_file():
        return str(home)
    raise RuntimeError(
        "cargo not found: set CARGO, install cargo on PATH, or install to ~/.cargo/bin/cargo"
    )


CARGO = _resolve_cargo()


def test_cargo_test_passes():
    r = subprocess.run([CARGO, "test", "-q"], cwd=EVIDENCE, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_live_client_emits_full_params(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, "sk-or-test")
    seen = {}

    def post(body, key):
        seen.update(body)
        return {"model": lc.MODEL, "choices": [{"message": {"content": "{}"}}]}

    send = lc.make_send(9001, post=post)
    send([{"instruction": "i"}])
    assert len(send.model_calls) == 1
    entry = send.model_calls[0]
    assert entry["kind"] == "model_call"
    assert set(entry["params"]) == set(lc.PARAM_KEYS)
    assert entry["params"]["top_p"] is None and entry["params"]["stop"] is None
    assert entry["params"]["reasoning"] == {"enabled": False}
    assert "reply_raw" in entry
    blob = json.dumps(entry)
    assert not any(x in blob for x in ("Bearer", "Authorization", "sk-or-test"))


def test_pack_cli_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, "sk-or-test")
    trace = []
    send = lc.make_send(9001, post=lambda b, k: {"model": lc.MODEL, "choices": [{"message": {"content": "{}"}}]},
                        trace=trace)
    send([{"instruction": "i"}])
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("\n".join(json.dumps(x, sort_keys=True) for x in trace) + "\n")
    bundle_path = tmp_path / "bundle.json"
    withdrawn = ROOT / "data" / "consent_withdrawn.toml"
    pack = subprocess.run(
        [CARGO, "run", "-q", "--bin", "ward-evidence", "--", "pack", str(trace_path), "--withdrawn", str(withdrawn)],
        cwd=EVIDENCE,
        capture_output=True,
        text=True,
        check=True,
    )
    bundle_path.write_text(pack.stdout)
    verify = subprocess.run(
        [CARGO, "run", "-q", "--bin", "ward-evidence", "--", "verify", str(bundle_path)],
        cwd=EVIDENCE,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr
