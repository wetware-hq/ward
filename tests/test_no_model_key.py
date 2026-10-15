"""Scripted runs never see a model key: bar.sh clears WARD_MODEL_API_KEY and OPENROUTER*; a scripted run that
still sees one refuses loudly before running anything."""
import os, subprocess, pytest
from ward import live

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("var", ["WARD_MODEL_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"])
def test_scripted_run_refuses_when_key_visible(monkeypatch, var):
    monkeypatch.setenv(var, "x")
    called = []
    with pytest.raises(live.ModelKeyVisible, match=var):
        live.run_scripted("S05", lambda s: called.append(s))
    assert called == []


def test_scripted_run_clean_env_runs(monkeypatch):
    for k in list(os.environ):
        if k == "WARD_MODEL_API_KEY" or k.startswith("OPENROUTER"):
            monkeypatch.delenv(k)
    assert live.run_scripted("S05", lambda s: (True, True, "d"))["status"] == live.SCRIPTED


def test_bar_clears_keys(tmp_path):
    for r in "forms orders figures letters cards ward stack_truth cards_truth cards_wording wording".split():
        (tmp_path / r).mkdir()
    for f in ("forms_orders_lines_SIGNED.md", "cards_lines_SIGNED.md"):
        (tmp_path / "wording" / f).write_text("")
    env = dict(os.environ, WARD_MODEL_API_KEY="x", OPENROUTER_API_KEY="y", OPENROUTER_X="z")
    out = subprocess.run(["bash", os.path.join(ROOT, "scripts/bar.sh"), str(tmp_path), "--env"],
                         capture_output=True, text=True, env=env).stdout
    assert not any(l.startswith(("WARD_MODEL_API_KEY=", "OPENROUTER")) for l in out.splitlines())
    assert "unset WARD_MODEL_API_KEY" in out
