"""Three-state prompt guard: model-facing instructions that expect yes / no / abstain (or true / false / null)
must offer all three. Binary-only wording (e.g. true|false with no null, or yes/no with no abstain) in those
contexts is a scan failure. Reusable from tests, prepush (via pytest), and sibling repos' own gates."""
import ast
import pathlib
import re
import tomllib

KIND = "THREE-STATE-PROMPT-BINARY-ONLY"

# Contexts where the model reply must be three-state (not an exhaustive list of every prompt).
_THREE_STATE_CTX = re.compile(
    r"(?i)(patient declined|declined this question|"
    r"reply with json.*\bdecision\b|compliance_prompt_id|"
    r"whose value must be one of:\s*yes,\s*no)"
)

_ANSWER_JSON_BIN = re.compile(r'\{[^{}]*["\']?answer["\']?\s*:\s*true\s*\|\s*false\s*\}', re.I)
_ANSWER_JSON_SLASH = re.compile(r'\{[^{}]*["\']?answer["\']?\s*:\s*true\s*/\s*false\s*\}', re.I)
_TRUE_FALSE_PIPE = re.compile(r"\btrue\s*\|\s*false\b", re.I)
_TRUE_OR_FALSE = re.compile(r"\btrue\s+or\s+false\b", re.I)
_YES_NO_ENUM = re.compile(r"(?i)one of:\s*yes,\s*no\b(?!\s*,\s*abstain)")
_YES_OR_NO = re.compile(r"(?i)\byes or no\b")


def _docstrings(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                out.add(id(b.value))
    return out


def _needs_three_state(text: str) -> bool:
    return bool(_THREE_STATE_CTX.search(text))


def _offers_abstain(text: str) -> bool:
    return bool(re.search(r"\bnull\b", text, re.I) or re.search(r"(?i)\babstain\b", text))


def _binary_answer_schema(text: str) -> bool:
    if _offers_abstain(text):
        return False
    if _ANSWER_JSON_BIN.search(text) or _ANSWER_JSON_SLASH.search(text):
        return True
    if _TRUE_FALSE_PIPE.search(text) or _TRUE_OR_FALSE.search(text):
        return True
    return False


def _yes_no_without_abstain(text: str) -> bool:
    if _offers_abstain(text):
        return False
    return bool(_YES_NO_ENUM.search(text) or _YES_OR_NO.search(text))


def violations_in_text(text: str, path: str = "") -> list[tuple[str, str]]:
    """Return (kind, detail) for each violation in a single prompt string."""
    if not _needs_three_state(text):
        return []
    out = []
    if _binary_answer_schema(text):
        out.append((KIND, "answer JSON offers true|false without null"))
    if _yes_no_without_abstain(text):
        out.append((KIND, "yes/no wording without abstain or null"))
    return out


def _strings_from_py(path: pathlib.Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    skip = _docstrings(tree)
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def _strings_from_toml(path: pathlib.Path) -> list[tuple[int, str]]:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []

    def walk(obj, lineno=1):
        if isinstance(obj, str):
            yield lineno, obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from walk(v, lineno)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v, lineno)

    return list(walk(doc))


def scan_file(path: pathlib.Path) -> list[tuple[str, int, str, str]]:
    """path, line, kind, detail for one file."""
    p = pathlib.Path(path)
    rel = str(p)
    if p.suffix == ".py":
        strings = _strings_from_py(p)
    elif p.suffix == ".toml":
        strings = _strings_from_toml(p)
    else:
        return []
    hits = []
    for lineno, text in strings:
        for kind, detail in violations_in_text(text, rel):
            hits.append((rel, lineno, kind, detail))
    return hits


def scan(
    root: pathlib.Path,
    *,
    py_under=("ward",),
    toml_under=("data",),
    exclude_substrings=("threestate_scan.py", "test_threestate_scan.py"),
) -> list[tuple[str, int, str, str]]:
    """Scan ward code and data prompt templates under root."""
    root = pathlib.Path(root)
    out = []
    for sub in py_under:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = str(p.relative_to(root))
            if any(x in rel for x in exclude_substrings):
                continue
            out.extend(scan_file(p))
    for sub in toml_under:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.toml")):
            rel = str(p.relative_to(root))
            if any(x in rel for x in exclude_substrings):
                continue
            out.extend(scan_file(p))
    return out


if __name__ == "__main__":
    import sys

    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    hits = scan(root)
    for path, lineno, kind, detail in hits:
        print(f"{path}:{lineno}\t{kind}\t{detail}")
    sys.exit(1 if hits else 0)
