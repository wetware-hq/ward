"""Stack -> letters wiring (landed letters features): the declined questions go to letters as --declined TOML built
from the forms log; a patient letter carries the signed declined line and never an absence line; a GP letter with a
line sourced from a declined sensitive question is refused with SENSITIVE_DECLINED_REFUSED; letters refusals are
named by their signed letters id (letters_refusals_WORDING.md + _SAFETY.md)."""
import re, tempfile
from stack import adapter, endware, scenarios
from stack.harness import Harness
from stack.scenarios import SCENARIOS

S12 = "S12-patient-declines-safety-question-to-letter-with-privacy-line"
S15 = "S15-obstetrics-au"


def _run(sid):
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    return h, fn(h, tempfile.mkdtemp())


LETTERS_SIGNED_FILE = adapter.LETTERS_WORDING      # the letters signing file (Educator wording + Physician safety)


def test_letters_signed_rows_read_both_files():
    rows, src = adapter.letters_signed(), open(LETTERS_SIGNED_FILE, encoding="utf-8").read()
    for k in ("SENSITIVE_DECLINED_REFUSED", "DECLINED-NO-ABSENCE-LINE"):
        assert f"| {k} | {rows[k]} | {rows[k]} |" in src
    assert f'- PRIVACY_BLOCKED unset: "{rows["PRIVACY_BLOCKED.unset"]}"' in src
    assert "copy_refusal" not in rows                       # held, not signed


def test_letters_line_id_names_a_refusal_by_signed_text():
    t = adapter.letters_signed()["SENSITIVE_DECLINED_REFUSED"].replace("{lid}", "L6")
    assert adapter.letters_line_id("x\n" + t + "\n") == "letters:SENSITIVE_DECLINED_REFUSED"
    assert adapter.letters_line_id("nothing signed here") is None


def test_declined_rows_from_the_forms_log():
    h, _ = _run(S12)
    rows = h.declined_rows("SYNTH-P1201")
    assert [r["item"] for r in rows] == ["allergy_any"]
    r = rows[0]
    assert r["section"] == "allergies" and r["safety"] is True and isinstance(r["sensitive"], bool)
    assert r["question"] == h.question_texts["allergy_any"]


def test_s12_patient_letter_has_signed_declined_line_and_no_absence_line():
    _, art = _run(S12)
    pt = adapter.lt_lines()["LT-DECLINED-PT-SAFETY"].split("[")[0]
    assert art["exit"] == 0 and pt in art["letter"]
    allergies = art["letter"].split("Allergies", 1)[1].split("\n## ", 1)[0]
    assert not re.search(r"none recorded|No allergies", allergies, re.I)


def test_s15_gp_line_from_declined_sensitive_question_refused_by_id():
    h, _ = _run(S15)
    gp = [r for r in h.trace if r.get("method") == "letters_build" and r.get("adversarial")]
    assert gp and not gp[-1]["accepted"]
    assert gp[-1]["response"]["line_id"] == "letters:SENSITIVE_DECLINED_REFUSED"


def test_s12_privacy_probes_planted_and_refused_by_id():
    h, _ = _run(S12)
    ids = [r["response"].get("line_id") for r in h.trace if r.get("method") == "letters_build" and r.get("adversarial")]
    assert "letters:PRIVACY_BLOCKED.unset" in ids and "letters:PRIVACY_BLOCKED.missing" in ids


def test_absence_rule_is_scoped_to_the_declined_item():
    """DECLINED-NO-ABSENCE-LINE (the answer file's strings are examples): an absence in another section is not about
    the declined question; one under its heading, or naming it, is."""
    from stack.scorer import absence_lines
    art = {"letter": "## Your test results\n- none recorded.\n## Allergies\n- none recorded.\n"
                     "## Next\n- Allergies: none recorded\n"}
    assert absence_lines(art, ["none recorded"], ["allergies"]) == ["- none recorded.", "- Allergies: none recorded"]
    assert len(absence_lines(art, ["none recorded"])) == 3          # unscoped: every hit
