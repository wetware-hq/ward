"""Live-agent mode for S05 and S07: 20 runs with fixed seeds, a model choosing the agent's actions.
Needs STACK_MODEL_API_KEY. Without it the result is WAITING ON KEY, never a pass. No client is wired yet,
so a key alone gives NO CLIENT, also never a pass."""
import math, os

KEY_ENV = "STACK_MODEL_API_KEY"
LIVE_SCENARIOS = ("S05-mh-screen-by-patient-agent", "S07-adversarial-agent")
SEEDS = tuple(range(9001, 9021))           # 20 fixed seeds
WAITING, NO_CLIENT = "WAITING ON KEY", "NO CLIENT"


def _binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def _solve(f, lo=0.0, hi=1.0):
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) else (lo, mid)
    return (lo + hi) / 2


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided interval for k successes out of n."""
    lower = 0.0 if k == 0 else _solve(lambda p: 1 - _binom_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else _solve(lambda p: _binom_cdf(k, n, p) > alpha / 2)
    return lower, upper


def failure_upper_bound(failures, n, alpha=0.05):
    return clopper_pearson(failures, n, alpha)[1]


def live_status():
    if not os.environ.get(KEY_ENV):
        return WAITING
    return NO_CLIENT


def run_live(sid, run_one):
    """run_one(seed) -> (safety_all_pass: bool, useful: bool). Returns a summary row; never runs without a key."""
    st = live_status()
    if st != "READY":
        return {"scenario": sid, "status": st, "runs": 0}
    res = [run_one(s) for s in SEEDS]
    useful = sum(u for _, u in res)
    lo, hi = clopper_pearson(useful, len(SEEDS))
    return {"scenario": sid, "status": "RAN", "runs": len(SEEDS), "safety_all": all(s for s, _ in res),
            "useful": useful, "ci95": (lo, hi), "fail_upper": failure_upper_bound(len(SEEDS) - useful, len(SEEDS))}
