"""Card ROAM-2 — "explore" covers the room.

ROAM-1 proved the dog goes somewhere on command and comes back, and said so
about itself: *"It does not prove the dog explores. It proves the dog WANDERS
under a budget without hitting anything. There is no coverage objective, no
frontier, no memory of where it has been."* This file is the objective.

Three pieces and three groups below:

* **the map's one new reader** — ``OnlineSemanticMap.coverage_candidates``,
  least recently seen first, body-frame bearings, the map's OWN visibility rule
  deciding what the robot can already see. It is a reader: a test here proves
  it changes nothing;
* **the policy** — ``PatrolLimits.coverage_bias``, DEFAULT OFF so MOVE-1's and
  ROAM-1's measured baselines cannot move, and last in the yield ladder so a
  map can never argue with a wall, a person or the tether;
* **the runtime** — the ROAM-1 region asking the map once per tick, outside
  every runtime lock, and degrading to ROAM-1's wander whenever the map has
  nothing to say.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision
from parcel_robot.online_map.entries import STATUS_DECAYED, MapObservation, WriterProvenance
from parcel_robot.online_map.hygiene import prior_for
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.patrol.mission import (
    PatrolCommand,
    PatrolLimits,
    PatrolPolicy,
    PatrolSense,
    limits_from_safety,
    sense_from_snapshot,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
PROFILE_ENV = "PARCEL_PROFILE"
BACKEND_NAME = "roam2-test"

PROV = WriterProvenance(
    session_id="roam2-test",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)


# --------------------------------------------------------------------------
# 1. the map's one new reader
# --------------------------------------------------------------------------


def _observation(
    label: str, x: float, y: float, *, wall_s: float, frame_id: str = "f1"
) -> MapObservation:
    """One admissible observation, sized by C-2's OWN prior for the label.

    The extents come from ``prior_for`` rather than from a literal, because
    C-2's hygiene gate refuses a place that is the wrong size for its class and
    a fixture with hand-picked numbers silently stops creating entries the day
    somebody re-tunes a prior.
    """

    prior, _key = prior_for(label)
    return MapObservation(
        label=label,
        score=0.6,
        surface_x=x,
        surface_y=y,
        surface_z=1.0,
        range_m=4.0,
        bearing_rad=0.0,
        depth_m=4.0,
        extent_w_m=(prior.min_w_m + prior.max_w_m) / 2.0,
        extent_h_m=(prior.min_h_m + prior.max_h_m) / 2.0,
        inlier_pixels=900,
        frame_id=frame_id,
        visit_id="v1",
        observed_wall_s=wall_s,
        robot_x=0.0,
        robot_y=0.0,
        provenance=PROV,
    )


def _map_with(*places: tuple[str, float, float, float]) -> OnlineSemanticMap:
    """A map holding one entry per ``(label, x, y, last_seen_wall_s)``."""

    learned = OnlineSemanticMap(provenance=PROV)
    for index, (label, x, y, wall_s) in enumerate(places):
        learned.note_frame(queries=(label,))
        learned.observe(_observation(label, x, y, wall_s=wall_s, frame_id=f"f{index}"))
    return learned


def test_the_query_ranks_least_recently_seen_first() -> None:
    """The whole objective in one assertion: oldest place, first row."""

    learned = _map_with(
        ("bench", 0.0, 20.0, 900.0),  # seen most recently
        ("lamppost", 20.0, 0.0, 100.0),  # seen longest ago
        ("planter", -20.0, 0.0, 500.0),
    )
    rows = learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0)
    assert [row["label"] for row in rows] == ["lamppost", "planter", "bench"]
    assert [row["age_s"] for row in rows] == [900.0, 500.0, 100.0]


def test_an_age_the_clock_cannot_compute_sorts_last_and_says_so() -> None:
    """``None``, never zero. Zero reads as "seen just now" and hides the place."""

    learned = _map_with(
        ("lamppost", 20.0, 0.0, 100.0),
        ("bench", 0.0, 20.0, 5000.0),  # stamped AFTER the clock: skew
    )
    rows = learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0)
    assert [row["label"] for row in rows] == ["lamppost", "bench"]
    assert rows[0]["age_s"] == 900.0
    assert rows[1]["age_s"] is None

    # No clock at all is the same answer for every row, and still not zero.
    blind = learned.coverage_candidates(0.0, 0.0, 0.0)
    assert {row["age_s"] for row in blind} == {None}


def test_the_query_hides_what_the_robot_can_already_see() -> None:
    """The map's OWN visibility rule, the one ``close_visit`` decays against."""

    learned = _map_with(
        ("bench", 2.0, 0.0, 100.0),  # 2 m away: in view
        ("lamppost", 20.0, 0.0, 100.0),  # 20 m away: not
    )
    rows = learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0)
    assert [row["label"] for row in rows] == ["lamppost"]
    assert rows[0]["visibility_range_m"] == pytest.approx(8.0)

    everything = learned.coverage_candidates(
        0.0, 0.0, 0.0, now_wall_s=1000.0, exclude_visible=False
    )
    assert {row["label"]: row["within_visibility"] for row in everything} == {
        "bench": True,
        "lamppost": False,
    }


