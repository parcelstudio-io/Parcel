"""H3 arena: the drive model driving a headless city through the real doors.

Everything here is EXPERIMENT code. It owns no authority and adds none: every
admission decision is delegated to a component that already ships —

* ``LOOK``      -> ``navigation/awareness_sweep.py`` (R28 table + bounded arc)
* ``REMARK``    -> ``realtime/whisperer.py`` ``ChatterScheduler.due`` (quiet
                   window, night band, owner presence, cadence) plus the
                   admitted-name test the runtime's ``_curiosity_admitted_names``
                   applies (mirrored here because it is a method on
                   ``RobotRuntime``, which this card must not touch)
* ``GO_CHECK`` / ``APPROACH`` -> ``brain/validator.py`` ``PlanValidator`` over a
                   system-authored ``sketch_navigate`` plan, then
                   ``patrol/mission.py`` ``PatrolPolicy`` with the travel radius
                   as its tether, then ``navigation/reactive_safety.py``
* every dispatched command -> ``core/hard_stop.py`` ``finalize_command``

The dog's own proposals come from ``attention/drives.py``; the choice among
coverage candidates comes from ``patrol/coverage.py``.
"""

from __future__ import annotations

import gzip
import json
import math
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import mujoco

from parcel_robot.attention.drives import DEFAULT_DYNAMICS as DRIVE_DYNAMICS
from parcel_robot.attention.drives import (
    DriveSignal,
    DriveSignalKind,
    DriveState,
    InitiativeDigest,
    InitiativeKind,
    InitiativePolicy,
    InitiativeProposal,
    update_drives,
)
from parcel_robot.backends.base import DynamicAgentTrack
from parcel_robot.brain.compiler import compile_plan_sketch
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.brain.validator import (
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
)
from parcel_robot.core.hard_stop import InterventionSeverity, finalize_command
from parcel_robot.core.input_health import (
    InputEvidence,
    RequiredInput,
    evaluate_input_health,
    evidence_origin,
    requirements_allowing_sim_fixtures,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.awareness_sweep import (
    AwarenessLimits,
    AwarenessSweep,
    awareness_yaw_permitted,
)
from parcel_robot.navigation.reactive_safety import (
    apply_reactive_safety,
    scan_evidence_from_observation,
)
from parcel_robot.online_map.entries import MapObservation, WriterProvenance
from parcel_robot.online_map.hygiene import prior_for
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.patrol.coverage import CoverageSelection, select_coverage_candidate
from parcel_robot.patrol.mission import (
    PatrolPolicy,
    PatrolSense,
    forward_clearance_from_scan,
    limits_from_safety,
)
from parcel_robot.perception.city_semantics import extract_city_semantics
from parcel_robot.realtime.config import CuriosityConfig
from parcel_robot.realtime.whisperer import (
    TIME_BAND_NIGHT,
    ChatterScheduler,
    ChatterState,
    time_band_of,
)
from parcel_robot.simulation.dynamic_city import DynamicCity
from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness, HeadlessCityWorld
from parcel_robot.voice.local_plans import sketch_navigate

#: The map's own visibility rule decides what is NOT a coverage candidate. The
#: shipped 8.0 m excludes every entry in ``city_block`` (max entry radius
#: 8.08 m from home), which is ROAM-2 handoff H1 in one line: *"a future
#: measurement needs either a larger scene, a smaller visibility_range_m, or a
#: metric over recency"*. This is that smaller number, chosen as roughly the
#: radius inside which the 70-degree camera cone actually re-detects a place
#: rather than merely being near it. It is a HARNESS parameter; the product
#: default is untouched and the shipped-default candidate count is reported.
MAP_VISIBILITY_RANGE_M = 4.0

#: Where the dog stands when nobody has asked it for anything. Grid-searched
#: over the block for the pose that maximises clearance to every dynamic-agent
#: route SUBJECT TO at least five map entries lying in the 3-6 m band, because
#: a home with nothing in reach cannot test a travel radius. The winner has
#: 1.45 m of static clearance and 1.06 m to the nearest pedestrian route.
#:
#: The origin is NOT a candidate: cyclist-1's route runs straight through it,
#: so a dog parked there is ridden over by the venue rather than by anything
#: the drive model did. The 1.06 m is recorded because it is under the gate's
#: 1.2 m person stop: on this scene a dog standing at ANY home with places in
#: reach is walked past closer than the gate's own social zone, and row D4 is
#: reported with that attribution rather than against it.
HOME_POSE: tuple[float, float, float] = (1.0, 1.5, 0.0)

#: THE ANNOYANCE BUDGET, and the one number this experiment takes from the
#: pre-registered D1 band rather than from the repo. "At most one self-started
#: behaviour per ten minutes" is a policy an owner can state; it caps the rate
#: at 6/h before any door refuses, which sits inside D1's 3-8/h. Disclosed in
#: RESULTS: D1 therefore measures the rate REALIZED through the doors, not a
#: free-running drive rate. Every other parameter comes from the repo's own
#: shipped cadences (see ``attention/drives.py``).
INITIATIVE_REFRACTORY_S = 600.0

#: How long one GO_CHECK / APPROACH errand may run. The smallest budget that
#: can plausibly reach a 6 m tether and come back: 2 x 6 m at the patrol's
#: 0.25 m/s cruise is 48 s of pure driving, and ROAM-1/ROAM-2 measured that
#: most patrol ticks are avoidance turns rather than cruise (17-26 m of path
#: for 1.4-6.5 m of net displacement). Four minutes is that ratio plus the
#: return leg. It is a BOUND, not a target: the errand ends early on
#: ``boxed_in`` or when the drive is satisfied.
ERRAND_BUDGET_S = 240.0

#: How long an object must have been out of view before seeing it again is
#: news. Without it a stationary dog notices the same lamppost every tick.
RENOTICE_AFTER_S = 60.0

#: Card-free provenance for the arena's learned map.
PROVENANCE = WriterProvenance(
    session_id="h3-arena",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)

#: The H2 fix, as one selection. Reasons, not tuning:
#: * ``min_candidate_distance_m`` 3.0 — a place inside three metres is a place
#:   the dog can look at; a leg is for something further than a look.
#: * ``forward_bearing_weight`` 0.6 — under the age term's 1.0 so a very stale
#:   place behind still beats a fresh one ahead, but a tie goes forward.
#: * ``path_novelty_weight`` 0.4 — H2's third option: prefer away from the
#:   path already walked.
H2_SELECTION = CoverageSelection(
    min_candidate_distance_m=3.0,
    forward_bearing_weight=0.6,
    age_weight=1.0,
    path_novelty_weight=0.4,
    path_novelty_span_m=6.0,
)


@dataclass(frozen=True)
class ArmSpec:
    """One experimental arm."""

    name: str
    drives_enabled: bool
    travel_radius_m: float
    selection: CoverageSelection
    kinds: tuple[str, ...]


_LOOK_REMARK_KINDS = (
    InitiativeKind.LOOK.value,
    InitiativeKind.REMARK.value,
    InitiativeKind.REST.value,
)
_ALL_KINDS = tuple(kind.value for kind in InitiativeKind)

ARMS: dict[str, ArmSpec] = {
    "baseline": ArmSpec("baseline", False, 0.0, CoverageSelection(), ()),
    "look_remark": ArmSpec("look_remark", True, 0.0, CoverageSelection(), _LOOK_REMARK_KINDS),
    "radius6": ArmSpec("radius6", True, 6.0, H2_SELECTION, _ALL_KINDS),
    "radius10": ArmSpec("radius10", True, 10.0, H2_SELECTION, _ALL_KINDS),
}


@dataclass
class RunConfig:
    arm: str
    seed: int
    duration_s: float = 3600.0
    start_hour: float = 14.0
    log_path: Path | None = None
    control_dt_s: float = 0.1
    #: F4 probe. False reproduces the FIRST build of this arena, which gated
    #: the quiet window and the night band only where the product does —
    #: inside the remark door. It exists so the claim "nothing in the product
    #: gates a discretionary motion by time of day" is a measurement rather
    #: than an assertion.
    withhold_time_bands: bool = True
    #: D5 probe: on the FIRST admitted initiative, pull the next owner turn to
    #: +3 s and the e-stop to +8 s so the preemption latency is measured
    #: against a behaviour that is certainly running. Off in the four arms;
    #: the arms report only the overlaps that happened on their own.
    probe_preemption: bool = False


@dataclass
class _Active:
    """The behaviour currently being expressed, and its bounds."""

    proposal: InitiativeProposal
    started_s: float
    deadline_s: float
    patrol: PatrolPolicy | None = None
    target_row: dict[str, Any] | None = None
    target_id: str | None = None
    checked: int = 0
    ticks: int = 0


@dataclass
class _Counters:
    proposals: int = 0
    admitted: int = 0
    refusals: dict[str, int] = field(default_factory=dict)
    admitted_by_kind: dict[str, int] = field(default_factory=dict)
    proposed_by_kind: dict[str, int] = field(default_factory=dict)
    admitted_in_quiet: int = 0
    admitted_in_night: int = 0
    attributed: int = 0

    def refuse(self, reason: str) -> None:
        self.refusals[reason] = self.refusals.get(reason, 0) + 1


class InitiativeArena:
    """One 60-simulated-minute run of one arm, at 10 Hz."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.arm = ARMS[config.arm]
        self.rng = random.Random(config.seed)
        harness = HeadlessCityQualityHarness()
        self.world: HeadlessCityWorld = harness.world
        self.gate = harness.reactive_safety
        self.world.reset(robot=HOME_POSE)
        self.home = (HOME_POSE[0], HOME_POSE[1])
        self.city = DynamicCity.default(seed=config.seed)
        self._mocap = self._resolve_mocap_ids()
        self.pose: tuple[float, float, float] = HOME_POSE
        self.learned = self._seed_map()
        # The curiosity block ships OFF (every remark is a billed hosted
        # response). The arena turns it on because a remark door that is off
        # is not a door; every other field is the shipped default.
        self.curiosity_config = CuriosityConfig(enabled=True)
        self.chatter = ChatterScheduler(
            config=self.curiosity_config,
            clock=lambda: self.sim_t,
            rng=random.Random(config.seed + 17),
            time_band=self._band,
        )
        self.sweep = AwarenessSweep(AwarenessLimits(enabled=True, idle_period_s=0.1))
        self.registry = SkillContractRegistry.default(include_system_skills=True).restricted(
            ("NavigateTo", "Hold", "MoveRelative"), system_authored=True
        )
        self.validator = PlanValidator(self.registry)
        self.router = DeterministicIntentRouter()
        self.policy = InitiativePolicy(
            travel_radius_m=self.arm.travel_radius_m,
            refractory_s=INITIATIVE_REFRACTORY_S,
            go_check_budget_s=ERRAND_BUDGET_S,
            seed=config.seed,
            kinds=self.arm.kinds or _ALL_KINDS,
        )

        self.sim_t = 0.0
        self.drives = DriveState()
        self.active: _Active | None = None
        self.counters = _Counters()
        self.last_initiative_at_s: float | None = None
        self.last_owner_turn_s: float | None = None
        self.idle_since_s = 0.0
        self.estop = False
        self.estop_at_s = 900.0 + self.rng.uniform(0.0, 1200.0)
        self.estop_clear_s = math.inf
        self._estop_fired = False
        self.next_owner_turn_s = self.rng.uniform(360.0, 600.0)
        self._seen_objects: dict[str, float] = {}
        self._baselined = False
        self._pending_preempt: dict[str, Any] | None = None
        self._probe_stage = 0
        self._agent_in_contact = False
        self._person_signal_at: dict[str, float] = {}
        self._last_battery_s = 0.0
        self._last_idle_signal_s = 0.0
        self._previous_command = VelocityCommand()
        self._log_rows: list[str] = []

        # measurements
        self.initiations: list[dict[str, Any]] = []
        self.preemptions: list[dict[str, Any]] = []
        self.max_radius_m = 0.0
        self.min_agent_clearance_m = math.inf
        self.min_agent_clearance_under_initiative_m = math.inf
        self.agent_contacts = 0
        self.contact_records: list[dict[str, Any]] = []
        self.contact_ticks = 0
        self.contacts_while_translating = 0
        self.contacts_while_stationary = 0
        self.contact_agents: set[str] = set()
        self.visited_cells: set[tuple[int, int]] = set()
        self.command_stream: list[tuple[float, float, float]] = []
        self.candidate_counts: list[int] = []
        self.patrol_reasons: dict[str, int] = {}
        self.owner_turns = 0
        self.withheld_quiet = 0
        self.withheld_night = 0
        self.owner_turns_during_initiative = 0
        self.min_clearance_toward_agent_m = math.inf
        self.path: list[tuple[float, float]] = []

    # ------------------------------------------------------------------ setup
    def _resolve_mocap_ids(self) -> dict[str, int]:
        ids: dict[str, int] = {}
        for agent in self.city.agents:
            body = mujoco.mj_name2id(
                self.world.model, mujoco.mjtObj.mjOBJ_BODY, agent.spec.body_name
            )
            if body >= 0:
                ids[agent.spec.agent_id] = int(self.world.model.body_mocapid[body])
        return ids

    def _seed_map(self) -> OnlineSemanticMap:
        """A map that already knows the block, with staggered last-seen ages."""

        learned = OnlineSemanticMap(
            provenance=PROVENANCE, visibility_range_m=MAP_VISIBILITY_RANGE_M
        )
        _regions, objects = extract_city_semantics(self.world.model)
        for index, spec in enumerate(objects):
            label = str(spec["label"])
            x, y = float(spec["position"][0]), float(spec["position"][1])
            self._ingest(learned, label, x, y, wall_s=-60.0 * (index + 1), frame_id=f"seed{index}")
        return learned

    def _ingest(
        self,
        learned: OnlineSemanticMap,
        label: str,
        x: float,
        y: float,
        *,
        wall_s: float,
        frame_id: str,
    ) -> None:
        prior, _key = prior_for(label)
        learned.note_frame(queries=(label,))
        learned.observe(
            MapObservation(
                label=label,
                score=0.6,
                surface_x=x,
                surface_y=y,
                surface_z=1.0,
                range_m=max(0.5, math.hypot(x, y)),
                bearing_rad=math.atan2(y, x),
                depth_m=max(0.5, math.hypot(x, y)),
                extent_w_m=(prior.min_w_m + prior.max_w_m) / 2.0,
                extent_h_m=(prior.min_h_m + prior.max_h_m) / 2.0,
                inlier_pixels=900,
                frame_id=frame_id,
                visit_id="h3",
                observed_wall_s=self._wall(wall_s),
                robot_x=self.pose[0],
                robot_y=self.pose[1],
                provenance=PROVENANCE,
            )
        )

    @staticmethod
    def _wall(sim_s: float) -> float:
        """Sim seconds on a synthetic wall clock the map can subtract."""

        return 1_700_000_000.0 + float(sim_s)

    def _band(self) -> str:
        total_s = float(self.config.start_hour) * 3600.0 + self.sim_t
        return time_band_of(int(total_s // 3600.0) % 24)

    # ------------------------------------------------------------------- loop
    def run(self) -> dict[str, Any]:
        dt = self.config.control_dt_s
        ticks = round(self.config.duration_s / dt)
        observation = self.world.observe()
        for tick in range(ticks):
            self.sim_t = tick * dt
            observation = self._decorate(observation)
            command, row = self._tick(observation, tick)
            self.world.apply(command)
            self.city.step(dt)
            self._write_mocap()
            observation = self.world.step()
            self._record(row)
        self._flush_log()
        return self.summary()

    def _write_mocap(self) -> None:
        for agent in self.city.agents:
            mocap = self._mocap.get(agent.spec.agent_id)
            if mocap is None or mocap < 0:
                continue
            self.world.data.mocap_pos[mocap, 0] = agent.x
            self.world.data.mocap_pos[mocap, 1] = agent.y

    def _decorate(self, observation: Any) -> Any:
        """Put the moving crowd into the observation the product code reads."""

        self.pose = (
            float(observation.robot.x),
            float(observation.robot.y),
            float(observation.robot.yaw),
        )
        nearest = self.city.nearest_person(
            *self.pose, robot_radius_m=self.world.robot_radius_m
        )
        tracks = tuple(
            DynamicAgentTrack(
                agent_id=str(item["id"]),
                kind=str(item["kind"]),
                x=float(item["x"]),
                y=float(item["y"]),
                vx=float(item["vx"]),
                vy=float(item["vy"]),
                radius_m=float(item["radius_m"]),
            )
            for item in self.city.snapshots()
        )
        if nearest is None:
            return replace(observation, dynamic_agents=tracks, emergency_stopped=self.estop)
        return replace(
            observation,
            nearest_person_m=float(nearest["distance_m"]),
            nearest_person_bearing_rad=float(nearest["bearing_rad"]),
            nearest_person_id=str(nearest["id"]),
            dynamic_agents=tracks,
            emergency_stopped=self.estop,
        )

    def _tick(self, observation: Any, tick: int) -> tuple[VelocityCommand, dict[str, Any]]:
        events = self._events()
        self._map_refresh(observation, tick)
        if tick % 10 == 0:
            # The runtime ticks the chatter scheduler at 1 Hz whether or not it
            # has anything to say (``_step_curiosity``), and the Poisson anchor
            # is set on the FIRST tick. Calling ``due`` only when a remark is
            # proposed would set the anchor at that moment and refuse the first
            # remark of every session on its own stimulus floor.
            self.chatter.due(
                ChatterState(
                    at_s=self.sim_t,
                    owner_present=bool(observation.owner.visible),
                    lane_busy=False,
                    activity_running=self.active is not None,
                )
            )
        signals = self._signals(observation, events)
        if self.arm.drives_enabled:
            self.drives = update_drives(
                self.drives, signals, now_s=self.sim_t, dynamics=DRIVE_DYNAMICS
            )
        preempted = self._preempt(events)
        # THE FEATURE VECTOR THE DECISION WAS MADE ON. Logged separately from
        # the end-of-tick vector because ``_begin`` discharges the drive that
        # justified an admitted proposal: a Stage-B corpus keyed on the
        # post-decision vector would be training on the consequence of the
        # label rather than on its cause.
        drives_at_decision = self.drives.as_dict()
        proposal, verdict = self._decide(observation)
        command, note = self._express(observation)
        gated, gate_note = apply_reactive_safety(
            command, observation, policy=self.gate, now=observation.timestamp
        )
        # The e-stop latch is the only severity this arena ever raises; a
        # normal tick dispatches CLEAR so the gate above stays the only thing
        # that shapes the command.
        severity = InterventionSeverity.HARD_STOP if self.estop else InterventionSeverity.CLEAR
        decision = finalize_command(gated, severity, previous_command=self._previous_command)
        final = decision.command
        self._previous_command = final
        row = {
            "t": round(self.sim_t, 2),
            "d0": drives_at_decision,
            "d": self.drives.as_dict(),
            "sig": [signal.kind for signal in signals],
            "p": None if proposal is None else proposal.as_dict(),
            "v": verdict,
            "a": None if self.active is None else self.active.proposal.kind,
            "cmd": [round(final.vx, 5), round(final.vy, 5), round(final.vyaw, 5)],
            "gate": gate_note,
            "note": note,
            "e": self.estop,
            "band": self._band(),
            "quiet": self._quiet_now(),
            "pose": [round(self.pose[0], 4), round(self.pose[1], 4)],
            "ev": events,
            "pre": preempted,
        }
        return final, row

    # -------------------------------------------------------------- the world
    def _events(self) -> list[str]:
        events: list[str] = []
        if self.sim_t >= self.next_owner_turn_s:
            events.append("owner_turn")
            self.owner_turns += 1
            if self.active is not None:
                self.owner_turns_during_initiative += 1
            self.chatter.note_turn(at=self.sim_t)
            self.last_owner_turn_s = self.sim_t
            self.next_owner_turn_s = self.sim_t + self.rng.uniform(360.0, 600.0)
        if not self._estop_fired and self.sim_t >= self.estop_at_s:
            # The row it feeds (D5) is about preempting a behaviour that is
            # RUNNING, so the injection waits for one — up to a cap, after
            # which it fires anyway so every run carries an e-stop.
            last_call = self.config.duration_s - 60.0
            due = self.active is not None or self.sim_t >= last_call
            if due:
                self._estop_fired = True
                self.estop = True
                self.estop_clear_s = self.sim_t + 30.0
                events.append("estop")
        elif self.estop and self.sim_t >= self.estop_clear_s:
            self.estop = False
            events.append("estop_clear")
        return events

    def _map_refresh(self, observation: Any, tick: int) -> None:
        if tick % 10:  # 1 Hz, like the runtime's semantic scan cadence
            return
        for item in observation.semantic_objects:
            self._ingest(
                self.learned,
                item.label,
                float(item.position[0]),
                float(item.position[1]),
                wall_s=self.sim_t,
                frame_id=f"t{tick}",
            )

    def _signals(self, observation: Any, events: list[str]) -> list[DriveSignal]:
        signals: list[DriveSignal] = []
        for item in observation.semantic_objects:
            last = self._seen_objects.get(item.object_id)
            self._seen_objects[item.object_id] = self.sim_t
            if not self._baselined:
                continue
            if last is not None and self.sim_t - last < RENOTICE_AFTER_S:
                continue
            signals.append(
                DriveSignal(DriveSignalKind.NOTICING.value, self.sim_t, float(item.confidence))
            )
        # R11's rule, applied here for its reason: the FIRST digest of a
        # session is a baseline, not a discovery. Without it the dog opens
        # every run having just noticed the entire block at once.
        self._baselined = True
        if observation.nearest_person_m is not None and observation.nearest_person_m <= 4.0:
            agent_id = str(observation.nearest_person_id)
            last = self._person_signal_at.get(agent_id, -math.inf)
            if self.sim_t - last >= 20.0:
                self._person_signal_at[agent_id] = self.sim_t
                signals.append(DriveSignal(DriveSignalKind.PERSON_SEEN.value, self.sim_t, 1.0))
        if "owner_turn" in events:
            signals.append(DriveSignal(DriveSignalKind.OWNER_TURN.value, self.sim_t, 1.0))
        if self.sim_t - self._last_idle_signal_s >= 30.0 and self.active is None:
            self._last_idle_signal_s = self.sim_t
            signals.append(DriveSignal(DriveSignalKind.IDLE_TIME.value, self.sim_t, 1.0))
        if self.sim_t - self._last_battery_s >= 60.0:
            self._last_battery_s = self.sim_t
            fraction = max(0.0, 1.0 - 0.4 * self.sim_t / max(1.0, self.config.duration_s))
            intensity = max(0.0, min(1.0, (0.5 - fraction) * 2.0))
            if intensity > 0.0:
                signals.append(
                    DriveSignal(DriveSignalKind.BATTERY.value, self.sim_t, intensity)
                )
        return signals

    # ---------------------------------------------------------- the proposals
    def _quiet_now(self) -> bool:
        if self.last_owner_turn_s is None:
            return False
        return self.sim_t - self.last_owner_turn_s < self.curiosity_config.quiet_s

    def _digest(self, observation: Any) -> InitiativeDigest:
        rows = self._coverage_rows()
        # E2-D2's lesson, applied to the SELECTION rather than to the gate: a
        # proposer that picks the most interesting place and then discovers the
        # consent radius refuses it has bought a refusal, not a walk. So the
        # radius bounds the candidate set BEFORE the selection ranks it.
        reachable = self._within_consent(rows)
        choice = select_coverage_candidate(
            reachable, selection=self.arm.selection, path=tuple(self.path[-200:])
        )
        look_bearing = None
        look_subject = None
        if observation.semantic_objects:
            item = observation.semantic_objects[0]
            look_bearing = self._bearing_to(item.position[0], item.position[1])
            look_subject = item.label
        names = self._admitted_names()
        remark_subject = None
        if names:
            visible = [item.label for item in observation.semantic_objects if item.label in names]
            remark_subject = visible[0] if visible else None
        row = None if choice is None else choice.row
        return InitiativeDigest(
            at_s=self.sim_t,
            idle_s=self.sim_t - self.idle_since_s,
            owner_present=bool(observation.owner.visible),
            emergency_stopped=self.estop,
            look_bearing_rad=look_bearing,
            look_subject=look_subject,
            person_id=observation.nearest_person_id,
            person_range_m=observation.nearest_person_m,
            person_bearing_rad=observation.nearest_person_bearing_rad,
            remark_subject=remark_subject,
            place_id=None if row is None else str(row["entry_id"]),
            place_bearing_rad=None if row is None else float(row["bearing_rad"]),
            place_range_m=None if row is None else float(row["distance_m"]),
            place_age_s=None if row is None or row["age_s"] is None else float(row["age_s"]),
        )

    def _within_consent(self, rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        """Places the consent radius can reach, measured from HOME.

        From home, not from the dog: ``travel_radius_m`` is how far the owner
        has agreed the dog may BE, so a place 7 m from home is not made
        eligible by the dog having already walked 3 m toward it.
        """

        if not self.policy.travel_allowed:
            return rows
        radius = self.policy.travel_radius_m
        return tuple(
            row
            for row in rows
            if math.hypot(
                float(row["surface_x"]) - self.home[0],
                float(row["surface_y"]) - self.home[1],
            )
            <= radius
        )

    def _coverage_rows(self) -> tuple[dict[str, Any], ...]:
        rows = self.learned.coverage_candidates(
            *self.pose,
            now_wall_s=self._wall(self.sim_t),
            # Above the entry count on purpose: ``coverage_candidates``
            # truncates AFTER a sort whose last tie-break is the uuid4 entry
            # id, so a limit under the map size would decide WHICH rows
            # survive on a value that differs per process.
            limit=32,
        )
        self.candidate_counts.append(len(rows))
        return rows

    def _admitted_names(self) -> frozenset[str]:
        """Mirrors ``RobotRuntime._curiosity_admitted_names`` (that file is untouchable)."""

        from parcel_robot.online_map.entries import NAME_VLM_PROPOSED

        vocabulary = set(self.learned.known_places())
        proposed = {
            str(name.text)
            for entry in self.learned.active_entries()
            for name in entry.names
            if str(name.provenance) == NAME_VLM_PROPOSED
        }
        return frozenset(vocabulary - proposed)

    def _decide(self, observation: Any) -> tuple[InitiativeProposal | None, str | None]:
        if not self.arm.drives_enabled or self.active is not None:
            return None, None
        # THE WITHHOLDING THRESHOLDS, and they are not doors. The DESIGN's own
        # framing: "the safety envelope for initiative already exists as
        # withholding thresholds (rate caps, quiet_s=90, night_quiet, R28
        # input-health, the proactive-motion allowlist)". A threshold is a
        # place a proposal is not FORMED; a door is a place a proposal is
        # refused. Forming one here and letting the remark door refuse it
        # would be the proposer fighting the gate (E2-D2), and it would only
        # protect remarks anyway — MEASURED FINDING: nothing in the product
        # gates a discretionary *motion* by time of day. The remark door has
        # night_quiet and quiet_s; the R28 table, the plan validator and the
        # reactive gate have no clock. So the band has to be read here, from
        # the same ``CuriosityConfig`` and the same ``time_band_of``.
        if self.config.withhold_time_bands:
            if self.curiosity_config.night_quiet and self._band() == TIME_BAND_NIGHT:
                self.withheld_night += 1
                return None, None
            if self._quiet_now():
                self.withheld_quiet += 1
                return None, None
        from parcel_robot.attention.drives import propose

        digest = self._digest(observation)
        proposal = propose(
            self.drives, digest, self.policy, last_initiative_at_s=self.last_initiative_at_s
        )
        if proposal is None:
            return None, None
        self.counters.proposals += 1
        self.counters.proposed_by_kind[proposal.kind] = (
            self.counters.proposed_by_kind.get(proposal.kind, 0) + 1
        )
        verdict = self._admit(proposal, observation)
        if verdict != "admitted":
            self.counters.refuse(verdict)
            # A refused proposal still spends the refractory: the whisperer's
            # ``note_refusal`` rule — do not re-offer a refused candidate every
            # tick — applied to every kind.
            self.last_initiative_at_s = self.sim_t
            return proposal, verdict
        self._begin(proposal)
        return proposal, verdict

    def _admit(self, proposal: InitiativeProposal, observation: Any) -> str:
        if proposal.kind == InitiativeKind.REST.value:
            return "admitted"
        if proposal.kind == InitiativeKind.LOOK.value:
            return "admitted" if self._yaw_permitted(observation) else "r28_refused"
        if proposal.kind == InitiativeKind.REMARK.value:
            return self._admit_remark(proposal, observation)
        return self._admit_travel(proposal, observation)

    def _yaw_permitted(self, observation: Any) -> bool:
        origin, label = evidence_origin(observation.backend)
        evidence = {
            RequiredInput.SCAN: scan_evidence_from_observation(observation),
            RequiredInput.POSE: InputEvidence(
                captured_at=observation.timestamp,
                frame_id="odom",
                payload_valid=True,
                origin=origin,
                fixture_label=label,
            ),
        }
        if self._previous_command != VelocityCommand():
            evidence[RequiredInput.CONTROLLER_FEEDBACK] = InputEvidence(
                captured_at=observation.timestamp,
                frame_id="base_link",
                payload_valid=True,
                origin=origin,
                fixture_label=label,
            )
        verdict = evaluate_input_health(
            evidence,
            now=observation.timestamp,
            requirements=requirements_allowing_sim_fixtures(),
        )
        return awareness_yaw_permitted(verdict, latched=self.estop)

    def _admit_remark(self, proposal: InitiativeProposal, observation: Any) -> str:
        state = ChatterState(
            at_s=self.sim_t,
            owner_present=bool(observation.owner.visible),
            lane_busy=False,
            activity_running=self.active is not None,
        )
        if not self.chatter.due(state, stimulus=True):
            reasons = sorted(self.chatter.skips.items(), key=lambda item: -item[1])
            return f"chatter_{reasons[0][0]}" if reasons else "chatter_refused"
        if not proposal.subject or proposal.subject not in self._admitted_names():
            self.chatter.note_refusal(at=self.sim_t)
            return "name_not_admitted"
        return "admitted"

    def _admit_travel(self, proposal: InitiativeProposal, observation: Any) -> str:
        if not self.policy.travel_allowed:
            return "travel_radius_zero"
        if proposal.kind == InitiativeKind.APPROACH.value:
            # MEASURED REFUSAL, not a harness gap. The admitted skill table has
            # NavigateTo (a semantic place), FollowFormation / OrbitOwner (the
            # OWNER) and MoveRelative (a direction). There is no contract for
            # "walk up to that person over there", so an APPROACH initiative
            # cannot be admitted by any door that exists today.
            return "approach_no_skill_contract"
        label = self._label_for(proposal.target_id)
        if label is None:
            return "no_target_label"
        snapshot = build_observation_snapshot(
            observation,
            snapshot_id=f"h3-{int(self.sim_t * 10)}",
            now=observation.timestamp,
            emergency_stopped=self.estop,
            obstacle_stop_m=self.gate.obstacle_stop_m,
            person_stop_m=self.gate.person_stop_m,
        )
        try:
            frame = self.router.route(
                f"go to the {label}", turn_id=f"h3-{self.config.seed}-{int(self.sim_t * 10)}"
            )
            plan = compile_plan_sketch(
                sketch_navigate(f"go to the {label}", object_labels=(label,)),
                frame,
                snapshot,
                self.registry,
            )
            self.validator.validate(plan, snapshot)
        except PlanValidationError as error:
            return f"plan_{error.code}"
        except (ValueError, TypeError, KeyError) as error:
            return f"plan_error_{type(error).__name__}"
        return "admitted"

    def _row_for(self, entry_id: str | None) -> dict[str, Any] | None:
        if entry_id is None:
            return None
        for row in self._coverage_rows():
            if str(row["entry_id"]) == entry_id:
                return dict(row)
        return None

    def _label_for(self, entry_id: str | None) -> str | None:
        if entry_id is None:
            return None
        for entry in self.learned.active_entries():
            if entry.entry_id == entry_id:
                return str(entry.label)
        return None

    def _begin(self, proposal: InitiativeProposal) -> None:
        self.counters.admitted += 1
        self.counters.admitted_by_kind[proposal.kind] = (
            self.counters.admitted_by_kind.get(proposal.kind, 0) + 1
        )
        if proposal.drive:
            self.counters.attributed += 1
        if self._quiet_now():
            self.counters.admitted_in_quiet += 1
        if self._band() == "night":
            self.counters.admitted_in_night += 1
        self.last_initiative_at_s = self.sim_t
        if self.config.probe_preemption and self._probe_stage < 2:
            # Two probes, on two different initiatives: an owner turn ends the
            # first one, so an e-stop aimed at the same behaviour would arrive
            # to an empty channel and measure nothing.
            if self._probe_stage == 0:
                self.next_owner_turn_s = self.sim_t + 3.0
            else:
                self.estop_at_s = self.sim_t + 3.0
                self._estop_fired = False
            self._probe_stage += 1
        self.initiations.append(
            {
                **proposal.as_dict(),
                "quiet": self._quiet_now(),
                "band": self._band(),
                "drives": self.drives.as_dict(),
            }
        )
        patrol = None
        target_row = None
        if proposal.travels:
            target_row = self._row_for(proposal.target_id)
            patrol = PatrolPolicy(
                limits_from_safety(
                    person_stop_m=self.gate.person_stop_m,
                    obstacle_stop_m=self.gate.obstacle_stop_m,
                    budget_s=proposal.budget_s,
                    tether_m=self.policy.travel_radius_m,
                    coverage_bias=True,
                )
            )
        self.active = _Active(
            proposal=proposal,
            started_s=self.sim_t,
            deadline_s=self.sim_t + max(proposal.budget_s, 0.1),
            patrol=patrol,
            target_row=target_row,
            target_id=proposal.target_id,
        )
        self.drives = DRIVE_DYNAMICS.satisfied(self.drives, proposal.drive)
        if proposal.kind == InitiativeKind.REMARK.value:
            self.chatter.note_remark(at=self.sim_t)
        if proposal.kind == InitiativeKind.LOOK.value:
            self.sweep.reset()

    # -------------------------------------------------------- expression side
    def _preempt(self, events: list[str]) -> str | None:
        """The owner speaks or the e-stop fires: the initiative ends this tick."""

        trigger = None
        if "owner_turn" in events:
            trigger = "owner_turn"
        if "estop" in events:
            trigger = "estop"
        if trigger is None:
            return None
        if self.active is None:
            return None
        # Opened here, CLOSED in ``_record`` by reading the dispatched command
        # stream: the latency is measured off the log, never asserted.
        self._pending_preempt = {
            "trigger": trigger,
            "at_s": round(self.sim_t, 3),
            "at_tick": len(self.command_stream),
            "kind": self.active.proposal.kind,
            "held_s": round(self.sim_t - self.active.started_s, 3),
        }
        self._end("preempted")
        return trigger

    def _end(self, reason: str) -> None:
        if self.active is None:
            return
        if self.initiations:
            self.initiations[-1].setdefault("ended", reason)
            self.initiations[-1].setdefault("ticks", self.active.ticks)
            self.initiations[-1].setdefault("checked", self.active.checked)
        self.active = None
        self.sweep.reset()
        self.idle_since_s = self.sim_t

    def _express(self, observation: Any) -> tuple[VelocityCommand, str]:
        if self.active is None:
            return VelocityCommand(), "idle"
        active = self.active
        active.ticks += 1
        if self.sim_t >= active.deadline_s:
            self._end("budget")
            return VelocityCommand(), "budget_done"
        kind = active.proposal.kind
        if kind in {InitiativeKind.REST.value, InitiativeKind.REMARK.value}:
            self._end("expressed")
            return VelocityCommand(), f"{kind}_expressed"
        if kind == InitiativeKind.LOOK.value:
            return self._express_look(observation)
        return self._express_travel(observation)

    def _express_look(self, observation: Any) -> tuple[VelocityCommand, str]:
        before = self.sweep.sweeps_completed
        proposal = self.sweep.step(
            self.sim_t, idle=True, yaw_permitted=self._yaw_permitted(observation)
        )
        if self.sweep.sweeps_completed > before:
            self._end("sweep_complete")
            return VelocityCommand(), "look_complete"
        if proposal is None:
            return VelocityCommand(), "look_arming"
        return VelocityCommand(vyaw=proposal.vyaw), proposal.reason

    def _express_travel(self, observation: Any) -> tuple[VelocityCommand, str]:
        active = self.active
        if active is None or active.patrol is None:
            return VelocityCommand(), "no_errand"
        # THE TARGET IS LATCHED AT PROPOSAL TIME. ``GO_CHECK(place, budget)``
        # names a place; re-selecting every tick is what turns an errand into
        # a weathervane (the forward-bearing term would re-elect whatever the
        # nose happens to be pointing at). The selection therefore runs once,
        # in ``propose``/``_begin``; this only re-reads the LATCHED row.
        rows = self._coverage_rows()
        target_id = active.target_id or active.proposal.target_id
        current = next((row for row in rows if str(row["entry_id"]) == target_id), None)
        if current is None:
            # The map no longer offers it: it has been re-seen, which is what
            # "go and check it" means. The ERRAND does not end there — the
            # product's roam runs to its budget and treats the coverage bearing
            # as a preference, never as an arrival test (``_step_roam`` has no
            # arrival branch) — so the next stalest place inside the consent
            # radius is latched and the leg continues.
            active.checked += 1
            choice = select_coverage_candidate(
                self._within_consent(rows),
                selection=self.arm.selection,
                path=tuple(self.path[-200:]),
            )
            active.target_id = None if choice is None else str(choice.row["entry_id"])
            current = None if choice is None else choice.row
        if current is None:
            return self._patrol_step(active, observation, bearing=None, age=None)
        bearing = float(current["bearing_rad"])
        age = None if current["age_s"] is None else float(current["age_s"])
        return self._patrol_step(active, observation, bearing=bearing, age=age)

    def _patrol_step(
        self,
        active: _Active,
        observation: Any,
        *,
        bearing: float | None,
        age: float | None,
    ) -> tuple[VelocityCommand, str]:
        sense = PatrolSense(
            elapsed_s=self.sim_t - active.started_s,
            x=self.pose[0],
            y=self.pose[1],
            yaw=self.pose[2],
            forward_clearance_m=self._forward_clearance(observation),
            person_clearance_m=observation.nearest_person_m,
            person_bearing_rad=observation.nearest_person_bearing_rad,
            collision=bool(observation.collision),
            coverage_bearing_rad=bearing,
            coverage_age_s=age,
        )
        command = active.patrol.step(sense)
        self.patrol_reasons[command.reason] = self.patrol_reasons.get(command.reason, 0) + 1
        if command.reason in {"budget_exhausted", "boxed_in"}:
            self._end(command.reason)
            return VelocityCommand(), command.reason
        return VelocityCommand(vx=command.vx, vy=command.vy, vyaw=command.vyaw), command.reason

    @staticmethod
    def _forward_clearance(observation: Any) -> float | None:
        if observation.lidar_ranges:
            return forward_clearance_from_scan(
                observation.lidar_ranges,
                angle_min_rad=float(observation.lidar_angle_min_rad or -math.pi),
                angle_increment_rad=float(observation.lidar_angle_increment_rad or 0.0),
                range_max_m=observation.lidar_range_max_m,
            )
        return observation.nearest_obstacle_m

    def _bearing_to(self, x: float, y: float) -> float:
        bearing = math.atan2(y - self.pose[1], x - self.pose[0])
        return math.atan2(
            math.sin(bearing - self.pose[2]), math.cos(bearing - self.pose[2])
        )

    # ------------------------------------------------------------ measurement
    def _record(self, row: dict[str, Any]) -> None:
        x, y, yaw = self.pose
        self.path.append((x, y))
        self.max_radius_m = max(
            self.max_radius_m, math.hypot(x - self.home[0], y - self.home[1])
        )
        self.visited_cells.add(_block_cell(x, y))
        nearest = self.city.nearest_person(
            x, y, yaw, robot_radius_m=self.world.robot_radius_m
        )
        if nearest is not None:
            clearance = float(nearest["distance_m"])
            self.min_agent_clearance_m = min(self.min_agent_clearance_m, clearance)
            if self.active is not None:
                self.min_agent_clearance_under_initiative_m = min(
                    self.min_agent_clearance_under_initiative_m, clearance
                )
            # The gate's own "toward" test (reactive_safety._toward, +/-1.15
            # rad of the travel bearing): the clearance the dog's OWN motion
            # is responsible for, as opposed to a pedestrian walking into a
            # robot that is holding station.
            vx, vy, _vyaw = row["cmd"]
            if math.hypot(vx, vy) > 1e-9:
                travel = math.atan2(vy, vx)
                bearing = float(nearest["bearing_rad"])
                delta = math.atan2(math.sin(bearing - travel), math.cos(bearing - travel))
                if abs(delta) < 1.15:
                    self.min_clearance_toward_agent_m = min(
                        self.min_clearance_toward_agent_m, clearance
                    )
            # Edge-detected, the way the world counts a static contact: one
            # continuous press is one contact, not one per 0.1 s.
            if clearance <= 0.0 and not self._agent_in_contact:
                self.agent_contacts += 1
                self._agent_in_contact = True
                vx0, vy0, _ = row["cmd"]
                dog_translating = math.hypot(vx0, vy0) > 1e-9
                relative = None
                if dog_translating:
                    travel0 = math.atan2(vy0, vx0)
                    raw = float(nearest["bearing_rad"]) - travel0
                    relative = math.atan2(math.sin(raw), math.cos(raw))
                if dog_translating:
                    self.contacts_while_translating += 1
                else:
                    self.contacts_while_stationary += 1
                self.contact_agents.add(str(nearest["id"]))
                if len(self.contact_records) < 50:
                    self.contact_records.append(
                        {
                            "at_s": round(self.sim_t, 2),
                            "agent": str(nearest["id"]),
                            "dog_translating": dog_translating,
                            "bearing_from_travel_rad": (
                                None if relative is None else round(relative, 3)
                            ),
                            "initiative": (
                                None if self.active is None else self.active.proposal.kind
                            ),
                            "agent_speed_mps": round(
                                math.hypot(float(nearest["vx"]), float(nearest["vy"])), 3
                            ),
                        }
                    )
            elif clearance > 0.0:
                self._agent_in_contact = False
            if clearance <= 0.0:
                self.contact_ticks += 1
        self.command_stream.append(tuple(row["cmd"]))
        if self._pending_preempt is not None:
            moving = any(abs(value) > 1e-9 for value in row["cmd"])
            initiative_running = row["a"] is not None
            if not initiative_running and not moving:
                pending = dict(self._pending_preempt)
                pending["ticks_to_yield"] = len(self.command_stream) - 1 - pending["at_tick"]
                pending["command_at_yield"] = list(row["cmd"])
                self.preemptions.append(pending)
                self._pending_preempt = None
        self._log_rows.append(json.dumps(row, separators=(",", ":"), sort_keys=True))
        if len(self._log_rows) >= 5000:
            self._flush_log()

    def _flush_log(self) -> None:
        if self.config.log_path is None or not self._log_rows:
            self._log_rows = []
            return
        path = Path(self.config.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8") as handle:
            handle.write("\n".join(self._log_rows) + "\n")
        self._log_rows = []

    def summary(self) -> dict[str, Any]:
        hours = self.config.duration_s / 3600.0
        expressive = {
            kind: count
            for kind, count in self.counters.admitted_by_kind.items()
            if kind != InitiativeKind.REST.value
        }
        return {
            "arm": self.arm.name,
            "seed": self.config.seed,
            "duration_s": self.config.duration_s,
            "start_hour": self.config.start_hour,
            "hours": hours,
            "proposals": self.counters.proposals,
            "proposed_by_kind": dict(self.counters.proposed_by_kind),
            "admitted": self.counters.admitted,
            "admitted_by_kind": dict(self.counters.admitted_by_kind),
            "expressive_initiations": sum(expressive.values()),
            "initiations_per_hour": sum(expressive.values()) / hours,
            "initiations_per_hour_with_rest": self.counters.admitted / hours,
            "admitted_fraction": (
                self.counters.admitted / self.counters.proposals
                if self.counters.proposals
                else None
            ),
            "refusals": dict(self.counters.refusals),
            "max_radius_m": self.max_radius_m,
            "visited_cells": sorted(self.visited_cells),
            "visited_cell_fraction": len(self.visited_cells) / 9.0,
            "home": list(self.home),
            "agent_contacts": self.agent_contacts,
            "min_agent_clearance_m": (
                None if math.isinf(self.min_agent_clearance_m) else self.min_agent_clearance_m
            ),
            "contact_records": self.contact_records,
            "contact_ticks": self.contact_ticks,
            "contact_seconds": round(self.contact_ticks * self.config.control_dt_s, 2),
            "contacts_while_translating": self.contacts_while_translating,
            "contacts_while_stationary": self.contacts_while_stationary,
            "contact_agents": sorted(self.contact_agents),
            "patrol_reasons": dict(self.patrol_reasons),
            "owner_turns": self.owner_turns,
            "owner_turns_during_initiative": self.owner_turns_during_initiative,
            "min_clearance_toward_agent_m": (
                None
                if math.isinf(self.min_clearance_toward_agent_m)
                else self.min_clearance_toward_agent_m
            ),
            "min_agent_clearance_under_initiative_m": (
                None
                if math.isinf(self.min_agent_clearance_under_initiative_m)
                else self.min_agent_clearance_under_initiative_m
            ),
            "static_collisions": self.world.collision_count,
            "min_static_clearance_m": self.world.minimum_clearance_m,
            "person_stop_m": self.gate.person_stop_m,
            "obstacle_stop_m": self.gate.obstacle_stop_m,
            "preemptions": self.preemptions,
            "withheld_quiet": self.withheld_quiet,
            "withheld_night": self.withheld_night,
            "admitted_in_quiet": self.counters.admitted_in_quiet,
            "admitted_in_night": self.counters.admitted_in_night,
            "attributed_initiations": self.counters.attributed,
            "places_checked": sum(
                int(item.get("checked", 0)) for item in self.initiations
            ),
            "initiations": self.initiations,
            "candidates_mean": (
                sum(self.candidate_counts) / len(self.candidate_counts)
                if self.candidate_counts
                else 0.0
            ),
            "command_sha": _stream_sha(self.command_stream),
            "translation_sha": _stream_sha(
                [(vx, vy, 0.0) for vx, vy, _ in self.command_stream]
            ),
            "estop_at_s": self.estop_at_s,
            "chatter": {
                "ticks": self.chatter.ticks,
                "admitted": self.chatter.admitted,
                "remarks": self.chatter.remarks,
                "skips": dict(self.chatter.skips),
            },
        }


def _block_cell(x: float, y: float) -> tuple[int, int]:
    """The 3x3 grid of 4 m blocks covering the [-6, 6] m city square."""

    return (
        min(2, max(0, math.floor((x + 6.0) / 4.0))),
        min(2, max(0, math.floor((y + 6.0) / 4.0))),
    )


def _stream_sha(stream: list[tuple[float, float, float]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for vx, vy, vyaw in stream:
        digest.update(f"{vx:.6f},{vy:.6f},{vyaw:.6f};".encode())
    return digest.hexdigest()


def shipped_default_candidate_probe() -> dict[str, Any]:
    """How many coverage candidates the SHIPPED 8 m visibility rule offers.

    Reported alongside the arms because it is the measured form of ROAM-2
    handoff H1: on this scene the shipped rule leaves the objective with
    almost nothing to say, whatever the selection on top of it does.
    """

    world = HeadlessCityWorld()
    _regions, objects = extract_city_semantics(world.model)
    counts: dict[str, int] = {}
    for visibility in (8.0, MAP_VISIBILITY_RANGE_M):
        learned = OnlineSemanticMap(provenance=PROVENANCE, visibility_range_m=visibility)
        for index, spec in enumerate(objects):
            label = str(spec["label"])
            x, y = float(spec["position"][0]), float(spec["position"][1])
            prior, _key = prior_for(label)
            learned.note_frame(queries=(label,))
            learned.observe(
                MapObservation(
                    label=label,
                    score=0.6,
                    surface_x=x,
                    surface_y=y,
                    surface_z=1.0,
                    range_m=max(0.5, math.hypot(x, y)),
                    bearing_rad=math.atan2(y, x),
                    depth_m=max(0.5, math.hypot(x, y)),
                    extent_w_m=(prior.min_w_m + prior.max_w_m) / 2.0,
                    extent_h_m=(prior.min_h_m + prior.max_h_m) / 2.0,
                    inlier_pixels=900,
                    frame_id=f"probe{index}",
                    visit_id="probe",
                    observed_wall_s=1_700_000_000.0 - 60.0 * (index + 1),
                    robot_x=0.0,
                    robot_y=0.0,
                    provenance=PROVENANCE,
                )
            )
        rows = learned.coverage_candidates(
            0.0, 0.0, 0.0, now_wall_s=1_700_000_000.0, limit=32
        )
        counts[f"visibility_{visibility}"] = len(rows)
    return counts
