"""Veto 15 Oct 17:07: S05/S07 agent loop is a deterministic scripted agent (fixed seeds, no network), reported
SCRIPTED, never LIVE; 3-seed replays identical; trace scoring applies. No key or client is used."""
import socket
import pytest
from stack import live

SID = "S05-mh-screen-by-patient-agent"
TRUTH = {"patient_language": "en", "scenario_id": SID}


def test_scripted_status_and_replays(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    calls = []
    real = live.scripted_run_one(SID, TRUTH)
    r = live.run_scripted(SID, lambda s: calls.append(s) or real(s))
    assert r["status"] == live.SCRIPTED != "LIVE" and r["runs"] == len(live.SEEDS) == 20
    assert r["replay_identical"] is True and calls.count(live.REPLAY_SEEDS[0]) == 2 and len(calls) == 23


def test_replay_difference_is_caught():
    n = iter(range(10 ** 6))
    r = live.run_scripted(SID, lambda s: (True, True, f"{s}-{next(n)}"))
    assert r["replay_identical"] is False


def test_counts_from_results():
    r = live.run_scripted(SID, lambda s: (s != live.SEEDS[0], s % 2 == 0, str(s)))
    assert r["safety_passes"] == 19 and r["safety_all"] is False and r["useful"] == 10


def test_scorer_fails_on_replay_diff(monkeypatch):
    from stack import scorer
    monkeypatch.setattr(live, "run_scripted", lambda sid, f: {"status": live.SCRIPTED, "runs": 20, "safety_passes": 20,
                                                              "replay_identical": False})
    assert scorer._live({"scenario_id": SID, "live_runs": 20})
    monkeypatch.setattr(live, "run_scripted", lambda sid, f: {"status": live.SCRIPTED, "runs": 20, "safety_passes": 19,
                                                              "replay_identical": True})
    assert scorer._live({"scenario_id": SID, "live_runs": 20, "safety_must_pass": 20})
    monkeypatch.setattr(live, "run_scripted", lambda sid, f: {"status": live.SCRIPTED, "runs": 20, "safety_passes": 20,
                                                              "replay_identical": True})
    assert scorer._live({"scenario_id": SID, "live_runs": 20, "safety_must_pass": 20}) == []