def test_the_bearing_is_in_the_body_frame() -> None:
    """Same frame as ``PatrolSense.person_bearing_rad``, or the policy steers wrong."""

    learned = _map_with(("lamppost", 0.0, 20.0, 100.0))
    ahead = learned.coverage_candidates(0.0, 0.0, math.pi / 2, now_wall_s=1000.0)
    assert ahead[0]["bearing_rad"] == pytest.approx(0.0, abs=1e-3)
    to_port = learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0)
    assert to_port[0]["bearing_rad"] == pytest.approx(math.pi / 2, abs=1e-3)
    behind = learned.coverage_candidates(0.0, 0.0, -math.pi / 2, now_wall_s=1000.0)
    assert abs(behind[0]["bearing_rad"]) == pytest.approx(math.pi, abs=1e-3)


def test_an_empty_map_answers_with_an_empty_tuple_not_an_error() -> None:
    """"Nothing to go and look at" is a real answer and must not raise."""

    learned = OnlineSemanticMap(provenance=PROV)
    assert learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0) == ()
    # A pose the caller could not measure is refused as an empty answer too.
    assert learned.coverage_candidates(float("nan"), 0.0, 0.0) == ()


def test_a_decayed_place_is_not_a_coverage_objective() -> None:
    """A place the map stopped believing must not be somewhere to walk to."""

    learned = _map_with(("lamppost", 20.0, 0.0, 100.0), ("bench", 0.0, 20.0, 200.0))
    for entry in learned.entries():
        if entry.label == "lamppost":
            entry.mark_decayed(1000.0, "test")
            assert entry.status == STATUS_DECAYED
    rows = learned.coverage_candidates(0.0, 0.0, 0.0, now_wall_s=1000.0)
    assert [row["label"] for row in rows] == ["bench"]


def test_the_coverage_query_is_a_READER_and_changes_nothing() -> None:
    """The card says "one public query, not the writer". This is that claim."""

    learned = _map_with(("lamppost", 20.0, 0.0, 100.0), ("bench", 0.0, 20.0, 200.0))
    before = [
        (e.entry_id, e.label, e.surface_x, e.surface_y, e.last_seen_wall_s,
         e.status, e.detection_count, e.evidence_frames, len(e.history))
        for e in learned.entries()
    ]
    stats_before = learned.stats()
    for _ in range(5):
        learned.coverage_candidates(1.0, 2.0, 0.3, now_wall_s=2000.0)
    after = [
        (e.entry_id, e.label, e.surface_x, e.surface_y, e.last_seen_wall_s,
         e.status, e.detection_count, e.evidence_frames, len(e.history))
        for e in learned.entries()
    ]
    assert after == before
    assert learned.stats() == stats_before


# --------------------------------------------------------------------------
# 2. the policy — default OFF, and last in the ladder
# --------------------------------------------------------------------------


def _sense(**kwargs) -> PatrolSense:
    base = {
        "elapsed_s": 1.0,
        "x": 0.0,
        "y": 0.0,
        "yaw": 0.0,
        "forward_clearance_m": 6.0,
        "person_clearance_m": 6.0,
        "person_bearing_rad": math.pi,
    }
    base.update(kwargs)
    return PatrolSense(**base)  # type: ignore[arg-type]


def test_coverage_is_off_by_default_so_the_measured_baselines_cannot_move() -> None:
    """MOVE-1's and ROAM-1's numbers are a purchase input. They do not move."""

    assert PatrolLimits().coverage_bias is False
    shipped = PatrolPolicy(PatrolLimits())
    with_objective = shipped.step(_sense(coverage_bearing_rad=1.5, coverage_age_s=900.0))
    assert with_objective == PatrolCommand(vx=0.25, reason="advance")
    assert shipped.coverage_legs == 0


