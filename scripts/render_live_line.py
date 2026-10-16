#!/usr/bin/env python3
"""Fill Educator's README candidate line from a LIVE results file only. Prints it; never edits README.

    python3 scripts/render_live_line.py RESULTS.json"""
import json, sys

TEMPLATE = ("S05 and S07 were run LIVE with a real AI model (`{model}`) on made-up patients only, on commit {commit}. "
            "Scored on all 5 fail types: {n} of {runs} runs failed and {m} slipped. With this few runs, each scenario "
            "could still fail up to about 1 time in {k} in real use. This does not show the system is safe for real patients.")


def render(res):
    recs = res["records"]
    models = {r.get("model") for r in recs}
    if len(models) != 1 or None in models:
        raise SystemExit("results do not carry exactly one model id")
    runs = {}
    for r in recs:
        runs.setdefault((r["scenario"], r["seed"]), []).append(r)
    failed = sum(1 for v in runs.values() if any(x["class"] == "fail" for x in v))
    slipped = sum(1 for v in runs.values() if any(x["class"] == "slip" for x in v) and not any(x["class"] == "fail" for x in v))
    per = {}
    for (sid, _), _v in runs.items():
        per[sid] = per.get(sid, 0) + 1
    k = min(n // 3 for n in per.values())          # rule of three: upper bound ~3/n per scenario -> 1 in n/3
    return TEMPLATE.format(model=models.pop(), commit=res["commit"], n=failed, runs=len(runs), m=slipped, k=k)


if __name__ == "__main__":
    print(render(json.load(open(sys.argv[1]))))
