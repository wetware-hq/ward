"""bindi.ward_handoff.v1: validate and admit hand-offs without re-running bindi gates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import sequence_field as sf

HANDOFF_SCHEMA = "bindi.ward_handoff.v1"
CASE_ID_RE = re.compile(r"^SYNTH-[A-Za-z0-9._-]+$")
EVIDENCE_LEVELS = frozenset({"sequence_level", "structure_validated"})
GATE_STATUSES_RAN = frozenset({"pass", "refuse"})


class HandoffError(ValueError):
    """Hand-off record missing, malformed, or not admissible."""


def load_handoff_bytes(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"handoff is not valid JSON: {exc}") from exc
    problems = validate_handoff(document)
    if problems:
        raise HandoffError("handoff failed validation: " + "; ".join(problems))
    return document


def load_handoff(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise HandoffError(f"handoff not found: {source}")
    return load_handoff_bytes(source.read_bytes())


def is_signed(handoff: dict[str, Any]) -> bool:
    signature = handoff.get("signature") or {}
    return bool(handoff.get("signed")) and bool(signature.get("signed")) and bool(signature.get("signed_by"))


def validate_handoff(handoff: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(handoff, dict):
        return ["handoff must be a JSON object"]
    if handoff.get("schema") != HANDOFF_SCHEMA:
        problems.append(f"schema must be {HANDOFF_SCHEMA!r}, found {handoff.get('schema')!r}")
    case_id = handoff.get("case_id")
    if not isinstance(case_id, str) or not CASE_ID_RE.match(case_id):
        problems.append("case_id must match ^SYNTH-[A-Za-z0-9._-]+$")
    if handoff.get("synthetic") is not True:
        problems.append("synthetic must be true")
    if not isinstance(handoff.get("signed"), bool):
        problems.append("signed is required and must be true or false")
    signature = handoff.get("signature")
    if not isinstance(signature, dict) or not isinstance(signature.get("signed"), bool):
        problems.append("signature.signed is required and must be true or false")
    level = handoff.get("evidence_level")
    if level not in EVIDENCE_LEVELS:
        problems.append(f"evidence_level must be one of {sorted(EVIDENCE_LEVELS)}")
    for field in ("presentation", "consent", "data_class"):
        if not isinstance(handoff.get(field), dict):
            problems.append(f"{field} is required and must be an object")
    shown = handoff.get("shown_sequences")
    if shown is not None:
        if not isinstance(shown, list):
            problems.append("shown_sequences must be a list when present")
        else:
            for i, row in enumerate(shown):
                problems.extend(sf.validate_sequence_field(row, path=f"shown_sequences[{i}]"))
    for gate_name in ("human_reference_gate", "hazard_screen"):
        gate = handoff.get(gate_name)
        if gate is not None:
            problems.extend(_validate_gate_record(gate, gate_name))
    return problems


def _validate_gate_record(gate: Any, name: str) -> list[str]:
    if not isinstance(gate, dict):
        return [f"{name} must be an object"]
    problems = []
    for field in ("status", "verdict"):
        if not isinstance(gate.get(field), str) or not gate.get(field):
            problems.append(f"{name}.{field} is required")
    return problems


def admission_refusals(handoff: dict[str, Any], *, case_id: str | None = None) -> list[str]:
    problems = validate_handoff(handoff)
    if problems:
        return problems
    if not is_signed(handoff):
        return ["handoff is not signed (signed and signature.signed / signed_by required)"]
    if case_id is not None and handoff.get("case_id") != case_id:
        return [f"handoff.case_id {handoff.get('case_id')!r} != case record {case_id!r}"]
    shown = handoff.get("shown_sequences") or []
    if shown:
        for gate_name in ("human_reference_gate", "hazard_screen"):
            gate = handoff.get(gate_name)
            if gate is None:
                return [f"{gate_name} is required when shown_sequences is non-empty"]
            status = gate.get("status")
            if status not in GATE_STATUSES_RAN:
                return [f"{gate_name} did not run (status={status!r}); expected pass or refuse from bindi"]
            if status != "pass":
                return [f"{gate_name} status is {status!r}; ward refuses a handoff with a failed output gate"]
    return []


def verify_bindi_gates(handoff: dict[str, Any]) -> dict[str, Any]:
    """Record bindi gate verdicts on the ward trace without re-running them."""
    out: dict[str, Any] = {"verified": True, "re_ran": False}
    for gate_name in ("human_reference_gate", "hazard_screen"):
        gate = handoff.get(gate_name)
        if gate is None:
            out[gate_name] = None
            continue
        out[gate_name] = {
            "status": gate.get("status"),
            "verdict": gate.get("verdict"),
            "reason": gate.get("reason"),
            "reference_sha256": gate.get("reference_sha256"),
        }
    shown = handoff.get("shown_sequences") or []
    out["shown_sequence_count"] = len(shown)
    out["evidence_level"] = handoff.get("evidence_level")
    return out
