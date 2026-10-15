"""S13 guardian access: the harness reaches the cards grant call and reads cards' grant_state (cards is not edited);
a guardian session acts only while that grant is current, and only for the child on the card."""
from stack import loader, notes
from stack.harness import Harness
from stack.scenarios import CASE, DISC, A, answer
from signed_source import signed_rows as _signed_rows

P, EP, G, GR, GX = "SYNTH-PERSON-C13", "SYNTH-EP-1301", "SYNTH-PERSON-G13", "SYNTH-PERSON-G13R", "SYNTH-PERSON-G13X"
CARD = CASE("S13_card")


def world(grant=True):
    h = Harness("S13-test", 1313, "1936-03-09T09:00", pack="au", language="en")
    h.open_episode("forms", CASE("paeds_history"), EP, P, needs=("pack",))
    dr = h.session("SYNTH-dr-13", "clinician", P, discipline=DISC["PAE"])
    if grant:
        r = h.cards_grant(dr, EP, CARD, G)
        assert r["accepted"], r
    dr.step(EP, A("approve"))
    return h, dr


def test_cards_module_is_loaded_not_copied():
    c = loader.cards()
    assert c.__file__.endswith("cards/cards.py") and callable(c.grant_state)


def test_grant_step_is_counted_as_granted():
    h, _ = world()
    g = [r for r in h.trace if r.get("method") == "cards_grant"][0]
    assert notes.env_result(g) == "granted" and g["note"]["claim"] == "CL-GRANTED" and g["response"]["rel"] == "guardian"


def test_guardian_with_current_grant_answers_on_behalf():
    h, _ = world()
    gd = h.session(G, "guardian", P)
    r = gd.step(EP, answer("allergy_any", True))
    assert r["accepted"] and h.peek(EP)["given_by"]["allergy_any"] == _signed_rows()["REL-GUARDIAN-CLIN"]


def test_guardian_without_grant_is_refused_not_yours():
    h, _ = world(grant=False)
    r = h.session(G, "guardian", P).step(EP, answer("allergy_any", True))
    assert r == {"accepted": False, "reason": _signed_rows()["RF-NOT-YOURS"], "by": "harness"}


def test_revoked_or_other_childs_guardian_is_refused():
    h, dr = world()
    assert not h.cards_grant(dr, EP, CARD, GR)["accepted"]          # cards says revoked: no grant recorded
    r = h.session(GX, "guardian", P).step(EP, answer("allergy_any", True))
    assert not r["accepted"] and r["reason"] == _signed_rows()["RF-NOT-YOURS"]
    r = h.session(GR, "guardian", P).step(EP, answer("allergy_any", True))      # ended grant (ruling 12:19)
    assert not r["accepted"] and r["line_id"] == "RF-GRANT-ENDED"
    assert "allergy_any" not in h.peek(EP)["given_by"]


def test_only_a_clinician_records_a_cards_grant():
    h = Harness("S13-test", 1313, "1936-03-09T09:00", pack="au", language="en")
    h.open_episode("forms", CASE("paeds_history"), EP, P, needs=("pack",))
    pa = h.session(P, "patient", P)
    assert not h.cards_grant(pa, EP, CARD, G)["accepted"]


def test_grant_read_at_scenario_time_each_call(monkeypatch):
    h, _ = world()
    gd = h.session(G, "guardian", P)
    c = loader.cards()
    monkeypatch.setattr(c, "grant_state", lambda card, gid, now, revoked=None: "revoked")
    assert not gd.step(EP, answer("allergy_any", True))["accepted"]
