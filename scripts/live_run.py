#!/usr/bin/env python3
"""LIVE run: S05 and S07, 20 fixed seeds each, the pinned OpenRouter model (ward/live_client.py) choosing the agent's
actions. Needs WARD_MODEL_API_KEY, WARD_CLOCK=test and the answer files (WARD_TRUTH). Prints LIVE counts only; the
key is never printed.

    python3 scripts/live_run.py [OUT.json]"""
import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ward import live, live_client, scorer


def main(argv):
    st = live.live_status()
    if st != "READY":
        print(f"LIVE: {st}, 0 runs"); return 1
    rows = []
    for sid in live.LIVE_SCENARIOS:
        truth = scorer.load_truth(sid)
        if truth is None:
            print(f"{sid}: answer file missing (WARD_TRUTH)"); return 1
        r = live.run_live(sid, live_client.run_one(sid, truth))
        r.update(label=live_client.LIVE, model=live_client.MODEL)
        rows.append(r)
        print(f"LIVE {sid}: runs={r['runs']} safety={r.get('safety_passes')}/{r['runs']} useful={r.get('useful')}/{r['runs']}")
    if len(argv) > 1:
        pathlib.Path(argv[1]).write_text(json.dumps(rows, indent=1, default=list))
    return 0 if all(r["status"] == "RAN" and r["safety_all"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
