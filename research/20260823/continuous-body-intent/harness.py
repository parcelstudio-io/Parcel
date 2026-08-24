"""H4 harness — drive the body-intent stream into a private MuJoCo sim.

Four states, one 50 Hz composer loop, three adapters consuming the SAME intent
(the sim adapter over the real IPC, the fake quadruped, the Go2 stub's pure
call planner).  Everything row B1-B8 needs is produced here.

Run one state:
    .parcel/bin/python research/20260823/continuous-body-intent/harness.py \
        --state idle_hold --seconds 600 --socket <path> --out results/

The owner's simulator is never touched: ``--socket`` must be a private path.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import socket as socketlib
import threading
import time
from pathlib import Path

from fake_quadruped_adapter import FakeQuadrupedAdapter

from parcel_robot.audio.prosody import Accent, BeatTrack
from parcel_robot.contracts.body_intent import BodyIntentV1
from parcel_robot.control.go2_sport_body_adapter import (
    GO2_SPORT_MANIFEST,
    Go2SportBodyAdapter,
    Go2SportNotCommissionedError,
    sport_calls_for,
)
from parcel_robot.core.hard_stop import InterventionSeverity, finalize_command
from parcel_robot.core.velocity_smoother import VelocitySmoother
from parcel_robot.models import VelocityCommand
from parcel_robot.motion.body_composer import DEFAULT_LIMITS, BodyComposer
from parcel_robot.motion.expression import (
    MAX_BODY_HEIGHT_M,
    MAX_BODY_PITCH_RAD,
    MAX_HEAD_PITCH_RAD,
    MAX_HEAD_YAW_RAD,
    ExpressionEngine,
    ExpressionGate,
    IdleLayer,
)
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper, ShaperLimits
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.simulation.body_adapter import SimulationBodyAdapter
from parcel_robot.simulation.ipc import (
    PROTOCOL_VERSION,
    expression_to_message,
    request_status,
    send_message,
    validate_simulator_message,
    velocity_to_message,
)

TICK_HZ = 50.0
TICK_S = 1.0 / TICK_HZ
PLAN_HZ = 10.0
STATES = ("idle_hold", "idle_look", "navigating", "estop")
ESTOP_AT_S = 300.0
ESTOP_LATCH_S = 60.0
REPLY_SAMPLE_EVERY = 50
ENVELOPE = {
    "posture_dz": MAX_BODY_HEIGHT_M,
    "posture_pitch": MAX_BODY_PITCH_RAD,
    "gaze_yaw": MAX_HEAD_YAW_RAD,
    "gaze_pitch": MAX_HEAD_PITCH_RAD,
}
AXES = ("posture_dz", "posture_pitch", "posture_roll", "gaze_yaw", "gaze_pitch")


# --------------------------------------------------------------------------
# IPC with a rejection channel the product's fire-and-forget send does not use
# --------------------------------------------------------------------------
def send_and_read(message: dict, socket_path: Path, *, timeout: float) -> str | None:
    """Send one message and return the server's error text, if it replied.

    ``ipc.send_message`` never reads: a rejection is invisible to the sender by
    design.  This mirrors it byte for byte and then waits for the reply the
    server would have sent, so row B4 is measured rather than assumed.
    """

    payload = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
    with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(payload)
        client.shutdown(socketlib.SHUT_WR)
        chunks: list[bytes] = []
        try:
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except (TimeoutError, OSError):
            return None
    if not chunks:
        return None
    line = b"".join(chunks).decode("utf-8", errors="replace").splitlines()[0]
    try:
        response = json.loads(line)
    except json.JSONDecodeError:
        return line
    if isinstance(response, dict) and response.get("type") == "error":
        return str(response.get("error"))
    return None


class CountingBackend:
    """The real socket backend, wrapped so every wire message is inspected."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = Path(socket_path)
        self.sent = 0
        self.local_validation_failures: list[str] = []
        self.server_rejections: list[str] = []
        self.reply_samples = 0
        self.velocity_wire: list[str] = []
        self.transport_retries = 0
        self.transport_drops = 0
        self._since_sample = 0

    def _dispatch(self, message: dict) -> None:
        message = dict(message)
        message.setdefault("version", PROTOCOL_VERSION)
        try:
            validate_simulator_message(message)
        except (TypeError, ValueError) as error:  # the server would reject this
            self.local_validation_failures.append(f"{message.get('type')}: {error}")
            return
        self.sent += 1
        self._since_sample += 1
        sample = self._since_sample >= REPLY_SAMPLE_EVERY
        if sample:
            self._since_sample = 0
            self.reply_samples += 1
        # The simulator's PoseSocketServer is one connection per message behind
        # a listen(8) backlog, and it accepts at most MAX_CLIENTS_PER_POLL per
        # frame. Under host load the backlog overflows and connect() raises
        # BlockingIOError. ``_step_expression`` swallows exactly this today
        # (decorative motion must never fault the loop), so the harness does the
        # same — and COUNTS it, because a silently dropped frame is a finding.
        for attempt in range(3):
            try:
                if sample:
                    error_text = send_and_read(message, self.socket_path, timeout=0.08)
                    if error_text is not None:
                        self.server_rejections.append(error_text)
                else:
                    send_message(message, self.socket_path)
                return
            except OSError:
                if attempt == 2:
                    self.transport_drops += 1
                    return
                self.transport_retries += 1
                time.sleep(0.002)

    def expression(self, joint_offsets: dict[str, float]) -> None:
        self._dispatch(expression_to_message(joint_offsets))

    def move(self, command: VelocityCommand) -> None:
        message = velocity_to_message(command)
        self.velocity_wire.append(json.dumps(message, sort_keys=True, allow_nan=False))
        self._dispatch(message)

    def stop(self) -> None:
        self.velocity_wire.append(json.dumps({"type": "stop"}, sort_keys=True))
        self._dispatch({"version": PROTOCOL_VERSION, "type": "stop"})

    def probe_rejection(self) -> str | None:
        """Seeded positive control: prove the reply channel can see a refusal."""

        bad = {"version": PROTOCOL_VERSION, "type": "expression", "joints": {"FL_thigh": 99.0}}
        for _attempt in range(5):
            try:
                return send_and_read(bad, self.socket_path, timeout=0.5)
            except OSError:
                time.sleep(0.05)
        return None


