#!/usr/bin/env python3
"""Mutation stamp. digest() hashes safety_functions.toml plus the AST (ast.dump: no comments or layout) of every
function it lists. scripts/mutate.py records the digest in mutation.stamp after a full run with every mutant killed;
scripts/prepush.py fails when the digest differs and asks for a fresh mutation run.

    python3 scripts/safety_stamp.py      prints the current digest and whether mutation.stamp matches"""
import ast, hashlib, pathlib, sys, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAMP = "mutation.stamp"


def modules(cfg):
    if "modules" in cfg:
        return [(m["path"], set(m["functions"])) for m in cfg["modules"]]
    return [(cfg["module"], set(cfg["functions"]))]


def digest(root=ROOT):
    root = pathlib.Path(root)
    text = (root / "safety_functions.toml").read_text()
    h = hashlib.sha256(text.encode())
    for path, funcs in sorted(modules(tomllib.loads(text))):
        tree = ast.parse((root / path).read_text())
        found = sorted((n.name, n.lineno, ast.dump(n)) for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in funcs)
        for name, _, dump in found:
            h.update(f"\0{path}\0{name}\0{dump}".encode())
    return h.hexdigest()


def record(root=ROOT):
    (pathlib.Path(root) / STAMP).write_text(digest(root) + "\n")


def problem(root=ROOT):
    """None when mutation.stamp matches the current safety functions; else what to do."""
    p = pathlib.Path(root) / STAMP
    have = p.read_text().strip() if p.is_file() else ""
    if have == digest(root):
        return None
    return f"{STAMP}: safety functions changed since the last full mutation run; run scripts/mutate.py"


if __name__ == "__main__":
    print(digest(), "matches" if problem() is None else "STALE")
    sys.exit(0 if problem() is None else 1)
