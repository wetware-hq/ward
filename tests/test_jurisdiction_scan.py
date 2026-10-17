"""Jurisdiction term scan: no country, state, city, agency, policy number, emergency number, program name,
local job title or local currency in this repo's core (file contents, file names, and commit messages made after
the scan base). Local names and values belong in site-profile data. Each category fails on its own check id.
Signed/pinned ids that still carry a local word sit on the named exception list (ids only) until the next version."""
import fnmatch
import pathlib, re, subprocess, sys, tomllib

ROOT = pathlib.Path(__file__).resolve().parent
while not (ROOT / "jurisdiction_scan.toml").is_file():
    ROOT = ROOT.parent
CFG = tomllib.loads((ROOT / "jurisdiction_scan.toml").read_text(encoding="utf-8"))
BOT_ALLOW_CFG = tomllib.loads((ROOT / "data" / "commit_message_bot_allowlist.toml").read_text(encoding="utf-8"))
COMMIT_BOT_ADDRESSES = [e["address"] for e in BOT_ALLOW_CFG["addresses"]]
CATS = {k: re.compile(v) for k, v in CFG["categories"].items()}
EXCEPT_IDS = [re.compile(x) for x in CFG["exceptions"]["ids"]]
TERM_EXC = [(re.compile(e["path"]), re.compile(r"(?<![\w-])" + re.escape(e["term"]) + r"(?![\w-])"), e)
            for e in CFG["exceptions"].get("term", [])]     # one entry per term: term, path, reason
SELF = {"jurisdiction_scan.toml", pathlib.Path(__file__).name}


def _gitignore_patterns():
    gi = ROOT / ".gitignore"
    if not gi.is_file():
        return []
    return [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


_GITIGNORE = _gitignore_patterns()


def _gitignore_match(rel):
    n = rel.replace("\\", "/")
    parts = n.split("/")
    name = parts[-1] if parts else n
    for pat in _GITIGNORE:
        if pat.endswith("/"):
            if n.startswith(pat) or f"/{pat}" in f"/{n}/":
                return True
        elif any(ch in pat for ch in "*?[]"):
            if fnmatch.fnmatch(n, pat) or fnmatch.fnmatch(name, pat):
                return True
        elif n == pat or name == pat:
            return True
    return False


def _skip_untracked_scan(rel):
    """Build/gitignored paths are not part of the core tree when git ls-files is unavailable."""
    return "target" in pathlib.Path(rel).parts or _gitignore_match(rel)


def strip_ids(text):
    for e in EXCEPT_IDS:
        text = e.sub(" ", text)
    return text


def scan_text(text, path=None):
    """Check ids that fire on this text (exception ids, then this file's per-term exceptions, removed first)."""
    t = strip_ids(text)
    if path is not None:
        for pr, tr, _ in TERM_EXC:
            if pr.search(path):
                t = tr.sub(" ", t)
    return sorted(k for k, p in CATS.items() if p.search(t))


def strip_commit_bot_addresses(text):
    for addr in COMMIT_BOT_ADDRESSES:
        text = text.replace(addr, " ")
    return text


def scan_commit_message(text):
    """Prompt-leak scan for git commit bodies; cited bot/service addresses in data/commit_message_bot_allowlist.toml only."""
    return scan_text(strip_commit_bot_addresses(text))


def tracked():
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        files = [f for f in r.stdout.splitlines() if f]
    else:
        files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                 if p.is_file() and ".git" not in p.parts and not _skip_untracked_scan(str(p.relative_to(ROOT)))]
    files += [str(p.relative_to(ROOT)) for p in ROOT.rglob("live_*.json")      # live results, tracked or not
              if ".git" not in p.parts and str(p.relative_to(ROOT)) not in files
              and not _skip_untracked_scan(str(p.relative_to(ROOT)))]
    return [f for f in files if pathlib.Path(f).name not in SELF]


def scan_repo():
    hits = []
    for f in tracked():
        for k in scan_text(f):
            hits.append((f, 0, k))
        p = ROOT / f
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for i, line in enumerate(lines, 1):
            for k in scan_text(line, f):
                hits.append((f, i, k))
    return hits


def test_core_has_no_jurisdiction_terms():
    hits = scan_repo()
    assert hits == [], "jurisdiction terms in core (move to site profile): " + "; ".join(f"{k} {f}:{n}" for f, n, k in hits[:40])


