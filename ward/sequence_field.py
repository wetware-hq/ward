"""bindi.sequence_field.v1 validation (hand-rolled; mirrors bindi/src/bindi/provenance.py)."""

from __future__ import annotations

import re
from typing import Any

AA_FULL_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
PROVENANCE_KINDS = frozenset({"design_tool", "fixture", "reference"})
BINDING_CLAIM_FIELDS = frozenset(
    {"margin", "mutant_complex_score", "wild_type_complex_score", "binding", "affinity"}
)


def validate_sequence_field(value: Any, *, path: str = "sequence_field") -> list[str]:
    problems: list[str] = []
    if not isinstance(value, dict):
        return [f"{path} must be an object with sequence and provenance"]
    seq = value.get("sequence")
    if not isinstance(seq, str) or not seq or not AA_FULL_RE.match(seq):
        problems.append(f"{path}.sequence must be a non-empty one-letter amino-acid string")
    prov = value.get("provenance")
    if not isinstance(prov, dict):
        problems.append(f"{path}.provenance is required")
        return problems
    kind = prov.get("kind")
    if kind not in PROVENANCE_KINDS:
        problems.append(
            f"{path}.provenance.kind must be one of {sorted(PROVENANCE_KINDS)}, found {kind!r}"
        )
    elif kind == "design_tool":
        if not str(prov.get("tool") or "").strip():
            problems.append(f"{path}.provenance.tool is required when kind is design_tool")
        if not str(prov.get("scoring_function") or "").strip():
            problems.append(f"{path}.provenance.scoring_function is required when kind is design_tool")
    claim_fields = [name for name in BINDING_CLAIM_FIELDS if name in value]
    if kind != "design_tool" and claim_fields:
        problems.append(
            f"{path} has provenance.kind={kind!r} but carries binding claim field(s) "
            f"{claim_fields!r}: only design_tool provenance may include margin or affinity claims"
        )
    extra = set(value.keys()) - {"sequence", "provenance"} - BINDING_CLAIM_FIELDS
    if extra:
        problems.append(f"{path} has unexpected field(s): {sorted(extra)}")
    return problems
