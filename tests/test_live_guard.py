"""Live guard: refused unless clock mode is test and every record is a listed synthetic 1930s test patient; nothing is
sent on refusal. Expected lines come from the signed source (forms_orders_lines_SIGNED.md via forms WORDING)."""
import tempfile
import pytest
from ward import live
from ward.scorer import _line_text as signed_line          # forms WORDING, synced from forms_orders_lines_SIGNED.md
from ward.harness import Harness
from ward.scenarios import SCENARIOS

CLEAN = {"patient": "SYNTH-P1501", "date": "1937-10-16", "events": [{"at": "1936-03-09T09:00"}]}


@pytest.fixture
def test_clock(monkeypatch):
    monkeypatch.setenv(live.CLOCK_ENV, "test")


def _refused(records, want):
    sent = []
    with pytest.raises(live.LiveRefused) as e:
        live.send_guarded(records, sent.append)
    assert sent == [] and e.value.line_id == want and e.value.text == signed_line(want) and e.value.text
    return e.value


def test_clean_synthetic_passes(test_clock):
    sent = []
    live.send_guarded([CLEAN], sent.append)
    assert sent == [[CLEAN]]


@pytest.mark.parametrize("rec", [
    {"patient": "MRN-4471823", "date": "2026-10-14", "test": True},                 # forged test flag, real-looking
    {"patient": "MRN-4471823", "date": "1937-01-01", "is_test": "yes", "synthetic": True},
    {"patient": "SYNTH-P9999", "date": "1937-01-01"},                                # 1930s, unlisted id
    {"patient": "SYNTH-P1501", "date": "1937-01-01", "events": [{"at": "2026-10-14"}]},   # one modern date
    {"patient": "SYNTH-P1501", "note": "seen 1929-12-31"}, {"patient": "SYNTH-P1501", "date": "1940-01-01"},
    {"date": "1937-01-01"}, "SYNTH-P1501"])
def test_not_test_refused(test_clock, rec):
    _refused([CLEAN, rec], "RF-LIVE-NOT-TEST")


def test_empty_refused(test_clock):
    _refused([], "RF-LIVE-NOT-TEST")


def test_boundary_years_pass(test_clock):
    live.live_guard([{"patient": "SYNTH-P0101", "a": "1930-01-01", "b": "1939-12-31"}])


@pytest.mark.parametrize("mode", ["real", "", "TEST", None])
def test_clock_not_test_refused(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv(live.CLOCK_ENV, raising=False)
    else:
        monkeypatch.setenv(live.CLOCK_ENV, mode)
    _refused([CLEAN], "RF-LIVE-CLOCK-NOT-TEST")


def test_patient_list_is_the_scenario_set():
    seen = set()
    for sid, (seed, start, pack, fn, *_) in SCENARIOS.items():
        h = Harness(sid, seed, start, pack=pack, language="en")
        fn(h, tempfile.mkdtemp())
        seen |= {ep.patient for ep in h.episodes.values() if ep.patient.startswith("SYNTH-")}
    assert set(live.TEST_PATIENTS) == seen


def test_lines_are_staff_only():
    from ward import scorer
    assert {"RF-LIVE-NOT-TEST", "RF-LIVE-CLOCK-NOT-TEST"} <= set(scorer.STAFF_ONLY_LINES)


def test_guard_reads_ward_clock_only(monkeypatch):
    assert live.CLOCK_ENV == "WARD_CLOCK" and live.KEY_ENV == "WARD_MODEL_API_KEY"
    monkeypatch.delenv("WARD_CLOCK", raising=False)
    monkeypatch.setenv("ST" + "ACK_CLOCK", "test")                # the old name never opens the guard
    _refused([CLEAN], "RF-LIVE-CLOCK-NOT-TEST")