def test_the_default_off_policy_is_INDIFFERENT_to_the_objective() -> None:
    """Not just "still advances" — the same command sequence, tick for tick."""

    ticks = [
        {"elapsed_s": 1.0, "forward_clearance_m": 6.0},
        {"elapsed_s": 1.25, "forward_clearance_m": 1.0},
        {"elapsed_s": 1.5, "forward_clearance_m": 6.0},
        {"elapsed_s": 1.75, "forward_clearance_m": 6.0},
    ]
    blind = PatrolPolicy(PatrolLimits())
    told = PatrolPolicy(PatrolLimits())
    for tick in ticks:
        a = blind.step(_sense(**tick))
        b = told.step(_sense(coverage_bearing_rad=2.9, coverage_age_s=4000.0, **tick))
        assert a == b


def test_the_objective_is_off_at_every_layer_until_a_profile_says_otherwise() -> None:
    """DEFAULTS OFF, all the way down — the wave's standing rule, as a test.

    The 17:38 draft of this card defaulted the objective ON in
    ``limits_from_safety`` (the roam behaviour's only constructor) on the
    reasoning that the prototype should explore. That is a behaviour change
    nobody wrote in a profile, which is exactly what ``../TASK_BOARD.md`` rule
    1 forbids, so all three layers now default OFF and the ONLY thing that can
    turn the objective on is ``roam: {coverage: true}`` in words.

    This is also what makes ROAM-2's baseline arm a real baseline: flag-off,
    the roam behaviour is ROAM-1's, and the two measured arms differ by one
    config line (``PREREGISTRATION.md`` §2).
    """

    assert PatrolLimits().coverage_bias is False
    assert limits_from_safety(person_stop_m=0.7, obstacle_stop_m=0.65).coverage_bias is False
    on = limits_from_safety(person_stop_m=0.7, obstacle_stop_m=0.65, coverage_bias=True)
    assert on.coverage_bias is True


def _roaming_limits(**kwargs) -> PatrolLimits:
    """The ROAMING limits — i.e. the objective explicitly ON, as a profile does."""

    kwargs.setdefault("coverage_bias", True)
    return limits_from_safety(person_stop_m=0.7, obstacle_stop_m=0.65, **kwargs)


def test_the_patrol_turns_onto_the_least_recently_seen_bearing() -> None:
    """SEED S1's guard: without the objective the patrol just walks on."""

    policy = PatrolPolicy(_roaming_limits())
    command = policy.step(_sense(coverage_bearing_rad=1.5, coverage_age_s=900.0))
    assert command.reason == "turn_coverage"
    assert command.vyaw > 0.0  # to port, because the objective is to port
    assert command.vx == 0.0
    mirrored = PatrolPolicy(_roaming_limits())
    assert mirrored.step(_sense(coverage_bearing_rad=-1.5, coverage_age_s=900.0)).vyaw < 0.0


def test_a_leg_is_counted_when_the_alignment_converges() -> None:
    """A leg is an alignment that CONVERGED and became a walk. Counted once."""

    policy = PatrolPolicy(_roaming_limits())
    assert policy.step(_sense(coverage_bearing_rad=1.5, coverage_age_s=900.0)).reason == (
        "turn_coverage"
    )
    assert policy.coverage_legs == 0
    assert policy.coverage_aligning is True
    walked = policy.step(
        _sense(elapsed_s=2.0, coverage_bearing_rad=0.1, coverage_age_s=900.0)
    )
    assert walked.reason == "advance_coverage"
    assert walked.vx > 0.0
    assert policy.coverage_legs == 1
    assert policy.coverage_aligning is False
    # Walking on down the same leg does not count a second one.
    policy.step(_sense(elapsed_s=2.25, coverage_bearing_rad=0.05, coverage_age_s=900.0))
    assert policy.coverage_legs == 1


