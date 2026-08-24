"""Run the preregistered terminal-aware H3 mechanism experiment."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from parcel_robot.models import VelocityCommand
from parcel_robot.simulation.dynamic_city import circle_contact_ttc

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
H3 = REPO / "research" / "20260823" / "drives-and-initiative"
CANONICAL_RESULTS = H3 / "results" / "runs.json"

SEEDS = (1, 2, 3)
DURATION_S = 3600.0
CONTROL_DT_S = 0.1
HOME_ARRIVAL_M = 0.25
RETURN_SPEED_MPS = 0.30
RETURN_BUDGET_S = 60.0
SHOULDER_RADIUS_M = 0.8
SHOULDER_ARRIVAL_M = 0.20
SHOULDER_BUDGET_S = 30.0
TTC_STOP_S = 0.8
TTC_SLOW_S = 1.8
TTC_MIN_SCALE = 0.15
ROBOT_RADIUS_M = 0.32
TRAVEL_TETHER_M = 6.0
PREDICTION_TIMES_S = (0.0, 1.0, 2.0, 3.0, 4.0)
N_SHOULDER_SAMPLES = 16


def _load_h3() -> ModuleType:
    """Load the frozen H3 research harness without making it a package."""

    name = "parcel_h3_frozen_arena"
    spec = importlib.util.spec_from_file_location(name, H3 / "arena.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load H3 arena")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


H3_ARENA = _load_h3()


@dataclass
class ActionTerminal:
    """Research-only terminal state for one self-authored travel action."""

    source_kind: str
    source_end: str
    entered_s: float
    phase: str = "return_home"
    phase_entered_s: float = 0.0
    shoulder: tuple[float, float] | None = None
    ticks: int = 0
    gate_interventions: int = 0


class TerminalAwareArena(H3_ARENA.InitiativeArena):
    """H3 radius-six arm with an explicit preemptible action terminal."""

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.terminal: ActionTerminal | None = None
        self.terminal_rows: list[dict[str, Any]] = []
        self.dynamic_gate_counts = {"stop": 0, "slow": 0, "clear": 0}
        self.dynamic_gate_bearings = {"front": 0, "side": 0, "rear": 0}
        self._terminal_probe_scheduled = False

    def _decide(self, observation: Any) -> tuple[Any, str | None]:
        if self.terminal is not None:
            return None, None
        return super()._decide(observation)

    def _end(self, reason: str) -> None:
        active = self.active
        should_terminal = (
            active is not None
            and active.proposal.travels
            and reason in {"budget", "budget_exhausted", "boxed_in"}
        )
        source_kind = None if active is None else active.proposal.kind
        super()._end(reason)
        if not should_terminal or source_kind is None:
            return
        self.terminal = ActionTerminal(
            source_kind=source_kind,
            source_end=reason,
            entered_s=self.sim_t,
            phase_entered_s=self.sim_t,
        )
        if not self._terminal_probe_scheduled:
            # Preregistered probe: exercise authority release while RETURN is
            # actually commanding motion, rather than hoping a natural event
            # happens to overlap it.
            self.next_owner_turn_s = self.sim_t + 3.0
            self._terminal_probe_scheduled = True

    def _preempt(self, events: list[str]) -> str | None:
        if self.terminal is None:
            return super()._preempt(events)
        trigger = "estop" if "estop" in events else "owner_turn" if "owner_turn" in events else None
        if trigger is None:
            return None
        self._pending_preempt = {
            "trigger": trigger,
            "at_s": round(self.sim_t, 3),
            "at_tick": len(self.command_stream),
            "kind": f"terminal:{self.terminal.phase}",
            "held_s": round(self.sim_t - self.terminal.entered_s, 3),
        }
        self._release_terminal(f"preempted:{trigger}", reached=False)
        return trigger

    def _express(self, observation: Any) -> tuple[VelocityCommand, str]:
        if self.terminal is not None:
            command, note = self._terminal_step(observation)
        else:
            command, note = super()._express(observation)
        command, gate_note = self._all_track_gate(command, observation)
        if self.terminal is not None and gate_note != "all_tracks_clear":
            self.terminal.gate_interventions += 1
        if gate_note == "all_tracks_clear":
            return command, note
        return command, f"{note}|{gate_note}"

    def _terminal_step(self, observation: Any) -> tuple[VelocityCommand, str]:
        terminal = self.terminal
        if terminal is None:
            return VelocityCommand(), "terminal_released"
        terminal.ticks += 1
        if terminal.phase == "return_home":
            distance = math.hypot(self.home[0] - self.pose[0], self.home[1] - self.pose[1])
            if distance <= HOME_ARRIVAL_M:
                self._release_terminal("home", reached=True)
                return VelocityCommand(), "terminal_home_release"
            if self.sim_t - terminal.phase_entered_s >= RETURN_BUDGET_S:
                terminal.phase = "stand_aside"
                terminal.phase_entered_s = self.sim_t
                terminal.shoulder = self._select_shoulder(observation)
                return VelocityCommand(), "terminal_return_timeout"
            return self._command_to(self.home, RETURN_SPEED_MPS), "terminal_return"

        if terminal.shoulder is None:
            terminal.shoulder = self._select_shoulder(observation)
        distance = math.hypot(
            terminal.shoulder[0] - self.pose[0],
            terminal.shoulder[1] - self.pose[1],
        )
        if distance <= SHOULDER_ARRIVAL_M:
            self._release_terminal("stand_aside", reached=True)
            return VelocityCommand(), "terminal_shoulder_release"
        if self.sim_t - terminal.phase_entered_s >= SHOULDER_BUDGET_S:
            self._release_terminal("terminal_timeout", reached=False)
            return VelocityCommand(), "terminal_timeout_release"
        return self._command_to(terminal.shoulder, RETURN_SPEED_MPS), "terminal_stand_aside"

    def _release_terminal(self, outcome: str, *, reached: bool) -> None:
        terminal = self.terminal
        if terminal is None:
            return
        row = {
            **asdict(terminal),
            "released_s": round(self.sim_t, 3),
            "elapsed_s": round(self.sim_t - terminal.entered_s, 3),
            "outcome": outcome,
            "reached_terminal": reached,
            "release_command": [0.0, 0.0, 0.0],
        }
        self.terminal_rows.append(row)
        if self.initiations:
            self.initiations[-1]["terminal"] = {
                "outcome": outcome,
                "reached": reached,
                "elapsed_s": row["elapsed_s"],
            }
        self.terminal = None
        self.idle_since_s = self.sim_t

    def _command_to(self, target: tuple[float, float], max_speed: float) -> VelocityCommand:
        dx = target[0] - self.pose[0]
        dy = target[1] - self.pose[1]
        distance = math.hypot(dx, dy)
        if distance <= 1e-9:
            return VelocityCommand()
        speed = min(max_speed, max(0.08, distance * 0.8))
        world_vx = dx / distance * speed
        world_vy = dy / distance * speed
        cosine = math.cos(self.pose[2])
        sine = math.sin(self.pose[2])
        return VelocityCommand(
            vx=cosine * world_vx + sine * world_vy,
            vy=-sine * world_vx + cosine * world_vy,
        )

    def _select_shoulder(self, observation: Any) -> tuple[float, float]:
        candidates: list[tuple[float, float, float, float]] = []
        for index in range(N_SHOULDER_SAMPLES):
            angle = 2.0 * math.pi * index / N_SHOULDER_SAMPLES
            x = self.pose[0] + SHOULDER_RADIUS_M * math.cos(angle)
            y = self.pose[1] + SHOULDER_RADIUS_M * math.sin(angle)
            if math.hypot(x - self.home[0], y - self.home[1]) > TRAVEL_TETHER_M:
                continue
            minimum = math.inf
            for track in observation.dynamic_agents:
                for future_s in PREDICTION_TIMES_S:
                    actor_x = float(track.x) + float(track.vx) * future_s
                    actor_y = float(track.y) + float(track.vy) * future_s
                    clearance = (
                        math.hypot(actor_x - x, actor_y - y)
                        - ROBOT_RADIUS_M
                        - float(track.radius_m)
                    )
                    minimum = min(minimum, clearance)
            candidates.append((minimum, -math.hypot(x - self.home[0], y - self.home[1]), x, y))
        if not candidates:
            return self.home
        _clearance, _home_tie, x, y = max(candidates)
        return (x, y)

    def _all_track_gate(
        self, command: VelocityCommand, observation: Any
    ) -> tuple[VelocityCommand, str]:
        speed = math.hypot(command.vx, command.vy)
        if speed <= 1e-9:
            self.dynamic_gate_counts["clear"] += 1
            return command, "all_tracks_clear"
        cosine = math.cos(self.pose[2])
        sine = math.sin(self.pose[2])
        world_vx = cosine * command.vx - sine * command.vy
        world_vy = sine * command.vx + cosine * command.vy
        risks: list[tuple[float, float]] = []
        for track in observation.dynamic_agents:
            ttc = circle_contact_ttc(
                float(track.x) - self.pose[0],
                float(track.y) - self.pose[1],
                float(track.vx) - world_vx,
                float(track.vy) - world_vy,
                ROBOT_RADIUS_M + float(track.radius_m),
                horizon_s=TTC_SLOW_S,
            )
            if ttc is None:
                continue
            bearing = _wrap(math.atan2(float(track.y) - self.pose[1], float(track.x) - self.pose[0]) - self.pose[2])
            risks.append((ttc, bearing))
        if not risks:
            self.dynamic_gate_counts["clear"] += 1
            return command, "all_tracks_clear"
        ttc, bearing = min(risks)
        bucket = "front" if abs(bearing) < math.pi / 4.0 else "rear" if abs(bearing) > 3.0 * math.pi / 4.0 else "side"
        self.dynamic_gate_bearings[bucket] += 1
        if ttc <= TTC_STOP_S:
            self.dynamic_gate_counts["stop"] += 1
            return VelocityCommand(vyaw=command.vyaw), f"all_tracks_stop:{bucket}"
        scale = max(TTC_MIN_SCALE, (ttc - TTC_STOP_S) / (TTC_SLOW_S - TTC_STOP_S))
        self.dynamic_gate_counts["slow"] += 1
        return (
            VelocityCommand(vx=command.vx * scale, vy=command.vy * scale, vyaw=command.vyaw),
            f"all_tracks_slow:{bucket}",
        )

    def summary(self) -> dict[str, Any]:
        row = super().summary()
        row.update(
            {
                "terminal_rows": self.terminal_rows,
                "terminal_incomplete": None if self.terminal is None else asdict(self.terminal),
                "dynamic_gate_counts": self.dynamic_gate_counts,
                "dynamic_gate_bearings": self.dynamic_gate_bearings,
            }
        )
        return row


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _geometry_table() -> list[dict[str, Any]]:
    scenarios = (
        ("front_closing", 2.0, 0.0, -1.0, 0.0, True),
        ("side_closing", 0.0, 2.0, 0.0, -1.0, True),
        ("rear_closing", -2.0, 0.0, 1.0, 0.0, True),
        ("front_diverging", 2.0, 0.0, 1.0, 0.0, False),
        ("front_static", 2.0, 0.0, 0.0, 0.0, False),
    )
    rows = []
    for name, x, y, vx, vy, expected in scenarios:
        ttc = circle_contact_ttc(x, y, vx, vy, 0.56, horizon_s=5.0)
        rows.append(
            {
                "scenario": name,
                "ttc_s": ttc,
                "collision_selected": ttc is not None,
                "expected_collision_selected": expected,
                "passed": (ttc is not None) is expected,
            }
        )
    return rows


def _canonical_headline() -> dict[int, dict[str, Any]]:
    payload = json.loads(CANONICAL_RESULTS.read_text())
    return {
        int(row["seed"]): row
        for row in payload["runs"]
        if row.get("label") == "radius6" and int(row["seed"]) in SEEDS
    }


def _baseline_integrity(
    current: list[dict[str, Any]], canonical: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    keys = (
        "expressive_initiations",
        "agent_contacts",
        "contacts_while_stationary",
        "contacts_while_translating",
        "command_sha",
        "translation_sha",
    )
    rows = []
    for run in current:
        seed = int(run["seed"])
        expected = canonical[seed]
        matches = {key: run[key] == expected[key] for key in keys}
        rows.append({"seed": seed, "matches": matches, "all_match": all(matches.values())})
    return rows


def _pooled(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "initiatives": sum(int(row["expressive_initiations"]) for row in runs),
        "contacts": sum(int(row["agent_contacts"]) for row in runs),
        "stationary_contacts": sum(int(row["contacts_while_stationary"]) for row in runs),
        "moving_contacts": sum(int(row["contacts_while_translating"]) for row in runs),
        "contact_seconds": round(sum(float(row["contact_seconds"]) for row in runs), 3),
        "max_preemption_ticks": max(
            (
                int(item["ticks_to_yield"])
                for row in runs
                for item in row["preemptions"]
            ),
            default=None,
        ),
        "preemption_commands_all_zero": all(
            all(float(value) == 0.0 for value in item["command_at_yield"])
            for row in runs
            for item in row["preemptions"]
        ),
    }


def _ratio(value: float, baseline: float) -> float | None:
    return None if baseline == 0.0 else value / baseline


def _rows(
    baseline_runs: list[dict[str, Any]], proposed_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline = _pooled(baseline_runs)
    proposed = _pooled(proposed_runs)
    terminals = [item for run in proposed_runs for item in run["terminal_rows"]]
    probe_terminals = [item for item in terminals if str(item["outcome"]).startswith("preempted:")]
    natural = [item for item in terminals if item not in probe_terminals]
    reached = [item for item in natural if bool(item["reached_terminal"])]
    all_released = all(item["release_command"] == [0.0, 0.0, 0.0] for item in terminals) and all(
        run["terminal_incomplete"] is None for run in proposed_runs
    )
    stationary_ratio = _ratio(proposed["stationary_contacts"], baseline["stationary_contacts"])
    total_ratio = _ratio(proposed["contacts"], baseline["contacts"])
    initiative_ratio = _ratio(proposed["initiatives"], baseline["initiatives"])
    contact_time_ratio = _ratio(proposed["contact_seconds"], baseline["contact_seconds"])
    return {
        "TA1_stationary_contacts": {
            "baseline": baseline["stationary_contacts"],
            "proposed": proposed["stationary_contacts"],
            "ratio": stationary_ratio,
            "bar": "proposed <= 5% of baseline",
            "passed": stationary_ratio is not None and stationary_ratio <= 0.05,
        },
        "TA2_all_contacts": {
            "baseline": baseline["contacts"],
            "proposed": proposed["contacts"],
            "ratio": total_ratio,
            "bar": "proposed <= 10% of baseline",
            "passed": total_ratio is not None and total_ratio <= 0.10,
        },
        "TA3_moving_contacts": {
            "baseline": baseline["moving_contacts"],
            "proposed": proposed["moving_contacts"],
            "bar": "proposed <= baseline",
            "passed": proposed["moving_contacts"] <= baseline["moving_contacts"],
        },
        "TA4_initiative_retained": {
            "baseline": baseline["initiatives"],
            "proposed": proposed["initiatives"],
            "ratio": initiative_ratio,
            "per_seed": [int(row["expressive_initiations"]) for row in proposed_runs],
            "bar": "each seed > 0 and pooled >= 80% of baseline",
            "passed": initiative_ratio is not None
            and initiative_ratio >= 0.80
            and all(int(row["expressive_initiations"]) > 0 for row in proposed_runs),
        },
        "TA5_preemption": {
            "events": sum(len(row["preemptions"]) for row in proposed_runs),
            "max_ticks": proposed["max_preemption_ticks"],
            "all_commands_zero": proposed["preemption_commands_all_zero"],
            "bar": "maximum <= 1 tick and exact zero",
            "passed": proposed["max_preemption_ticks"] is not None
            and proposed["max_preemption_ticks"] <= 1
            and proposed["preemption_commands_all_zero"],
        },
        "TA6_terminals": {
            "started_and_released": len(terminals),
            "probe_preempted": len(probe_terminals),
            "natural": len(natural),
            "natural_reached": len(reached),
            "natural_reached_fraction": None if not natural else len(reached) / len(natural),
            "all_released_exact_zero_and_none_incomplete": all_released,
            "outcomes": _counts(str(item["outcome"]) for item in terminals),
            "bar": ">= 90% natural reach; every terminal releases",
            "passed": bool(natural)
            and len(reached) / len(natural) >= 0.90
            and all_released,
        },
        "TA7_contact_time": {
            "baseline_s": baseline["contact_seconds"],
            "proposed_s": proposed["contact_seconds"],
            "ratio": contact_time_ratio,
            "bar": "proposed <= 10% of baseline",
            "passed": contact_time_ratio is not None and contact_time_ratio <= 0.10,
        },
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _run_one(seed: int, proposed: bool, duration_s: float) -> dict[str, Any]:
    config = H3_ARENA.RunConfig(
        arm="radius6",
        seed=seed,
        duration_s=duration_s,
        control_dt_s=CONTROL_DT_S,
    )
    arena = TerminalAwareArena(config) if proposed else H3_ARENA.InitiativeArena(config)
    return arena.run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=DURATION_S)
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    if args.duration_s <= 0.0:
        raise SystemExit("--duration-s must be positive")

    baseline_runs = []
    proposed_runs = []
    for seed in SEEDS:
        baseline_runs.append(_run_one(seed, False, args.duration_s))
        proposed_runs.append(_run_one(seed, True, args.duration_s))

    integrity = (
        _baseline_integrity(baseline_runs, _canonical_headline())
        if args.duration_s == DURATION_S
        else []
    )
    geometry = _geometry_table()
    rows = _rows(baseline_runs, proposed_runs)
    headline_names = (
        "TA1_stationary_contacts",
        "TA2_all_contacts",
        "TA4_initiative_retained",
        "TA5_preemption",
        "TA6_terminals",
    )
    valid = bool(integrity) and all(item["all_match"] for item in integrity)
    payload = {
        "design_sha256": "1a32b273616617b166652a9c67ec25e081c14789ac1a59535fee430637cef517",
        "parameters": {
            "seeds": list(SEEDS),
            "duration_s": args.duration_s,
            "control_dt_s": CONTROL_DT_S,
            "home_arrival_m": HOME_ARRIVAL_M,
            "return_speed_mps": RETURN_SPEED_MPS,
            "return_budget_s": RETURN_BUDGET_S,
            "shoulder_radius_m": SHOULDER_RADIUS_M,
            "shoulder_budget_s": SHOULDER_BUDGET_S,
            "ttc_stop_s": TTC_STOP_S,
            "ttc_slow_s": TTC_SLOW_S,
            "robot_radius_m": ROBOT_RADIUS_M,
        },
        "baseline_integrity": integrity,
        "baseline_valid": valid,
        "geometry_table": geometry,
        "geometry_passed": all(item["passed"] for item in geometry),
        "baseline_runs": baseline_runs,
        "proposed_runs": proposed_runs,
        "rows": rows,
        "headline_confirmed": valid and all(rows[name]["passed"] for name in headline_names),
    }
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"valid": valid, "rows": rows, "headline_confirmed": payload["headline_confirmed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
