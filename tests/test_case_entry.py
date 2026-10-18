"""Immunology case entry (WET-71): validate, refuse unsigned/invalid, run gates, verify tracechain."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ward import case_entry, immunology_case as ic, tracechain as tc
from ward.scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = ROOT / "fixtures" / "immunology_case_PLACEHOLDER.json"

TEST_KEY_B64 = base64.b64encode(bytes(range(32))).decode()
TEST_SALT_B64 = base64.b64encode(b"synthetic-test-salt-0123456789ab").decode()


@pytest.fixture
def trace_env(monkeypatch):
    monkeypatch.setenv(tc.SIGNING_KEY_ENV, TEST_KEY_B64)
    monkeypatch.setenv(tc.SALT_ENV, TEST_SALT_B64)


@pytest.fixture
def siblings_env(monkeypatch):
    sib = os.environ.get("WARD_SIBLINGS_DIR") or str(ROOT / "siblings")
    if not Path(sib, "forms").is_dir():
        pytest.skip("sibling clones not available for letters integration")
    monkeypatch.setenv("WARD_SIBLINGS_DIR", sib)
    wording = Path(sib) / "wording" / "forms_orders_lines_SIGNED.md"
    if not wording.is_file():
        pytest.skip("wording file missing under siblings")
    letters = Path(sib) / "letters"
    cfg_dir = letters / "config"
    profile_dir = letters / "profile_au"
    if not (cfg_dir / "site.toml").is_file():
        cfg_dir.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "site.toml").write_text(
            (ROOT / "examples" / "site_profile_TEST_EXAMPLE.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (cfg_dir / "site.toml").write_text('locale = "au"\nprofile = "profile_au"\n', encoding="utf-8")


def _signed_case(path: Path | None = None) -> dict:
    raw = json.loads((path or PLACEHOLDER).read_text(encoding="utf-8"))
    raw["signature"] = {"signed": True, "signed_by": "SYNTH-clinical-signoff-test"}
    return raw


EXPECTED_SCENARIOS = frozenset({
    "S01-preproc-checklist",
    "S02-ed-triage-to-discharge-letter",
    "S03-med-rec-pharmacist",
    "S03b-med-rec-pharmacist-au",
    "S04-allied-referral-physio",
    "S05-mh-screen-by-patient-agent",
    "S06a-sdm-on-behalf-eu-de",
    "S06b-sdm-on-behalf-au",
    "S07-adversarial-agent",
    "S08-three-fails-escalation",
    "S09-overdue-order",
    "S10-results-figure",
    "S10b-results-figure-au",
    "S11-patient-revokes-agent-midway",
    "S12-patient-declines-safety-question-to-letter-with-privacy-line",
    "S13-paeds-guardian-au",
    "S14-oncology-results-au",
    "S15-obstetrics-au",
})


def test_scenario_table_unchanged():
    assert set(SCENARIOS) == EXPECTED_SCENARIOS
    assert "S15-obstetrics-au" in SCENARIOS


def test_placeholder_validates_but_is_not_admitted():
    case = json.loads(PLACEHOLDER.read_text(encoding="utf-8"))
    assert ic.validate_case(case) == []
    assert ic.admission_refusals(case)


def test_unsigned_case_refuses_before_gates(tmp_path, trace_env):
    result = case_entry.run_case(PLACEHOLDER, tmp_path / "out")
    assert result["exit_code"] == case_entry.EXIT_REFUSED
    assert result["stages"] == ["case_validate"]
    harness = tmp_path / "out" / "trace.jsonl"
    assert not harness.exists()
    trace = tc.read_trace(result["trace"])
    assert trace["header"]["info"]["case_source"] == result["case_source"]
    assert len(trace["blocks"]) == 1


def test_schema_invalid_case_refuses(tmp_path, trace_env):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = case_entry.run_case(bad, tmp_path / "out")
    assert result["exit_code"] == case_entry.EXIT_CASE_INVALID
    assert not (tmp_path / "out" / "trace.jsonl").exists()


def test_signed_case_runs_to_letter(tmp_path, trace_env, siblings_env):
    case_file = tmp_path / "signed.json"
    case_file.write_text(json.dumps(_signed_case(), sort_keys=True), encoding="utf-8")
    out = tmp_path / "run"
    result = case_entry.run_case(case_file, out)
    assert result["exit_code"] == case_entry.EXIT_OK
    assert result["stages"] == list(case_entry.STAGES)
    assert (out / "trace.jsonl").is_file()
    letter_path = result.get("letter_path")
    assert letter_path and Path(letter_path).is_file()
    text = Path(letter_path).read_text(encoding="utf-8")
    assert "SYNTH-PIMM001" in text or "consent" in text.lower()


def test_case_trace_verifies_with_cli(tmp_path, trace_env, siblings_env):
    case_file = tmp_path / "signed.json"
    case_file.write_text(json.dumps(_signed_case(), sort_keys=True), encoding="utf-8")
    out = tmp_path / "run"
    result = case_entry.run_case(case_file, out)
    assert result["exit_code"] == case_entry.EXIT_OK
    verify = subprocess.run(
        [sys.executable, "-m", "ward.tracechain", "verify", result["trace"]],
        capture_output=True,
        text=True,
        env={**os.environ, tc.SIGNING_KEY_ENV: TEST_KEY_B64, tc.SALT_ENV: TEST_SALT_B64},
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    trace = tc.read_trace(result["trace"])
    assert trace["header"]["info"]["case_source"] == result["case_source"]


def test_schema_file_present():
    schema = json.loads((ROOT / "schemas" / "immunology_case.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "bindi.immunology_case.v1"
    assert "neoantigen" in schema["properties"]