def test_a_stale_map_wanders_it_never_stops() -> None:
    """SEED S2's guard, and it is four different kinds of "nothing to say"."""

    cases = {
        "no bearing at all": {"coverage_bearing_rad": None, "coverage_age_s": 900.0},
        "no computable age": {"coverage_bearing_rad": 1.5, "coverage_age_s": None},
        "seen a moment ago": {"coverage_bearing_rad": 1.5, "coverage_age_s": 1.0},
        "nothing supplied": {},
    }
    for name, kwargs in cases.items():
        policy = PatrolPolicy(_roaming_limits())
        command = policy.step(_sense(**kwargs))
        assert command.reason == "advance", name
        assert command.vx > 0.0, f"{name}: a stale map must never stop the dog"
        assert command.vyaw == 0.0, name
        assert policy.coverage_legs == 0, name


def test_a_stale_map_mid_leg_finishes_as_a_wander_rather_than_stalling() -> None:
    """The map going quiet under a walking dog is a wander, not a halt."""

    policy = PatrolPolicy(_roaming_limits())
    policy.step(_sense(coverage_bearing_rad=1.5, coverage_age_s=900.0))
    assert policy.coverage_aligning is True
    lost = policy.step(_sense(elapsed_s=1.25))
    assert lost == PatrolCommand(vx=0.25, reason="advance")
    assert policy.coverage_aligning is False


def test_a_coverage_leg_never_crosses_the_tether() -> None:
    """SEED S3's guard: the tether outranks the objective, always."""

    policy = PatrolPolicy(_roaming_limits(tether_m=10.0))
    # Latch home at the origin.
    policy.step(_sense(x=0.0, y=0.0, coverage_bearing_rad=0.0, coverage_age_s=900.0))
    # Now 12 m out along +y, nose still pointing away from home, with the
    # objective pointing further out still.
    out = _sense(
        elapsed_s=30.0,
        x=0.0,
        y=12.0,
        yaw=math.pi / 2,
        coverage_bearing_rad=0.0,
        coverage_age_s=4000.0,
    )
    command = policy.step(out)
    assert command.reason == "turn_tether"
    assert command.vx == 0.0


def test_a_person_and_a_wall_both_outrank_the_objective() -> None:
    """Yield order: contact, person, tether, geometry, hysteresis, THEN coverage."""

    person = PatrolPolicy(_roaming_limits())
    blocked = person.step(
        _sense(
            person_clearance_m=0.2,
            person_bearing_rad=0.0,
            coverage_bearing_rad=1.5,
            coverage_age_s=900.0,
        )
    )
    assert blocked.reason == "turn_person"

    wall = PatrolPolicy(_roaming_limits())
    assert wall.step(
        _sense(forward_clearance_m=0.2, coverage_bearing_rad=1.5, coverage_age_s=900.0)
    ).reason == "turn_blocked"

    contact = PatrolPolicy(_roaming_limits())
    assert contact.step(
        _sense(collision=True, coverage_bearing_rad=1.5, coverage_age_s=900.0)
    ).reason == "turn_contact"

    spent = PatrolPolicy(_roaming_limits(budget_s=10.0))
    assert spent.step(
        _sense(elapsed_s=11.0, coverage_bearing_rad=1.5, coverage_age_s=900.0)
    ).reason == "budget_exhausted"


def test_an_alignment_that_cannot_converge_gives_up_and_walks() -> None:
    """An unreachable objective may not spend the budget turning on the spot."""

    # ``replace`` rather than a seventh argument on ``limits_from_safety``:
    # the give-up window is a package constant, not something the reactive
    # gate's thresholds derive, and the roam behaviour has no business tuning it.
    limits = replace(_roaming_limits(), coverage_giveup_after_s=2.0)
    policy = PatrolPolicy(limits)
    elapsed = 1.0
    reasons: list[str] = []
    for _ in range(24):
        reasons.append(
            policy.step(
                _sense(elapsed_s=elapsed, coverage_bearing_rad=2.9, coverage_age_s=900.0)
            ).reason
        )
        elapsed += 0.25
    assert "advance" in reasons, "an unreachable objective must release the dog"
    assert reasons.count("turn_coverage") < len(reasons)
    # And the cool-off keeps it from re-adopting the same bearing every tick:
    # each give-up buys at least one whole hold window of walking.
    assert reasons.count("advance") >= 4


def test_a_nonsense_objective_is_refused_rather_than_read_as_zero() -> None:
    """A NaN bearing compares False against every threshold. Refuse it loudly."""

    with pytest.raises(ValueError, match="coverage_bearing_rad must be finite"):
        _sense(coverage_bearing_rad=float("nan"), coverage_age_s=10.0)
    with pytest.raises(ValueError, match="coverage_age_s must be finite"):
        _sense(coverage_bearing_rad=0.1, coverage_age_s=-4.0)
    with pytest.raises(ValueError, match="coverage_align_tolerance_rad"):
        PatrolLimits(coverage_align_tolerance_rad=0.0)
    with pytest.raises(ValueError, match="coverage_min_age_s"):
        PatrolLimits(coverage_min_age_s=-1.0)


