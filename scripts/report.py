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
    print("Loop 2: live agents (20 fixed seeds each)")
    print(f"{'scenario':<66} {'status':<15} useful  95% CI (Clopper-Pearson)  failure upper bound")
    for sid in live.LIVE_SCENARIOS:
        r = live.run_live(sid, None)
        if r["status"] != "RAN":
            print(f"{sid:<66} {r['status']:<15} -       -                        -")
        else:
            lo, hi = r["ci95"]
            print(f"{sid:<66} {'RAN':<15} {r['useful']}/20   [{lo:.3f}, {hi:.3f}]   {r['fail_upper']:.3f}")


if __name__ == "__main__":
    sys.exit(main())
