"""Lines stack reuses from another signed file match their signed source exactly (no skip)."""
import re
from stack import paths, scorer, endware


def _signed(name, lid):
    """Byte-exact: the raw last cell, with exactly one pad space each side removed and nothing else."""
    text = open(f"{paths.SIBLINGS}/wording/{name}", "rb").read().decode("utf-8")
    m = re.search(rf"^\| {re.escape(lid)} \|(.*)\|$", text, re.M)
    assert m, (name, lid)
    cell = m.group(1).split("|")[-1]
    assert cell.startswith(" ") and cell.endswith(" ") and not cell[1:-1].startswith(" ") and not cell[1:-1].endswith(" ")
    return cell[1:-1]


def test_alert_template_matches_its_single_signed_source():
    from stack import adapter
    assert adapter.LT_SIGNED_FILE.endswith("letters_status_lines_SIGNED.md")
    assert scorer.ALERT_TEMPLATE == _signed("letters_status_lines_SIGNED.md", "LT-SENSITIVE-ALERT-CLIN") \
        == adapter.lt_lines()["LT-SENSITIVE-ALERT-CLIN"]


def test_decline_text_is_in_every_signed_declined_line():
    for lid in ("LT-DECLINED-PT", "LT-DECLINED-CLIN", "LT-DECLINED-PT-SAFETY", "LT-DECLINED-CLIN-SAFETY"):
        assert endware.DECLINE_TEXT in _signed("letters_status_lines_SIGNED.md", lid)


def test_run_traces_not_run_matches_signed():
    from stack import locales
    assert locales.line(paths.NOT_RUN) == _signed("forms_orders_lines_SIGNED.md", paths.NOT_RUN)
