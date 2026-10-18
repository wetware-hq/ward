"""Three-state prompt scan: no binary-only model instructions where abstain/null is required."""
import os
import subprocess
import sys
import textwrap

from ward import threestate_scan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DECLINED_CTX = "Synthetic test form for the patient's agent. The patient declined this question. "

OLD_DECLINED_S05 = _DECLINED_CTX + 'Reply with JSON {"answer": true|false} only.'


def test_ward_has_no_binary_only_three_state_prompts():
    hits = threestate_scan.scan(ROOT)
    assert hits == [], "\n".join(f"{p}:{ln} {k} {d}" for p, ln, k, d in hits)


def test_scan_flags_old_declined_s05_prompt_at_84cf447():
    """Regression: live_client declined branch used true|false only before WET-60."""
    v = threestate_scan.violations_in_text(OLD_DECLINED_S05, "ward/live_client.py")
    assert v and v[0][0] == threestate_scan.KIND


def test_scan_passes_fixed_declined_s05_prompt():
    fixed = (
        _DECLINED_CTX
        + 'Reply with JSON {"answer": true|false|null} only; use null to '
        "abstain and not answer for the patient."
    )
    assert threestate_scan.violations_in_text(fixed) == []


def test_scan_allows_boolean_only_when_patient_answered():
    answered = (
        "Synthetic test form for the patient's agent. Record exactly what the "
        'patient said. Reply with JSON {"answer": true|false} only.'
    )
    assert threestate_scan.violations_in_text(answered) == []


def test_scan_flags_spaced_true_false_pipe_in_declined_context():
    bad = _DECLINED_CTX + 'Reply with JSON {"answer": true | false} only.'
    assert threestate_scan.violations_in_text(bad)


def test_scan_flags_slash_true_false_in_declined_context():
    bad = _DECLINED_CTX + 'Reply with JSON {"answer": true/false} only.'
    assert threestate_scan.violations_in_text(bad)


def test_scan_flags_true_or_false_phrase_in_declined_context():
    bad = _DECLINED_CTX + "Reply true or false in JSON field answer only."
    assert threestate_scan.violations_in_text(bad)


def test_scan_flags_yes_or_no_in_declined_context():
    bad = _DECLINED_CTX + "Answer yes or no only."
    assert threestate_scan.violations_in_text(bad)


def test_scan_flags_yes_no_without_abstain_in_compliance_like_prompt(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(
        textwrap.dedent(
            """\
            [prompts.x]
            instruction = "Reply with JSON containing exactly one field, decision, whose value must be one of: yes, no. No prose."
            """
        ),
        encoding="utf-8",
    )
    hits = threestate_scan.scan_file(bad)
    assert hits and hits[0][2] == threestate_scan.KIND


def test_scan_accepts_compliance_prompts_toml():
    hits = threestate_scan.scan_file(os.path.join(ROOT, "data", "compliance_prompts.toml"))
    assert hits == []


def test_threestate_scan_cli_exits_one_on_hits(tmp_path):
    ward = tmp_path / "ward"
    ward.mkdir()
    (ward / "leak.py").write_text(
        'PROMPT = "The patient declined this question. Reply {\\"answer\\": true|false} only."\n',
        encoding="utf-8",
    )
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "ward").mkdir()
    (clean / "ward" / "ok.py").write_text('PROMPT = "Record the patient said. {\\"answer\\": true|false}."\n', encoding="utf-8")
    hit = subprocess.run(
        [sys.executable, "-m", "ward.threestate_scan", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert hit.returncode == 1 and threestate_scan.KIND in hit.stdout
    ok = subprocess.run(
        [sys.executable, "-m", "ward.threestate_scan", str(clean)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0
