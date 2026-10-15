"""No box-clock reads in stack, forms or orders source (the scenario clock is the harness's own); figures has one
approved clock (clock.now) and stack sets its mode explicitly, never overriding figures' internals."""
import pathlib, re
from stack import paths

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOX = re.compile(r"\b(datetime\.(now|utcnow|today)|date\.today|time\.(time|time_ns|localtime|gmtime|strftime|monotonic|perf_counter))\b")


def _reads(base):
    out = []
    for p in base.rglob("*.py"):
        rel = p.relative_to(base).as_posix()
        if rel.startswith((".venv/", "tests/")) or "__pycache__" in rel or p.name.startswith("test_"):
            continue
        out += [f"{base.name}/{rel}:{n}" for n, l in enumerate(p.read_text().splitlines(), 1) if BOX.search(l.split("#")[0])]
    return out


def test_no_box_clock_reads_in_stack_forms_orders():
    assert [r for b in (ROOT, pathlib.Path(paths.SIBLINGS) / "forms", pathlib.Path(paths.SIBLINGS) / "orders")
            for r in _reads(b)] == []


def test_stack_sets_the_figures_clock_mode_and_never_overrides_figures():
    src = (ROOT / "stack" / "endware.py").read_text()
    assert 'FIGURES_CLOCK="test"' in src and "FIGURES_SCENARIO_CLOCK=" in src
    assert not re.search(r"figures\.(DRAWN|ANCHOR)", src)


def test_letters_runs_on_the_scenario_clock_in_test_mode(monkeypatch):
    import subprocess
    from stack import endware
    seen = {}
    real = subprocess.run
    def spy(cmd, *a, **k):
        if endware.LETTERS in cmd:
            seen.update(k.get("env") or {})
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.delenv("LETTERS_CLOCK", raising=False)
    from stack.harness import Harness
    from stack.scenarios import SCENARIOS
    import tempfile
    sid = "S13-paeds-guardian-au"
    seed, start, pack, fn, *_ = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language="en")
    fn(h, tempfile.mkdtemp())
    assert seen.get("LETTERS_CLOCK") == "test" and seen.get("LETTERS_SCENARIO_CLOCK", "").startswith(h.clock.date().isoformat())
