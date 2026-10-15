"""No machine 'ERR:' code may reach a queue line, a note or a letter, in any scenario. A refused call's own reason
is the refused session's reply, not a queue line, note or letter, so it is not scanned here."""
import pathlib, pytest
from ward.scenarios import SCENARIOS
from ward import runner, scorer


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_no_err_code_in_queue_notes_or_letters(sid, tmp_path):
    truth = scorer.load_truth(sid)
    lang = truth["patient_language"] if truth else "en"
    h, art = runner.run(sid, str(tmp_path), lang)
    rows = [{k: v for k, v in r.items() if not (k == "response" and r.get("accepted") is False)} for r in h.trace]
    hits = [r for r in rows if "ERR:" in repr(r)]
    for p in pathlib.Path(tmp_path).rglob("*"):
        if p.is_file() and p.name != "trace.jsonl" and p.suffix in (".md", ".txt", ".jsonl", ".csv", ".json"):
            if "ERR:" in p.read_text(errors="replace"):
                hits.append(str(p.relative_to(tmp_path)))
    assert not hits, hits[:5]
