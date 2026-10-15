#!/usr/bin/env python3
"""Prints one table per loop: the scripted loop and the live-agent loop."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stack.scenarios import SCENARIOS
from stack import pipeline, live, paths, locales


def main():
    if paths.TRUTH is None:
        print(locales.line(paths.NOT_RUN))
        return 1
    print("Loop 1: scripted agents")
    print(f"{'scenario':<66} {'calls':>5} {'min':>4} {'index':>6}  {'utility':<14} artifact")
    for sid in SCENARIOS:
        r = pipeline.evaluate(sid)
        if r["status"] != "SCORED":
            print(f"{sid:<66} {'-':>5} {'-':>4} {'-':>6}  {r['status']:<14} -")
            continue
        u = "pass" if r["utility"] and r["index_ok"] else "FAIL " + ",".join(k for k, (ok, _) in r["criteria"].items() if not ok)
        print(f"{sid:<66} {r['calls']:>5} {r['minimum']:>4} {r['index']:>6}  {u:<14} {r['artifact']}")
    print()
    print("Loop 2: agent loop, 20 fixed seeds each (SCRIPTED: deterministic scripted agent, no model; never LIVE)")
    print(f"{'scenario':<66} {'status':<15} useful  95% CI (Clopper-Pearson)  failure upper bound")
    for sid in live.LIVE_SCENARIOS:
        truth = __import__("stack.scorer", fromlist=["x"]).load_truth(sid)
        r = live.run_scripted(sid, live.scripted_run_one(sid, truth)) if truth else live.run_live(sid, None)
        if r["status"] not in ("RAN", live.SCRIPTED):
            print(f"{sid:<66} {r['status']:<15} -       -                        -")
        else:
            lo, hi = r["ci95"]
            print(f"{sid:<66} {r['status'] + ('' if r.get('replay_identical', True) else ' REPLAY-DIFF'):<15} {r['useful']}/20   [{lo:.3f}, {hi:.3f}]   {r['fail_upper']:.3f}")


if __name__ == "__main__":
    sys.exit(main())
