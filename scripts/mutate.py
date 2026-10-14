#!/usr/bin/env python3
"""Mutation testing for the locale-block guard: each mutant must make the test suite fail."""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUTANTS = [
    ("stack/harness.py", "        if ep.blocks:\n            # locale layer", "        if False:\n            # locale layer"),
    ("stack/harness.py", 'CLINICIAN_ROLES = ("clinician",)', 'CLINICIAN_ROLES = ("clinician", "patient", "patient_agent")'),
    ("stack/harness.py", 'b = ("BK-NO-LEGAL-TERM" if on_behalf and', 'b = ("BK-NO-LEGAL-TERM" if False and'),
    ("stack/harness.py", "        if ep.blocks:\n            self._emit(\"harness\", op=\"export_refused\"",
     "        if False:\n            self._emit(\"harness\", op=\"export_refused\""),
    ("stack/harness.py", "        if ep.blocks:                        # hidden", "        if False:                        # hidden"),
    ("stack/harness.py", "rec.update(interpreter_used=True, blocked_for_output=list(ep.blocks))", "pass"),
    ("stack/locales.py", "    if patient_wording_block(language):", "    if False:"),
    ("stack/locales.py", '    if "pack" in needs and letter_pack_block(pack):', "    if False:"),
    ("stack/locales.py", '    if "legal_term" in needs and legal_term_block(pack):', "    if False:"),
    ("stack/adapter.py", '    if bundle["blocks"]:', "    if False:"),
    ("stack/endware.py", '    if any(bd["blocks"] for bd in bundles):', "    if False:"),
    # leak guard: sensitive answers never reach clinician notes
    ("stack/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if False:'),
    ("stack/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if f["sensitive"] and f["safety"] and audience != "patient":'),
    ("stack/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if f["sensitive"] and f["status"] == "answered" and audience != "patient":'),
    ("stack/adapter.py", '            continue\n        if f["status"] in', '            pass\n        if f["status"] in'),
    ("stack/adapter.py", '"sensitive": i in sens', '"sensitive": False'),
    # figures data check and non-synthetic export
    ("stack/endware.py", '    good = [r for r in all_rows if not data_check(r)]', '    good = all_rows'),
    ("stack/endware.py", '    good = [r for r in all_rows if not data_check(r)]', '    good = [] if bad else all_rows'),
    ("stack/endware.py", '    if not good:                              # nothing left', '    if False:                              # nothing left'),
    ("stack/endware.py", 'ln = locales.line("FG-ROW-OMITTED"', 'ln = locales.line("FG-REFUSE-DATA"'),
    ("stack/endware.py", '    if lines and os.path.exists(lp):', '    if False:'),
    ("stack/scorer.py", 'if not (n == 1 if "exactly once" in expect else n >= 1):', 'if not (n >= 1):'),
    ("stack/scorer.py", '        if pts != truth["expected_plotted_points"]:', '        if False:'),
    ("stack/scorer.py", '        if want is None or _fill_match(want, cap_and_text):', '        if want is None:'),
    ("stack/scorer.py", '    missing = [r["seq"] for r in snaps if not any(', '    missing = [r["seq"] for r in snaps[:1] if not any('),
    ("stack/scorer.py", '        if sl.get("line_id") == "CQ-WAITING-PARENT" and sl.get("text"):', '        if False:'),
    ("stack/endware.py", '        return "unit"', '        return None'),
    ("stack/endware.py", '        return "date"\n    try:', '        return None\n    try:'),
    ("stack/harness.py", 'r = {"accepted": reason is None,', 'r = {"accepted": True,'),
    ("stack/harness.py", '        self._adv = False                    # this method logs', '        pass                    # this method logs'),
]


def main():
    survived = 0
    for n, (path, old, new) in enumerate(MUTANTS, 1):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, "stack")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "out"))
            src = open(os.path.join(dst, path)).read()
            if old not in src:
                print(f"mutant {n}: SITE NOT FOUND in {path}"); survived += 1; continue
            open(os.path.join(dst, path), "w").write(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "tests/test_scorer.py"], cwd=dst,
                               capture_output=True, text=True)
            killed = r.returncode != 0
            survived += not killed
            print(f"mutant {n}: {'killed' if killed else 'SURVIVED'}  {path}: {old.strip()[:60]}")
    print(f"{len(MUTANTS) - survived} of {len(MUTANTS)} mutants killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
