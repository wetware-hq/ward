"""A fresh clone has no figures/.venv: the figures interpreter comes from WARD_FIGURES_PYTHON, else figures' own
.venv when present, else this interpreter. Never a path that doesn't exist."""
import importlib, os
import pytest
from ward import endware

# Snapshot the process settings at import so restores never inherit a monkeypatched interpreter.
_SAVED = {k: os.environ.get(k) for k in ("WARD_FIGURES_PYTHON", "WARD_SIBLINGS_DIR", "WARD_WORKSPACE")}


@pytest.fixture(autouse=True)
def _restore():
    yield
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(endware)


def _reload(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v) if v is not None else monkeypatch.delenv(k, raising=False)
    return importlib.reload(endware)


def test_setting_wins(monkeypatch, tmp_path):
    marker = str(tmp_path / "fake-python")
    open(marker, "w").write("#!/bin/sh\n")
    os.chmod(marker, 0o755)
    assert _reload(monkeypatch, WARD_FIGURES_PYTHON=marker).FIGURES_PY == marker


def test_no_venv_falls_back_to_this_interpreter(monkeypatch, tmp_path):
    e = _reload(monkeypatch, WARD_FIGURES_PYTHON=None, WARD_SIBLINGS_DIR=str(tmp_path))
    assert os.path.exists(e.FIGURES_PY)
