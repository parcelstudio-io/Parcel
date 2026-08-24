"""Row B9 — what the composer costs the 10 Hz loop.

A harness copy of the control-loop cadence: fetch one observation over the
simulator socket (what ``backend.observe()`` does), run the real smoother /
shaper / ``finalize_command`` chain, dispatch under ``_dispatch_active``'s send
rule, and record the elapsed time the way ``component_metrics`` records
``ControlLoopWork``.

Three arms, each measured on its own so contention cannot be blamed on the
wrong one:

* ``baseline``  — the loop as above.
* ``in_loop``   — the same loop, plus a full 50 Hz worth of composer ticks and
  sim-adapter dispatches executed INSIDE the measured section (five per 10 Hz
  tick).  This is the pessimistic reading of B9.
* ``thread``    — the composer on its own 50 Hz thread, the way expression
  already runs today, with the 10 Hz loop measured beside it.  This is the
  shape the product would actually adopt, and it measures GIL contention
  rather than in-line work.

Plus a microbenchmark of ``compose`` + ``adapter.apply`` with the socket
replaced by a sink, because that is the number that generalizes off this host.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import threading
import time
from pathlib import Path

from harness import TodayPathShadow, scripted_target

from parcel_robot.core.hard_stop import InterventionSeverity, finalize_command
from parcel_robot.core.velocity_smoother import VelocitySmoother
from parcel_robot.models import VelocityCommand
from parcel_robot.motion.body_composer import BodyComposer
from parcel_robot.motion.expression import ExpressionEngine, ExpressionGate, IdleLayer
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper, ShaperLimits
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.simulation.body_adapter import SimulationBodyAdapter
from parcel_robot.simulation.ipc import (
    publish_expression,
    publish_stop,
    publish_velocity,
    request_status,
)

LOOP_HZ = 10.0
LOOP_S = 1.0 / LOOP_HZ
COMPOSER_HZ = 50.0
ARMS = ("baseline", "in_loop", "thread")


class SocketBody:
    """The sim backend as the adapter wants it, over the private socket.

    Every publish tolerates a transient transport failure the way
    ``_step_expression`` does today (decorative motion may never fault the
    loop) and COUNTS it: the simulator's one-connection-per-message server has
    a ``listen(8)`` backlog and accepts at most four clients per frame, which
    overflows into ``BlockingIOError`` when this host is loaded.
    """

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.transport_retries = 0
        self.transport_drops = 0

    def _publish(self, send) -> None:
        for attempt in range(3):
            try:
                send()
                return
            except OSError:
                if attempt == 2:
                    self.transport_drops += 1
                    return
                self.transport_retries += 1
                time.sleep(0.002)

    def expression(self, joint_offsets: dict[str, float]) -> None:
        self._publish(lambda: publish_expression(joint_offsets, self.socket_path))

    def move(self, command: VelocityCommand) -> None:
        self._publish(lambda: publish_velocity(command, self.socket_path))

    def stop(self) -> None:
        self._publish(lambda: publish_stop(self.socket_path))


class SinkBody:
    """No I/O at all: for the microbenchmark."""

    def expression(self, joint_offsets: dict[str, float]) -> None:
        return None

    def move(self, command: VelocityCommand) -> None:
        return None

    def stop(self) -> None:
        return None


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "n": len(ordered),
        "p50_ms": round(at(0.50), 4),
        "p95_ms": round(at(0.95), 4),
        "p99_ms": round(at(0.99), 4),
        "max_ms": round(max(ordered), 4),
        "mean_ms": round(sum(ordered) / len(ordered), 4),
    }


def run_arm(arm: str, seconds: float, socket_path: Path, seed: int) -> dict[str, object]:
    profile = RobotProfile.go2()
    body = SocketBody(socket_path)
    smoother = VelocitySmoother()
    shaper = SCurveVelocityShaper(
        ShaperLimits(1.2, 3.0), ShaperLimits(1.2, 3.0), ShaperLimits(2.4, 6.0)
    )
    shadow = TodayPathShadow()
    rng = random.Random(seed)
    composer = BodyComposer()
    adapter = SimulationBodyAdapter(body, profile)
    engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed + 1)))
    gate = ExpressionGate()
    stop_event = threading.Event()
    thread: threading.Thread | None = None

    if arm == "thread":
        thread_composer = BodyComposer()
        thread_adapter = SimulationBodyAdapter(body, profile)
        thread_engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed + 2)))

        def loop() -> None:
            period = 1.0 / COMPOSER_HZ
            while not stop_event.is_set():
                started = time.perf_counter()
                intent = thread_composer.compose(
                    now_s=started,
                    finalized_velocity=None,
                    offsets=thread_engine.step(started, gate),
                )
                thread_adapter.apply(intent, now_s=started)
                stop_event.wait(max(0.0, period - (time.perf_counter() - started)))

        thread = threading.Thread(target=loop, name="h4-composer", daemon=True)
        thread.start()

    work_ms: list[float] = []
    load_before = os.getloadavg()
    start = time.perf_counter()
    next_tick = start
    observation_errors = 0
    while True:
        now = time.perf_counter()
        elapsed = now - start
        if elapsed >= seconds:
            break
        started = time.perf_counter()

        try:
            request_status(socket_path, timeout=1.0)
        except (OSError, RuntimeError, TypeError, ValueError):
            observation_errors += 1
        target = scripted_target("navigating", elapsed, rng)
        if target is None:
            finalized = None
            smoother.reset(now=now)
            shaper.reset()
        else:
            smoothed = smoother.step(target, now=now)
            if math.hypot(target.vx, target.vy) <= 1e-9 and abs(target.vyaw) > 1e-9:
                smoothed = VelocityCommand(vyaw=smoothed.vyaw)
            shaped = VelocityCommand(*shaper.step((smoothed.vx, smoothed.vy, smoothed.vyaw), dt_s=LOOP_S))
            finalized = finalize_command(shaped, InterventionSeverity.CLEAR).command

        before = len(shadow.wire)
        shadow.observe(finalized, now)
        if len(shadow.wire) > before:
            if finalized is None:
                body.stop()
            else:
                body.move(finalized)

        if arm == "in_loop":
            for sub in range(5):
                sub_now = now + sub * (1.0 / COMPOSER_HZ)
                intent = composer.compose(
                    now_s=sub_now,
                    finalized_velocity=finalized,
                    offsets=engine.step(sub_now, gate),
                )
                adapter.apply(intent, now_s=sub_now)

        work_ms.append((time.perf_counter() - started) * 1000.0)
        next_tick += LOOP_S
        sleep_for = next_tick - time.perf_counter()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_tick = time.perf_counter()

    stop_event.set()
    if thread is not None:
        thread.join(timeout=2.0)
    return {
        "arm": arm,
        "seconds": round(time.perf_counter() - start, 3),
        "observation_errors": observation_errors,
        "transport_retries": body.transport_retries,
        "transport_drops": body.transport_drops,
        "loadavg_before": [round(v, 2) for v in load_before],
        "loadavg_after": [round(v, 2) for v in os.getloadavg()],
        "loop_work": percentiles(work_ms),
    }


def synthetic_loop(iterations: int, seed: int, *, with_composer: bool) -> dict[str, float]:
    """The loop body with the socket removed, with and without the composer.

    The socket arms above are honest but noisy: one ``request_status`` round
    trip on a host at load 170 swamps everything else, and a 5 % criterion
    cannot be read through that. This is the same arithmetic — smoother,
    rotate-in-place rule, S-curve shaper, ``finalize_command``, dispatch rule,
    and (optionally) five composer ticks with their adapter dispatches — with
    a sink in place of the transport, so the delta IS the composer.
    """

    profile = RobotProfile.go2()
    body = SinkBody()
    smoother = VelocitySmoother()
    shaper = SCurveVelocityShaper(
        ShaperLimits(1.2, 3.0), ShaperLimits(1.2, 3.0), ShaperLimits(2.4, 6.0)
    )
    shadow = TodayPathShadow()
    composer = BodyComposer()
    adapter = SimulationBodyAdapter(body, profile)
    engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed + 3)))
    gate = ExpressionGate()
    rng = random.Random(seed)
    samples: list[float] = []
    for index in range(iterations):
        now = index * LOOP_S
        started = time.perf_counter()
        target = scripted_target("navigating", now, rng)
        if target is None:
            finalized = None
            smoother.reset(now=now)
            shaper.reset()
        else:
            smoothed = smoother.step(target, now=now)
            if math.hypot(target.vx, target.vy) <= 1e-9 and abs(target.vyaw) > 1e-9:
                smoothed = VelocityCommand(vyaw=smoothed.vyaw)
            shaped = VelocityCommand(
                *shaper.step((smoothed.vx, smoothed.vy, smoothed.vyaw), dt_s=LOOP_S)
            )
            finalized = finalize_command(shaped, InterventionSeverity.CLEAR).command
        before = len(shadow.wire)
        shadow.observe(finalized, now)
        if len(shadow.wire) > before:
            body.stop() if finalized is None else body.move(finalized)
        if with_composer:
            for sub in range(5):
                sub_now = now + sub / COMPOSER_HZ
                intent = composer.compose(
                    now_s=sub_now,
                    finalized_velocity=finalized,
                    offsets=engine.step(sub_now, gate),
                )
                adapter.apply(intent, now_s=sub_now)
        samples.append((time.perf_counter() - started) * 1000.0)
    return percentiles(samples)


def microbenchmark(iterations: int, seed: int) -> dict[str, object]:
    profile = RobotProfile.go2()
    composer = BodyComposer()
    adapter = SimulationBodyAdapter(SinkBody(), profile)
    engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed)))
    gate = ExpressionGate()
    command = VelocityCommand(vx=0.4)
    samples: list[float] = []
    for index in range(iterations):
        now = index / COMPOSER_HZ
        offsets = engine.step(now, gate)
        started = time.perf_counter()
        intent = composer.compose(now_s=now, finalized_velocity=command, offsets=offsets)
        adapter.apply(intent, now_s=now)
        samples.append((time.perf_counter() - started) * 1000.0)
    return {"compose_plus_apply": percentiles(samples)}


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 loop-cost measurement")
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--out", default="results/loop_cost.json")
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20260823)
    args = parser.parse_args()

    socket_path = Path(args.socket).resolve()
    if socket_path == Path("/tmp/parcel_sim.sock"):
        raise SystemExit("refusing to touch the owner's simulator socket")

    arms = {arm: run_arm(arm, args.seconds, socket_path, args.seed) for arm in ARMS}
    baseline = arms["baseline"]["loop_work"]["p99_ms"]  # type: ignore[index]
    synthetic_without = synthetic_loop(args.iterations, args.seed, with_composer=False)
    synthetic_with = synthetic_loop(args.iterations, args.seed, with_composer=True)
    payload: dict[str, object] = {
        "arms": arms,
        "micro": microbenchmark(args.iterations, args.seed),
        "synthetic_loop": {
            "without_composer": synthetic_without,
            "with_composer_5_ticks": synthetic_with,
            "p99_delta_pct": round(
                100.0
                * (synthetic_with["p99_ms"] - synthetic_without["p99_ms"])
                / synthetic_without["p99_ms"],
                3,
            ),
            "p50_delta_pct": round(
                100.0
                * (synthetic_with["p50_ms"] - synthetic_without["p50_ms"])
                / synthetic_without["p50_ms"],
                3,
            ),
        },
        "p99_delta_pct": {
            arm: round(
                100.0 * (arms[arm]["loop_work"]["p99_ms"] - baseline) / baseline,  # type: ignore[index]
                3,
            )
            for arm in ARMS
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
