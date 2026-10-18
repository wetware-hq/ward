"""The OpenRouter client: READY only with key + client; every send through the live guard; a reply from any model
but the pinned one fails the run; the key never reaches records, prompts or errors. No network: post is stubbed."""
import json
import pytest
from ward import live, live_client as lc
from ward.scorer import load_truth

KEY = "sk-or-test-NOT-A-REAL-KEY"


def _post(content, model=lc.MODEL, seen=None):
    def post(body, key):
        if seen is not None:
            seen.append((body, key))
        return {"model": model, "choices": [{"message": {"content": json.dumps(content)}}]}
    return post


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, KEY)
    monkeypatch.setenv(live.CLOCK_ENV, "test")


def test_status_ready_only_with_key_and_client(monkeypatch):
    monkeypatch.delenv(live.KEY_ENV, raising=False)
    assert live.live_status() == live.WAITING
    monkeypatch.setenv(live.KEY_ENV, KEY)
    assert live.live_status() == "READY"
    monkeypatch.setattr(live, "CLIENT_MODULE", None)
    assert live.live_status() == live.NO_CLIENT


def test_pinned_dated_model():
    assert lc.MODEL == "deepseek/deepseek-v4-pro-0813"


def test_mismatched_model_fails(ready):
    rec = [{"patient": "SYNTH-P0501", "date": "1934-03-12", "instruction": "x"}]
    with pytest.raises(lc.ModelMismatch):
        live.send_guarded(rec, lc.make_send(9001, _post({"answer": True}, model="deepseek/deepseek-v4-pro")))


def test_guard_runs_before_send(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, KEY)
    monkeypatch.delenv(live.CLOCK_ENV, raising=False)
    seen = []
    with pytest.raises(live.LiveRefused):
        live.send_guarded([{"patient": "SYNTH-P0501", "date": "1934-03-12", "instruction": "x"}],
                          lc.make_send(9001, _post({}, seen=seen)))
    assert seen == []


@pytest.mark.parametrize("sid,content", [("S05-mh-screen-by-patient-agent", None),
                                         ("S07-adversarial-agent", {"order": list(range(10))})])
def test_run_one_key_never_in_body(ready, sid, content):
    seen = []
    told = {"mh_q1": False, "mh_q3": None, "mh_q2": True}
    def post(body, key):
        seen.append((body, key))
        recs = json.loads(body["messages"][1]["content"])
        if content is not None:
            c = content
        else:
            rec = recs[0]
            qid = rec["question_id"]
            ps = told[qid]
            c = {"answer": None if ps is None else ps}
        return {"model": lc.MODEL, "choices": [{"message": {"content": json.dumps(c)}}]}
    truth = load_truth(sid) or {}
    lc.run_one(sid, truth, post)(9001)
    assert seen and all(k == KEY and KEY not in json.dumps(b) for b, k in seen)


def test_mismatch_fails_the_run(ready):
    r = lc.run_one("S07-adversarial-agent", {}, _post({"order": list(range(10))}, model="other/model"))(9001)
    assert r == (False, False)


def test_scripted_still_refuses_with_key(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, KEY)
    with pytest.raises(live.ModelKeyVisible):
        live.run_scripted("S05-mh-screen-by-patient-agent", lambda s: (True, True, ""))


def test_live_scenarios_only():
    assert set(lc.AGENTS) == set(live.LIVE_SCENARIOS) and live.SEEDS == tuple(range(9001, 9021))


def test_reasoning_off_so_answer_fits_max_tokens(monkeypatch):
    # a reasoning model spent all 120 tokens thinking and returned no content (LIVE 17 Oct): reasoning stays off
    seen = {}
    def post(body, key):
        seen.update(body)
        return {"model": lc.MODEL, "choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setenv(live.KEY_ENV, "x")
    send = lc.make_send(1, post=post)
    send([{"instruction": "i"}])
    assert seen["reasoning"] == {"enabled": False} and seen["max_tokens"] == 120
    p = send.model_calls[0]["params"]
    assert p["reasoning"] == {"enabled": False} and p["top_p"] is None and p["stop"] is None
