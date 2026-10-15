"""scripts/bar.sh sets every setting the letters/cards/ward prepush checks read, from one SIBLINGS argument."""
import pytest
import os, pathlib, subprocess

BAR = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "bar.sh"
NEEDED = {"WARD_TRUTH", "LETTERS_TRUTH", "CARDS_TRUTH", "CARDS_WORDING", "WORDING_DIRS", "REUSED_SIGNED",
          "CARDS_SIGNED", "WARD_SIBLINGS_DIR"}


def _tree(tmp):
    for d in ("stack_truth", "cards_truth", "cards_wording", "wording"):
        (tmp / d).mkdir()
    for f in ("forms_orders_lines_SIGNED.md", "cards_lines_SIGNED.md"):
        (tmp / "wording" / f).write_text("")


def test_env_sets_every_setting(tmp_path):
    _tree(tmp_path); _repos(tmp_path)
    out = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True, check=True).stdout
    assert {l.split("=")[0] for l in out.splitlines()} >= NEEDED
    assert str(tmp_path) not in out                       # printed relative to SIBLINGS


def test_missing_folder_fails(tmp_path):
    _tree(tmp_path); _repos(tmp_path)
    (tmp_path / "cards_wording").rmdir()
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and "CARDS_WORDING" in r.stdout


def test_backup_truth_refused(tmp_path):
    _tree(tmp_path); _repos(tmp_path)
    (tmp_path / "stack_truth").rename(tmp_path / "stack_truth.bak-r9")
    (tmp_path / "stack_truth").symlink_to(tmp_path / "stack_truth.bak-r9")
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and "backup" in r.stdout


REPOS = ("forms", "orders", "figures", "letters", "cards", "ward")


def _repos(tmp, names=REPOS):
    for r in names:
        (tmp / r).mkdir()


def test_all_repos_present_passes(tmp_path):
    _tree(tmp_path); _repos(tmp_path)
    assert subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True).returncode == 0


def test_ward_absent_fails_loudly(tmp_path):
    _tree(tmp_path); _repos(tmp_path, REPOS[:-1])
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and "missing repo: ward" in r.stdout


def test_ward_misnamed_stack_fails_loudly(tmp_path):
    _tree(tmp_path); _repos(tmp_path, REPOS[:-1] + ("st" + "ack",))
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and "missing repo: ward" in r.stdout and "old name" in r.stdout


@pytest.mark.parametrize("gone", REPOS[:-1])
def test_any_repo_absent_fails(tmp_path, gone):
    _tree(tmp_path); _repos(tmp_path, tuple(r for r in REPOS if r != gone))
    r = subprocess.run(["bash", str(BAR), str(tmp_path), "--env"], capture_output=True, text=True)
    assert r.returncode == 2 and f"missing repo: {gone}" in r.stdout
