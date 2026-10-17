"""Lab resource and tool compliance: model supplies yes / no / abstain only; routing is deterministic here.
Prompt text lives in data/compliance_prompts.toml (not in code). Abstain always routes to a human and is labelled
for staff; it never becomes deny."""
import pathlib, tomllib
from .live_client import BadReply

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPTS_FILE = ROOT / "data" / "compliance_prompts.toml"
THREE_STATE = frozenset(("yes", "no", "abstain"))
_SCHEMA = {
    "type": "object",
    "properties": {"decision": {"type": "string", "enum": ["yes", "no", "abstain"]}},
    "required": ["decision"],
    "additionalProperties": False,
}


def _load():
    return tomllib.loads(PROMPTS_FILE.read_text(encoding="utf-8"))


def prompts_doc():
    """Path cited in tests and docs."""
    return PROMPTS_FILE


def abstain_human_label():
    return _load()["meta"]["abstain_human_label"]


def prompt_spec(prompt_id: str) -> dict:
    spec = _load().get("prompts", {}).get(prompt_id)
    if not spec or "instruction" not in spec:
        raise KeyError(prompt_id)
    return spec


def compliance_response_format():
    """OpenRouter-style JSON schema: decision enum only, no reasoning field in the reply."""
    return {
        "type": "json_schema",
        "json_schema": {"name": "lab_resource_three_state", "strict": True, "schema": _SCHEMA},
    }


def build_record(prompt_id: str, patient: str, date: str) -> dict:
    spec = prompt_spec(prompt_id)
    return {
        "patient": patient,
        "date": date,
        "compliance_prompt_id": prompt_id,
        "resource_id": spec["resource_id"],
        "tool_id": spec["tool_id"],
        "instruction": spec["instruction"],
    }


def parse_three_state(obj) -> str:
    """Strict parser: malformed or free-text decisions fail the call (BadReply), never coerced."""
    if not isinstance(obj, dict):
        raise BadReply("compliance reply not a json object")
    if set(obj.keys()) != {"decision"}:
        raise BadReply("compliance reply must contain only decision")
    decision = obj.get("decision")
    if not isinstance(decision, str) or decision not in THREE_STATE:
        raise BadReply("compliance decision must be yes, no, or abstain")
    return decision


def apply_decision(decision: str, prompt_id: str) -> dict:
    """Deterministic route from the three-state model input."""
    spec = prompt_spec(prompt_id)
    base = {
        "prompt_id": prompt_id,
        "resource_id": spec["resource_id"],
        "tool_id": spec["tool_id"],
        "decision": decision,
    }
    if decision == "yes":
        return {**base, "route": "allow", "human_visible": None}
    if decision == "no":
        return {**base, "route": "deny", "human_visible": None}
    if decision == "abstain":
        label = abstain_human_label()
        return {
            **base,
            "route": "human",
            "human_visible": label,
            "staff_surface": f"[{label}] resource={spec['resource_id']} tool={spec['tool_id']}",
        }
    raise BadReply("compliance decision must be yes, no, or abstain")


def decide(send, prompt_id: str, patient: str, date: str):
    """One guarded model call; returns apply_decision outcome or raises BadReply."""
    from . import live
    rec = build_record(prompt_id, patient, date)
    return live.send_guarded([rec], send)
