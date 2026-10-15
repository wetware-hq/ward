"""S13: letters reader-id route (by hand, ended reader) and the au guardian view read from the locale pack."""
import os, re, tempfile
import pytest
from ward import adapter, harness, scenarios, notes, locales

pytestmark = pytest.mark.skipif(not os.path.exists(adapter.LETTERS_WORDING), reason="letters wording not present")


def _run():
    sid = next(k for k in scenarios.SCENARIOS if k.startswith("S13"))
    seed, start, pack, fn, *_ = scenarios.SCENARIOS[sid]
    h = harness.Harness(sid, seed, start, pack=pack, language="en")
    return h, fn(h, tempfile.mkdtemp())


@pytest.fixture(scope="module")
def run():
    return _run()


LETTERS_SAFETY_SIGNED_FILE = adapter.LETTERS_WORDING.replace("_WORDING", "_SAFETY")   # Physician re-signs


def test_reader_ended_signed_from_safety_file():
    t = adapter.letters_signed()["CQ-LETTER-READER-ENDED"]
    assert f'CQ-LETTER-READER-ENDED re-signed' in open(LETTERS_SAFETY_SIGNED_FILE, encoding="utf-8").read()
    assert f': "{t}"' in open(LETTERS_SAFETY_SIGNED_FILE, encoding="utf-8").read()


def test_letter_to_guardian_without_grant_id_goes_by_hand(run):
    h, art = run
    assert art.get("by_hand") == "CQ-LETTER-BY-HAND"
    q = [r for r in h.trace if r.get("op") == "clinician_queue" and r.get("line_id") == "CQ-LETTER-BY-HAND"]
    assert q and "[check_n]" not in q[0]["text"]
    ew = [r for r in h.trace if r["kind"] == "endware" and not r.get("audit")][-1]
    assert notes.env_result(ew) == "blocked"


def test_ended_reader_probe(run):
    h, _ = run
    p = [r for r in h.trace if r.get("method") == "letters_build" and r.get("response", {}).get("line_id") == "letters:CQ-LETTER-READER-ENDED"]
    assert p and not p[0]["accepted"]


def test_guardian_view_from_locale_pack(run):
    h, _ = run
    v = [r for r in h.trace if r.get("op") == "guardian_view"]
    assert v and v[-1]["locale_key"] == "LOCALE-AU-GUARDIAN-VIEW"
    texts = v[-1]["result"]
    assert locales.line("PV-LETTER-BY-HAND") in texts
    assert any(t.startswith(locales.line("PV-BEFORE-PROC").split("[")[0]) for t in texts)


def test_no_guardian_branch_in_view_code():
    src = open(os.path.join(os.path.dirname(harness.__file__), "harness.py")).read()
    body = src[src.index("def guardian_view"):].split("\n    def ", 1)[0]
    assert "guardian" not in body.split('"""', 2)[-1].replace("guardian_view", "")


def test_by_hand_letter_has_nothing_to_cite(run):
    from ward import scorer
    h, art = run
    assert scorer.cites_logged(h, art)[0]
    assert not scorer.cites_logged(h, dict(art, by_hand=None))[0]


def test_locale_view_rule_reads_the_pack_key(run):
    from ward import scorer
    h, _ = run
    assert scorer._locale_view(h, "LOCALE-AU-GUARDIAN-VIEW") == ""
    assert scorer._locale_view(h, "LOCALE-NZ-GUARDIAN-VIEW")


def test_guardian_view_is_patient_side(run):
    from ward import scorer
    h, art = run
    assert locales.line("PV-LETTER-BY-HAND") in scorer._patient_surface(h, art)
