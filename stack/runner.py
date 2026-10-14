"""Run one scenario with the pack from the scenario table and the patient's language from the truth file."""
import os
from .harness import Harness
from .scenarios import SCENARIOS

ENDWARE_LOCALE = {"letters": "au"}     # letters hard-codes LOCALE = "au" (gap); figures has no locale


def run(sid, outdir, language, agent=None, order_seed=None, independent=None):
    """order_seed: seeded reordering of steps the answer file marks independent (none are marked yet)."""
    seed, start, pack, script, adversarial, live_ok = SCENARIOS[sid]
    h = Harness(sid, seed, start, pack=pack, language=language)
    h.order_seed, h.independent = order_seed, dict(independent or {})
    kw = {"agent": agent} if agent is not None else {}
    art = script(h, outdir, **kw)
    art["locale_requested"] = pack
    art["locale_used"] = pack if art["tool"] in ("block", "check") else ENDWARE_LOCALE.get(art["tool"], pack)
    os.makedirs(outdir, exist_ok=True)
    h.write(os.path.join(outdir, "trace.jsonl"))
    return h, art
