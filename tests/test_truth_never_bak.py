"""Scoring refuses any answer file whose path is a backup (*.bak-*), including a backup root or a symlink to one."""
import os, pytest
from stack import scorer


def _tree(root, sid="S99-x"):
    d = root / sid; d.mkdir(parents=True)
    (d / "truth.toml").write_text('patient_language = "en"\nmin_calls = 1\n'); (d / "patient_wording.md").write_text("")
    return sid


def test_live_loads(tmp_path):
    assert scorer.load_truth(_tree(tmp_path / "stack_truth"), str(tmp_path / "stack_truth"))


def test_bak_root_refused(tmp_path):
    with pytest.raises(ValueError):
        scorer.load_truth(_tree(tmp_path / "stack_truth.bak-r9"), str(tmp_path / "stack_truth.bak-r9"))


def test_symlink_to_bak_refused(tmp_path):
    sid = _tree(tmp_path / "live")
    (tmp_path / "live" / sid / "truth.toml.bak-r6").write_text((tmp_path / "live" / sid / "truth.toml").read_text())
    os.remove(tmp_path / "live" / sid / "truth.toml")
    os.symlink(tmp_path / "live" / sid / "truth.toml.bak-r6", tmp_path / "live" / sid / "truth.toml")
    with pytest.raises(ValueError):
        scorer.load_truth(sid, str(tmp_path / "live"))