# --------------------------------------------------------------------------
# what today's runtime would put on the wire, for the byte-identity row
# --------------------------------------------------------------------------
class TodayPathShadow:
    """``_dispatch_active``'s send rule, replayed on the same finalized stream."""

    def __init__(self, refresh_s: float = 0.2) -> None:
        self.refresh_s = refresh_s
        self._last: VelocityCommand | None = None
        self._last_at: float | None = None
        self._was_moving = False
        self.wire: list[str] = []

    def observe(self, command: VelocityCommand | None, now_s: float) -> None:
        if command is None:
            if self._was_moving:
                self.wire.append(json.dumps({"type": "stop"}, sort_keys=True))
                self._was_moving = False
                self._last = None
                self._last_at = None
            return
        stale = self._last_at is None or now_s - self._last_at >= self.refresh_s
        if command == self._last and not stale:
            return
        self.wire.append(
            json.dumps(velocity_to_message(command), sort_keys=True, allow_nan=False)
        )
        self._last = command
        self._last_at = now_s
        self._was_moving = any(abs(v) > 1e-6 for v in (command.vx, command.vy, command.vyaw))


# --------------------------------------------------------------------------
# derivative bookkeeping
# --------------------------------------------------------------------------
class AxisDerivatives:
    """Rolling non-uniform 1st/2nd/3rd divided differences of one axis."""

    def __init__(self, bound: float) -> None:
        self.bound = bound
        self._t: list[float] = []
        self._x: list[float] = []
        self.max_d1 = 0.0
        self.max_d2 = 0.0
        self.max_d3 = 0.0
        self.over_bound = 0
        self.over_bound_1pct = 0
        self.samples = 0

    def push(self, t: float, x: float) -> None:
        self._t.append(t)
        self._x.append(x)
        if len(self._t) > 4:
            self._t.pop(0)
            self._x.pop(0)
        if len(self._t) < 4:
            return
        first = [
            (self._x[i + 1] - self._x[i]) / max(self._t[i + 1] - self._t[i], 1e-9) for i in range(3)
        ]
        second = [
            (first[i + 1] - first[i]) / max((self._t[i + 2] - self._t[i]) / 2.0, 1e-9)
            for i in range(2)
        ]
        third = (second[1] - second[0]) / max((self._t[3] - self._t[0]) / 3.0, 1e-9)
        self.samples += 1
        self.max_d1 = max(self.max_d1, max(abs(v) for v in first))
        self.max_d2 = max(self.max_d2, max(abs(v) for v in second))
        self.max_d3 = max(self.max_d3, abs(third))
        if abs(third) > self.bound + 1e-6:
            self.over_bound += 1
        if abs(third) > self.bound * 1.01:
            self.over_bound_1pct += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "declared_jerk_bound": self.bound,
            "max_abs_d1": round(self.max_d1, 6),
            "max_abs_d2": round(self.max_d2, 4),
            "max_abs_d3": round(self.max_d3, 2),
            "ticks_over_bound": self.over_bound,
            # The strict count above is measured on WALL-clock intervals, so a
            # late tick inflates a divided difference; this one allows 1 % for
            # that. results/limiter_bench.json has the jitter-free number.
            "ticks_over_bound_beyond_1pct": self.over_bound_1pct,
            "max_d3_over_bound_ratio": round(self.max_d3 / self.bound, 5),
            "samples": self.samples,
        }


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------
class BasePoller:
    """1 Hz base-pose sampling on its own thread, off the emission loop."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.samples: list[tuple[float, float, float, float]] = []
        self.errors = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="h4-base-poller", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                status = request_status(self.socket_path, timeout=1.0)
                robot = status.get("robot", {})
                self.samples.append(
                    (
                        time.perf_counter(),
                        float(robot.get("x", 0.0)),
                        float(robot.get("y", 0.0)),
                        float(robot.get("z", 0.0)),
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                self.errors += 1
            self._stop.wait(1.0)


def scripted_target(state: str, elapsed: float, rng: random.Random) -> VelocityCommand | None:
    """The behaviour layer's DESIRED velocity (pre-safety), or None for idle."""

    if state in {"idle_hold", "idle_look"}:
        return None
    if state == "estop" and elapsed >= ESTOP_AT_S:
        return None
    # A patrol-ish leg: cruise, then a rotate-in-place, then cruise back.
    phase = elapsed % 24.0
    if phase < 9.0:
        return VelocityCommand(vx=0.45)
    if phase < 12.0:
        return VelocityCommand(vyaw=0.6)
    if phase < 21.0:
        return VelocityCommand(vx=0.45)
    return VelocityCommand(vyaw=-0.6)


