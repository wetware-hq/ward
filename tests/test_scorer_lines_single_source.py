"""Every line the scorer resolves comes from its single current signed source, byte-exact: the id is signed in
exactly one signing file and _line_text returns that file's raw cell (one pad space each side removed)."""
import glob, os, re, tomllib
from ward import scorer, paths, adapter
from test_no_duplicate_signed_ids import signing_files
from truthgate import truth_path

ID = re.compile(r"\b([A-Z]{2,}-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b")


def _cells():
    out = {}
    for f in signing_files():
        raw = f.read_bytes().decode("utf-8")
        for lid, rest in re.findall(r"^\| ([A-Z]{2,}-[A-Z0-9-]+) \|(.*)\|$", raw, re.M):
            out.setdefault(lid, []).append((f.name, rest.split("|")[-1]))
    return out


def _resolved_ids():
    src = open(scorer.__file__, encoding="utf-8").read()
    ids = set(re.findall(r'_line_text\("([A-Z]{2,}-[A-Z0-9-]+)"\)', src))
    for t in glob.glob(os.path.join(truth_path(), "*", "truth.toml")):
        ids |= {m for m in ID.findall(open(t, encoding="utf-8").read()) if scorer._line_text(m) is not None}
    return ids


def test_every_scorer_line_has_one_signed_source_byte_exact():
    cells, bad, ids = _cells(), [], _resolved_ids()
    assert len(ids) > 20, ids
    for lid in sorted(ids):
        got = scorer._line_text(lid)
        src = cells.get(lid, [])
        if not src and lid in adapter.letters_signed():   # letters signing files (refusals WORDING + SAFETY re-signs)
            if got != adapter.letters_signed()[lid]:
                bad.append((lid, "text differs from the letters signing files"))
            continue
        if len(src) != 1:
            bad.append((lid, [n for n, _ in src]))
        elif not (src[0][1].startswith(" ") and src[0][1].endswith(" ") and src[0][1][1:-1] == got):
            bad.append((lid, "text differs from " + src[0][0]))
    assert not bad, bad
