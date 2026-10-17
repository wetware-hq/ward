"""Lab/tool compliance: three-state model input only; prompts from data/compliance_prompts.toml."""
import json
import pytest
from ward import compliance, live
from ward.live_client import BadReply, MODEL, make_compliance_send


KEY = "sk-or-test-NOT-A-REAL-KEY"
PATIENT, DATE = "SYNTH-P0501", "1934-03-12"
PROMPT = "synth_lab_analyser_use"


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, KEY)
    monkeypatch.setenv(live.CLOCK_ENV, "test")


def _post(decision):
    def post(body, key):
        assert body["reasoning"] == {"enabled": False}
        fmt = body["response_format"]
        assert fmt["type"] == "json_schema"
        assert "abstain" in str(fmt["json_schema"]["schema"])
        return {"model": MODEL, "choices": [{"message": {"content": json.dumps({"decision": decision})}}]}
    return post


def test_prompts_live_in_data_file():
    assert compliance.prompts_doc().name == "compliance_prompts.toml"
    spec = compliance.prompt_spec(PROMPT)
    assert "SYNTH-LAB" in spec["resource_id"] and spec["instruction"]


def test_abstain_routes_human_with_visible_label(ready):
    send = make_compliance_send(9001, post=_post("abstain"))
    out = compliance.decide(send, PROMPT, PATIENT, DATE)
    assert out["route"] == "human"
    assert out["human_visible"] == compliance.abstain_human_label()
    assert compliance.abstain_human_label() in out["staff_surface"]
    assert out["decision"] == "abstain"


def test_yes_and_no_do_not_route_human(ready):
    for decision, route in (("yes", "allow"), ("no", "deny")):
        send = make_compliance_send(9001, post=_post(decision))
        out = compliance.decide(send, PROMPT, PATIENT, DATE)
        assert out["route"] == route
        assert out["human_visible"] is None


@pytest.mark.parametrize("content", [
    '{"decision": "maybe"}',
    '{"decision": "yes", "reasoning": "because"}',
    '{"answer": "yes"}',
    '"yes"',
    "not json",
])
def test_malformed_or_free_text_fails_not_coerced(ready, content):
    def post(body, key):
        return {"model": MODEL, "choices": [{"message": {"content": content}}]}
    send = make_compliance_send(9001, post=post)
    with pytest.raises(BadReply):
        compliance.decide(send, PROMPT, PATIENT, DATE)


def test_abstain_never_maps_to_deny(ready):
    """Planted abstain must not be treated as no."""
    send = make_compliance_send(9001, post=_post("abstain"))
    out = compliance.decide(send, PROMPT, PATIENT, DATE)
    assert out["route"] != "deny"


def test_parse_three_state_unit():
    assert compliance.parse_three_state({"decision": "no"}) == "no"
    with pytest.raises(BadReply):
        compliance.parse_three_state({"decision": "nope"})


def test_apply_decision_routes():
    spec = compliance.prompt_spec(PROMPT)
    yes = compliance.apply_decision("yes", PROMPT)
    assert yes["route"] == "allow" and yes["human_visible"] is None
    assert yes["resource_id"] == spec["resource_id"]
    no = compliance.apply_decision("no", PROMPT)
    assert no["route"] == "deny"
    abstain = compliance.apply_decision("abstain", PROMPT)
    assert abstain["route"] == "human" and abstain["human_visible"] == compliance.abstain_human_label()


def test_apply_decision_rejects_unknown_state():
    with pytest.raises(BadReply):
        compliance.apply_decision("maybe", PROMPT)
