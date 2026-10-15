"""The probe fails on every leak route (dummy values only, never a real key) and passes on a clean child."""
import os, subprocess, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import key_probe

DUMMY = "sk-or-" + "DUMMY0000"


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_clean_passes(tmp_path):
    assert key_probe.findings(_repo(tmp_path), env={"PATH": "/bin"}, home=str(tmp_path)) == []


@pytest.mark.parametrize("env", [{"WARD_MODEL_API_KEY": "x"}, {"OPENROUTER_API_KEY": "x"}, {"OPENROUTER_BASE": "x"},
                                 {"SOME_TOKEN": DUMMY}])
def test_env_leak_fails(tmp_path, env):
    f = key_probe.findings(_repo(tmp_path), env=env, home=str(tmp_path))
    assert f and DUMMY not in " ".join(f)                     # names only, never the value


@pytest.mark.parametrize("name,text", [(".env", "OPENROUTER_API_KEY=x\n"), (".env.local", "export WARD_MODEL_API_KEY=x\n"),
                                       ("ward.local.toml", f'key = "{DUMMY}"\n'), ("cfg/x.yaml", "OPENROUTER_KEY: x\n")])
def test_repo_file_leak_fails(tmp_path, name, text):
    r = _repo(tmp_path)
    (r / name).parent.mkdir(parents=True, exist_ok=True)
    (r / name).write_text(text)
    assert key_probe.findings(r, env={}, home=str(tmp_path)) == [f"repo file {name}"]


def test_home_config_fails(tmp_path):
    (tmp_path / ".config" / "openrouter").mkdir(parents=True)
    assert key_probe.findings(_repo(tmp_path / "r"), env={}, home=str(tmp_path))


def test_cli_exit_3_loud(tmp_path):
    r = _repo(tmp_path / "r")
    p = subprocess.run([sys.executable, key_probe.__file__, str(r)], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "OPENROUTER_API_KEY": DUMMY})
    assert p.returncode == 3 and "KEY PROBE FAILED" in p.stderr and DUMMY not in p.stderr + p.stdout


def test_bar_child_fails_on_leaked_dummy_file(tmp_path):
    """bar.sh: a dummy key file in a sibling repo stops that repo's run in the probe, before its tests."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for r in "forms orders figures letters cards ward stack_truth cards_truth cards_wording wording".split():
        _repo(tmp_path / r) if r in ("forms", "ward") else (tmp_path / r).mkdir()
    for f in ("forms_orders_lines_SIGNED.md", "cards_lines_SIGNED.md"):
        (tmp_path / "wording" / f).write_text("")
    (tmp_path / "ward" / "scripts").mkdir()
    (tmp_path / "ward" / "scripts" / "key_probe.py").write_text(open(key_probe.__file__).read())
    (tmp_path / "forms" / ".env").write_text("OPENROUTER_API_KEY=" + DUMMY + "\n")
    p = subprocess.run(["bash", os.path.join(root, "scripts/bar.sh"), str(tmp_path)], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "WARD_MODEL_API_KEY": DUMMY,
                            "WARD_FIGURES_PYTHON": sys.executable})
    out = p.stdout + p.stderr
    assert p.returncode != 0 and "KEY PROBE FAILED" in out and "repo file .env" in out and "!! forms failed" in out
    assert DUMMY not in out and "env name WARD_MODEL_API_KEY" not in out   # env -i: the leaked env var never reached the child
