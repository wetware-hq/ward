"""Entry point for a synthetic immunology case record beside the S01-S15 scenario table.

A signed, schema-valid case runs ward harness gates and letters endware, emitting a verifiable
hash-chained trace (ward/tracechain.py) with the case record sha256 pinned as case_source.
Unsigned or invalid records refuse before any harness gate runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
from typing import Any

from . import immunology_case as ic
from . import tracechain as tc
from .endware import letter
from .harness import Harness
from .scenarios import A, CASE, DISC, answer, tick
from .site_profile import FAMILY_DOCTOR as FD

EXIT_OK = 0
EXIT_CASE_INVALID = 1
EXIT_REFUSED = 2
EXIT_WARD_FAIL = 3

STAGES = (
    "case_validate",
    "forms_gates",
    "orders_gates",
    "harness_check",
    "letter",
    "case_complete",
)


def case_seed(case_id: str) -> int:
    return int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % 90000 + 1000


def harness_patient(case_id: str) -> str:
    """Patient id for forms/orders/letters (letters rejects some SYNTH-IMM-* shapes)."""
    slug = case_id.removeprefix("SYNTH-").replace("-", "").replace(".", "")
    return f"SYNTH-P{slug}"[:24]


def episode_ids(seed: int) -> tuple[str, str]:
    return f"SYNTH-EP-{seed}F", f"SYNTH-EP-{seed}O"


def _event_content(stage: str, case_id: str, seed: int, *, inputs: dict | None = None, outputs: dict | None = None):
    return {
        "arm": "case",
        "scenario": case_id,
        "seed": seed,
        "stage": stage,
        "inputs": inputs or {},
        "outputs": outputs or {},
    }


def _emit_stage(events: list[tc.Event], stage: str, case_id: str, seed: int, *, inputs=None, outputs=None):
    events.append(tc.Event(seed=seed, content=_event_content(stage, case_id, seed, inputs=inputs, outputs=outputs)))


def drive_case_harness(h: Harness, case: dict[str, Any], outdir: str, *, seed: int) -> dict[str, Any]:
    """Run forms and orders episodes and build a clinician letter. Harness gates only; not the scenario scorer."""
    patient = harness_patient(case["case_id"])
    ep_f, ep_o = episode_ids(seed)
    consent = case["consent"]
    neo = case["neoantigen"]
    pres = case["presentation"]
    record_id = "SYNTH-REC-IMM-CONSULT"

    h.open_episode("forms", CASE("immunology_referral"), ep_f, patient, needs=("pack",))
    dr = h.session("SYNTH-dr-imm", "clinician", patient, discipline=DISC["ONC"])
    pa = h.session(patient, "patient", patient)
    dr.step(ep_f, A("approve"))
    pa.step(ep_f, answer("design_use_confirmed", bool(consent.get("design_use"))))
    pa.step(ep_f, answer("research_scope_ack", consent.get("scope") == "research_only"))
    pa.step(ep_f, A("submit"))
    dr.step(ep_f, A("review"))
    forms_check = h.check(ep_f)

    h.open_episode("orders", CASE("immunology_handoff"), ep_o, patient, needs=("pack",))
    dr.step(ep_o, A("approve"))
    summary = (
        f"{pres['diagnosis']} ({pres['stage']}): {neo['gene']} {neo['variant']} "
        f"on {case['hla'].get('restriction_allele') or case['hla']['class_i'][0]}."
    )
    h.record("SYNTH-dr-imm", record_id, patient, "Results", summary)
    dr.step(ep_o, tick("file_consult", record_id))
    dr.step(ep_o, A("submit"))
    orders_check = h.check(ep_o)

    art = letter(h, outdir, patient, [ep_f], FD, f"update to {FD}", {})
    return {
        "forms_check": forms_check,
        "orders_check": orders_check,
        "artifact": art,
        "letter_exit": art.get("exit"),
        "letter_path": art.get("path"),
    }


def run_case(
    case_path: str | pathlib.Path,
    outdir: str | pathlib.Path,
    *,
    trace_path: str | pathlib.Path | None = None,
    pack: str = "au",
    language: str = "en",
    salt: bytes | None = None,
    signing_key=None,
) -> dict[str, Any]:
    """Validate, optionally run ward gates, write harness trace.jsonl and canonical tracechain JSONL."""
    case_path = pathlib.Path(case_path)
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    trace_path = pathlib.Path(trace_path) if trace_path else outdir / "case.chain.jsonl"

    raw = case_path.read_bytes()
    case_sha256 = hashlib.sha256(raw).hexdigest()
    events: list[tc.Event] = []
    seed = 0
    case_id = None

    try:
        case = ic.load_case_bytes(raw)
        case_id = case["case_id"]
        seed = case_seed(case_id)
    except ic.CaseError as exc:
        _emit_stage(
            events,
            "case_validate",
            case_id or "unknown",
            seed or 0,
            inputs={"case_sha256": case_sha256, "case_file": str(case_path)},
            outputs={"status": "error", "reason": str(exc)},
        )
        header_extra = {"case_source": case_sha256, "source_label": "ward-case-entry/refused"}
        trace = tc.build_chain(events, salt=_salt(salt), signing_key=_key(signing_key), header_extra=header_extra)
        tc.write_trace(trace, trace_path)
        return {
            "exit_code": EXIT_CASE_INVALID,
            "trace": str(trace_path),
            "case_source": case_sha256,
            "stages": ["case_validate"],
        }

    refusals = ic.admission_refusals(case)
    _emit_stage(
        events,
        "case_validate",
        case_id,
        seed,
        inputs={"case_sha256": case_sha256, "case_file": str(case_path)},
        outputs={"status": "refused" if refusals else "ok", "signed": ic.is_signed(case), "refusals": refusals},
    )
    if refusals:
        header_extra = {"case_source": case_sha256, "source_label": f"ward-case-entry:{case_id}"}
        trace = tc.build_chain(events, salt=_salt(salt), signing_key=_key(signing_key), header_extra=header_extra)
        tc.write_trace(trace, trace_path)
        return {
            "exit_code": EXIT_REFUSED,
            "trace": str(trace_path),
            "case_source": case_sha256,
            "case_id": case_id,
            "refusals": refusals,
            "stages": ["case_validate"],
        }

    h = Harness(f"case:{case_id}", seed, pack=pack, language=language)
    h._emit("meta", case_entry=True, case_id=case_id, case_source=case_sha256)

    ward_out = drive_case_harness(h, case, str(outdir), seed=seed)
    h.write(str(outdir / "trace.jsonl"))

    forms_ok = bool(ward_out["forms_check"].get("complete") or ward_out["forms_check"].get("all_done"))
    orders_ok = bool(ward_out["orders_check"].get("complete") or ward_out["orders_check"].get("all_done"))
    _emit_stage(
        events,
        "forms_gates",
        case_id,
        seed,
        outputs={"status": "ok" if forms_ok else "fail", "check": _jsonable(ward_out["forms_check"])},
    )
    _emit_stage(
        events,
        "orders_gates",
        case_id,
        seed,
        outputs={"status": "ok" if orders_ok else "fail", "check": _jsonable(ward_out["orders_check"])},
    )
    _emit_stage(
        events,
        "harness_check",
        case_id,
        seed,
        outputs={"status": "ok" if forms_ok and orders_ok else "fail"},
    )
    letter_exit = ward_out.get("letter_exit")
    letter_ok = letter_exit == 0 and bool(ward_out.get("letter_path"))
    _emit_stage(
        events,
        "letter",
        case_id,
        seed,
        outputs={
            "status": "ok" if letter_ok else "fail",
            "exit": letter_exit,
            "path": ward_out.get("letter_path"),
        },
    )
    exit_code = EXIT_OK if letter_ok and forms_ok and orders_ok else EXIT_WARD_FAIL
    _emit_stage(
        events,
        "case_complete",
        case_id,
        seed,
        outputs={"status": "ok" if exit_code == EXIT_OK else "fail", "exit_code": exit_code},
    )

    header_extra = {"case_source": case_sha256, "source_label": f"ward-case-entry:{case_id}"}
    trace = tc.build_chain(events, salt=_salt(salt), signing_key=_key(signing_key), header_extra=header_extra)
    tc.write_trace(trace, trace_path)

    return {
        "exit_code": exit_code,
        "trace": str(trace_path),
        "harness_trace": str(outdir / "trace.jsonl"),
        "case_source": case_sha256,
        "case_id": case_id,
        "letter_path": ward_out.get("letter_path"),
        "stages": list(STAGES),
    }


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


def _salt(salt: bytes | None) -> bytes:
    return salt if salt is not None else tc.salt_from_env()


def _key(signing_key):
    return signing_key if signing_key is not None else tc.signing_key_from_env()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m ward.case_entry",
                                description="Run a synthetic immunology case through ward gates and letters.")
    p.add_argument("case_file", type=pathlib.Path, help="bindi.immunology_case.v1 JSON record")
    p.add_argument("--outdir", type=pathlib.Path, default=pathlib.Path("case-out"),
                   help="directory for harness trace and letter artifacts")
    p.add_argument("--trace", type=pathlib.Path, default=None,
                   help="canonical tracechain JSONL path (default: <outdir>/case.chain.jsonl)")
    p.add_argument("--pack", default=os.environ.get("WARD_PACK", "au"))
    p.add_argument("--language", default="en")
    args = p.parse_args(argv)
    try:
        result = run_case(args.case_file, args.outdir, trace_path=args.trace, pack=args.pack, language=args.language)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "refusals"}, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