def run_state(state: str, seconds: float, socket_path: Path, seed: int) -> dict[str, object]:
    profile = RobotProfile.go2()
    backend = CountingBackend(socket_path)
    composer = BodyComposer()
    sim_adapter = SimulationBodyAdapter(backend, profile)
    fake_adapter = FakeQuadrupedAdapter()
    go2_stub = Go2SportBodyAdapter()
    shadow = TodayPathShadow()
    engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed)))
    rng = random.Random(seed + 1)
    smoother = VelocitySmoother()
    shaper = SCurveVelocityShaper(
        ShaperLimits(1.2, 3.0), ShaperLimits(1.2, 3.0), ShaperLimits(2.4, 6.0)
    )
    derivatives = {
        axis: AxisDerivatives(DEFAULT_LIMITS.jerk_bounds()[axis]) for axis in AXES
    }
    poller = BasePoller(socket_path)
    poller.start()

    emissions: list[float] = []
    gaps: list[float] = []
    envelope_violations = 0
    go2_stub_refusals = 0
    go2_calls = {"Move": 0, "StopMove": 0, "Euler": 0}
    trace: list[dict[str, object]] = []
    pending: list[tuple[float, str, object]] = []
    next_speech = 4.0
    estop_hold_at: float | None = None
    estop_stop_wire_at: float | None = None
    stops_before_estop = 0
    finalized: VelocityCommand | None = None
    last_plan_at = -1.0
    ticks = 0

    start = time.perf_counter()
    estop_event_at = start + ESTOP_AT_S if state == "estop" else None
    next_tick = start
    previous_emit: float | None = None
    while True:
        now = time.perf_counter()
        elapsed = now - start
        if elapsed >= seconds:
            break

        # ---- behaviour + the REAL finalize chain, at 10 Hz -----------------
        if elapsed - last_plan_at >= 1.0 / PLAN_HZ:
            last_plan_at = elapsed
            target = scripted_target(state, elapsed, rng)
            if target is None:
                finalized = None
                smoother.reset(now=now)
                shaper.reset()
            else:
                smoothed = smoother.step(target, now=now)
                if math.hypot(target.vx, target.vy) <= 1e-9 and abs(target.vyaw) > 1e-9:
                    smoothed = VelocityCommand(vyaw=smoothed.vyaw)
                shaped_triple = shaper.step(
                    (smoothed.vx, smoothed.vy, smoothed.vyaw), dt_s=1.0 / PLAN_HZ
                )
                shaped = VelocityCommand(*shaped_triple)
                finalized = finalize_command(shaped, InterventionSeverity.CLEAR).command

        # ---- gates and expression -----------------------------------------
        emergency = state == "estop" and ESTOP_AT_S <= elapsed < ESTOP_AT_S + ESTOP_LATCH_S
        gate = ExpressionGate(
            emergency_stopped=emergency,
            navigation_active=finalized is not None,
        )
        if state == "idle_look" and elapsed >= next_speech:
            pending.append((elapsed, "speech_start", rng.uniform(-0.6, 0.6)))
            pending.append((elapsed + 1.2, "speech_end", None))
            pending.append((elapsed + 1.2, "turn_pending", None))
            pending.append((elapsed + 2.0, "reply_started", None))
            pending.append((elapsed + 2.0, "arm", rng.uniform(0.2, 0.9)))
            next_speech = elapsed + rng.uniform(8.0, 16.0)
        due = [event for event in pending if event[0] <= elapsed]
        pending = [event for event in pending if event[0] > elapsed]
        for _when, kind, payload in due:
            _apply_speech_event(engine, kind, payload, elapsed, rng)
        offsets = engine.step(elapsed, gate)

        # ---- the composer: ALWAYS emits ------------------------------------
        intent = composer.compose(
            now_s=now,
            finalized_velocity=None if emergency else finalized,
            offsets=offsets,
            style="alert" if finalized is not None else "calm",
            emergency=emergency,
        )
        ticks += 1
        emissions.append(now)
        if previous_emit is not None:
            gaps.append((now - previous_emit) * 1000.0)
        previous_emit = now

        if _outside_envelope(intent):
            envelope_violations += 1
        for axis, value in zip(AXES, (*intent.posture, *intent.gaze)):
            derivatives[axis].push(now, value)

        # ---- the three bodies ----------------------------------------------
        sim_adapter.apply(intent, now_s=now)
        fake_adapter.apply(intent, now_s=now)
        for call in sport_calls_for(intent, GO2_SPORT_MANIFEST):
            go2_calls[call.method] += 1
        try:
            go2_stub.apply(intent, now_s=now)
        except Go2SportNotCommissionedError:
            go2_stub_refusals += 1

        shadow.observe(None if emergency else finalized, now)

        if estop_event_at is not None:
            if now < estop_event_at:
                stops_before_estop = sim_adapter.stop_publishes
            else:
                if estop_hold_at is None and intent.is_hold:
                    estop_hold_at = now
                if estop_stop_wire_at is None and sim_adapter.stop_publishes > stops_before_estop:
                    estop_stop_wire_at = now

        if ticks % 25 == 0 and len(trace) < 6000:
            trace.append(
                {
                    "t": round(elapsed, 4),
                    "hold": intent.is_hold,
                    "posture": [round(v, 6) for v in intent.posture],
                    "gaze": [round(v, 6) for v in intent.gaze],
                    "phase": round(intent.breathing_phase, 4),
                    "priority": intent.priority,
                }
            )

        next_tick += TICK_S
        sleep_for = next_tick - time.perf_counter()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_tick = time.perf_counter()

    poller.close()
    probe = backend.probe_rejection()
    duration = time.perf_counter() - start
    base = poller.samples
    drift = _drift(base)
    result: dict[str, object] = {
        "state": state,
        "seconds": round(duration, 3),
        "ticks": ticks,
        "emission_hz_mean": round(ticks / duration, 3),
        "gap_ms_max": round(max(gaps), 3) if gaps else None,
        "gap_ms_p99": round(_percentile(gaps, 0.99), 3) if gaps else None,
        "gap_ms_p50": round(_percentile(gaps, 0.50), 3) if gaps else None,
        "gaps_over_100ms": sum(1 for gap in gaps if gap > 100.0),
        "envelope_violations": envelope_violations,
        "derivatives": {axis: derivatives[axis].as_dict() for axis in AXES},
        "ipc": {
            "messages_sent": backend.sent,
            "transport_retries": backend.transport_retries,
            "transport_drops": backend.transport_drops,
            "local_validation_failures": backend.local_validation_failures,
            "reply_samples": backend.reply_samples,
            "server_rejections": backend.server_rejections,
            "seeded_rejection_probe": probe,
        },
        "sim_adapter": {
            "expression_publishes": sim_adapter.expression_publishes,
            "velocity_publishes": sim_adapter.velocity_publishes,
            "stop_publishes": sim_adapter.stop_publishes,
        },
        "byte_identity": _compare_wire(backend.velocity_wire, shadow.wire),
        "fake_quadruped": fake_adapter.summary(),
        "go2_stub": {
            "calls_planned": go2_calls,
            "adapter_refusals": go2_stub_refusals,
            "adapter_calls_attempted": ticks,
        },
        "composer": {
            "hold_ticks": composer.hold_ticks,
            "emergency_ticks": composer.emergency_ticks,
            "limited_ticks": composer.limited_ticks,
            "clamp_events": composer.clamp_events,
            "max_clamp_excess_frac": round(composer.max_clamp_excess_frac, 6),
            "epoch": composer.epoch,
            "seq": composer.seq,
        },
        "base_pose": {
            "samples": len(base),
            "poll_errors": poller.errors,
            "drift_xy_m": drift["xy"],
            "drift_z_m": drift["z"],
            "max_excursion_xy_m": drift["max_xy"],
        },
        "estop": _estop_result(estop_event_at, estop_hold_at, estop_stop_wire_at),
        "trace_points": len(trace),
    }
    return {"summary": result, "trace": trace}


