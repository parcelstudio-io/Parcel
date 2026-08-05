"""N-C1: ProposerBus + GoalArbiter + SigLIP stub."""

from __future__ import annotations

from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.instructnav.siglip import SigLIP2Matcher


def test_arbiter_prefers_priority_and_vetoes_ttl_and_lethal():
    arbiter = GoalArbiter(lethal_cost=lambda x, y: x > 9.0)
    now = 10.0
    goals = [
        SE2Goal(source="a", pose=(1.0, 0.0, 0.0), priority=1, issued_s=9.0, ttl_s=2.0),
        SE2Goal(source="b", pose=(2.0, 0.0, 0.0), priority=5, issued_s=9.5, ttl_s=2.0),
        SE2Goal(source="stale", pose=(0.0, 0.0, 0.0), priority=9, issued_s=0.0, ttl_s=1.0),
        SE2Goal(source="lethal", pose=(10.0, 0.0, 0.0), priority=9, issued_s=9.0, ttl_s=2.0),
    ]
    winner = arbiter.resolve(goals, now_s=now)
    assert winner is not None
    assert winner.source == "b"


def test_proposer_bus_publish_and_poll():
    bus = ProposerBus()

    def propose(*, now_s: float, **_kwargs):
        return SE2Goal(source="grounder", pose=(1.0, 2.0, 0.0), issued_s=now_s)

    bus.register("grounder", propose)
    goals = bus.poll(now_s=1.0)
    assert len(goals) == 1
    assert goals[0].pose == (1.0, 2.0, 0.0)


def test_siglip_degrades_loudly_to_string_match():
    matcher = SigLIP2Matcher(weights_dir="/tmp/parcel-missing-siglip")
    assert not matcher.available
    hit = matcher.match("streetlight", ["lamppost", "bench"])
    # string fallback: streetlight not substring of lamppost — None is ok;
    # alias path is caller's job. Exact-ish:
    hit2 = matcher.match("bench", ["lamppost", "bench"])
    assert hit2 is not None
    assert hit2.source == "string_fallback"
    assert hit is None or hit.source == "string_fallback"
