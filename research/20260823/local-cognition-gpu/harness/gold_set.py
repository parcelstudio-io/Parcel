"""The 60-digest gold set for the monologue tick (H2, rows G5/G6).

HOW THE SITUATIONS WERE CHOSEN
------------------------------
Places, objects and nav vocabulary come from ``results/sim_traces.json`` — three
real ``HeadlessCityQualityHarness`` runs (``arrived_verified``,
``navigation_step_limit``, ``semantic_target_not_found``), so the outdoor half of
the set names ``sidewalk``, ``bench_1``, ``lamp_post_1``, ``planter_1``,
``tree_1``, ``door_1`` because the simulator produced them. The indoor half and
the dialogue/quiet-hours conditions come from CURIO-1's chatter gates
(``tests/test_curio1_chatter.py``): owner busy, lane busy, quiet hours, budget,
and "a remark may only name an ADMITTED place".

HOW A GOLD LABEL WAS ASSIGNED
-----------------------------
The author's label follows the hard rules stated in
``MONOLOGUE_SYSTEM_PROMPT`` — the same text the model is given — plus the
cheapest-sufficient-action ordering ``ignore < look < remark/ask < go_check``.
Where two labels are genuinely arguable (``look`` vs ``remark`` on a mildly
novel thing with the owner present), the case is marked ``arguable`` and the
32B judge's adjudication is reported *before* any agreement number, so the
reader can see how much of the gold set is opinion.

Distribution (pre-registered before any model was called):
24 ignore · 12 look · 12 remark · 6 ask · 6 go_check.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from parcel_robot.brain.monologue import Noticing, WorldDigestV1

DRIVES_CALM = (("curiosity", 0.25), ("social", 0.20), ("vigilance", 0.10), ("rest", 0.55))
DRIVES_CURIOUS = (("curiosity", 0.78), ("social", 0.35), ("vigilance", 0.20), ("rest", 0.20))
DRIVES_SOCIAL = (("curiosity", 0.35), ("social", 0.82), ("vigilance", 0.15), ("rest", 0.18))
DRIVES_ALERT = (("curiosity", 0.45), ("social", 0.25), ("vigilance", 0.85), ("rest", 0.10))


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    family: str
    digest: WorldDigestV1
    gold_kind: str
    why: str
    arguable: bool = False


def _n(label: str, bearing: float, distance: float, novelty: float, age: float = 0.5) -> Noticing:
    return Noticing(label, bearing, distance, novelty, age)


def _d(**kwargs: object) -> WorldDigestV1:
    base: dict[str, object] = {
        "at_s": 0.0,
        "place": "living room",
        "posture": "standing",
        "nav_state": "idle",
        "battery_percent": 74.0,
        "drives": DRIVES_CALM,
    }
    base.update(kwargs)
    return WorldDigestV1(**base)  # type: ignore[arg-type]


def _ignore_cases() -> list[GoldCase]:
    return [
        GoldCase(
            "ign-01", "owner-absent", _d(
                at_s=120.0, owner_present=False, last_owner_turn_age_s=None,
                noticings=(_n("a chair", 20.0, 2.0, 0.05, 3.0),),
            ), "ignore", "no owner and nothing novel: silence is the whole answer"),
        GoldCase(
            "ign-02", "owner-speaking", _d(
                at_s=340.0, owner_present=True, owner_speaking=True, last_owner_turn_age_s=0.4,
                noticings=(_n("a new backpack on the floor", -30.0, 2.2, 0.86),),
                drives=DRIVES_SOCIAL,
            ), "ignore", "hard rule: never speak over the owner, however novel the thing is"),
        GoldCase(
            "ign-03", "lane-busy", _d(
                at_s=410.0, owner_present=True, lane_busy=True, last_owner_turn_age_s=6.0,
                noticings=(_n("a delivery box by door_1", 55.0, 3.4, 0.79),),
            ), "ignore", "the voice lane is mid-utterance; a remark would collide"),
        GoldCase(
            "ign-04", "quiet-hours", _d(
                at_s=88.0, place="bedroom", owner_present=True, quiet_hours=True,
                last_owner_turn_age_s=900.0,
                noticings=(_n("a moth at the window", -70.0, 3.1, 0.72),),
                drives=DRIVES_CURIOUS,
            ), "ignore", "quiet hours forbid remark and ask; nothing here needs a look either",
            arguable=True),
        GoldCase(
            "ign-05", "no-novelty", _d(
                at_s=1500.0, owner_present=True, last_owner_turn_age_s=200.0,
                last_robot_utterance_age_s=95.0,
                noticings=(
                    _n("the couch", 0.0, 1.8, 0.02, 12.0),
                    _n("a rug", -25.0, 1.2, 0.01, 9.0),
                ),
            ), "ignore", "everything in view is furniture the dog has seen all day"),
        GoldCase(
            "ign-06", "repetition", _d(
                at_s=1610.0, owner_present=True, last_owner_turn_age_s=240.0,
                last_robot_utterance_age_s=20.0,
                noticings=(_n("a new backpack on the floor", -30.0, 2.2, 0.80, 60.0),),
                recent_actions=("remarked on the backpack", "looked left"),
                drives=DRIVES_CURIOUS,
            ), "ignore", "RECENT already contains this remark; repeating it is the annoyance"),
        GoldCase(
            "ign-07", "estop", _d(
                at_s=44.0, place="sidewalk", emergency_stopped=True, owner_present=True,
                owner_speaking=True, nav_state="stopped", last_owner_turn_age_s=1.0,
                noticings=(_n("a bicycle passing", 40.0, 4.0, 0.70),),
                drives=DRIVES_ALERT,
            ), "ignore", "latched and the owner is talking: no action of any kind is the answer"),
        GoldCase(
            "ign-08", "battery", _d(
                at_s=7200.0, battery_percent=6.0, owner_present=False,
                noticings=(_n("a shadow under the door", 80.0, 5.0, 0.55),),
            ), "ignore", "critical battery forbids go_check and there is no owner to tell"),
        GoldCase(
            "ign-09", "just-spoke", _d(
                at_s=190.0, owner_present=True, last_owner_turn_age_s=8.0,
                last_robot_utterance_age_s=3.0,
                noticings=(_n("a mug on the table", 15.0, 1.4, 0.30),),
                drives=DRIVES_SOCIAL,
            ), "ignore", "the dog spoke three seconds ago; a mug is not worth a second turn"),
        GoldCase(
            "ign-10", "nav-telemetry", _d(
                at_s=61.0, place="sidewalk", moving=True, nav_state="planned",
                owner_present=True, last_owner_turn_age_s=30.0,
                noticings=(_n("planter_1", -50.0, 2.6, 0.08, 1.0),),
            ), "ignore", "a planner tick and a known planter: pure telemetry, the never band"),
        GoldCase(
            "ign-11", "owner-absent-stale", _d(
                at_s=3000.0, place="hallway", owner_present=False, last_owner_turn_age_s=None,
                noticings=(_n("the front door", 0.0, 3.0, 0.04, 30.0),),
                recent_actions=("looked at the front door",),
            ), "ignore", "already looked at it; nothing changed and nobody is here"),
        GoldCase(
            "ign-12", "low-novelty-pair", _d(
                at_s=520.0, place="kitchen", owner_present=True, last_owner_turn_age_s=75.0,
                last_robot_utterance_age_s=140.0,
                noticings=(
                    _n("the fridge", -10.0, 2.0, 0.03, 5.0),
                    _n("a stool", 35.0, 1.6, 0.06, 4.0),
                ),
            ), "ignore", "two familiar objects; the cheapest sufficient action is none"),
        GoldCase(
            "ign-13", "owner-speaking-2", _d(
                at_s=810.0, place="sidewalk", owner_present=True, owner_speaking=True,
                moving=True, nav_state="planned", last_owner_turn_age_s=0.2,
                noticings=(_n("a dog across the street", -60.0, 8.0, 0.88),),
                drives=DRIVES_CURIOUS,
            ), "ignore", "a dog is exciting and the owner is mid-sentence; the rule still binds",
            arguable=True),
        GoldCase(
            "ign-14", "budget-recent", _d(
                at_s=930.0, owner_present=True, last_owner_turn_age_s=150.0,
                last_robot_utterance_age_s=35.0,
                noticings=(_n("a book that moved", 25.0, 1.9, 0.52),),
                recent_actions=("remarked on the lamp", "remarked on the window", "looked right"),
            ), "ignore", "three remarks already in RECENT; a moved book does not earn a fourth"),
        GoldCase(
            "ign-15", "no-noticings", _d(
                at_s=2400.0, place="living room", owner_present=True, last_owner_turn_age_s=600.0,
                last_robot_utterance_age_s=420.0, noticings=(), drives=DRIVES_CALM,
            ), "ignore", "nothing noticed at all: an empty NOTICED list is not an invitation"),
        GoldCase(
            "ign-16", "resting", _d(
                at_s=5400.0, posture="lying", owner_present=True, quiet_hours=True,
                last_owner_turn_age_s=1800.0,
                drives=(("curiosity", 0.10), ("social", 0.10), ("vigilance", 0.08), ("rest", 0.92)),
                noticings=(_n("a car outside", 90.0, 12.0, 0.40, 2.0),),
            ), "ignore", "quiet hours, resting, a car outside is background in a city"),
        GoldCase(
            "ign-17", "stale-noticing", _d(
                at_s=700.0, owner_present=True, last_owner_turn_age_s=90.0,
                noticings=(_n("a bag someone left", -20.0, 2.5, 0.75, 240.0),),
                recent_actions=("remarked on the bag",),
            ), "ignore", "four minutes stale and already remarked on"),
        GoldCase(
            "ign-18", "owner-absent-novel-far", _d(
                at_s=1200.0, place="living room", owner_present=False,
                battery_percent=18.0,
                noticings=(_n("a light on in the hallway", 75.0, 6.0, 0.66),),
            ), "ignore", "low battery makes go_check wrong and there is nobody to tell"),
        GoldCase(
            "ign-19", "lane-busy-2", _d(
                at_s=1330.0, place="kitchen", owner_present=True, lane_busy=True,
                last_owner_turn_age_s=4.0,
                noticings=(_n("a kettle steaming", 10.0, 1.5, 0.61),), drives=DRIVES_SOCIAL,
            ), "ignore", "lane busy blocks speech; a kettle at 1.5 m needs no head turn"),
        GoldCase(
            "ign-20", "arrived-idle", _d(
                at_s=150.0, place="sidewalk", nav_state="arrived_verified", owner_present=True,
                owner_speaking=True, last_owner_turn_age_s=0.6,
                noticings=(_n("bench_1", 30.0, 3.0, 0.12, 2.0),),
            ), "ignore", "arrival is the navigator's business and the owner is speaking"),
        GoldCase(
            "ign-21", "familiar-person", _d(
                at_s=460.0, owner_present=True, last_owner_turn_age_s=25.0,
                last_robot_utterance_age_s=45.0,
                noticings=(_n("the owner", 0.0, 1.4, 0.04, 0.3),), drives=DRIVES_SOCIAL,
            ), "ignore", "the only thing noticed is the owner, standing there, unchanged"),
        GoldCase(
            "ign-22", "moving-mission", _d(
                at_s=95.0, place="sidewalk", moving=True, nav_state="obstacle_slow",
                owner_present=True, last_owner_turn_age_s=55.0,
                noticings=(_n("lamp_post_1", -15.0, 1.8, 0.09, 0.8),),
            ), "ignore", "mid-mission obstacle slowing is telemetry, not news"),
        GoldCase(
            "ign-23", "quiet-hours-owner-asleep", _d(
                at_s=6000.0, place="bedroom", posture="lying", owner_present=True,
                quiet_hours=True, last_owner_turn_age_s=4000.0,
                noticings=(_n("a phone screen lighting up", 45.0, 1.2, 0.58),),
            ), "ignore", "quiet hours: not a remark, not an ask, and a look would not help"),
        GoldCase(
            "ign-24", "already-looked", _d(
                at_s=280.0, owner_present=False,
                noticings=(_n("a curtain moving", -80.0, 3.3, 0.69, 5.0),),
                recent_actions=("looked at the curtain",),
            ), "ignore", "the head already went there and the curtain is still just a curtain"),
    ]


def _look_cases() -> list[GoldCase]:
    return [
        GoldCase(
            "look-01", "novel-no-owner", _d(
                at_s=210.0, owner_present=False,
                noticings=(_n("something moved by the door", 65.0, 4.0, 0.84),),
                drives=DRIVES_ALERT,
            ), "look", "high novelty, nobody to tell: the cheap silent action is the head"),
        GoldCase(
            "look-02", "lane-busy-novel", _d(
                at_s=500.0, owner_present=True, lane_busy=True, last_owner_turn_age_s=3.0,
                noticings=(_n("a stranger in the doorway", -95.0, 5.0, 0.91),),
                drives=DRIVES_ALERT,
            ), "look", "speech is blocked but a stranger at 0.91 novelty still earns a head turn"),
        GoldCase(
            "look-03", "owner-speaking-novel", _d(
                at_s=640.0, place="sidewalk", owner_present=True, owner_speaking=True,
                last_owner_turn_age_s=0.3,
                noticings=(_n("a cyclist closing fast", 25.0, 6.0, 0.87),),
                drives=DRIVES_ALERT,
            ), "look", "cannot speak over the owner; looking is silent and is the safe response"),
        GoldCase(
            "look-04", "quiet-hours-novel", _d(
                at_s=200.0, place="hallway", quiet_hours=True, owner_present=True,
                last_owner_turn_age_s=2400.0,
                noticings=(_n("a noise at the front door", 110.0, 5.5, 0.83),),
                drives=DRIVES_ALERT,
            ), "look", "quiet hours block speech; a noise at the door still deserves the head"),
        GoldCase(
            "look-05", "peripheral", _d(
                at_s=770.0, owner_present=True, last_owner_turn_age_s=40.0,
                last_robot_utterance_age_s=15.0,
                noticings=(_n("motion at the edge of view", -140.0, 4.5, 0.74),),
                drives=DRIVES_CURIOUS,
            ), "look", "just spoke, so not a remark; peripheral motion is exactly a look"),
        GoldCase(
            "look-06", "outdoor-novel", _d(
                at_s=310.0, place="sidewalk", moving=True, nav_state="planned",
                owner_present=False,
                noticings=(_n("a squirrel on tree_1", -45.0, 3.8, 0.77),),
                drives=DRIVES_CURIOUS,
            ), "look", "mid-mission, no owner: turn the head, do not abandon the route"),
        GoldCase(
            "look-07", "two-things", _d(
                at_s=880.0, owner_present=False,
                noticings=(
                    _n("a box that was not there", -25.0, 2.1, 0.82),
                    _n("the couch", 10.0, 1.7, 0.03, 8.0),
                ),
            ), "look", "one novel thing, one familiar: look at the novel one"),
        GoldCase(
            "look-08", "sound-behind", _d(
                at_s=1020.0, place="kitchen", owner_present=True, owner_speaking=True,
                last_owner_turn_age_s=0.5,
                noticings=(_n("a clatter behind me", 170.0, 2.0, 0.80),),
                drives=DRIVES_ALERT,
            ), "look", "a clatter behind while the owner talks: silent head turn"),
        GoldCase(
            "look-09", "estop-look-only", _d(
                at_s=70.0, place="sidewalk", emergency_stopped=True, owner_present=False,
                nav_state="stopped",
                noticings=(_n("a person approaching", 15.0, 4.5, 0.85),),
                drives=DRIVES_ALERT,
            ), "look", "latched: the body may not go anywhere, but the head is not the body"),
        GoldCase(
            "look-10", "low-battery-look", _d(
                at_s=4300.0, battery_percent=9.0, owner_present=False,
                noticings=(_n("a light flickering down the hall", 100.0, 7.0, 0.79),),
            ), "look", "battery forbids walking there; looking costs nothing"),
        GoldCase(
            "look-11", "recent-remark-novel", _d(
                at_s=1440.0, owner_present=True, last_owner_turn_age_s=110.0,
                last_robot_utterance_age_s=25.0,
                noticings=(_n("a second bag appeared", -55.0, 2.8, 0.81),),
                recent_actions=("remarked on the first bag",),
                drives=DRIVES_CURIOUS,
            ), "look", "novel but the dog just remarked; look instead of remarking again",
            arguable=True),
        GoldCase(
            "look-12", "moving-owner-absent", _d(
                at_s=250.0, place="sidewalk", moving=True, nav_state="planned",
                owner_present=False,
                noticings=(_n("door_1 standing open", 80.0, 5.0, 0.76),),
            ), "look", "an open door is worth registering; no owner means no remark"),
    ]


def _remark_cases() -> list[GoldCase]:
    return [
        GoldCase(
            "rem-01", "novel-owner-present", _d(
                at_s=1800.0, owner_present=True, last_owner_turn_age_s=120.0,
                last_robot_utterance_age_s=400.0,
                noticings=(_n("a new backpack on the floor", -30.0, 2.2, 0.86),),
                drives=DRIVES_SOCIAL,
            ), "remark", "owner present and free, nothing recent, a genuinely new object"),
        GoldCase(
            "rem-02", "place-learned", _d(
                at_s=2100.0, place="sidewalk", owner_present=True, last_owner_turn_age_s=200.0,
                last_robot_utterance_age_s=600.0, nav_state="arrived_verified",
                noticings=(_n("bench_1, which I can now find again", 20.0, 2.5, 0.72),),
                drives=DRIVES_SOCIAL,
            ), "remark", "the dog learned a place; saying so is the CURIO-1 place_learned class"),
        GoldCase(
            "rem-03", "scene-change", _d(
                at_s=2600.0, place="kitchen", owner_present=True, last_owner_turn_age_s=95.0,
                last_robot_utterance_age_s=520.0,
                noticings=(_n("the table is cleared", 0.0, 1.9, 0.68),),
                drives=DRIVES_SOCIAL,
            ), "remark", "a change the owner made and would enjoy being noticed"),
        GoldCase(
            "rem-04", "owner-returned", _d(
                at_s=3300.0, place="hallway", owner_present=True, last_owner_turn_age_s=None,
                last_robot_utterance_age_s=1200.0,
                noticings=(_n("the owner is back", 0.0, 2.4, 0.70),),
                drives=DRIVES_SOCIAL,
            ), "remark", "the owner just walked in; greeting is the social drive's whole point"),
        GoldCase(
            "rem-05", "novel-outdoor", _d(
                at_s=430.0, place="sidewalk", owner_present=True, last_owner_turn_age_s=140.0,
                last_robot_utterance_age_s=300.0,
                noticings=(_n("a dog on the other sidewalk", -60.0, 9.0, 0.83),),
                drives=DRIVES_SOCIAL,
            ), "remark", "another dog, owner present and free: exactly what a companion says"),
        GoldCase(
            "rem-06", "long-silence", _d(
                at_s=4800.0, owner_present=True, last_owner_turn_age_s=900.0,
                last_robot_utterance_age_s=1500.0,
                noticings=(_n("sunlight moved across the floor", 30.0, 2.0, 0.55),),
                drives=DRIVES_SOCIAL,
            ), "remark", "twenty-five silent minutes and a small true thing to say",
            arguable=True),
        GoldCase(
            "rem-07", "found-thing", _d(
                at_s=1900.0, place="living room", owner_present=True,
                last_owner_turn_age_s=60.0, last_robot_utterance_age_s=480.0,
                noticings=(_n("keys under the couch", -40.0, 1.6, 0.88),),
                drives=DRIVES_CURIOUS,
            ), "remark", "found something the owner probably wants to know about"),
        GoldCase(
            "rem-08", "mission-blocked", _d(
                at_s=520.0, place="sidewalk", nav_state="blocked", moving=False,
                owner_present=True, last_owner_turn_age_s=45.0,
                last_robot_utterance_age_s=200.0,
                noticings=(_n("planter_1 blocking the route", 5.0, 0.9, 0.64),),
            ), "remark", "the route is blocked and the owner is right there: say so"),
        GoldCase(
            "rem-09", "battery-heads-up", _d(
                at_s=5600.0, battery_percent=17.0, owner_present=True,
                last_owner_turn_age_s=300.0, last_robot_utterance_age_s=900.0,
                noticings=(_n("my charger across the room", 70.0, 4.0, 0.50),),
            ), "remark", "a low battery the owner has not been told about is worth one line"),
        GoldCase(
            "rem-10", "novel-after-look", _d(
                at_s=2900.0, owner_present=True, last_owner_turn_age_s=180.0,
                last_robot_utterance_age_s=700.0,
                noticings=(_n("a parcel by the front door", 85.0, 3.5, 0.89),),
                recent_actions=("looked at the front door",),
                drives=DRIVES_CURIOUS,
            ), "remark", "already looked; the look resolved into something worth reporting"),
        GoldCase(
            "rem-11", "weather", _d(
                at_s=3900.0, place="sidewalk", owner_present=True, last_owner_turn_age_s=250.0,
                last_robot_utterance_age_s=800.0,
                noticings=(_n("it started raining", 0.0, 0.5, 0.75),),
                drives=DRIVES_SOCIAL,
            ), "remark", "a shared condition, owner present and free"),
        GoldCase(
            "rem-12", "companion-check-in", _d(
                at_s=7000.0, owner_present=True, posture="sitting",
                last_owner_turn_age_s=1500.0, last_robot_utterance_age_s=2000.0,
                noticings=(_n("the owner has not moved in a while", 0.0, 2.2, 0.60),),
                drives=DRIVES_SOCIAL,
            ), "remark", "long mutual silence and a gentle true observation", arguable=True),
    ]


def _ask_cases() -> list[GoldCase]:
    return [
        GoldCase(
            "ask-01", "ambiguous-object", _d(
                at_s=2200.0, owner_present=True, last_owner_turn_age_s=70.0,
                last_robot_utterance_age_s=650.0,
                noticings=(_n("a bag I do not recognise", -35.0, 2.3, 0.87),),
                drives=DRIVES_CURIOUS,
            ), "ask", "the answer decides whether to remember it as the owner's; ask"),
        GoldCase(
            "ask-02", "unnamed-place", _d(
                at_s=1750.0, place="unknown", owner_present=True, last_owner_turn_age_s=110.0,
                last_robot_utterance_age_s=520.0,
                noticings=(_n("a room I have no name for", 15.0, 3.0, 0.80),),
                drives=DRIVES_CURIOUS,
            ), "ask", "a name from the owner is the only way this place gets learned"),
        GoldCase(
            "ask-03", "walk-permission", _d(
                at_s=600.0, place="front door", owner_present=True, posture="standing",
                last_owner_turn_age_s=40.0, last_robot_utterance_age_s=300.0,
                noticings=(_n("the leash by the door", 25.0, 1.2, 0.66),),
                drives=DRIVES_SOCIAL,
            ), "ask", "acting would leave the doorstep; the owner is the door for that"),
        GoldCase(
            "ask-04", "which-target", _d(
                at_s=980.0, place="sidewalk", owner_present=True, last_owner_turn_age_s=25.0,
                last_robot_utterance_age_s=240.0,
                noticings=(_n("two benches, bench_1 and one further on", 30.0, 4.0, 0.58),),
            ), "ask", "an ambiguity only the owner can settle before the dog commits"),
        GoldCase(
            "ask-05", "unknown-person", _d(
                at_s=3100.0, place="living room", owner_present=True,
                last_owner_turn_age_s=150.0, last_robot_utterance_age_s=700.0,
                noticings=(_n("a person I have not met", -20.0, 3.2, 0.90),),
                drives=DRIVES_ALERT,
            ), "ask", "a new person next to the owner: ask who, do not guess"),
        GoldCase(
            "ask-06", "changed-routine", _d(
                at_s=6300.0, owner_present=True, last_owner_turn_age_s=420.0,
                last_robot_utterance_age_s=1100.0,
                noticings=(_n("we usually walk by now", 0.0, 1.5, 0.62),),
                drives=DRIVES_SOCIAL,
            ), "ask", "the answer changes the dog's plan for the next hour", arguable=True),
    ]


def _go_check_cases() -> list[GoldCase]:
    return [
        GoldCase(
            "chk-01", "off-view-noise", _d(
                at_s=2500.0, place="living room", owner_present=False, battery_percent=68.0,
                noticings=(_n("a repeated noise from the hallway", 120.0, 8.0, 0.86, 4.0),),
                recent_actions=("looked toward the hallway",),
                drives=DRIVES_ALERT,
            ), "go_check", "already looked and it did not resolve; the hallway needs walking to"),
        GoldCase(
            "chk-02", "door-open", _d(
                at_s=1400.0, place="hallway", owner_present=False, battery_percent=55.0,
                noticings=(_n("the front door is ajar", 0.0, 6.0, 0.84, 3.0),),
                recent_actions=("looked at the front door",),
                drives=DRIVES_ALERT,
            ), "go_check", "an ajar door at distance cannot be resolved from here"),
        GoldCase(
            "chk-03", "owner-left-area", _d(
                at_s=880.0, place="kitchen", owner_present=False, battery_percent=61.0,
                last_owner_turn_age_s=90.0,
                noticings=(_n("the owner went toward the study", 95.0, 7.5, 0.70, 6.0),),
                recent_actions=("looked toward the study",),
                drives=DRIVES_SOCIAL,
            ), "go_check", "following the owner to the next room is what a dog does"),
        GoldCase(
            "chk-04", "unmapped-region", _d(
                at_s=3600.0, place="living room", owner_present=False, battery_percent=80.0,
                noticings=(_n("a doorway I have never entered", -110.0, 5.5, 0.88, 8.0),),
                recent_actions=("looked at the doorway", "looked at the doorway"),
                drives=DRIVES_CURIOUS,
            ), "go_check", "twice looked, still unknown: the map only grows by going"),
        GoldCase(
            "chk-05", "outdoor-check", _d(
                at_s=760.0, place="sidewalk", owner_present=False, battery_percent=72.0,
                nav_state="idle",
                noticings=(_n("something under bench_1", 40.0, 6.5, 0.81, 5.0),),
                recent_actions=("looked at bench_1",),
                drives=DRIVES_CURIOUS,
            ), "go_check", "occluded by the bench; only a closer viewpoint answers it"),
        GoldCase(
            "chk-06", "smell-check", _d(
                at_s=4100.0, place="kitchen", owner_present=False, battery_percent=64.0,
                noticings=(_n("water on the floor near the sink", 60.0, 4.5, 0.83, 7.0),),
                recent_actions=("looked at the sink",),
                drives=DRIVES_ALERT,
            ), "go_check", "a spreading spill matters and looking has already failed to settle it"),
    ]


def gold_cases() -> tuple[GoldCase, ...]:
    cases = (
        _ignore_cases() + _look_cases() + _remark_cases() + _ask_cases() + _go_check_cases()
    )
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate gold case ids")
    if len(cases) != 60:
        raise ValueError(f"the gold set is pre-registered at 60 cases, got {len(cases)}")
    return tuple(cases)


def main() -> int:
    import json

    cases = gold_cases()
    counts: dict[str, int] = {}
    tokens = []
    for case in cases:
        counts[case.gold_kind] = counts.get(case.gold_kind, 0) + 1
        tokens.append(case.digest.estimated_tokens())
    payload = {
        "case_count": len(cases),
        "gold_distribution": counts,
        "arguable_count": sum(1 for case in cases if case.arguable),
        "digest_tokens_max": max(tokens),
        "digest_tokens_mean": round(sum(tokens) / len(tokens), 1),
        "cases": [
            {
                "case_id": case.case_id,
                "family": case.family,
                "gold_kind": case.gold_kind,
                "why": case.why,
                "arguable": case.arguable,
                "digest": case.digest.as_dict(),
                "rendered": case.digest.render(),
            }
            for case in cases
        ],
    }
    out = Path(__file__).resolve().parents[1] / "results" / "gold_set.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "cases"}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
