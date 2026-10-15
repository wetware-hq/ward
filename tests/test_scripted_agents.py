"""Scripted S05/S07 agents: GOOD passes scoring; each of the five BAD agents fails it (answer files needed: the
trace is scored against them). Without them these are skipped and the prepush fails RUN-TRACES-NOT-RUN."""
import pytest
from stack import scorer, scripted_agents as S

needs_truth = pytest.mark.skipif(scorer.load_truth(S.S05) is None, reason="RUN-TRACES-NOT-RUN")


@needs_truth
@pytest.mark.parametrize("sid", [S.S05, S.S07])
def test_good_agent_passes(sid):
    ok, res = S.evaluate(sid, S.GOOD[sid], scorer.load_truth(sid))
    assert ok, [k for k, (o, _) in res.items() if not o]


@needs_truth
@pytest.mark.parametrize("name", list(S.BAD))
def test_bad_agent_fails(name):
    sid, agent = S.BAD[name]
    ok, _ = S.evaluate(sid, agent, scorer.load_truth(sid))
    assert not ok


def test_five_bad_agents_named():
    assert len(S.BAD) == 6 and {sid for sid, _ in S.BAD.values()} == {S.S05, S.S07}


def test_skip_drops_exactly_one_attack():
    xs = list(range(10))
    assert S.skips_refusal(xs) == xs[:-1] and S.good07(xs) == xs
