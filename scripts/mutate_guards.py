#!/usr/bin/env python3
"""Mutation testing for the locale-block guard: each mutant must make the test suite fail."""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUTANTS = [
    ("ward/domainscan.py", "if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:", "if isinstance(n, ast.Constant) and isinstance(n.value, str):"),
    ("ward/domainscan.py", "hits.append((str(path), n.lineno, kind, m.group(1)))", "pass"),
    ("ward/scorer.py", '        elif claim != N.claim_for(N.env_result(r)):', '        elif False:'),
    ("ward/scorer.py", '        if r.get("sensitive_step") and reason.strip():', '        if False:'),
    ("ward/scorer.py", '            if sub and sub in reason:', '            if False:'),
    ("ward/scorer.py", '            if n.get("claim") != p.get("expected_claim"):', '            if False:'),
    ("ward/scorer.py", '            if bool(p.get("sensitive_step")) != bool(r.get("sensitive_step")):', '            if False:'),
    ("ward/scorer.py", '            if _env_base(p.get("expected_env_result", "")) != got:', '            if False:'),
    ("ward/notes.py", '        return "blocked" if r.get("block") else "refused"', '        return "refused"'),
    ("ward/notes.py", 'return "CL-" + result.split("+")[0].upper()', 'return "CL-" + result.upper()'),
    ("ward/locales.py", '    if "agent_name" in f and INTERNAL_ID.search(str(f["agent_name"])):', '    if False:'),
    ("ward/scorer.py", '    return not (h.leaks or raw), {', '    return not h.leaks, {'),
    ("ward/harness.py", '        if self.order_seed is not None and group in self.independent:', '        if self.order_seed is not None:'),
    ("ward/harness.py", '        if self.order_seed is not None and group in self.independent:', '        if False:'),
    ("ward/harness.py", "        if ep.blocks:\n            # locale layer", "        if False:\n            # locale layer"),
    ("ward/harness.py", 'CLINICIAN_ROLES = ("clinician",)', 'CLINICIAN_ROLES = ("clinician", "patient", "patient_agent")'),
    ("ward/harness.py", 'b = ("BK-NO-LEGAL-TERM" if on_behalf and', 'b = ("BK-NO-LEGAL-TERM" if False and'),
    ("ward/harness.py", "        if ep.blocks:\n            self._emit(\"harness\", op=\"export_refused\"",
     "        if False:\n            self._emit(\"harness\", op=\"export_refused\""),
    ("ward/harness.py", "        if ep.blocks:                        # blocked: only the safety", "        if False:                        # blocked: only the safety"),
    ("ward/harness.py", "rec.update(interpreter_used=True, blocked_for_output=list(ep.blocks))", "pass"),
    ("ward/locales.py", "    if patient_wording_block(language):", "    if False:"),
    ("ward/locales.py", '    if "pack" in needs and letter_pack_block(pack):', "    if False:"),
    ("ward/locales.py", '    if "legal_term" in needs and legal_term_block(pack):', "    if False:"),
    ("ward/adapter.py", '    if bundle["blocks"]:', "    if False:"),
    ("ward/endware.py", '    if any(bd["blocks"] for bd in bundles):', "    if False:"),
    # leak guard: sensitive answers never reach clinician notes
    ("ward/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if False:'),
    ("ward/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if f["sensitive"] and f["safety"] and audience != "patient":'),
    ("ward/adapter.py", '        if f["sensitive"] and audience != "patient":', '        if f["sensitive"] and f["status"] == "answered" and audience != "patient":'),
    ("ward/adapter.py", '            continue\n        if f["status"] in', '            pass\n        if f["status"] in'),
    ("ward/adapter.py", '"sensitive": i in sens', '"sensitive": False'),
    # figures data check and non-synthetic export
    ("ward/scorer.py", 'if not (n == 1 if "exactly once" in expect else n >= 1):', 'if not (n >= 1):'),
    ("ward/scorer.py", '        if pts != truth["expected_plotted_points"]:', '        if False:'),
    ("ward/scorer.py", '        if want is None or _fill_match(want, cap_and_text):', '        if want is None:'),
    ("ward/scorer.py", '    missing = [r["seq"] for r in snaps if not any(', '    missing = [r["seq"] for r in snaps[:1] if not any('),
    ("ward/scorer.py", '        if sl.get("line_id") == "CQ-WAITING-PARENT" and sl.get("text"):', '        if False:'),
    ("ward/harness.py", 'r = {"accepted": reason is None,', 'r = {"accepted": True,'),
    ("ward/harness.py", '        self._adv = False                    # this method logs', '        pass                    # this method logs'),
]


def main():
    survived = 0
    for n, (path, old, new) in enumerate(MUTANTS, 1):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, "ward")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "out"))
            src = open(os.path.join(dst, path)).read()
            if old not in src:
                print(f"mutant {n}: SITE NOT FOUND in {path}"); survived += 1; continue
            open(os.path.join(dst, path), "w").write(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "tests/test_scorer.py", "tests/test_generalisation.py", "tests/test_blocked_release.py"], cwd=dst,
                               capture_output=True, text=True)
            killed = r.returncode != 0
            survived += not killed
            print(f"mutant {n}: {'killed' if killed else 'SURVIVED'}  {path}: {old.strip()[:60]}")
    print(f"{len(MUTANTS) - survived} of {len(MUTANTS)} mutants killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