def _apply_speech_event(
    engine: ExpressionEngine, kind: str, payload: object, now: float, rng: random.Random
) -> None:
    if kind == "speech_start":
        engine.reactions.on_speech_start(now, float(payload))  # type: ignore[arg-type]
    elif kind == "speech_end":
        engine.reactions.on_speech_end(now)
    elif kind == "turn_pending":
        engine.reactions.on_turn_pending(now)
    elif kind == "reply_started":
        engine.reactions.on_reply_started(now)
    elif kind == "arm":
        track = BeatTrack(
            duration_s=1.8,
            accents=tuple(
                Accent(time_s=0.25 * k, strength=rng.uniform(0.5, 1.0)) for k in range(7)
            ),
            envelope_hop_s=0.01,
            rms_envelope=(),
            arousal=float(payload),  # type: ignore[arg-type]
        )
        engine.beats.arm(track, playback_start_s=now, epoch=engine.speech_epoch)


def _outside_envelope(intent: BodyIntentV1) -> bool:
    values = {
        "posture_dz": intent.posture[0],
        "posture_pitch": intent.posture[1],
        "gaze_yaw": intent.gaze[0],
        "gaze_pitch": intent.gaze[1],
    }
    if abs(intent.posture[2]) > 1e-12:
        return True
    return any(abs(value) > ENVELOPE[axis] + 1e-12 for axis, value in values.items())


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[index]


