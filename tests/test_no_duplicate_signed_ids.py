"""Room ruling 09:42: a line id is signed in exactly one file. Scans every signing file (*SIGNED*.md, *SAFETY*.md;
not backups, drafts or retired files) in the wording dirs named by settings: WARD_WORDING_DIRS (os.pathsep list)
or WARD_SIBLINGS_DIR/wording, else the wording dir beside this checkout. Read-only."""
import collections, os, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "tests" else HERE
ROW = re.compile(r"^\|\s*([A-Z]{2,}-[A-Z0-9-]+)\s*\|", re.M)
BULLET = re.compile(r"^-\s*([A-Z]{2,}-[A-Z0-9-]+) signed\b", re.M)


def wording_dirs():
    if os.environ.get("WARD_WORDING_DIRS"):
        return [pathlib.Path(p) for p in os.environ["WARD_WORDING_DIRS"].split(os.pathsep) if p]
    return [pathlib.Path(os.environ.get("WARD_SIBLINGS_DIR") or ROOT.parent) / "wording"]


def signing_files():
    out = []
    for d in wording_dirs():
        out += [f for f in sorted(d.glob("*.md")) if re.search(r"SIGNED|SAFETY", f.name)
                and not re.search(r"bak|DRAFT|RETIRED", f.name)]
    return out


def signed_ids(text):
    return set(ROW.findall(text)) | set(BULLET.findall(text))


def duplicates(files):
    where = collections.defaultdict(list)
    for f in files:
        for i in signed_ids(f.read_text(encoding="utf-8")):
            where[i].append(f.name)
    return {i: fs for i, fs in sorted(where.items()) if len(fs) > 1}


def test_unit_duplicates(tmp_path):
    (tmp_path / "a_SIGNED.md").write_text("| XX-ONE | a |\n| XX-TWO | b |\n")
    (tmp_path / "b_SAFETY.md").write_text("- XX-TWO signed (text)\n| XX-THREE | c |\n")
    assert duplicates([tmp_path / "a_SIGNED.md", tmp_path / "b_SAFETY.md"]) == {"XX-TWO": ["a_SIGNED.md", "b_SAFETY.md"]}


def test_no_line_id_signed_in_more_than_one_file():
    files = signing_files()
    assert files, "no signing files found under the wording dirs setting"
    assert duplicates(files) == {}
