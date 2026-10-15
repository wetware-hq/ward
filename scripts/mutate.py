#!/usr/bin/env python3
"""Mutation testing of every safety function listed in safety_functions.toml (no hand-picked list, no arguments).
Mutants: flip a comparison, swap and/or, drop a 'not', flip a True/False, remove a guard return; map a signed line id
to a wrong signed line (a constant id passed to a line call, or a value in a listed line table); and make a refusal
change the session, log or role (each [[session]] statement injected before every refusal in that function).
Each mutant runs pytest on a fresh copy of the git-tracked files, in parallel. A mutant is killed when pytest fails.
Usage: scripts/mutate.py     Exit 0 only if every mutant is killed."""
import ast, concurrent.futures as cf, os, pathlib, re, shutil, subprocess, sys, tempfile, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = tomllib.loads((ROOT / "safety_functions.toml").read_text())
FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot,
        ast.IsNot: ast.Is, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt}
LINE_CALLS = set(CFG.get("line_calls", ["msg", "_line", "Refused"]))
ID = re.compile(r"[A-Z]{2,4}-[A-Z0-9-]*[A-Z0-9]$")


def _ids(tree):
    return sorted({n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and ID.match(n.value)})


def _refusal(stmt):
    if isinstance(stmt, ast.Raise):
        return True
    return isinstance(stmt, ast.Return) and stmt.value is not None and any(
        isinstance(d, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "accepted" and isinstance(v, ast.Constant)
                                        and v.value is False for k, v in zip(d.keys, d.values)) for d in ast.walk(stmt.value))


def sites(tree, funcs, sess):
    out, ids = [], _ids(tree)
    for f in ast.walk(tree):
        if isinstance(f, ast.FunctionDef) and f.name in funcs:
            for n in ast.walk(f):
                if isinstance(n, ast.Compare):
                    out += [("cmp", n, k) for k in range(len(n.ops))]
                elif isinstance(n, ast.BoolOp):
                    out.append(("boolop", n, 0))
                elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
                    out.append(("not", n, 0))
                elif isinstance(n, ast.Constant) and isinstance(n.value, bool):
                    out.append(("bool", n, 0))
                elif isinstance(n, ast.If) and any(isinstance(b, (ast.Return, ast.Raise)) for b in n.body):
                    out.append(("guard", n, 0))
                elif isinstance(n, ast.Call) and (getattr(n.func, "id", None) in LINE_CALLS or getattr(n.func, "attr", None) in LINE_CALLS) \
                        and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and ID.match(n.args[0].value) \
                        and len(ids) > 1:
                    out.append(("line", n.args[0], ids))
            for k, stmt in enumerate(sess.get(f.name, [])):
                out.append(("sess", f, stmt))
        if isinstance(f, ast.Assign) and getattr(f.targets[0], "id", "") in CFG.get("line_tables", []) and isinstance(f.value, ast.Dict):
            vals = sorted({v.value for v in f.value.values if isinstance(v, ast.Constant)})
            for v in f.value.values:
                if isinstance(v, ast.Constant):
                    out.append(("line", v, vals if len(vals) > 1 else ids))
    return out


class Unnot(ast.NodeTransformer):
    def __init__(self, t):
        self.t = t

    def visit_UnaryOp(self, n):
        self.generic_visit(n)
        return n.operand if n is self.t else n


def _inject(body, stmt):
    out = []
    for s in body:
        for fld in ("body", "orelse", "finalbody"):
            if hasattr(s, fld) and isinstance(getattr(s, fld), list) and not isinstance(s, (ast.FunctionDef, ast.ClassDef)):
                setattr(s, fld, _inject(getattr(s, fld), stmt))
        if isinstance(s, ast.Try):
            for h in s.handlers:
                h.body = _inject(h.body, stmt)
        if _refusal(s):
            out.append(ast.parse(stmt).body[0])
        out.append(s)
    return out


def mutate(src, funcs, sess, i):
    tree = ast.parse(src)
    kind, n, k = sites(tree, funcs, sess)[i]
    line = getattr(n, "lineno", "?")
    if kind == "cmp":
        n.ops[k] = FLIP.get(type(n.ops[k]), ast.Eq)()
    elif kind == "boolop":
        n.op = ast.Or() if isinstance(n.op, ast.And) else ast.And()
    elif kind == "not":
        tree = Unnot(n).visit(tree)
    elif kind == "bool":
        n.value = not n.value
    elif kind == "guard":
        n.body = [ast.Pass()]
    elif kind == "line":
        new = next(x for x in k if x != n.value)
        kind = f"line:{n.value}->{new}"
        n.value = new
    elif kind == "sess":
        n.body = _inject(n.body, k)
        kind = f"sess:{n.name}:{k}"
    return f"{kind}@{line}", ast.unparse(ast.fix_missing_locations(tree))


def _run(job):
    path, label, code = job
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td) / "w"
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        for f in files:
            (work / f).parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / f).exists():
                shutil.copy2(ROOT / f, work / f)
        (work / path).write_text(code)
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"], cwd=work, capture_output=True,
                           env=dict(os.environ, WARD_SIBLINGS_DIR=os.environ.get("WARD_SIBLINGS_DIR") or str(ROOT.parent)))
        return label if r.returncode == 0 else None


sys.path.insert(0, str(ROOT / "scripts"))
START = __import__("safety_stamp").digest(ROOT)      # stamp only what was mutated: the sources as they were at start


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    if _run((CFG["modules"][0]["path"], "baseline", (ROOT / CFG["modules"][0]["path"]).read_text())) is None:
        print("baseline: the unmutated copy fails its tests (untracked file?); refusing to count mutants")
        return 1
    jobs = []
    for m in CFG["modules"]:
        src = (ROOT / m["path"]).read_text()
        funcs = set(m["functions"])
        sess = {s["function"]: s["statements"] for s in CFG.get("session", []) if s["path"] == m["path"]}
        for i in range(len(sites(ast.parse(src), funcs, sess))):
            label, code = mutate(src, funcs, sess, i)
            jobs.append((m["path"], f'{m["path"]} {label}', code))
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("MUTATE_WORKERS", os.cpu_count() or 2))) as ex:
        survivors = [s for s in ex.map(_run, jobs) if s]
    for s in survivors:
        print(f"SURVIVED {s}")
    print(f"mutation: {len(jobs) - len(survivors)}/{len(jobs)} killed")
    if not survivors and __import__("safety_stamp").digest(ROOT) == START:   # unchanged while mutating
        __import__("safety_stamp").record(ROOT)
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