def _drift(samples: list[tuple[float, float, float, float]]) -> dict[str, float | None]:
    if len(samples) < 2:
        return {"xy": None, "z": None, "max_xy": None}
    first = samples[0]
    last = samples[-1]
    excursions = [math.dist((first[1], first[2]), (s[1], s[2])) for s in samples]
    return {
        "xy": round(math.dist((first[1], first[2]), (last[1], last[2])), 6),
        "z": round(abs(last[3] - first[3]), 6),
        "max_xy": round(max(excursions), 6),
    }


def _compare_wire(composer_wire: list[str], today_wire: list[str]) -> dict[str, object]:
    identical = composer_wire == today_wire
    first_difference = None
    if not identical:
        for index in range(max(len(composer_wire), len(today_wire))):
            left = composer_wire[index] if index < len(composer_wire) else None
            right = today_wire[index] if index < len(today_wire) else None
            if left != right:
                first_difference = {"index": index, "composer": left, "today": right}
                break
    return {
        "composer_messages": len(composer_wire),
        "today_messages": len(today_wire),
        "byte_identical": identical,
        "first_difference": first_difference,
    }


def _estop_result(
    event_at: float | None, hold_at: float | None, stop_wire_at: float | None
) -> dict[str, object]:
    if event_at is None:
        return {"injected": False}
    intent_ms = None if hold_at is None else round((hold_at - event_at) * 1000.0, 4)
    wire_ms = None if stop_wire_at is None else round((stop_wire_at - event_at) * 1000.0, 4)
    return {
        "injected": True,
        "hold_seen": hold_at is not None,
        "intent_latency_ms": intent_ms,
        "intent_latency_ticks": None if intent_ms is None else round(intent_ms / (TICK_S * 1000.0), 3),
        "wire_stop_latency_ms": wire_ms,
        "wire_stop_latency_ticks": None if wire_ms is None else round(wire_ms / (TICK_S * 1000.0), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 body-intent harness")
    parser.add_argument("--state", choices=STATES, required=True)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--out", default="results")
    parser.add_argument("--seed", type=int, default=20260823)
    args = parser.parse_args()

    socket_path = Path(args.socket).resolve()
    if socket_path == Path("/tmp/parcel_sim.sock"):
        raise SystemExit("refusing to touch the owner's simulator socket")

    payload = run_state(args.state, args.seconds, socket_path, args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / f"state_{args.state}.json"
    summary_path.write_text(json.dumps(payload["summary"], indent=2, sort_keys=True))
    (out_dir / f"trace_{args.state}.json").write_text(json.dumps(payload["trace"]))
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    print(f"wrote {summary_path}")


if __name__ == "__main__":
    main()
