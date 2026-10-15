"""scripts/bar.sh sets every setting the letters/cards/stack prepush checks read, from one SIBLINGS argument."""
import os, pathlib, subprocess

BAR = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "bar.sh"
NEEDED = {"STACK_TRUTH", "LETTERS_TRUTH", "CARDS_TRUTH", "CARDS_WORDING", "WORDING_DIRS", "REUSED_SIGNED",
          "CARDS_SIGNED", "STACK_SIBLINGS_DIR"}


def _tree(tmp):
    for d in ("stack_truth", "cards_truth", "cards_wording", "wording"):
        (tmp / d).mkdir()
    for f in ("forms_orders_lines_SIGNED.md", "cards_lines_SIGNED.md"):
        (tmp / "wording" / f).write_text("")


def test_env_sets_every_setting(tmp_path):
    _tree(tmp_path)
    out = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True, check=True).stdout
    assert {l.split("=")[0] for l in out.splitlines()} >= NEEDED
    assert str(tmp_path) not in out                       # printed relative to SIBLINGS


def test_missing_folder_fails(tmp_path):
    _tree(tmp_path)
    (tmp_path / "cards_wording").rmdir()
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and "CARDS_WORDING" in r.stdout
