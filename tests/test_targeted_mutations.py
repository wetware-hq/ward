"""Targeted mutations, each must be caught by its declared scenario test (no answer files needed):
(a) a resubmit reports ST-CHECK-PASS without re-running the check -> S12/S13/S15 resubmit-still-failing fail;
(b) G13F's grant expiry judged by the box clock, not the scenario clock -> S13-T-guardian-unexpired fails."""
import datetime
import pytest
from stack import harness, scenario_tests as st

SIDS = {"S12": "S12-patient-declines-safety-question-to-letter-with-privacy-line", "S13": "S13-paeds-guardian-au",
        "S15": "S15-obstetrics-au"}


@pytest.mark.parametrize("sid", SIDS.values())
def test_resubmit_clean_passes(sid):
    assert st.check_resubmit_still_failing(st.run_resubmit_still_failing(sid)) == []


@pytest.mark.parametrize("sid", SIDS.values())
def test_resubmit_pass_without_check_caught(sid, monkeypatch):
    orig = harness.Harness._out

    def mutant(self, h, rec, r):
        out = orig(self, h, rec, r)
        last = self.trace[-1]
        if last.get("resubmit"):
            last["response"]["result"] = st._signed("ST-CHECK-PASS")      # skips the re-run check
        return out
    monkeypatch.setattr(harness.Harness, "_out", mutant)
    assert st.check_resubmit_still_failing(st.run_resubmit_still_failing(sid))


def test_g13f_clean_passes():
    assert st._s13_g13f(None, None, {}) == []


def test_g13f_box_clock_caught(monkeypatch):
    orig = harness.Harness._person_access

    class Box:
        def date(self):
            return datetime.date.today()                                  # the box clock, not the scenario's

    def mutant(self, h):
        real, self.clock = self.clock, Box()
        try:
            return orig(self, h)
        finally:
            self.clock = real
    monkeypatch.setattr(harness.Harness, "_person_access", mutant)
    assert st._s13_g13f(None, None, {})
