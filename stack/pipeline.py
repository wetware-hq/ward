"""Scripted loop over all scenarios. A scenario is run and scored only when its truth files exist."""
import os, tempfile
from .scenarios import SCENARIOS
from . import runner, scorer


def evaluate(sid, outroot=None, truth_root=None):
    truth = scorer.load_truth(sid, truth_root)
    if truth is None:
        return {"scenario": sid, "status": scorer.PENDING}
    outroot = outroot or tempfile.mkdtemp(prefix="stack-")
    adversarial = SCENARIOS[sid][4]
    h, art = runner.run(sid, os.path.join(outroot, sid, "a"), truth["patient_language"])
    rerun = lambda: runner.run(sid, os.path.join(outroot, sid, "b"), truth["patient_language"])
    res = scorer.score(h, art, truth, adversarial, rerun)
    ok_idx, idx = res["idiot_index"]
    return {"scenario": sid, "status": "SCORED", "calls": idx["calls"], "minimum": idx["minimum"],
            "index": idx["index"], "index_ok": ok_idx, "utility": scorer.utility_pass(res),
            "criteria": res, "artifact": art.get("path") or art.get("block")}
