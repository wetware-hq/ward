"""Canonical bindi case_id in the harness; letters-compatible id only at the letters boundary."""

from __future__ import annotations

import re

CASE_ID_RE = re.compile(r"^SYNTH-[A-Za-z0-9._-]+$")
_IMM_PREFIX = "SYNTH-IMM-"
_LETTERS_IMM_PREFIX = "SYNTH-PIMM"


def canonical_patient_id(case_id: str) -> str:
    """Patient id in harness episodes and bindi alignment (same as case_id)."""
    if not CASE_ID_RE.match(case_id):
        raise ValueError(f"case_id must match synthetic pattern, found {case_id!r}")
    return case_id


def letters_patient_id(case_id: str) -> str:
    """Id shape accepted by letters notes template for the Patient: line only."""
    canonical_patient_id(case_id)
    if case_id.startswith(_IMM_PREFIX):
        return _LETTERS_IMM_PREFIX + case_id[len(_IMM_PREFIX) :]
    return case_id


def case_id_from_letters_patient(letters_patient: str) -> str:
    """Inverse of letters_patient_id for ids produced by that mapping."""
    if letters_patient.startswith(_LETTERS_IMM_PREFIX):
        return _IMM_PREFIX + letters_patient[len(_LETTERS_IMM_PREFIX) :]
    return letters_patient
