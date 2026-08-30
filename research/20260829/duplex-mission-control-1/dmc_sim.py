"""Procedural semantic-stream mission simulator for DMC-1.

This module is deliberately isolated from Parcel's product runtime.  Grid
steps stand in for bounded mid-level navigation intents; nothing here can call
an actuator or a motion gateway.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from local_policy import DIRECTIONS, FEATURES, FEATURE_TO_ID, WINDOW, predict


FRAME_HZ = 10
MOVE_PERIOD_FRAMES = 5
DIRECTION_DELTA = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}
DELTA_DIRECTION = {value: key for key, value in DIRECTION_DELTA.items()}
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

PLACE_WORDS = (
    "amber nook",
    "birch corner",
    "cobalt gate",
    "dune alcove",
    "elm landing",
    "fern lobby",
    "garnet threshold",
    "harbor bench",
)

TRAIN_PHRASES = {
    "immediate": (
        "go to {target}",
        "please head to {target}",
        "walk over to {target}",
    ),
    "correction": (
        "actually go to {target} instead",
        "change that and head to {target}",
        "no, make the destination {target}",
    ),
    "queue": (
        "after that go to {target}",
        "then visit {target}",
        "queue {target} for later",
    ),
    "stop": ("stop", "hold right there", "freeze please"),
    "resume": ("continue", "resume the paused trip", "carry on"),
    "status": ("what are you doing", "where are you going", "status please"),
}

HELD_OUT_PHRASES = {
    "immediate": (
        "could you make your way to {target}",
        "switch over and check {target}",
        "your next destination is {target}",
    ),
    "correction": (
        "scratch that; {target} is where I meant",
        "revise the current trip toward {target}",
        "I meant {target}, not the old place",
    ),
    "queue": (
        "once this is finished, remember to visit {target}",
        "put {target} behind the current errand",
        "save a trip to {target} for afterward",
    ),
    "stop": ("don't move another step", "pause your body now", "stay exactly there"),
    "resume": ("pick the interrupted route back up", "return to the paused errand", "proceed again"),
    "status": ("which errand is active", "tell me the current mission", "what is in your queue"),
}


Cell = tuple[int, int]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Command:
    tick: int
    kind: str
    transcript: str
    target: str | None = None
    task_id: str | None = None
    race_after_proposal: bool = False


@dataclass(frozen=True, slots=True)
class ParsedSteering:
    kind: str
    target: str | None
    confidence: float
    transcript: str


@dataclass(frozen=True, slots=True)
class Receipt:
    receipt_id: str
    task_id: str
    revision: int
    step_id: str
    attempt: int
    status: str
    due_tick: int
    terminal: bool
    duplicate_of: str | None = None


@dataclass(frozen=True, slots=True)
class NarrationFrame:
    event: str
    task_id: str | None
    revision: int | None
    status: str
    tense: str
    receipt_id: str | None
    evidence: str
    resume_target: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "task_id": self.task_id,
            "revision": self.revision,
            "status": self.status,
            "tense": self.tense,
            "receipt_id": self.receipt_id,
            "evidence": self.evidence,
            "resume_target": self.resume_target,
        }


@dataclass(frozen=True, slots=True)
class DynamicInterval:
    cell: Cell
    start: int
    end: int
    mode: str = "solid"

    def occupied(self, tick: int) -> bool:
        if not self.start <= tick < self.end:
            return False
        if self.mode == "flicker":
            return (tick - self.start) % 4 in {0, 1, 3}
        return True


@dataclass(frozen=True, slots=True)
class EpisodeSpec:
    seed: int
    split: str
    width: int
    height: int
    start: Cell
    static_blocks: frozenset[Cell]
    places: dict[str, Cell]
    critical_cells: frozenset[Cell]
    dynamic: tuple[DynamicInterval, ...]
    stale_intervals: tuple[tuple[int, int], ...]
    sound_ticks: frozenset[int]
    commands: tuple[Command, ...]
    max_ticks: int = 2_400

    @property
    def spec_digest(self) -> str:
        return _digest(
            {
                "seed": self.seed,
                "split": self.split,
                "shape": [self.width, self.height],
                "start": self.start,
                "static_blocks": sorted(self.static_blocks),
                "places": self.places,
                "critical_cells": sorted(self.critical_cells),
                "dynamic": [
                    {"cell": item.cell, "start": item.start, "end": item.end, "mode": item.mode}
                    for item in self.dynamic
                ],
                "stale_intervals": self.stale_intervals,
                "sound_ticks": sorted(self.sound_ticks),
                "commands": [
                    {
                        "tick": command.tick,
                        "kind": command.kind,
                        "transcript": command.transcript,
                        "target": command.target,
                        "task_id": command.task_id,
                        "race_after_proposal": command.race_after_proposal,
                    }
                    for command in self.commands
                ],
                "max_ticks": self.max_ticks,
            }
        )

    def in_bounds(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def is_static_free(self, cell: Cell) -> bool:
        return self.in_bounds(cell) and cell not in self.static_blocks

    def sensors_fresh(self, tick: int) -> bool:
        return not any(start <= tick < end for start, end in self.stale_intervals)

    def dynamic_occupied(self, cell: Cell, tick: int) -> bool:
        return any(item.cell == cell and item.occupied(tick) for item in self.dynamic)

    def occupied(self, cell: Cell, tick: int) -> bool:
        return not self.is_static_free(cell) or self.dynamic_occupied(cell, tick)


def _neighbors(spec: EpisodeSpec, cell: Cell, *, tick: int | None = None) -> list[Cell]:
    result: list[Cell] = []
    for dx, dy in DIRECTION_DELTA.values():
        candidate = (cell[0] + dx, cell[1] + dy)
        if not spec.is_static_free(candidate):
            continue
        if tick is not None and spec.dynamic_occupied(candidate, tick):
            continue
        result.append(candidate)
    return result


def shortest_path(
    spec: EpisodeSpec,
    start: Cell,
    goal: Cell,
    *,
    tick: int | None = None,
) -> list[Cell] | None:
    if start == goal:
        return [start]
    queue: deque[Cell] = deque([start])
    parent: dict[Cell, Cell | None] = {start: None}
    while queue:
        current = queue.popleft()
        for neighbor in _neighbors(spec, current, tick=tick):
            if neighbor in parent:
                continue
            parent[neighbor] = current
            if neighbor == goal:
                path = [goal]
                cursor = current
                while cursor is not None:
                    path.append(cursor)
                    cursor = parent[cursor]
                return list(reversed(path))
            queue.append(neighbor)
    return None


def _connected_grid(
    rng: random.Random, width: int, height: int
) -> tuple[Cell, frozenset[Cell], list[Cell]]:
    all_cells = [(x, y) for y in range(height) for x in range(width)]
    for _ in range(128):
        start = rng.choice(all_cells)
        density = rng.uniform(0.08, 0.18)
        blocks = {cell for cell in all_cells if cell != start and rng.random() < density}
        provisional = EpisodeSpec(
            seed=0,
            split="build",
            width=width,
            height=height,
            start=start,
            static_blocks=frozenset(blocks),
            places={},
            critical_cells=frozenset(),
            dynamic=(),
            stale_intervals=(),
            sound_ticks=frozenset(),
            commands=(),
        )
        reachable: list[Cell] = []
        for cell in all_cells:
            if cell not in blocks and shortest_path(provisional, start, cell) is not None:
                reachable.append(cell)
        if len(reachable) >= max(12, int(width * height * 0.7)):
            return start, frozenset(blocks), reachable
    raise RuntimeError("could not generate connected procedural grid")


def _phrase(rng: random.Random, kind: str, target: str | None, *, held_out: bool) -> str:
    table = HELD_OUT_PHRASES if held_out else TRAIN_PHRASES
    template = rng.choice(table[kind])
    return template.format(target=target) if target is not None else template


def generate_spec(seed: int, split: str) -> EpisodeSpec:
    if split not in {"train", "dev", "frozen", "adversarial"}:
        raise ValueError(split)
    rng = random.Random(seed)
    if split in {"train", "dev"}:
        width = rng.randint(5, 8)
        height = rng.randint(5, 8)
    else:
        width = rng.randint(9, 14)
        height = rng.randint(9, 14)
    start, blocks, reachable = _connected_grid(rng, width, height)
    ranked = sorted(
        (cell for cell in reachable if cell != start),
        key=lambda cell: abs(cell[0] - start[0]) + abs(cell[1] - start[1]),
        reverse=True,
    )
    pool = ranked[: max(8, len(ranked) // 2)]
    selected = rng.sample(pool, 4)
    names = list(PLACE_WORDS)
    rng.shuffle(names)
    places = {names[index]: selected[index] for index in range(4)}
    targets = list(places)

    # Put people on cells that lie on likely routes, then make each eventually
    # clear.  One flickering interval challenges snapshot-only release logic.
    route_cells: list[Cell] = []
    cursor = start
    for name in targets:
        provisional = EpisodeSpec(
            seed=seed,
            split=split,
            width=width,
            height=height,
            start=start,
            static_blocks=blocks,
            places=places,
            critical_cells=frozenset(),
            dynamic=(),
            stale_intervals=(),
            sound_ticks=frozenset(),
            commands=(),
        )
        path = shortest_path(provisional, cursor, places[name]) or [cursor]
        route_cells.extend(path[1:-1])
        cursor = places[name]
    route_cells = list(dict.fromkeys(route_cells)) or [selected[0]]
    rng.shuffle(route_cells)
    dynamic = (
        DynamicInterval(route_cells[0], 12, 16, "solid"),
        DynamicInterval(route_cells[min(1, len(route_cells) - 1)], 55, 78, "flicker"),
        DynamicInterval(route_cells[min(2, len(route_cells) - 1)], 135, 170, "solid"),
    )
    if split == "adversarial":
        dynamic += (
            DynamicInterval(route_cells[min(3, len(route_cells) - 1)], 205, 275, "flicker"),
        )

    critical_candidates = rng.sample(reachable, min(max(2, len(reachable) // 12), 10))
    critical = frozenset(critical_candidates)
    stale = [(42, 47), (102, 109)]
    if split in {"frozen", "adversarial"}:
        stale.extend([(188, 199), (310, 322)])
    if split == "adversarial":
        stale.extend([(71, 82), (228, 244)])

    held_out = split in {"frozen", "adversarial"}
    commands = (
        Command(0, "immediate", _phrase(rng, "immediate", targets[0], held_out=held_out), targets[0], "task-origin"),
        Command(24, "immediate", _phrase(rng, "immediate", targets[1], held_out=held_out), targets[1], "task-interrupt", split == "adversarial"),
        Command(28, "correction", _phrase(rng, "correction", targets[2], held_out=held_out), targets[2], None, True),
        Command(56, "queue", _phrase(rng, "queue", targets[3], held_out=held_out), targets[3], "task-queued"),
        Command(88, "stop", _phrase(rng, "stop", None, held_out=held_out), None, None, True),
        Command(103, "resume", _phrase(rng, "resume", None, held_out=held_out)),
        Command(180, "status", _phrase(rng, "status", None, held_out=held_out)),
        # A second resume is benign if the interrupting task has completed and
        # offered the original mission by then; otherwise it is correctly
        # ignored rather than resurrecting unrelated work.
        Command(320, "resume", _phrase(rng, "resume", None, held_out=held_out)),
    )
    sounds = frozenset({35, 73, 142, 230, 411})
    return EpisodeSpec(
        seed=seed,
        split=split,
        width=width,
        height=height,
        start=start,
        static_blocks=blocks,
        places=places,
        critical_cells=critical,
        dynamic=dynamic,
        stale_intervals=tuple(stale),
        sound_ticks=sounds,
        commands=commands,
    )


def parse_steering(transcript: str, place_names: Iterable[str]) -> ParsedSteering:
    text = " ".join(str(transcript).lower().split())
    target = next((name for name in place_names if name.lower() in text), None)
    if any(token in text for token in ("stop", "hold right", "freeze", "don't move", "pause your body", "stay exactly")):
        return ParsedSteering("stop", None, 1.0, transcript)
    if any(token in text for token in ("continue", "resume", "carry on", "pick the interrupted", "return to the paused", "proceed again")):
        return ParsedSteering("resume", None, 0.99, transcript)
    if any(token in text for token in ("what are", "where are", "status", "which errand", "current mission", "in your queue")):
        return ParsedSteering("status", None, 0.98, transcript)
    if target is None:
        return ParsedSteering("clarify", None, 0.0, transcript)
    if any(token in text for token in ("actually", "change that", "no,", "scratch that", "revise", "i meant")):
        return ParsedSteering("correction", target, 0.98, transcript)
    if any(token in text for token in ("after that", "then visit", "queue", "once this", "behind the current", "for afterward")):
        return ParsedSteering("queue", target, 0.98, transcript)
    return ParsedSteering("immediate", target, 0.96, transcript)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    revision: int
    target_name: str
    target_cell: Cell
    status: str = "queued"
    started: bool = False
    reached: bool = False
    terminal_scheduled: bool = False


class TaskLedger:
    """Deterministic owner of task identity, revision, queue, and receipts."""

    def __init__(self, places: dict[str, Cell]):
        self.places = places
        self.tasks: dict[str, TaskRecord] = {}
        self.active_id: str | None = None
        self.suspended: list[str] = []
        self.queued: deque[str] = deque()
        self.resume_offer_id: str | None = None
        self.stop_latched = False
        self.accepted_receipts: set[str] = set()
        self.terminal_keys: set[tuple[str, int]] = set()
        self.rejected_stale = 0
        self.rejected_duplicate = 0
        self.events: list[dict[str, object]] = []

    @property
    def active(self) -> TaskRecord | None:
        return None if self.active_id is None else self.tasks[self.active_id]

    def _activate(self, record: TaskRecord) -> None:
        record.status = "running"
        record.started = False
        record.reached = False
        record.terminal_scheduled = False
        self.active_id = record.task_id
        self.resume_offer_id = None

    def apply(self, parsed: ParsedSteering, command: Command, tick: int) -> list[NarrationFrame]:
        frames: list[NarrationFrame] = []
        if parsed.kind == "clarify":
            frames.append(NarrationFrame("clarify", None, None, "not_started", "not_started", None, "transcript_unresolved"))
            return frames
        if parsed.kind == "status":
            active = self.active
            frames.append(
                NarrationFrame(
                    "status",
                    None if active is None else active.task_id,
                    None if active is None else active.revision,
                    "running" if active else "idle",
                    "running" if active else "not_started",
                    None,
                    "task_ledger",
                    self.resume_offer_id,
                )
            )
            return frames
        if parsed.kind == "stop":
            self.stop_latched = True
            active = self.active
            if active is not None:
                active.status = "suspended"
            frames.append(
                NarrationFrame(
                    "suspended",
                    None if active is None else active.task_id,
                    None if active is None else active.revision,
                    "suspended",
                    "stopped",
                    None,
                    "local_stop_latch",
                )
            )
            return frames
        if parsed.kind == "resume":
            if self.stop_latched:
                self.stop_latched = False
                active = self.active
                if active is not None:
                    active.status = "running"
                frames.append(
                    NarrationFrame(
                        "resumed",
                        None if active is None else active.task_id,
                        None if active is None else active.revision,
                        "running" if active else "idle",
                        "running" if active else "not_started",
                        None,
                        "explicit_owner_resume",
                    )
                )
                return frames
            if self.active is None and self.resume_offer_id is not None:
                resume_id = self.resume_offer_id
                record = self.tasks[resume_id]
                self.suspended = [item for item in self.suspended if item != resume_id]
                self._activate(record)
                frames.append(NarrationFrame("resumed", record.task_id, record.revision, "running", "running", None, "explicit_owner_resume"))
                return frames
            frames.append(NarrationFrame("resume_ignored", None, None, "not_started", "not_started", None, "no_resumable_task"))
            return frames

        if parsed.target is None or parsed.target not in self.places:
            frames.append(NarrationFrame("clarify", None, None, "not_started", "not_started", None, "target_unresolved"))
            return frames

        if parsed.kind == "correction":
            active = self.active
            if active is None:
                task_id = command.task_id or f"task-correction-{tick}"
                record = TaskRecord(task_id, 1, parsed.target, self.places[parsed.target])
                self.tasks[task_id] = record
                self._activate(record)
            else:
                active.revision += 1
                active.target_name = parsed.target
                active.target_cell = self.places[parsed.target]
                active.status = "running"
                active.started = False
                active.reached = False
                active.terminal_scheduled = False
                record = active
            frames.append(NarrationFrame("accepted", record.task_id, record.revision, "accepted", "not_started", None, "owner_correction"))
            self.events.append({"tick": tick, "event": "correction", "task_id": record.task_id, "revision": record.revision})
            return frames

        task_id = command.task_id or f"task-{tick}"
        record = TaskRecord(task_id, 1, parsed.target, self.places[parsed.target])
        self.tasks[task_id] = record
        if parsed.kind == "queue":
            record.status = "queued"
            self.queued.append(task_id)
            frames.append(NarrationFrame("accepted", task_id, 1, "queued", "waiting", None, "owner_queue"))
        else:
            if self.active is not None:
                old = self.active
                old.status = "suspended"
                if old.task_id not in self.suspended:
                    self.suspended.append(old.task_id)
            self._activate(record)
            frames.append(NarrationFrame("accepted", task_id, 1, "accepted", "not_started", None, "owner_directive"))
        self.events.append({"tick": tick, "event": parsed.kind, "task_id": task_id, "revision": 1})
        return frames

    def accept_receipt(self, receipt: Receipt, tick: int) -> tuple[bool, str, NarrationFrame | None]:
        if receipt.receipt_id in self.accepted_receipts:
            self.rejected_duplicate += 1
            return False, "duplicate_receipt", None
        record = self.tasks.get(receipt.task_id)
        if record is None or record.revision != receipt.revision:
            self.rejected_stale += 1
            return False, "stale_revision", None
        terminal_key = (receipt.task_id, receipt.revision)
        if receipt.terminal and terminal_key in self.terminal_keys:
            self.rejected_duplicate += 1
            return False, "duplicate_terminal", None
        self.accepted_receipts.add(receipt.receipt_id)
        if receipt.terminal:
            self.terminal_keys.add(terminal_key)
            record.status = receipt.status
            if self.active_id == record.task_id:
                self.active_id = None
            resume_target = None
            if self.suspended:
                resume_target = self.suspended[-1]
                self.resume_offer_id = resume_target
            elif self.queued:
                queued_id = self.queued.popleft()
                self._activate(self.tasks[queued_id])
            frame = NarrationFrame(
                receipt.status,
                receipt.task_id,
                receipt.revision,
                receipt.status,
                "completed" if receipt.status == "completed" else "stopped",
                receipt.receipt_id,
                "accepted_terminal_receipt",
                resume_target,
            )
            return True, "accepted_terminal", frame
        if receipt.status == "started":
            record.started = True
            frame = NarrationFrame("started", receipt.task_id, receipt.revision, "running", "running", receipt.receipt_id, "accepted_started_receipt")
            return True, "accepted_started", frame
        if receipt.status == "blocked":
            frame = NarrationFrame("blocked", receipt.task_id, receipt.revision, "blocked", "waiting", receipt.receipt_id, "accepted_blocked_receipt")
            return True, "accepted_blocked", frame
        return True, "accepted_progress", None


class FlatTaskState:
    """Negative-control task state: latest intent wins and history is lost."""

    def __init__(self, places: dict[str, Cell]):
        self.places = places
        self.task: TaskRecord | None = None
        self.stop_latched = False
        self.completed_tasks: set[str] = set()

    @property
    def active(self) -> TaskRecord | None:
        return self.task if self.task is not None and self.task.status not in TERMINAL_STATES else None

    def apply(self, parsed: ParsedSteering, command: Command, tick: int) -> list[NarrationFrame]:
        if parsed.kind == "stop":
            self.stop_latched = True
            return [NarrationFrame("suspended", self.task.task_id if self.task else None, self.task.revision if self.task else None, "suspended", "stopped", None, "intent_state")]
        if parsed.kind == "resume":
            self.stop_latched = False
            return [NarrationFrame("resumed", self.task.task_id if self.task else None, self.task.revision if self.task else None, "running" if self.task else "idle", "running" if self.task else "not_started", None, "intent_state")]
        if parsed.kind == "status":
            return [NarrationFrame("status", self.task.task_id if self.task else None, self.task.revision if self.task else None, "running" if self.active else "idle", "running" if self.active else "not_started", None, "intent_state")]
        if parsed.target is None:
            return []
        if parsed.kind == "queue":
            # Flat state cannot preserve a second task; it acknowledges and loses it.
            return [NarrationFrame("accepted", command.task_id, 1, "queued", "waiting", None, "intent_state")]
        if parsed.kind == "correction" and self.task is not None:
            self.task.revision += 1
            self.task.target_name = parsed.target
            self.task.target_cell = self.places[parsed.target]
            self.task.reached = False
            self.task.terminal_scheduled = False
        else:
            self.task = TaskRecord(command.task_id or f"flat-{tick}", 1, parsed.target, self.places[parsed.target], status="running")
        return [NarrationFrame("accepted", self.task.task_id, self.task.revision, "accepted", "not_started", None, "intent_state")]


@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    task_id: str | None
    revision: int | None
    next_cell: Cell | None


class Controller:
    def propose(self, features: list[float], history: list[list[float]], planned_direction: str | None) -> str:
        raise NotImplementedError


class ConservativeSnapshotController(Controller):
    def __init__(self) -> None:
        self.clear_count = 0

    def propose(self, features: list[float], history: list[list[float]], planned_direction: str | None) -> str:
        edge = features[FEATURE_TO_ID["edge_state"]]
        self.clear_count = self.clear_count + 1 if edge > 0.5 else 0
        if not features[FEATURE_TO_ID["has_task"]]:
            return "idle_expression"
        if features[FEATURE_TO_ID["stop_latched"]] > 0.5 or features[FEATURE_TO_ID["sensors_fresh"]] < 0.5:
            return "hold"
        if features[FEATURE_TO_ID["route_invalid"]] > 0.5:
            return "replan"
        if features[FEATURE_TO_ID["sound_active"]] > 0.5 and features[FEATURE_TO_ID["sound_allowed"]] > 0.5:
            return "orient"
        if features[FEATURE_TO_ID["at_goal"]] > 0.5 or planned_direction is None:
            return "hold"
        return planned_direction if self.clear_count >= 6 else "hold"


class ExplicitTemporalController(Controller):
    def __init__(self) -> None:
        self.clear_count = 0
        self.blocked_count = 0

    def propose(self, features: list[float], history: list[list[float]], planned_direction: str | None) -> str:
        edge = features[FEATURE_TO_ID["edge_state"]]
        self.clear_count = self.clear_count + 1 if edge > 0.5 else 0
        self.blocked_count = self.blocked_count + 1 if edge < -0.5 else 0
        if not features[FEATURE_TO_ID["has_task"]]:
            return "idle_expression"
        if features[FEATURE_TO_ID["stop_latched"]] > 0.5 or features[FEATURE_TO_ID["sensors_fresh"]] < 0.5:
            return "hold"
        if features[FEATURE_TO_ID["route_invalid"]] > 0.5 or self.blocked_count >= 5:
            return "replan"
        if features[FEATURE_TO_ID["sound_active"]] > 0.5 and features[FEATURE_TO_ID["sound_allowed"]] > 0.5:
            return "orient"
        if features[FEATURE_TO_ID["at_goal"]] > 0.5 or planned_direction is None:
            return "hold"
        return planned_direction if self.clear_count >= 2 else "hold"


class LearnedController(Controller):
    def __init__(self, model: Any):
        self.model = model

    def propose(self, features: list[float], history: list[list[float]], planned_direction: str | None) -> str:
        return predict(self.model, history)


@dataclass(slots=True)
class SystemMetrics:
    frames: int = 0
    moves: int = 0
    wrong_route_moves: int = 0
    raw_unsafe: int = 0
    admitted_unsafe: int = 0
    stale_action_rejections: int = 0
    stale_action_acceptances: int = 0
    post_stop_motion: int = 0
    replan_count: int = 0
    orient_count: int = 0
    false_hold_frames: int = 0
    clear_events: int = 0
    clear_latencies: list[int] = field(default_factory=list)
    narration_total: int = 0
    narration_valid: int = 0
    narration_terminal: int = 0
    narration_valid_terminal: int = 0
    premature_completion: int = 0
    terminal_receipts_accepted: int = 0
    terminal_narrations_covered: int = 0
    raw_serialized_bytes: int = 0
    event_serialized_bytes: int = 0
    encode_latency_ns: list[int] = field(default_factory=list)
    parser_correct: int = 0
    parser_total: int = 0
    interrupt_checks: int = 0
    interrupt_correct: int = 0


class MissionSystem:
    def __init__(
        self,
        name: str,
        spec: EpisodeSpec,
        controller: Controller,
        *,
        flat: bool = False,
        rng_seed: int,
    ):
        self.name = name
        self.spec = spec
        self.controller = controller
        self.flat = flat
        self.state: TaskLedger | FlatTaskState = FlatTaskState(spec.places) if flat else TaskLedger(spec.places)
        self.position = spec.start
        self.path: list[Cell] = []
        self.path_key: tuple[str, int, Cell] | None = None
        self.feature_history: deque[list[float]] = deque(maxlen=WINDOW)
        self.receipts: list[Receipt] = []
        self.receipt_counter = 0
        self.rng = random.Random(rng_seed)
        self.metrics = SystemMetrics()
        self.narrations: list[tuple[int, NarrationFrame]] = []
        self.valid_terminal_receipts: set[str] = set()
        self.move_cooldown = 0
        self.blocked_count = 0
        self.blocked_receipt_sent: set[tuple[str, int]] = set()
        self.last_edge_occupied = False
        self.clear_started_tick: int | None = None
        self.clear_cell: Cell | None = None
        self.visited_task_targets: set[tuple[str, int, Cell]] = set()
        self.old_revision_for_stale: tuple[str, int] | None = None

    @property
    def active(self) -> TaskRecord | None:
        return self.state.active

    def _schedule_receipt(self, task: TaskRecord, status: str, tick: int, *, terminal: bool) -> None:
        self.receipt_counter += 1
        receipt_id = f"{self.name}-r{self.receipt_counter}"
        delay = self.rng.randint(1, 8 if self.spec.split in {"frozen", "adversarial"} else 4)
        receipt = Receipt(receipt_id, task.task_id, task.revision, "navigate", 1, status, tick + delay, terminal)
        self.receipts.append(receipt)
        if terminal:
            duplicate = Receipt(
                receipt_id,
                task.task_id,
                task.revision,
                "navigate",
                1,
                status,
                tick + delay + 3,
                True,
                duplicate_of=receipt_id,
            )
            self.receipts.append(duplicate)

    def _schedule_stale_receipt(self, task_id: str, old_revision: int, tick: int) -> None:
        self.receipt_counter += 1
        self.receipts.append(
            Receipt(
                f"{self.name}-stale-{self.receipt_counter}",
                task_id,
                old_revision,
                "navigate",
                1,
                "completed",
                tick + 5,
                True,
            )
        )

    def _validate_narration(self, frame: NarrationFrame, tick: int) -> bool:
        if frame.event in {"completed", "failed", "cancelled"}:
            valid = frame.receipt_id is not None and frame.receipt_id in self.valid_terminal_receipts
            if not valid:
                self.metrics.premature_completion += 1
            else:
                self.metrics.terminal_narrations_covered += 1
            return valid
        if frame.receipt_id is not None:
            return isinstance(self.state, TaskLedger) and frame.receipt_id in self.state.accepted_receipts
        if frame.task_id is None:
            return frame.event in {"status", "suspended", "resumed", "resume_ignored", "clarify"}
        record = self.state.tasks.get(frame.task_id) if isinstance(self.state, TaskLedger) else self.state.task
        return record is not None and frame.revision == record.revision

    def _emit(self, frame: NarrationFrame, tick: int) -> None:
        started = time.perf_counter_ns()
        payload = json.dumps(frame.as_dict(), sort_keys=True, separators=(",", ":"))
        self.metrics.encode_latency_ns.append(time.perf_counter_ns() - started)
        self.metrics.event_serialized_bytes += len(payload.encode("utf-8"))
        self.metrics.narration_total += 1
        valid = self._validate_narration(frame, tick)
        self.metrics.narration_valid += int(valid)
        if frame.event in TERMINAL_STATES:
            self.metrics.narration_terminal += 1
            self.metrics.narration_valid_terminal += int(valid)
        self.narrations.append((tick, frame))

    def _raw_frame_bytes(self, tick: int, features: list[float], proposed: str) -> None:
        active = self.active
        raw = {
            "tick": tick,
            "position": self.position,
            "features": dict(zip(FEATURES, features, strict=True)),
            "active_task": None
            if active is None
            else {"task_id": active.task_id, "revision": active.revision, "target": active.target_name, "status": active.status},
            "proposal": proposed,
            "queue": list(self.state.queued) if isinstance(self.state, TaskLedger) else [],
            "suspended": list(self.state.suspended) if isinstance(self.state, TaskLedger) else [],
        }
        self.metrics.raw_serialized_bytes += len(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

    def _process_receipts(self, tick: int) -> None:
        due = [receipt for receipt in self.receipts if receipt.due_tick == tick]
        for receipt in due:
            if isinstance(self.state, FlatTaskState):
                # The negative control does not bind speech to receipts.
                continue
            accepted, _reason, frame = self.state.accept_receipt(receipt, tick)
            if accepted and receipt.terminal:
                self.metrics.terminal_receipts_accepted += 1
                self.valid_terminal_receipts.add(receipt.receipt_id)
            if frame is not None:
                self._emit(frame, tick)
        self.receipts = [receipt for receipt in self.receipts if receipt.due_tick > tick]

    def _handle_command(self, command: Command, tick: int) -> None:
        parsed = parse_steering(command.transcript, self.spec.places)
        self.metrics.parser_total += 1
        self.metrics.parser_correct += int(parsed.kind == command.kind)
        old = self.active
        old_key = None if old is None else (old.task_id, old.revision)
        frames = self.state.apply(parsed, command, tick)
        new = self.active
        if parsed.kind in {"immediate", "correction"}:
            self.metrics.interrupt_checks += 1
            if parsed.kind == "immediate":
                expected_task = command.task_id
                correct = (
                    new is not None
                    and new.task_id == expected_task
                    and new.target_name == parsed.target
                )
            else:
                correct = (
                    old_key is not None
                    and new is not None
                    and new.task_id == old_key[0]
                    and new.revision == old_key[1] + 1
                    and new.target_name == parsed.target
                )
            self.metrics.interrupt_correct += int(correct)
        if parsed.kind == "correction" and old_key is not None and new is not None and new.revision > old_key[1]:
            self._schedule_stale_receipt(old_key[0], old_key[1], tick)
        for frame in frames:
            self._emit(frame, tick)
        if new is not None and (old_key is None or (new.task_id, new.revision) != old_key):
            self.path = []
            self.path_key = None

    def _ensure_path(self, tick: int, *, avoid_dynamic: bool = False) -> tuple[str | None, Cell | None, bool]:
        active = self.active
        if active is None:
            self.path = []
            self.path_key = None
            return None, None, False
        key = (active.task_id, active.revision, active.target_cell)
        if self.path_key != key or not self.path or self.path[0] != self.position:
            self.path = shortest_path(self.spec, self.position, active.target_cell, tick=tick if avoid_dynamic else None) or [self.position]
            self.path_key = key
        if len(self.path) < 2:
            return None, None, self.position != active.target_cell
        next_cell = self.path[1]
        delta = (next_cell[0] - self.position[0], next_cell[1] - self.position[1])
        direction = DELTA_DIRECTION.get(delta)
        route_invalid = not self.spec.is_static_free(next_cell)
        return direction, next_cell, route_invalid

    def _features(self, tick: int, *, command_changed: bool = False) -> tuple[list[float], str | None, Cell | None]:
        active = self.active
        planned_direction, next_cell, route_invalid = self._ensure_path(tick)
        fresh = self.spec.sensors_fresh(tick)
        edge_state = 0.0
        if next_cell is not None and fresh:
            edge_state = -1.0 if self.spec.dynamic_occupied(next_cell, tick) else 1.0
        features = [0.0 for _ in FEATURES]
        features[FEATURE_TO_ID["has_task"]] = float(active is not None)
        features[FEATURE_TO_ID["stop_latched"]] = float(self.state.stop_latched)
        features[FEATURE_TO_ID["sensors_fresh"]] = float(fresh)
        features[FEATURE_TO_ID["edge_state"]] = edge_state
        features[FEATURE_TO_ID["route_invalid"]] = float(route_invalid)
        features[FEATURE_TO_ID["sound_active"]] = float(tick in self.spec.sound_ticks)
        critical = self.position in self.spec.critical_cells or (next_cell in self.spec.critical_cells if next_cell else False)
        features[FEATURE_TO_ID["critical_zone"]] = float(critical)
        features[FEATURE_TO_ID["sound_allowed"]] = float(not critical and not self.state.stop_latched)
        features[FEATURE_TO_ID["at_goal"]] = float(active is not None and self.position == active.target_cell)
        if planned_direction is not None:
            features[FEATURE_TO_ID[f"plan_{planned_direction}"]] = 1.0
        features[FEATURE_TO_ID["command_changed"]] = float(command_changed)
        features[FEATURE_TO_ID["blocked_reported"]] = float(self.blocked_count >= 5)
        return features, planned_direction, next_cell

    def _proposal(self, tick: int, *, command_changed: bool = False) -> tuple[Proposal, list[float], str | None]:
        features, direction, next_cell = self._features(tick, command_changed=command_changed)
        self.feature_history.append(features)
        active = self.active
        action = self.controller.propose(features, list(self.feature_history), direction)
        proposal_next = None
        if action in DIRECTIONS:
            dx, dy = DIRECTION_DELTA[action]
            proposal_next = (self.position[0] + dx, self.position[1] + dy)
        proposal = Proposal(
            action,
            None if active is None else active.task_id,
            None if active is None else active.revision,
            proposal_next,
        )
        return proposal, features, direction

    def _admit(self, proposal: Proposal, tick: int, planned_direction: str | None) -> bool:
        active = self.active
        if proposal.action not in DIRECTIONS:
            if proposal.action == "replan":
                self.metrics.replan_count += 1
                self.path = []
                self.path_key = None
                self._ensure_path(tick, avoid_dynamic=True)
            elif proposal.action == "orient":
                self.metrics.orient_count += 1
            return False

        unsafe = (
            active is None
            or self.state.stop_latched
            or not self.spec.sensors_fresh(tick)
            or proposal.next_cell is None
            or self.spec.occupied(proposal.next_cell, tick)
        )
        self.metrics.raw_unsafe += int(unsafe)
        if active is None or proposal.task_id != active.task_id or proposal.revision != active.revision:
            self.metrics.stale_action_rejections += 1
            return False
        if unsafe:
            return False
        if self.move_cooldown > 0:
            return False
        # Safety shell admits only observed-free adjacent cells.  Route choice
        # remains the model's responsibility so wrong but collision-free moves
        # are visible in mission and route-adherence metrics.
        if proposal.next_cell is None or not self.spec.is_static_free(proposal.next_cell):
            return False
        self.move_cooldown = MOVE_PERIOD_FRAMES
        old_position = self.position
        self.position = proposal.next_cell
        self.metrics.moves += 1
        self.metrics.wrong_route_moves += int(proposal.action != planned_direction)
        if self.state.stop_latched:
            self.metrics.post_stop_motion += 1
        if self.spec.occupied(self.position, tick):
            self.metrics.admitted_unsafe += 1
        if self.path and self.path[0] == old_position and len(self.path) > 1 and self.path[1] == self.position:
            self.path.pop(0)
        else:
            self.path = []
            self.path_key = None
        active = self.active
        if active is not None and not active.started:
            active.started = True
            self._schedule_receipt(active, "started", tick, terminal=False)
        return True

    def _track_blocker_liveness(self, tick: int, next_cell: Cell | None, admitted_move: bool) -> None:
        occupied = next_cell is not None and self.spec.dynamic_occupied(next_cell, tick)
        if occupied:
            self.blocked_count += 1
            self.clear_started_tick = None
            self.clear_cell = None
        else:
            if self.last_edge_occupied and next_cell is not None:
                self.metrics.clear_events += 1
                self.clear_started_tick = tick
                self.clear_cell = next_cell
            self.blocked_count = 0
        if admitted_move and self.clear_started_tick is not None and self.position == self.clear_cell:
            latency = tick - self.clear_started_tick
            self.metrics.clear_latencies.append(latency)
            self.metrics.false_hold_frames += max(0, latency - 1)
            self.clear_started_tick = None
            self.clear_cell = None
        self.last_edge_occupied = occupied

        active = self.active
        if (
            active is not None
            and self.blocked_count >= 8
            and (active.task_id, active.revision) not in self.blocked_receipt_sent
        ):
            self.blocked_receipt_sent.add((active.task_id, active.revision))
            self._schedule_receipt(active, "blocked", tick, terminal=False)

    def _arrival(self, tick: int) -> None:
        active = self.active
        if active is None or self.position != active.target_cell:
            return
        self.visited_task_targets.add((active.task_id, active.revision, active.target_cell))
        active.reached = True
        if isinstance(self.state, FlatTaskState):
            if active.task_id not in self.state.completed_tasks:
                self.state.completed_tasks.add(active.task_id)
                # Negative control narrates from intended/current position,
                # before a bound terminal receipt exists.
                self._emit(NarrationFrame("completed", active.task_id, active.revision, "completed", "completed", None, "predicted_from_intent"), tick)
                active.status = "completed"
            return
        if not active.terminal_scheduled:
            active.terminal_scheduled = True
            self._schedule_receipt(active, "completed", tick, terminal=True)

    def step(self, tick: int, commands: list[Command]) -> None:
        self.metrics.frames += 1
        if self.move_cooldown > 0:
            self.move_cooldown -= 1
        self._process_receipts(tick)

        race = any(command.race_after_proposal for command in commands)
        pre_proposal: Proposal | None = None
        pre_features: list[float] | None = None
        pre_direction: str | None = None
        if race:
            pre_proposal, pre_features, pre_direction = self._proposal(tick)
        for command in commands:
            self._handle_command(command, tick)
        if pre_proposal is None:
            proposal, features, direction = self._proposal(tick, command_changed=bool(commands))
        else:
            proposal, features, direction = pre_proposal, pre_features or [], pre_direction
        self._raw_frame_bytes(tick, features, proposal.action)
        admitted = self._admit(proposal, tick, direction)
        _direction, next_cell, _invalid = self._ensure_path(tick)
        self._track_blocker_liveness(tick, next_cell, admitted)
        self._arrival(tick)

    def outcome(self) -> dict[str, Any]:
        if isinstance(self.state, FlatTaskState):
            task_status = {self.state.task.task_id: self.state.task.status} if self.state.task else {}
            stale_receipts = 0
            duplicate_receipts = 0
            stack_exact = False
        else:
            task_status = {task_id: record.status for task_id, record in sorted(self.state.tasks.items())}
            stale_receipts = self.state.rejected_stale
            duplicate_receipts = self.state.rejected_duplicate
            stack_exact = (
                all(record.status == "completed" for record in self.state.tasks.values())
                and self.state.active is None
                and not self.state.queued
                and not self.state.suspended
                and self.state.resume_offer_id is None
            )
        expected_tasks = {"task-origin", "task-interrupt", "task-queued"}
        completed = {task_id for task_id, status in task_status.items() if status == "completed"}
        mission_success = expected_tasks <= completed
        precision = self.metrics.narration_valid / self.metrics.narration_total if self.metrics.narration_total else 1.0
        terminal_precision = self.metrics.narration_valid_terminal / self.metrics.narration_terminal if self.metrics.narration_terminal else 1.0
        terminal_coverage = self.metrics.terminal_narrations_covered / self.metrics.terminal_receipts_accepted if self.metrics.terminal_receipts_accepted else 1.0
        compression = 1.0 - self.metrics.event_serialized_bytes / max(1, self.metrics.raw_serialized_bytes)
        latencies = sorted(self.metrics.clear_latencies)
        p95_clear = float(np.percentile(latencies, 95)) / FRAME_HZ if latencies else None
        encode = np.asarray(self.metrics.encode_latency_ns or [0], dtype=np.float64) / 1_000_000.0
        return {
            "system": self.name,
            "mission_success": mission_success,
            "task_stack_exact": stack_exact,
            "task_status": task_status,
            "position": self.position,
            "moves": self.metrics.moves,
            "wrong_route_moves": self.metrics.wrong_route_moves,
            "raw_unsafe": self.metrics.raw_unsafe,
            "admitted_unsafe": self.metrics.admitted_unsafe,
            "stale_action_rejections": self.metrics.stale_action_rejections,
            "stale_action_acceptances": self.metrics.stale_action_acceptances,
            "post_stop_motion": self.metrics.post_stop_motion,
            "replan_count": self.metrics.replan_count,
            "orient_count": self.metrics.orient_count,
            "clear_events": self.metrics.clear_events,
            "clear_latencies_frames": latencies,
            "clear_p95_s": p95_clear,
            "false_hold_frames": self.metrics.false_hold_frames,
            "narration_precision": precision,
            "narration_total": self.metrics.narration_total,
            "narration_valid": self.metrics.narration_valid,
            "terminal_precision": terminal_precision,
            "narration_terminal": self.metrics.narration_terminal,
            "narration_valid_terminal": self.metrics.narration_valid_terminal,
            "terminal_coverage": terminal_coverage,
            "premature_completion": self.metrics.premature_completion,
            "terminal_receipts_accepted": self.metrics.terminal_receipts_accepted,
            "terminal_narrations_covered": self.metrics.terminal_narrations_covered,
            "stale_receipts_rejected": stale_receipts,
            "duplicate_receipts_rejected": duplicate_receipts,
            "raw_serialized_bytes": self.metrics.raw_serialized_bytes,
            "event_serialized_bytes": self.metrics.event_serialized_bytes,
            "compression_fraction": compression,
            "encode_p99_ms": float(np.percentile(encode, 99)),
            "parser_accuracy": self.metrics.parser_correct / max(1, self.metrics.parser_total),
            "interrupt_checks": self.metrics.interrupt_checks,
            "interrupt_correct": self.metrics.interrupt_correct,
            "simulated_frames": self.metrics.frames,
            "simulated_hours": self.metrics.frames / FRAME_HZ / 3600.0,
        }


def run_episode(spec: EpisodeSpec, policies: Any) -> dict[str, Any]:
    systems = [
        MissionSystem("F0_flat_latest_intent", spec, ExplicitTemporalController(), flat=True, rng_seed=spec.seed + 1),
        MissionSystem("L0_ledger_snapshot", spec, ConservativeSnapshotController(), rng_seed=spec.seed + 2),
        MissionSystem("L1_ledger_explicit_time", spec, ExplicitTemporalController(), rng_seed=spec.seed + 3),
        MissionSystem("A0_ledger_snapshot_mlp", spec, LearnedController(policies.snapshot), rng_seed=spec.seed + 4),
        MissionSystem("A1_ledger_history_gru", spec, LearnedController(policies.history), rng_seed=spec.seed + 5),
    ]
    command_by_tick: dict[int, list[Command]] = {}
    for command in spec.commands:
        command_by_tick.setdefault(command.tick, []).append(command)
    for tick in range(spec.max_ticks):
        commands = command_by_tick.get(tick, [])
        for system in systems:
            system.step(tick, commands)
    return {
        "seed": spec.seed,
        "split": spec.split,
        "spec_digest": spec.spec_digest,
        "shape": [spec.width, spec.height],
        "systems": {system.name: system.outcome() for system in systems},
    }


__all__ = [
    "EpisodeSpec",
    "FRAME_HZ",
    "generate_spec",
    "parse_steering",
    "run_episode",
    "shortest_path",
]
