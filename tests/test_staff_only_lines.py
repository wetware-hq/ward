"""RF-CLOCK-UNSET is signed for staff and agents only: it never appears (id or signed text) in any patient view,
patient-side reply or letter. A planted copy must be caught."""
import tempfile, pytest
from stack import scorer
from stack.harness import Harness
from stack.scenarios import SCENARIOS
from signed_source import signed_rows as _signed_rows


def _run(sid):
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    return h, fn(h, tempfile.mkdtemp())


def test_row_is_signed():
    assert "RF-CLOCK-UNSET" in _signed_rows()


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_staff_only_line_never_in_patient_output(sid):
    h, art = _run(sid)
    assert scorer.staff_only_in_patient_output(h, art) == []


def test_tamper_planted_in_patient_view_and_letter_is_caught():
    h, art = _run("S11-patient-revokes-agent-midway")
    text = _signed_rows()["RF-CLOCK-UNSET"]
    h._emit("harness", op="patient_view", episode="SYNTH-EP-1101", result={"line": text})
    hits = scorer.staff_only_in_patient_output(h, dict(art, letter="RF-CLOCK-UNSET", brief="x"))
    assert any("patient view" in x for x in hits) and any("letter" in x for x in hits)


def test_tamper_patient_side_reply_is_caught():
    h, art = _run("S11-patient-revokes-agent-midway")
    h._emit("call", actor="SYNTH-P1101", role="patient", patient="SYNTH-P1101", episode="SYNTH-EP-1101",
            method="observe", args=[], accepted=False, response={"reason": _signed_rows()["RF-CLOCK-UNSET"]},
            note={"claim": "CL-REFUSED", "reason": ""})
    assert scorer.staff_only_in_patient_output(h, art)