def test_the_sensing_adapter_carries_the_objective_and_defaults_to_none() -> None:
    """``sense_from_snapshot`` builds a byte-identical sense for every old caller."""

    payload = {"robot": {"x": 1.0, "y": 2.0, "heading": 90.0}, "obstacle_distance_m": 5.0}
    plain = sense_from_snapshot(payload, elapsed_s=3.0)
    assert plain is not None
    assert plain.coverage_bearing_rad is None and plain.coverage_age_s is None
    told = sense_from_snapshot(
        payload, elapsed_s=3.0, coverage_bearing_rad=0.4, coverage_age_s=77.0
    )
    assert told is not None
    assert told == replace(plain, coverage_bearing_rad=0.4, coverage_age_s=77.0)


# --------------------------------------------------------------------------
# 3. the runtime — the ROAM-1 region asking P1-B's map
# --------------------------------------------------------------------------


class _Backend:
    name = BACKEND_NAME

    def __init__(self) -> None:
        self.timestamp = 1.0
        self.obstacle_m = 10.0
        self.commands: list[object] = []

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=self.timestamp,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=self.obstacle_m,
            backend=BACKEND_NAME,
        )

    def move(self, command: object) -> None:
        self.commands.append(command)

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        return AgentDecision("Understood.")


#: The one config line that turns the coverage objective on. It is a literal
#: rather than a helper because it is the SAME line the measured arm B runs
#: with (``PREREGISTRATION.md`` §2) and a reader should see it spelled out.
COVERAGE_ON = "roam:\n  coverage: true\n"


def _runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, overlay: str | None = None
) -> RobotRuntime:
    """ROAM-1's own fixture shape: a real runtime, no simulator, no model.

    ``overlay`` defaults to ``None`` — i.e. NO ``roam:`` block, which is the
    shipped default and therefore coverage OFF. Tests that are about the
    objective pass :data:`COVERAGE_ON`, which is deliberate: it means every one
    of them exercises the same profile key an operator would write.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("PARCEL_REALTIME_CONFIG", raising=False)
    path = tmp_path / "roam2-robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    if overlay is None:
        monkeypatch.delenv(PROFILE_ENV, raising=False)
    else:
        (tmp_path / "roam2-robot.demo.yaml").write_text(overlay, encoding="utf-8")
        monkeypatch.setenv(PROFILE_ENV, "demo")
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="roam2 fixture",
        ),
    )


def _fresh(runtime: RobotRuntime) -> SimObservation:
    import time as _time

    runtime.backend.timestamp = _time.monotonic()
    return runtime.backend.observe()


def _install_map(runtime: RobotRuntime, learned: OnlineSemanticMap) -> None:
    """Attach a learned map the way ``_p1b_install_learned_map`` leaves one."""

    runtime._p1b_learned_map = learned


def test_a_runtime_with_no_learned_map_still_roams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipping ``oracle`` source, and every run before P1-B. Wander, never stop."""

    runtime = _runtime(tmp_path / "nomap", monkeypatch, overlay=COVERAGE_ON)
    try:
        assert runtime._p1b_learned_map is None
        runtime.start_roam()
        runtime._step_roam(_fresh(runtime))
        snapshot = runtime.roam_snapshot()
        assert snapshot["active"] is True
        assert snapshot["reason"] == "advance"
        coverage = snapshot["coverage"]
        assert coverage["enabled"] is True
        assert coverage["target"] is None and coverage["candidates"] == 0
        assert coverage["legs"] == 0
    finally:
        runtime.close()


