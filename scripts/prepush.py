#!/usr/bin/env python3
"""Minimal pre-push gate for stack, installed as .git/hooks/pre-push. Fails if the test suite fails, if a safety
function is missing from safety_functions.toml, or if any tracked file holds an internal name or a held-out or private
data-store path. Sibling repos are found through STACK_SIBLINGS_DIR (stack/paths.py), so no local workspace path may appear.

    python3 scripts/prepush.py"""
import pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = [re.compile(p) for p in (r"\bB" + r"IO\b", r"/work" + r"space\b", r"\bheld" + r"out\d", r"patient-" + r"store")]


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    problems = []
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for f in files:
        try:
            text = (ROOT / f).read_text()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for rx in FORBIDDEN:
            for m in rx.finditer(text):
                problems.append(f"{f}:{text.count(chr(10), 0, m.start()) + 1}: internal name or path")
    for args in (["tests/test_safety_functions.py"], []):
        if subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=ROOT).returncode:
            problems.append("pytest failed" + (f" ({args[0]})" if args else ""))
    for x in problems:
        print(x)
    print(f"prepush: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