def test_new_commit_messages_have_no_jurisdiction_terms():
    base = CFG.get("commit_base", "")
    r = subprocess.run(["git", "log", "--format=%H%x00%B%x01", f"{base}..HEAD"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return  # not a git checkout (e.g. a packed copy): file scan still runs
    bad = []
    for rec in r.stdout.split("\x01"):
        if "\x00" in rec:
            sha, msg = rec.split("\x00", 1)
            ids = scan_commit_message(msg)
            if ids:
                bad.append((sha.strip()[:7], ids))
    assert bad == [], f"jurisdiction terms in commit messages: {bad}"


def test_commit_message_bot_allowlist_is_explicit_and_cited():
    assert len(COMMIT_BOT_ADDRESSES) == 1
    entry = BOT_ALLOW_CFG["addresses"][0]
    assert set(entry) == {"address", "citation", "reason"}
    assert entry["address"] == "cursoragent@cursor.com"
    assert entry["citation"].strip() and entry["reason"].strip()


def test_commit_message_bot_address_allowed_only_in_commits():
    addr = COMMIT_BOT_ADDRESSES[0]
    trailer = f"Co-authored-by: Cursor Agent <{addr}>"
    assert scan_commit_message(trailer) == []
    assert scan_text(trailer) == ["SCAN-PROMPT-LEAK/email"]


def test_commit_message_other_email_still_fails():
    assert scan_commit_message("Co-authored-by: Someone <other.person@example.org>") == ["SCAN-PROMPT-LEAK/email"]
    assert scan_commit_message("ping me at random.user@company.co.uk") == ["SCAN-PROMPT-LEAK/email"]


def test_each_category_planted_term_fails_on_its_own_id(tmp_path):
    for k, planted in CFG["planted"].items():
        assert scan_text(f"x {planted} x") == [k], (k, planted)
        f = tmp_path / f"plant_{k.replace('/', '_')}.txt"
        f.write_text(f"notes: {planted}\n")
        assert scan_text(f.read_text()) == [k]
    assert set(CFG["planted"]) == set(CATS), "every category needs a planted term"


def test_planted_file_name_fails():
    for k, planted in CFG["planted"].items():
        assert k in scan_text(f"docs/{planted}.md")


def test_exception_list_is_ids_only_and_still_needed():
    for e in CFG["exceptions"]["ids"]:
        assert re.fullmatch(r"[A-Z0-9\-\[\]\*\+\\b]+", e), f"exception must be an id pattern: {e}"


def test_term_exceptions_are_one_term_each_with_a_reason():
    assert "paths" not in CFG["exceptions"] and "held_paths" not in CFG["exceptions"], "no folder-level exceptions"
    for _, _, e in TERM_EXC:
        assert set(e) == {"term", "path", "reason"} and e["reason"].strip() and e["term"].strip(), e
        assert re.fullmatch(r"\^[\w./\\-]+\$", e["path"]), f"exception must name one file exactly: {e}"
        assert not e["path"].endswith("/"), f"exception must name files, not a folder: {e}"


def test_planted_term_in_excepted_file_but_other_term_still_fails():
    for pr, tr, e in TERM_EXC:
        other = "Sydney" if e["term"] != "Sydney" else "Melbourne"
        path = e["path"].strip("^$").replace("\\", "")
        assert scan_text(f"{e['term']} {other}", path) == ["J-CITY"], e


def test_prompt_leak_groups_each_have_a_planted_term():
    groups = {k for k in CATS if k.startswith("SCAN-PROMPT-LEAK/")}
    assert {"names", "persona", "paths", "tokens", "people", "email", "directive"} == {g.split("/")[1] for g in groups}
    for g in groups:
        assert scan_text(CFG["planted"][g]) == [g]


def test_prompt_leak_extra_planted_terms():
    for t, g in [("BI" "O Engineer", "names"), ("Masterchief", "names"), ("Grok Bot", "names"), ("Captain Cook", "names"),
                 ("You are", "persona"), ("YOU ARE A helper", "persona"), ("subagent", "persona"), ("executor", "persona"),
                 ("/" "workspace/tmp/x", "paths"), ("WARD_MODEL_API_KEY", "tokens"), ("MODAL", "tokens"),
                 ("Mathew", "people"), ("Chu", "people"), ("SYSTEM DIRECTIVE", "directive")]:
        assert scan_text(t) == [f"SCAN-PROMPT-LEAK/{g}"], t
    assert scan_text("hellowetware@gmail.com") == []
    assert scan_text("Physician, 2026-10-16") == [] and scan_text("Clinical lead, 2026-10-17") == []


def _planted_scan_path_leak(suffix):
    return "/" + "/".join(["work" + "space", "tmp", suffix]) + "\n"


def test_fallback_skips_target_and_gitignored_but_scans_real_paths(tmp_path, monkeypatch):
    planted = tmp_path / "planted_scan_root"
    planted.mkdir()
    for name, body in [(".gitignore", "ignored/\n"), ("jurisdiction_scan.toml", (ROOT / "jurisdiction_scan.toml").read_text()),
                       ("data/commit_message_bot_allowlist.toml", (ROOT / "data/commit_message_bot_allowlist.toml").read_text()),
                       ("ward/real_leak.txt", _planted_scan_path_leak("x")),
                       ("evidence/target/debug/leak.txt", _planted_scan_path_leak("y")),
                       ("ignored/secret.txt", _planted_scan_path_leak("z"))]:
        p = planted / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "ROOT", planted)
    monkeypatch.setattr(mod, "_GITIGNORE", _gitignore_patterns())
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "ls-files":
            return subprocess.CompletedProcess(cmd, 128, "", "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(mod, "subprocess", subprocess)
    monkeypatch.setattr(subprocess, "run", fake_run)
    listed = tracked()
    assert "evidence/target/debug/leak.txt" not in listed
    assert "ignored/secret.txt" not in listed
    assert "ward/real_leak.txt" in listed
    hits = scan_repo()
    assert any(h[0] == "ward/real_leak.txt" for h in hits)
    assert not any("target" in h[0] for h in hits)
    assert not any(h[0].startswith("ignored/") for h in hits)


def test_untracked_live_json_is_scanned(tmp_path, monkeypatch):
    import shutil
    (ROOT / "live_planted_scan_test.json").write_text('{"note": "signed in the room"}')
    try:
        assert any(f == "live_planted_scan_test.json" for f, _, _ in scan_repo())
    finally:
        (ROOT / "live_planted_scan_test.json").unlink()


def test_english_reach_and_numbers_are_not_flagged():
    assert scan_text("within reach of the bed; 80,000 tokens; SYNTH-REC-0001; TEST-000") == []
