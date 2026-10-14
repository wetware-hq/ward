"""Every function that raises a refusal, maps a line, opens a queue entry or writes session state must be listed in
safety_functions.toml, the only input to scripts/mutate.py. Found by an AST scan, not by hand."""
import ast, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = tomllib.loads((ROOT / "safety_functions.toml").read_text())
CALLS = {"code", "msg", "_refuse", "Invalid", "Refused", "_line", "Mismatch"}
MUT = {"append", "pop", "add", "update", "clear", "remove", "extend", "insert", "setdefault", "discard"}
TABLES = set(CFG.get("line_tables", []))


def _self_attr(x):
    while isinstance(x, (ast.Subscript, ast.Attribute)):
        if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "self":
            return True
        x = x.value
    return False


def is_safety(f):
    for n in ast.walk(f):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call) and (getattr(n.func, "id", None) in CALLS or getattr(n.func, "attr", None) in CALLS):
            return True
        if isinstance(n, (ast.Name, ast.Attribute)) and (getattr(n, "id", None) in TABLES or getattr(n, "attr", None) in TABLES):
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value[:3] in ("CQ-", "RF-", "PV-"):
            return True
        tg = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
        if any(_self_attr(t) for t in tg):
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUT and _self_attr(n.func.value):
            return True
    return False


def scan(src):
    return sorted({f.name for f in ast.walk(ast.parse(src)) if isinstance(f, ast.FunctionDef) and is_safety(f)})


def missing(src, listed):
    return [f for f in scan(src) if f not in listed]


def test_every_safety_function_is_listed():
    for m in CFG["modules"]:
        assert missing((ROOT / m["path"]).read_text(), set(m["functions"])) == [], m["path"]


def test_listed_functions_and_session_targets_exist():
    for m in CFG["modules"]:
        names = {f.name for f in ast.walk(ast.parse((ROOT / m["path"]).read_text())) if isinstance(f, ast.FunctionDef)}
        assert sorted(set(m["functions"]) - names) == [], m["path"]
    for s in CFG.get("session", []):
        m = next(m for m in CFG["modules"] if m["path"] == s["path"])
        assert s["function"] in m["functions"] and s["statements"]


def test_scan_catches_a_planted_omission():
    m = CFG["modules"][0]
    src = (ROOT / m["path"]).read_text()
    for f in scan(src)[:3]:
        assert missing(src, set(m["functions"]) - {f}) == [f]
