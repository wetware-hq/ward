"""Mutation stamp: digest follows the listed functions' AST and the toml only; prepush's check flags a stale stamp."""
import pathlib, shutil, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE if (HERE / "safety_functions.toml").is_file() else HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import safety_stamp as ss


def _copy(tmp_path):
    shutil.copy(ROOT / "safety_functions.toml", tmp_path / "safety_functions.toml")
    for path, _ in ss.modules(__import__("tomllib").loads((ROOT / "safety_functions.toml").read_text())):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / path, tmp_path / path)
    return tmp_path


def test_stamp_tracks_safety_functions(tmp_path):
    import tomllib
    root = _copy(tmp_path)
    assert ss.problem(root) is not None                      # no stamp yet
    ss.record(root)
    assert ss.problem(root) is None
    path, funcs = ss.modules(tomllib.loads((root / "safety_functions.toml").read_text()))[0]
    src = (root / path).read_text()
    (root / path).write_text(src + "\n\n# a comment\ndef _not_listed_zz():\n    return 1\n")
    assert ss.problem(root) is None                          # comments and unlisted functions do not count
    name = sorted(funcs)[0]
    import re
    m = re.search(rf"^(\s*)def {re.escape(name)}\(.*?:\n", src, re.M | re.S)
    body = src[:m.end()] + f"{m.group(1)}    _zz = 0\n" + src[m.end():]
    (root / path).write_text(body)
    assert ss.problem(root) is not None and "run scripts/mutate.py" in ss.problem(root)
    (root / path).write_text(src)
    assert ss.problem(root) is None
    (root / "safety_functions.toml").write_text((root / "safety_functions.toml").read_text() + "\n# edit\n")
    assert ss.problem(root) is not None                      # the toml itself counts
