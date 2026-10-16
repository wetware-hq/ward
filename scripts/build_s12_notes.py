#!/usr/bin/env python3
"""Writes cases/S12.notes.txt: the synthetic clinician note lines L3 and L4, with their text read from
<siblings>/stack_truth/S12-.../truth.toml (read-only; never edited). Rerun if the truth file changes."""
import os, sys, tomllib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ward.site_profile import FAMILY_DOCTOR   # local reader word: site profile
TRUTH = __import__("os").path.join(__import__("ward.paths", fromlist=["TRUTH"]).TRUTH or "", "S12-patient-declines-safety-question-to-letter-with-privacy-line", "truth.toml")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases", "S12.notes.txt")


def main():
    t = tomllib.load(open(TRUTH, "rb"))
    rows = {r["source_line"].split()[-1]: r for r in t["expected_outputs"] if r.get("source_line", "").startswith("synthetic note")}
    m, f = rows["L3"], rows["L4"]
    l3 = f"{m['item']} {m['value']} {m['unit']} {m['frequency']} {m['route']} for {m['duration']}"
    l4 = f"{f['item']} {f['value']}, {FAMILY_DOCTOR}"
    with open(OUT, "w") as fh:
        fh.write(f"# Synthetic clinician note lines for S12, read from stack_truth (do not edit by hand).\nL3\tMedicines\t{l3}\nL4\tActions\t{l4}\n")
    print(open(OUT).read())


if __name__ == "__main__":
    main()
