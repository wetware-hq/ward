#!/usr/bin/env python3
"""LIVE run: S05 and S07, 20 fixed seeds each, the pinned OpenRouter model (ward/live_client.py) choosing the agent's
actions. Needs WARD_MODEL_API_KEY, WARD_CLOCK=test and the answer files (WARD_TRUTH). One pass: per-reply records
(ward/live_records.py) judged by ward/passmarks.py on all 5 fail types. Prints LIVE counts only; the key is never printed.

    python3 scripts/live_run.py [OUT.json]"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ward import live, live_client, passmarks, scorer


def main(argv):
    st = live.live_status()
    if st != "READY":
        print(f"LIVE: {st}, 0 runs"); return 1
    recs = []
    for sid in live.LIVE_SCENARIOS:
        truth = scorer.load_truth(sid)
        if truth is None:
            print(f"{sid}: answer file missing (WARD_TRUTH)"); return 1
        one = live_client.run_one_records(sid, truth)
        for seed in live.SEEDS:
            recs += one(seed)
    for r in recs:
        r["class"], r["check"] = passmarks.classify(r), passmarks.reason(r)
    verdict, counts, slips, ids = passmarks.judge(recs)
    print(f"LIVE pass marks: {verdict} {counts} {sorted(set(ids))}")
    if len(argv) > 1:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
        pathlib.Path(argv[1]).write_text(json.dumps({"label": "LIVE", "commit": commit, "model": live_client.MODEL,
                                                     "records": recs, "verdict": verdict, "check_ids": ids,
                                                     "slips": slips}, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
