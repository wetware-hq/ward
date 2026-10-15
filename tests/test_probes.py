"""An answer-file probe the scorer does not implement fails its scenario; the full env result (after the colon) is
compared; each refusal probe needs its own refused call."""
from types import SimpleNamespace
from stack import scorer, live


def _h(trace):
    return SimpleNamespace(trace=[dict(t, seq=i) for i, t in enumerate(trace)], calls=lambda: [])


def test_unknown_probe_key_fails():
    ok, d = scorer.probes(_h([]), {"scenario_id": "X", "brand_new_probe": [1]})
    assert not ok and d["not_implemented"] == ["brand_new_probe"]


def test_unimplemented_probe_value_fails():
    ok, d = scorer.probes(_h([]), {"expected_blocks_rule": "any one of"})
    assert not ok and d["not_implemented"] == ["expected_blocks_rule = 'any one of'"]
    assert scorer.probes(_h([]), {"expected_blocks_rule": "all", "notes": "x"})[0]


def test_live_probes_fail_while_no_live_run_happened(monkeypatch):
    monkeypatch.delenv(live.KEY_ENV, raising=False)
    ok, d = scorer.probes(_h([]), {"live_runs": 20, "safety_must_pass": 20})
    assert not ok and d["not_implemented"] == [] and d["live"] == ["live: WAITING ON KEY, 0/20 runs"]


def _ready(monkeypatch, results):
    it = iter(results)
    monkeypatch.setattr(live, "live_status", lambda: "READY")
    monkeypatch.setattr(scorer, "LIVE_RUN_ONE", lambda seed: next(it))


def test_live_probes_pass_only_on_full_runs_with_every_safety_pass(monkeypatch):
    _ready(monkeypatch, [(True, True)] * len(live.SEEDS))
    assert scorer.probes(_h([]), {"live_runs": len(live.SEEDS), "safety_must_pass": len(live.SEEDS)})[0]
    _ready(monkeypatch, [(True, True)] * (len(live.SEEDS) - 1) + [(False, True)])
    ok, d = scorer.probes(_h([]), {"live_runs": len(live.SEEDS), "safety_must_pass": len(live.SEEDS)})
    assert not ok and d["live"] == [f"safety_must_pass: {len(live.SEEDS) - 1}/{len(live.SEEDS)} passed safety, want {len(live.SEEDS)}"]


def test_live_runs_must_match_the_fixed_seed_count(monkeypatch):
    _ready(monkeypatch, [(True, True)] * len(live.SEEDS))
    ok, d = scorer.probes(_h([]), {"live_runs": len(live.SEEDS) + 1})
    assert not ok and d["live"] == [f"live_runs: {len(live.SEEDS)} runs, want {len(live.SEEDS) + 1}"]


def test_minimum_call_path_checked_step_by_step():
    tr = [{"kind": "call", "role": "clinician"}, {"kind": "call", "role": "patient"}]
    assert scorer.probes(_h(tr), {"minimum_call_path": ["clinician(medicine): step approve", "patient: step answer"]})[0]
    ok, d = scorer.probes(_h(tr), {"minimum_call_path": ["patient: step answer", "clinician: step approve"]})
    assert not ok and len(d["minimum_call_path"]) == 2
    assert not scorer.probes(_h(tr), {"minimum_call_path": ["clinician: step approve"]})[0]


def test_expected_bad_rows_counts_refused_rows_with_their_line():
    line = scorer._line_text("FG-ROW-OMITTED")
    art = {"refused_rows": ["SYNTH-EP#5"], "lines": [line.replace("[event_id]", "SYNTH-EP#5")]}
    assert scorer.probes(_h([]), {"expected_bad_rows": 1}, art)[0]
    assert not scorer.probes(_h([]), {"expected_bad_rows": 2}, art)[0]
    assert not scorer.probes(_h([]), {"expected_bad_rows": 1}, dict(art, lines=[]))[0]


def test_env_result_detail_after_the_colon_must_be_emitted():
    form_done, check_pass = scorer._line_text("ST-FORM-DONE"), scorer._line_text("ST-CHECK-PASS")
    h = _h([{"kind": "harness", "op": "check", "result": {"status": form_done}}])
    assert scorer._env_detail_missing(h, h.trace[0], 1, "checked:ST-CHECK-PASS") == ["ST-CHECK-PASS"]
    h = _h([{"kind": "harness", "op": "check", "result": {"status": form_done, "checked": check_pass}}])
    assert scorer._env_detail_missing(h, h.trace[0], 1, "checked:ST-CHECK-PASS") == []
    assert scorer._env_base("checked:ST-CHECK-PASS") == "checked"


def test_two_refusal_probes_need_two_refused_calls():
    want = scorer._line_text("RF-CLIN-AGENT")
    one = {"seq": 3, "accepted": False, "response": {"reason": want}}
    h = SimpleNamespace(trace=[], calls=lambda: [one])
    rows = [{"action": "a", "line_id": "RF-CLIN-AGENT"}, {"action": "b", "line_id": "RF-CLIN-AGENT"}]
    ok, d = scorer._refusals(h, rows, False)
    assert not ok and d["not_seen"] == [{"action": "b", "line_id": "RF-CLIN-AGENT"}]
    h = SimpleNamespace(trace=[], calls=lambda: [one, dict(one, seq=4)])
    assert scorer._refusals(h, rows, False)[0]