def test_the_roam_asks_the_map_and_the_policy_steers_at_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The product path: the runtime's own tick, P1-B's map, ROAM-1's policy."""

    import time as _time

    runtime = _runtime(tmp_path / "steer", monkeypatch, overlay=COVERAGE_ON)
    try:
        now = _time.time()
        learned = _map_with(
            ("bench", 0.0, 20.0, now - 60.0),
            ("lamppost", 20.0, 0.0, now - 3600.0),
        )
        _install_map(runtime, learned)
        runtime.start_roam()
        runtime._step_roam(_fresh(runtime))
        snapshot = runtime.roam_snapshot()
        coverage = snapshot["coverage"]
        assert coverage["label"] == "lamppost", "the OLDEST place is the objective"
        assert coverage["age_s"] == pytest.approx(3600.0, abs=5.0)
        assert coverage["candidates"] == 2
        # The lamppost is dead ahead of a robot at the origin facing +x, so the
        # patrol walks the leg rather than turning onto it.
        assert snapshot["reason"] == "advance_coverage"
        assert runtime.roam_idle_checkpoint() is True
    finally:
        runtime.close()


def test_the_turn_onto_a_new_objective_is_not_an_idle_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CURIO-1's consumer, unchanged: deciding where to go is a bad moment to talk."""

    import time as _time

    runtime = _runtime(tmp_path / "checkpoint", monkeypatch, overlay=COVERAGE_ON)
    try:
        now = _time.time()
        _install_map(runtime, _map_with(("lamppost", 0.0, 20.0, now - 3600.0)))
        runtime.start_roam()
        runtime._step_roam(_fresh(runtime))
        snapshot = runtime.roam_snapshot()
        assert snapshot["reason"] == "turn_coverage"
        assert snapshot["idle_checkpoint"] is False
        assert runtime.roam_idle_checkpoint() is False
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("overlay", "expected_key"),
    (
        # The SHIPPED default: no ``roam:`` block at all. This is the row that
        # would have caught the 17:38 draft's default-ON objective.
        (None, None),
        # And the same thing said out loud, which is what the baseline arm of
        # the measurement runs with.
        ("roam:\n  coverage: false\n", False),
    ),
    ids=("no roam block at all", "coverage: false"),
)
def test_the_objective_is_off_unless_a_profile_asks_for_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlay: str | None,
    expected_key: bool | None,
) -> None:
    """One config line is the whole difference between the card's two arms.

    Both halves of "off" are pinned: the shipped default (no ``roam`` block)
    and an explicit ``coverage: false``. In both the map is not even ASKED, so
    flag-off costs the control loop nothing at all and the baseline arm is
    ROAM-1 rather than ROAM-1-plus-a-query.
    """

    import time as _time

    runtime = _runtime(tmp_path / "off", monkeypatch, overlay=overlay)
    try:
        assert runtime.roam_config.get("coverage") is expected_key
        assert runtime._roam_limits(120.0).coverage_bias is False
        asked: list[object] = []

        class _Watched(OnlineSemanticMap):
            def coverage_candidates(self, *args, **kwargs):  # type: ignore[override]
                asked.append(args)
                return super().coverage_candidates(*args, **kwargs)

        watched = _Watched(provenance=PROV)
        watched.note_frame(queries=("lamppost",))
        watched.observe(
            _observation("lamppost", 0.0, 20.0, wall_s=_time.time() - 3600.0)
        )
        _install_map(runtime, watched)
        runtime.start_roam()
        runtime._step_roam(_fresh(runtime))
        assert asked == [], "coverage off must not even ask the map"
        snapshot = runtime.roam_snapshot()
        assert snapshot["reason"] == "advance"
        assert snapshot["coverage"]["enabled"] is False
    finally:
        runtime.close()


def test_a_map_that_raises_is_a_wander_and_never_an_ended_roam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preference that can stop a dog is a bug. This is the proof."""

    runtime = _runtime(tmp_path / "angry", monkeypatch, overlay=COVERAGE_ON)
    try:

        class _Angry(OnlineSemanticMap):
            def coverage_candidates(self, *args, **kwargs):  # type: ignore[override]
                raise RuntimeError("the map fell over")

        _install_map(runtime, _Angry(provenance=PROV))
        runtime.start_roam()
        runtime._step_roam(_fresh(runtime))
        snapshot = runtime.roam_snapshot()
        assert snapshot["active"] is True
        assert snapshot["reason"] == "advance"
        assert snapshot["coverage"]["target"] is None
    finally:
        runtime.close()


def test_the_misspelled_coverage_key_is_still_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sixth roam key joins the spelling guard rather than dodging it."""

    runtime = _runtime(
        tmp_path / "typo", monkeypatch, overlay="roam:\n  coverag: false\n"
    )
    try:
        with pytest.raises(ValueError, match="unknown roam config key"):
            _ = runtime.roam_config
    finally:
        runtime.close()
