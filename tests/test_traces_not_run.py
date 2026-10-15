"""With no answer-file setting, every check that asks whether the safety bar passed exits non-zero and prints the
signed RUN-TRACES-NOT-RUN line; trace tests skip as RUN-TRACES-NOT-RUN and never pass."""
import os, pathlib, subprocess, sys
from stack import locales, paths
from signed_source import signed_rows as _signed_rows

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "STACK_TRUTH"}
    return env


def _unset_root(tmp_path):
    """A checkout copy without stack.local.toml, so the setting is truly unset."""
    import shutil
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    files = r.stdout.split() if r.returncode == 0 and r.stdout.strip() else \
        [str(f.relative_to(ROOT)) for f in ROOT.rglob("*") if f.is_file() and "__pycache__" not in f.parts
         and ".git" not in f.parts and f.name != "stack.local.toml" and "out" not in f.relative_to(ROOT).parts[:1]]
    for f in files:
        if (ROOT / f).is_file():
            (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / f, tmp_path / f)
    for f in ("stack/paths.py", "scripts/prepush.py", "scripts/report.py", "tests/conftest.py", "tests/truthgate.py",
              "tests/test_e2e.py"):
        shutil.copy(ROOT / f, tmp_path / f)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_signed_line_exists():
    assert locales.line(paths.NOT_RUN) == _signed_rows()[paths.NOT_RUN]


def test_safety_bar_checks_fail_when_traces_not_run(tmp_path):
    root, env = _unset_root(tmp_path), _env(tmp_path)
    env["STACK_SIBLINGS_DIR"] = paths.SIBLINGS
    for script in (["scripts/prepush.py"], ["scripts/report.py"]):
        r = subprocess.run([sys.executable, *script], cwd=root, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode != 0, script
        assert locales.line(paths.NOT_RUN) in r.stdout, script
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "tests/test_e2e.py"],
                       cwd=root, env=env, capture_output=True, text=True, timeout=600)
    assert " passed" not in r.stdout.splitlines()[-1] or "skipped" in r.stdout
    assert paths.NOT_RUN in r.stdout and locales.line(paths.NOT_RUN) in r.stdout
    assert "PASSED" not in r.stdout


def test_prepush_refuses_answer_files(tmp_path):
    root, env = _unset_root(tmp_path), _env(tmp_path)
    env["STACK_SIBLINGS_DIR"] = paths.SIBLINGS
    (root / "stack_truth").mkdir()
    (root / "stack_truth" / "truth.toml").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    r = subprocess.run([sys.executable, "scripts/prepush.py"], cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "stack_truth/truth.toml: answer file or local setting committed" in r.stdout


def test_prepush_fails_on_stale_mutation_stamp(tmp_path):
    root, env = _unset_root(tmp_path), _env(tmp_path)
    env["STACK_SIBLINGS_DIR"] = paths.SIBLINGS
    (root / "mutation.stamp").write_text("0" * 64 + "\n")
    r = subprocess.run([sys.executable, "scripts/prepush.py"], cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "mutation.stamp: safety functions changed" in r.stdout
