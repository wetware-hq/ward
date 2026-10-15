"""Generalisation guard: no hard-coded specialty, ward, discipline or drug name in ward code.
Those names live in signed lists and data files (cases/*.toml, data/domain_terms.toml)."""
import os
from ward import domainscan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ward_code_holds_no_domain_literals():
    hits = [h for h in domainscan.scan(ROOT) if not h[0].endswith("domainscan.py")]
    assert hits == [], "\n".join(f"{f}:{ln} {k} {w}" for f, ln, k, w in hits)


def test_scanner_catches_a_planted_literal_and_skips_docstrings(tmp_path):
    p = tmp_path / "x.py"
    p.write_text('"""Module about aspirin (prose)."""\nDRUG = "warfarin 5 mg"\nWARD = "ICU"\nok = "edit"\n')
    hits = {(k, w.lower()) for _, _, k, w in domainscan.scan_file(p)}
    assert hits == {("drug", "warfarin"), ("ward", "icu")}


def test_vocabulary_is_data_not_code():
    assert domainscan.TERMS_FILE.suffix == ".toml" and set(domainscan.TERMS) == {"discipline", "specialty", "ward", "drug"}
