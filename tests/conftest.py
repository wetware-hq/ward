import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_terminal_summary(terminalreporter):
    from ward import paths, locales
    if paths.TRUTH is None:
        terminalreporter.write_line(locales.line(paths.NOT_RUN))


@pytest.fixture(autouse=True)
def _no_model_key_in_tests(monkeypatch):
    """Tests are scripted runs: no model key or provider setting is visible (bar.sh clears them too)."""
    for k in list(os.environ):
        if k == "WARD_MODEL_API_KEY" or k.startswith("OPENROUTER"):
            monkeypatch.delenv(k)
