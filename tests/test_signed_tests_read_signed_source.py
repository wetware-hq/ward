"""Guard (room ruling 10:18): a signed-content test must take its expected value from the signed source, never from
the file under test. A test counts as signed-content when its name or docstring says "signed" (or "wording"); its
module must then read a *_SIGNED.md file (a string naming one, or a helper/constant whose name says so: _signed...,
SIGNED...). Flags every such test whose module never reads a signed file."""
import ast, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "tests" else HERE
# Tests whose wording has no signed row yet: test id -> the exact line. Each entry must stay absent from every signing
# file; once the line is signed the entry fails, so the test is repointed to the signed source.
KNOWN_UNSIGNED = {}
SIGNED_NAME = re.compile(r"signing_files|_SIGNED\b|_SIGNED\.md|SIGNED_FILE|SIGNED\b")


def _test_files():
    return sorted(p for p in ROOT.rglob("test_*.py") if ".venv" not in p.parts and "node_modules" not in p.parts)


def reads_signed(src, tree):
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return any("_SIGNED" in s for s in strings) or any(SIGNED_NAME.search(n) or n.startswith("_signed") for n in names)


def flagged(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    if reads_signed(src, tree):
        return []
    out = []
    for f in ast.walk(tree):
        if isinstance(f, ast.FunctionDef) and f.name.startswith("test_"):
            doc = (ast.get_docstring(f) or "").lower()
            if "signed" in f.name or "wording" in f.name or "signed" in doc:
                out.append(f"{path.relative_to(ROOT)}::{f.name}")
    return out


def test_guard_flags_a_self_check(tmp_path):
    bad = tmp_path / "test_x.py"
    bad.write_text('def test_wording_matches():\n    assert open("WORDING.md").read() == open("WORDING.md").read()\n')
    good = tmp_path / "test_y.py"
    good.write_text('def test_wording_matches():\n    assert open("../wording/forms_orders_lines_SIGNED.md")\n')
    global ROOT
    old, ROOT = ROOT, tmp_path
    try:
        assert flagged(bad) == ["test_x.py::test_wording_matches"] and flagged(good) == []
    finally:
        ROOT = old


def signing_texts():
    import os
    d = pathlib.Path(os.environ.get("WARD_SIBLINGS_DIR") or ROOT.parent) / "wording"
    return [f.read_text(encoding="utf-8") for f in sorted(d.glob("*.md"))
            if re.search(r"SIGNED|SAFETY", f.name) and not re.search(r"bak|DRAFT|RETIRED", f.name)]


def test_every_signed_content_test_reads_the_signed_source():
    assert [x for p in _test_files() for x in flagged(p) if x not in KNOWN_UNSIGNED] == []


def test_known_unsigned_lines_are_still_unsigned():
    texts = signing_texts()
    assert texts
    assert [t for t, line in KNOWN_UNSIGNED.items() if any(line in s for s in texts)] == []
