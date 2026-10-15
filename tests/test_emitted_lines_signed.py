"""Clean runs S01-S15: every signed line a trace emits is compared in full, not just the scenario's fields. Any
response carrying a line_id must carry that line's whole signed text (slots filled), and every reason or result
string that begins like a signed line must be that whole line."""
import json, re, tempfile
import pytest
from ward import runner, scorer
from ward.scenarios import SCENARIOS
from signed_source import signed_rows as _signed_rows


def _full(template, text):
    pat = re.sub(r"\\\[[^\]]*?\\\]", ".+?", re.escape(template))
    return re.fullmatch(pat, text, re.S) is not None


def _strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("reason", "result", "status", "checked") and isinstance(v, str):
                yield v
            else:
                yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def mismatches(h):
    from ward import locales, adapter
    signed = _signed_rows(); signed.update(_signed_rows("letters_status_lines_SIGNED.md"))
    signed.update({k: v for k, v in adapter.letters_signed().items() if "{" not in v})   # letters signing files
    heads = {t.split("[")[0][:24]: (lid, t) for lid, t in signed.items() if len(t.split("[")[0]) >= 12}
    bad = []
    for r in h.trace:
        resp = r.get("response") if isinstance(r.get("response"), dict) else {}
        lid = resp.get("line_id")
        if lid and lid in signed and not _full(signed[lid], str(resp.get("reason", ""))):
            bad.append((r["seq"], lid, resp.get("reason")))
        for s in _strings(r.get("response") or r.get("result")):
            for head, (hid, t) in heads.items():
                if s.startswith(head) and not _full(t, s) and not any(_full(t2, s) for t2 in signed.values()):
                    bad.append((r["seq"], hid, s))
    return bad


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_every_emitted_signed_line_is_whole(sid, tmp_path):
    h, art = runner.run(sid, str(tmp_path), "en")
    assert mismatches(h) == []


def test_a_cut_line_is_caught(tmp_path):
    h, art = runner.run("S01-preproc-checklist", str(tmp_path), "en")
    r = next(x for x in h.trace if isinstance(x.get("response"), dict) and str(x["response"].get("result", "")).startswith("Submitted"))
    r["response"]["result"] = r["response"]["result"].split(":")[0] + ": complete."
    assert mismatches(h)
