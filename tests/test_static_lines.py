"""Static check (ast, not a sweep): every line id the harness passes to _line() is a signed row, so the
'ERR:' fallback in _line can never fire."""
import ast, pathlib
from ward import loader
from signed_source import signed_rows as _signed_rows

SRC = pathlib.Path(__file__).resolve().parent.parent / "ward" / "harness.py"


def line_ids():
    ids, dyn = set(), []
    for n in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "_line" and n.args:
            a = n.args[0]
            (ids.add(a.value) if isinstance(a, ast.Constant) else dyn.append(ast.unparse(a)))
    return ids, dyn


def test_every_harness_line_id_is_signed():
    ids, dyn = line_ids()
    lines = _signed_rows()
    assert ids and dyn == [] and sorted(i for i in ids if i not in lines) == []
