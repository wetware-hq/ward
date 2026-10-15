"""Room ruling 11:10: the line count a signing file's header states must equal the id rows parsed from that file.
Signing files are found as in test_no_duplicate_signed_ids (settings STACK_WORDING_DIRS / STACK_SIBLINGS_DIR). Read-only."""
import os, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "tests" else HERE
ROW = re.compile(r"^\|\s*([A-Z]{2,}-[A-Z0-9-]+)\s*\|", re.M)
STATED = re.compile(r"\b(\d+) lines\b")


def wording_dirs():
    if os.environ.get("STACK_WORDING_DIRS"):
        return [pathlib.Path(p) for p in os.environ["STACK_WORDING_DIRS"].split(os.pathsep) if p]
    return [pathlib.Path(os.environ.get("STACK_SIBLINGS_DIR") or ROOT.parent) / "wording"]


def signing_files():
    return [f for d in wording_dirs() for f in sorted(d.glob("*.md"))
            if re.search(r"SIGNED|SAFETY", f.name) and not re.search(r"bak|DRAFT|RETIRED", f.name)]


def mismatch(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    m = STATED.search(text.splitlines()[0] if text else "")
    if not m:
        return None
    rows = len(set(ROW.findall(text)))
    return None if rows == int(m.group(1)) else (int(m.group(1)), rows)


def test_unit_wrong_header_fails(tmp_path):
    f = tmp_path / "x_SIGNED.md"
    f.write_text("# x (SIGNED, 2 lines)\n| id | line |\n| XX-A | a |\n| XX-B | b |\n")
    assert mismatch(f) is None
    f.write_text("# x (SIGNED, 3 lines)\n| id | line |\n| XX-A | a |\n| XX-B | b |\n")
    assert mismatch(f) == (3, 2)


def test_temp_copy_of_real_file_with_wrong_header_fails(tmp_path):
    stated = [f for f in signing_files() if STATED.search(f.read_text(encoding="utf-8").splitlines()[0])]
    assert stated, "no signing file states a line count"
    for f in stated:
        text = f.read_text(encoding="utf-8")
        rows = len(set(ROW.findall(text)))
        lines = text.splitlines(True)
        lines[0] = STATED.sub(f"{rows + 1} lines", lines[0], count=1)
        copy = tmp_path / f.name
        copy.write_text("".join(lines), encoding="utf-8")
        assert mismatch(copy) == (rows + 1, rows)


def test_every_signing_header_count_matches_rows():
    files = signing_files()
    assert files, "no signing files found"
    bad = {f.name: mismatch(f) for f in files if mismatch(f)}
    assert not bad, f"header states (count, parsed rows) mismatch: {bad}"
