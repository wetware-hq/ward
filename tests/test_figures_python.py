"""A fresh clone has no figures/.venv: the figures interpreter comes from WARD_FIGURES_PYTHON, else figures' own
.venv when present, else this interpreter. Never a path that doesn't exist."""
import importlib, os, sys
from ward import endware


def _reload(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v) if v is not None else monkeypatch.delenv(k, raising=False)
    return importlib.reload(endware)


def test_setting_wins(monkeypatch):
    assert _reload(monkeypatch, WARD_FIGURES_PYTHON=sys.executable).FIGURES_PY == sys.executable


def test_no_venv_falls_back_to_this_interpreter(monkeypatch, tmp_path):
    e = _reload(monkeypatch, WARD_FIGURES_PYTHON=None, WARD_SIBLINGS_DIR=str(tmp_path))
    assert os.path.exists(e.FIGURES_PY)
    _reload(monkeypatch, WARD_SIBLINGS_DIR=None)
