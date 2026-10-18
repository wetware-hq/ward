"""Synthetic clinical-immunology case records (bindi.immunology_case.v1).

Hand-rolled validation against schemas/immunology_case.v1.schema.json (no JSON-Schema runtime).
A record is admitted to ward only when validation passes and the clinical signature is present.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CASE_SCHEMA = "bindi.immunology_case.v1"
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schemas" / "immunology_case.v1.schema.json"

AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]{8,15}$")
HLA_I_RE = re.compile(r"^HLA-[ABC]\*[0-9]{2}:[0-9]{2}$")
CASE_ID_RE = re.compile(r"^SYNTH-[A-Za-z0-9._-]+$")

CONSENT_SCOPES = {"research_only", "clinical_care", "none"}
SENSITIVITIES = {"public", "internal", "sensitive"}
RELEASES = {"not_a_release", "released"}


class CaseError(ValueError):
    """The case record is missing, malformed, or not synthetic."""


def load_case_bytes(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseError(f"case record is not valid JSON: {exc}") from exc
    problems = validate_case(document)
    if problems:
        raise CaseError("case record failed validation: " + "; ".join(problems))
    return document


def load_case(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise CaseError(f"case record not found: {source}")
    return load_case_bytes(source.read_bytes())


def validate_case(case: Any) -> list[str]:
    """Return validation problems; empty means the record matches the documented contract."""
    problems: list[str] = []
    if not isinstance(case, dict):
        return ["case record must be a JSON object"]
    if case.get("schema") != CASE_SCHEMA:
        problems.append(f"schema must be {CASE_SCHEMA!r}, found {case.get('schema')!r}")

    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not CASE_ID_RE.match(case_id):
        problems.append("case_id must match ^SYNTH-[A-Za-z0-9._-]+$ (synthetic ids only)")

    presentation = case.get("presentation")
    if not isinstance(presentation, dict):
        problems.append("presentation is required and must be an object")
    else:
        for field in ("summary", "diagnosis", "stage"):
            if not str(presentation.get(field) or "").strip():
                problems.append(f"presentation.{field} is required")

    hla = case.get("hla")
    restriction = None
    if not isinstance(hla, dict):
        problems.append("hla is required and must be an object")
    else:
        class_i = hla.get("class_i")
        if not isinstance(class_i, list) or not class_i:
            problems.append("hla.class_i must be a non-empty list of class I alleles")
            class_i = []
        for allele in class_i:
            if not isinstance(allele, str) or not HLA_I_RE.match(allele):
                problems.append(f"hla.class_i entry is not a class I allele: {allele!r}")
        restriction = hla.get("restriction_allele")
        if restriction is not None:
            if not HLA_I_RE.match(str(restriction)):
                problems.append(f"hla.restriction_allele is not a class I allele: {restriction!r}")
            elif restriction not in class_i:
                problems.append(
                    f"hla.restriction_allele {restriction!r} is not in hla.class_i {class_i!r}"
                )

    neo = case.get("neoantigen")
    if not isinstance(neo, dict):
        problems.append("neoantigen is required and must be an object")
    else:
        for field in ("gene", "variant"):
            if not str(neo.get(field) or "").strip():
                problems.append(f"neoantigen.{field} is required")
        mutant = neo.get("mutant_peptide")
        wild = neo.get("wild_type_peptide")
        for name, value in (("mutant_peptide", mutant), ("wild_type_peptide", wild)):
            if not isinstance(value, str) or not AA_RE.match(value):
                problems.append(
                    f"neoantigen.{name} must be 8-15 one-letter residues, found {value!r}"
                )
        if isinstance(mutant, str) and isinstance(wild, str) and AA_RE.match(mutant) and AA_RE.match(wild):
            if mutant == wild:
                problems.append(
                    "neoantigen.mutant_peptide equals wild_type_peptide: there is nothing to "
                    "design against and no margin could be stated"
                )
            elif len(mutant) != len(wild):
                problems.append(
                    "neoantigen.mutant_peptide and wild_type_peptide differ in length; the "
                    "wild-type counterpart must be the same peptide without the variant"
                )

    consent = case.get("consent")
    if not isinstance(consent, dict):
        problems.append("consent is required and must be an object")
    else:
        for field in ("obtained", "design_use"):
            if not isinstance(consent.get(field), bool):
                problems.append(f"consent.{field} is required and must be true or false")
        if consent.get("scope") not in CONSENT_SCOPES:
            problems.append(f"consent.scope must be one of {sorted(CONSENT_SCOPES)}")

    data_class = case.get("data_class")
    if not isinstance(data_class, dict):
        problems.append("data_class is required and must be an object")
    else:
        if data_class.get("synthetic") is not True:
            problems.append(
                "data_class.synthetic must be true: ward refuses any record not marked synthetic"
            )
        if data_class.get("sensitivity") not in SENSITIVITIES:
            problems.append(f"data_class.sensitivity must be one of {sorted(SENSITIVITIES)}")
        if data_class.get("release") not in RELEASES:
            problems.append(f"data_class.release must be one of {sorted(RELEASES)}")

    signature = case.get("signature")
    if not isinstance(signature, dict) or not isinstance(signature.get("signed"), bool):
        problems.append("signature.signed is required and must be true or false")

    return problems


def is_signed(case: dict[str, Any]) -> bool:
    signature = case.get("signature") or {}
    return bool(signature.get("signed")) and bool(signature.get("signed_by"))


def admission_refusals(case: dict[str, Any]) -> list[str]:
    """Why ward must not open harness gates for this record (fail closed)."""
    problems = validate_case(case)
    if problems:
        return problems
    if not is_signed(case):
        return ["case record is not signed (signature.signed and signature.signed_by required)"]
    consent = case.get("consent") or {}
    if not consent.get("obtained"):
        return ["consent.obtained is false"]
    if not consent.get("design_use"):
        return ["consent.design_use is false"]
    return []
