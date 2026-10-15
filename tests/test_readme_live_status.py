"""The README carries the signed Live-model status line word for word (read from the signing file when present)."""
import os, pathlib, re
from ward import paths

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"
BAR_SIGNED = pathlib.Path(paths.SIBLINGS) / "STABILITY_BAR.md"    # the signed source


def test_readme_has_signed_live_status():
    if not BAR_SIGNED.is_file():
        import pytest; pytest.skip("signing file not present")
    m = re.search(r"^## Live-model status \(signed by Physician\)\n\n(.+?)\n", BAR_SIGNED.read_text(), re.M)
    assert m and m.group(1) in README.read_text()
