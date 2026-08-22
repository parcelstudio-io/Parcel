"""Card NM-1 + ASK-1 — correctness over consistency, and a question that grants
nothing.

Four properties, each with the seed that reddens it named in its docstring:

1. **No VLM on the 10 Hz control thread, fatally.** Not the two hand-listed
   methods P1-D checked, but a transitive walk of the loop's own call graph —
   and the loop now MARKS its thread, so the runtime tripwire is armed on the
   real loop for the first time.
2. **The veto is published, not computed inline.** Navigation reads a board;
   a missing / stale / mismatched / declined verdict is an ASK, and no
   inference ever happens on the caller's thread.
3. **`as_ask()` reaches the owner and grants nothing** — no lease, no door, no
   motion — until the owner confirms against a freshly compiled revision.
4. **A k-agreed name is not vocabulary until an independent judge agrees.**

The MEASUREMENTS behind this card (including the one that refutes its own
premise) are in ``scrum/20260822/task_18/NM1_STATUS.md``. Nothing here loads a
model unless it is explicitly GPU-gated: the seat and the judge are both
injected, which is the point of the seams.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.online_map.entries import (
    NAME_DETECTOR_LABEL,
    NAME_PROMOTED,
    NAME_PROMOTION_VISITS,
    NAME_VLM_PROPOSED,
    MapEntry,
    ProposedName,
    WriterProvenance,
)
from parcel_robot.online_map.naming import (
    HOLD_EVENT,
    hold_at_hypothesis,
    run_naming_pass,
)
from parcel_robot.perception_abstention import (
    OUTCOME_ASK,
    VETO_ABSENT,
    VETO_PRESENT,
    VETO_UNAVAILABLE,
    AbstentionVerdict,
    ControlLoopViolation,
    PlaceEvidence,
    clear_control_thread,
    control_thread_ids,
    in_control_thread,
    mark_control_thread,
)
from parcel_robot.realtime.tool_broker import (
    CONFIRM_KEY,
    CONFIRM_TOKEN_KEY,
    STATUS_OK,
    STATUS_UNCERTAIN_PLACE,
    TOOL_NAVIGATE_TO,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.vlm_veto.bureau import (
    PublishedVerdict,
    VerdictBureau,
    place_revision,
)
from parcel_robot.vlm_veto.judge import (
    JUDGE_ACCEPT,
    JUDGE_MIN_SCORE,
    JUDGE_REJECT,
    JUDGE_UNAVAILABLE,
    JudgeVerdict,
    NullNamingJudge,
    OwlV2NamingJudge,
)
from parcel_robot.vlm_veto.verifier import VetoAnswer

REPO = Path(__file__).resolve().parents[1]


# ==========================================================================
# helpers
# ==========================================================================


def _cold_runtime(tmp_path: Any, *, realtime: bool = False) -> Any:
    """A real ``RobotRuntime`` on an in-memory store. ~0.1 s, no GPU, no sim.

    The owner's ``parcel_memory.sqlite3`` is never opened: ``memory.path`` is
    ``:memory:``, which is the same posture every other runtime test takes.

    ``realtime=True`` writes a minimal ``realtime.yaml`` into ``tmp_path`` and
    points ``PARCEL_REALTIME_CONFIG`` at it, which is what makes the runtime
    build a ``RealtimeToolBroker`` and therefore a real ``ToolDoors``. Mode
    ``text`` and no credential: consent to the FEATURE is not consent to a
    session, so nothing connects and nothing is spent.
    """

    from parcel_robot.audio_io import AudioDeviceStatus
    from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
    from parcel_robot.runtime import RobotRuntime

    config = tmp_path / "robot.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    if realtime:
        (tmp_path / "realtime.yaml").write_text(
            "enabled: true\nmode: text\n", encoding="utf-8"
        )
        os.environ["PARCEL_REALTIME_CONFIG"] = str(tmp_path / "realtime.yaml")
    observation = SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner", x=1.0, y=0.0, visible=True, confidence=0.9),
        backend="fake",
    )

    class _Backend:
        name = "fake"

        def observe(self) -> Any:
            return observation

        def move(self, command: object) -> None: ...
        def stop(self) -> None: ...
        def pose(self, pose: object) -> None: ...
        def trajectory(self, skill: object) -> None: ...
        def move_owner(self, dx: float, dy: float) -> None: ...

    audio = AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )
    return RobotRuntime(config, _Backend(), audio_status=audio)


def _place(place_id: str = "p1", **kwargs: Any) -> PlaceEvidence:
    base = {
        "label": "bench",
        "x": 3.0,
        "y": 1.0,
        "z": 0.4,
        "label_support": 6,
        "detection_count": 8,
        "evidence_frames": 6,
        "ground_evidence_fraction": 0.4,
        "similarity": 0.7,
        "crop_png": b"\x89PNG-fake",
    }
    base.update(kwargs)
    return PlaceEvidence(place_id=place_id, **base)  # type: ignore[arg-type]


class _RecordingRunner:
    """A seat that records WHICH THREAD asked it. That is the whole property."""

    def __init__(self, verdict: str = VETO_PRESENT) -> None:
        self.calls: list[int] = []
        self.verdict = verdict
        self.verifier = type("V", (), {"name": "recording"})()

    def veto_for(self, query: str, place: PlaceEvidence) -> VetoAnswer:
        self.calls.append(threading.get_ident())
        return VetoAnswer(self.verdict, p_yes=0.9, latency_ms=41.0, model="recording")


class _StubJudge:
    """A judge whose answer the test chooses. No model, no GPU, no pixels."""

    name = "stub"

    def __init__(self, outcome: str = JUDGE_ACCEPT, strength: float | None = 0.8) -> None:
        self.outcome = outcome
        self.strength = strength
        self.asked: list[str] = []

    def judge(self, name: str, crop_png: bytes | None, *, entry_id: str = "") -> JudgeVerdict:
        self.asked.append(name)
        strength = self.strength if self.outcome != JUDGE_UNAVAILABLE else None
        return JudgeVerdict(
            self.outcome,
            name=name,
            entry_id=entry_id,
            strength=strength,
            floor=JUDGE_MIN_SCORE,
            model=self.name,
        )


class _FakeMap:
    """The smallest thing ``run_naming_pass`` can drive. Real entries, real k-gate."""

    def __init__(self, entries: list[MapEntry]) -> None:
        self._entries = entries

    def active_entries(self) -> list[MapEntry]:
        return list(self._entries)

    def known_places(self) -> tuple[str, ...]:
        names: set[str] = set()
        for entry in self._entries:
            names.update(entry.admissible_names())
        return tuple(sorted(names))

    def propose_name(
        self, entry_id: str, text: str, *, visit_id: str, wall_s: float
    ) -> ProposedName:
        entry = next(e for e in self._entries if e.entry_id == entry_id)
        names = list(entry.names)
        for index, name in enumerate(names):
            if name.text == text:
                updated = name.with_visit(str(visit_id))
                names[index] = updated
                entry.names = tuple(names)
                return updated
        fresh = ProposedName(
            text=text,
            provenance=NAME_VLM_PROPOSED,
            visits=1,
            supporting_visit_ids=(str(visit_id),),
        )
        entry.names = (*names, fresh)
        return fresh


_PROVENANCE = WriterProvenance(
    session_id="nm1-test", seat="fixture", detector_name="scene_gt", scene_id="city_block"
)


def _entry(label: str = "bollard", entry_id: str = "e1") -> MapEntry:
    return MapEntry(
        entry_id=entry_id,
        label=label,
        surface_x=1.0,
        surface_y=2.0,
        surface_z=0.4,
        provenance=_PROVENANCE,
        first_seen_wall_s=100.0,
        last_seen_wall_s=100.0,
        thumbnail=b"\x89PNG-fake",
        names=(ProposedName(text=label, provenance=NAME_DETECTOR_LABEL),),
    )


def _run_three_visits(entry: MapEntry, name: str, judge: Any) -> list[Any]:
    fake = _FakeMap([entry])

    def describe(_thumb: bytes | None) -> Any:
        return type("A", (), {"text": name})()

    return [
        run_naming_pass(
            fake, describe, visit_id=f"v{i}", budget_s=0.0, judge=judge, wall_s=100.0 + i
        )
        for i in range(NAME_PROMOTION_VISITS)
    ]


# ==========================================================================
# 1. DW-2 (a) — THE FATAL CONTROL-THREAD TEST
# ==========================================================================


#: Names that must not be reachable from the 10 Hz loop: a model constructor, a
#: warm-up, an inference, an image encode, a weight load, a network call. Read
#: as attribute names on any call in the loop's transitive call graph.
FATAL_ON_THE_LOOP = frozenset(
    {
        # constructors / loaders
        "Qwen3VLVerifier",
        "OwlV2NamingJudge",
        "load_owlv2_detector",
        "runner_for",
        "bureau_for",
        "default_naming_judge",
        "load",
        "warm_up",
        "warm_up_png",
        # inference
        "veto_for",
        "verify",
        "describe",
        "judge",
        "run_batch",
        "run_naming_pass",
        "generate",
        # image encode / decode
        "imencode",
        "imdecode",
        "_encode_thumbnail",
        # network
        "urlopen",
        "request",
        "post",
        "connect",
        "from_pretrained",
        "snapshot_download",
    }
)


def _runtime_call_graph() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """``RobotRuntime`` methods -> (the ``self.<method>`` they call, every attr call).

    A whole-graph walk and not a two-method spot check: P1-D's version listed
    ``_dispatch_active`` and ``_step_navigation`` by hand, which is exactly as
    good as the list stays current.
    """

    source = (REPO / "src/parcel_robot/runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    self_edges: dict[str, set[str]] = {}
    attr_calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "RobotRuntime":
            continue
        for func in node.body:
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            edges: set[str] = set()
            attrs: set[str] = set()
            for inner in ast.walk(func):
                if not isinstance(inner, ast.Call):
                    continue
                target = inner.func
                if isinstance(target, ast.Attribute):
                    attrs.add(target.attr)
                    value = target.value
                    if isinstance(value, ast.Name) and value.id == "self":
                        edges.add(target.attr)
                elif isinstance(target, ast.Name):
                    attrs.add(target.id)
            self_edges[func.name] = edges
            attr_calls[func.name] = attrs
    return self_edges, attr_calls


def _reachable_from(entry: str, edges: dict[str, set[str]]) -> set[str]:
    seen = {entry}
    stack = [entry]
    while stack:
        current = stack.pop()
        for nxt in edges.get(current, ()):
            if nxt in edges and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def test_FATAL_no_model_call_is_reachable_from_the_10_hz_control_loop() -> None:
    """DW-2 (a). The whole call graph, not two methods.

    SEED: add ``self._nm1_veto.veto_for("bench", place)`` (or any name in
    :data:`FATAL_ON_THE_LOOP`) anywhere in ``_control_loop_body`` or in
    ANYTHING it transitively calls. Reproduced on a scratch copy of ``src/``:
    the seed lands in ``_step_navigation`` and this test goes red.
    """

    edges, attrs = _runtime_call_graph()
    assert "_control_loop" in edges, "the control loop was renamed; fix this test"
    reachable = _reachable_from("_control_loop", edges)
    assert len(reachable) > 20, (
        "the call-graph walk found almost nothing, which means it is not walking "
        f"— {sorted(reachable)}"
    )
    offenders: dict[str, set[str]] = {}
    for method in sorted(reachable):
        overlap = attrs.get(method, set()) & FATAL_ON_THE_LOOP
        if overlap:
            offenders[method] = overlap
    assert not offenders, f"the 10 Hz loop reaches a model: {offenders}"


def test_the_control_loop_marks_its_own_thread() -> None:
    """The tripwire is only a tripwire once something arms it.

    Card P1-D built ``mark_control_thread`` and nothing in the product called
    it, so the "we will catch the call site somebody adds tomorrow" claim was
    unbacked. This asserts the loop arms it AND disarms it on the way out.

    Driven by handing ``RobotRuntime._control_loop`` a host object that supplies
    only ``_control_loop_body`` — the real function, on a real thread, with no
    monkeypatch on a class other sessions are running tests against.

    SEED: delete the ``mark_control_thread()`` call from ``_control_loop``.
    """

    from parcel_robot.runtime import RobotRuntime

    source = inspect.getsource(RobotRuntime._control_loop)
    assert "mark_control_thread()" in source
    assert "clear_control_thread()" in source

    seen: dict[str, Any] = {}

    class _LoopHost:
        def _control_loop_body(self) -> None:
            seen["inside"] = in_control_thread()
            seen["ids"] = control_thread_ids()
            seen["tid"] = threading.get_ident()

    thread = threading.Thread(
        target=RobotRuntime._control_loop, args=(_LoopHost(),), daemon=True
    )
    thread.start()
    thread.join(timeout=5.0)
    assert seen.get("inside") is True, "the loop ran without marking its thread"
    assert seen["tid"] in seen["ids"], "the registry never saw the loop"
    assert not in_control_thread(), "this thread was never a control loop"


def test_the_control_loop_unmarks_itself_so_the_id_is_not_inherited() -> None:
    """Thread ids are recycled. A loop that exits marked poisons the next thread.

    SEED: drop the ``finally: clear_control_thread()`` arm.
    """

    from parcel_robot.runtime import RobotRuntime

    seen: dict[str, int] = {}

    class _LoopHost:
        def _control_loop_body(self) -> None:
            seen["tid"] = threading.get_ident()

    thread = threading.Thread(
        target=RobotRuntime._control_loop, args=(_LoopHost(),), daemon=True
    )
    thread.start()
    thread.join(timeout=5.0)
    assert "tid" in seen
    assert seen["tid"] not in control_thread_ids()


def test_a_control_loop_that_raises_still_unmarks_its_thread() -> None:
    """The ``finally`` is load-bearing: a crashing loop must not leave a mark.

    SEED: turn the ``try/finally`` into a plain call followed by the clear.
    """

    from parcel_robot.runtime import RobotRuntime

    seen: dict[str, int] = {}

    class _AngryHost:
        def _control_loop_body(self) -> None:
            seen["tid"] = threading.get_ident()
            raise RuntimeError("the backend went away")

    def run() -> None:
        # Caught HERE and not by the threading machinery: the property under
        # test is the ``finally``, and an unhandled thread exception is just
        # noise in every other test's report.
        with contextlib.suppress(RuntimeError):
            RobotRuntime._control_loop(_AngryHost())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=5.0)
    assert "tid" in seen
    assert seen["tid"] not in control_thread_ids()


def test_the_naming_judge_refuses_the_control_thread_too() -> None:
    """The judge is 43-108 ms per call on this host — same rule as the VLM.

    SEED: delete the ``in_control_thread()`` guard from ``OwlV2NamingJudge.judge``.
    """

    judge = OwlV2NamingJudge(require_env=True)
    mark_control_thread()
    try:
        with pytest.raises(ControlLoopViolation):
            judge.judge("bench", b"\x89PNG-fake", entry_id="e1")
    finally:
        clear_control_thread()


def test_a_judge_violation_is_never_softened_into_a_hold() -> None:
    """``run_naming_pass`` swallows a broken judge on purpose. Not this one.

    A ``ControlLoopViolation`` swallowed as "unavailable" would turn the
    loudest signal in the system into a name that quietly holds.

    SEED: drop the ``except ControlLoopViolation: raise`` arm in ``_ask_the_judge``.
    """

    class _Exploding:
        name = "boom"

        def judge(self, name: str, crop_png: bytes | None, *, entry_id: str = "") -> Any:
            raise ControlLoopViolation("on the loop")

    entry = _entry()
    entry.names = (
        ProposedName(text="bollard", provenance=NAME_DETECTOR_LABEL),
        ProposedName(
            text="yellow cylinder",
            provenance=NAME_PROMOTED,
            visits=3,
            supporting_visit_ids=("a", "b", "c"),
        ),
    )
    with pytest.raises(ControlLoopViolation):
        _run_three_visits(entry, "yellow cylinder", _Exploding())


def test_the_runtime_still_imports_no_veto_package_and_no_tensor_library() -> None:
    """NM-1 moved the registry so that this could stay true.

    SEED: ``from parcel_robot.vlm_veto import mark_control_thread`` in
    ``runtime.py`` — which is the obvious way to write the marking, and the
    wrong one.
    """

    source = (REPO / "src/parcel_robot/runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = [
        name
        for name in imported
        if name.startswith("parcel_robot.vlm_veto")
        or name.split(".")[0] in {"torch", "transformers"}
    ]
    assert not forbidden, forbidden


# ==========================================================================
# 2. DW-2 (b) — A BOUNDED WORKER AND PUBLISHED, IDENTIFIED VERDICTS
# ==========================================================================


def test_the_gate_never_runs_inference_on_the_caller_s_thread() -> None:
    """The property the whole bureau exists for.

    SEED: return ``runner.veto_callable()`` from ``resolve_veto`` again (P1-D's
    synchronous seam) — the seat then answers on the caller's own thread.
    """

    runner = _RecordingRunner()
    bureau = VerdictBureau(runner)
    try:
        caller = threading.get_ident()
        place = _place()
        for _ in range(5):
            bureau.read("bench", place)
        bureau.drain()
        assert runner.calls, "the worker never ran at all — the seam is dead"
        assert caller not in runner.calls, (
            "the seat answered on the navigation thread: " f"{runner.calls} vs {caller}"
        )
    finally:
        bureau.close()


def test_a_missing_verdict_asks_and_requests_one() -> None:
    """First sight of a place is a question, and the question schedules the work.

    SEED: make ``read`` block on the worker instead of returning unavailable.
    """

    runner = _RecordingRunner()
    bureau = VerdictBureau(runner)
    try:
        answer = bureau.read("bench", _place())
        assert answer.verdict == VETO_UNAVAILABLE
        assert bureau.counts()["miss"] == 1
        assert bureau.counts()["requested"] == 1
        bureau.drain()
        assert bureau.read("bench", _place()).verdict == VETO_PRESENT
    finally:
        bureau.close()


def test_a_ready_matching_fresh_verdict_is_consumed() -> None:
    """The path is not merely safe, it works.

    SEED: make ``read`` always return unavailable — safe, and useless.
    """

    runner = _RecordingRunner(verdict=VETO_ABSENT)
    bureau = VerdictBureau(runner)
    try:
        place = _place()
        bureau.read("bench", place)
        bureau.drain()
        answer = bureau.read("bench", place)
        assert answer.verdict == VETO_ABSENT
        assert bureau.counts()["hit"] == 1
    finally:
        bureau.close()


def test_an_expired_verdict_is_not_consumed() -> None:
    """A verdict has a lifetime, and navigation checks it.

    SEED: delete the ``published.fresh(now)`` arm in ``read``.
    """

    clock = {"t": 1000.0}
    runner = _RecordingRunner()
    bureau = VerdictBureau(runner, ttl_s=10.0, clock=lambda: clock["t"])
    try:
        place = _place()
        bureau.read("bench", place)
        bureau.drain()
        assert bureau.read("bench", place).verdict == VETO_PRESENT
        clock["t"] += 11.0
        answer = bureau.read("bench", place)
        assert answer.verdict == VETO_UNAVAILABLE
        assert "expired" in answer.detail
        assert bureau.counts()["stale"] == 1
    finally:
        bureau.close()


def test_a_verdict_about_another_revision_of_the_place_is_not_consumed() -> None:
    """The identity half. The map learned more; the old answer is about a
    world that no longer exists.

    SEED: delete the ``published.matches(...)`` arm in ``read`` (or drop
    ``place_revision`` from the comparison).
    """

    runner = _RecordingRunner()
    bureau = VerdictBureau(runner)
    try:
        before = _place(evidence_frames=6)
        bureau.read("bench", before)
        bureau.drain()
        assert bureau.read("bench", before).verdict == VETO_PRESENT
        after = _place(evidence_frames=9)  # the map saw it three more times
        assert place_revision(after) != place_revision(before)
        answer = bureau.read("bench", after)
        assert answer.verdict == VETO_UNAVAILABLE
        assert bureau.counts()["mismatched"] == 1
    finally:
        bureau.close()


def test_the_revision_moves_when_the_pixels_move() -> None:
    """A new best-view crop is a new question, even at the same coordinates.

    SEED: drop ``crop_png`` from ``place_revision``.
    """

    assert place_revision(_place(crop_png=b"a")) != place_revision(_place(crop_png=b"b"))
    assert place_revision(_place(label="bench")) != place_revision(_place(label="shop"))
    # ...and ``similarity`` is deliberately NOT in it: it moves with the QUERY.
    assert place_revision(_place(similarity=0.1)) == place_revision(_place(similarity=0.9))


def test_a_published_verdict_cannot_be_edited() -> None:
    """Identity fields that can be rewritten are decoration.

    SEED: drop ``frozen=True`` from ``PublishedVerdict``.
    """

    verdict = PublishedVerdict(
        query="bench",
        place_id="p1",
        place_revision="rev",
        verdict=VETO_PRESENT,
        model="stub",
        captured_at=1.0,
        resolved_at=2.0,
        expires_at=3.0,
    )
    for field, value in (("query", "shop"), ("place_revision", "other"), ("verdict", VETO_ABSENT)):
        with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError is the point
            setattr(verdict, field, value)


def test_a_published_verdict_must_say_what_it_is_about() -> None:
    """SEED: make ``place_revision`` optional in ``__post_init__``."""

    for kwargs in (
        {"query": ""},
        {"place_id": ""},
        {"place_revision": ""},
    ):
        base = {
            "query": "bench",
            "place_id": "p1",
            "place_revision": "rev",
            "verdict": VETO_PRESENT,
            "model": "stub",
            "captured_at": 1.0,
            "resolved_at": 2.0,
            "expires_at": 3.0,
        }
        base.update(kwargs)
        with pytest.raises(ValueError):
            PublishedVerdict(**base)  # type: ignore[arg-type]


def test_the_queue_is_bounded_and_overflow_is_dropped_not_blocked() -> None:
    """A navigation call must never wait on a backlog.

    SEED: build the queue with ``maxsize=0``, or ``put`` instead of
    ``put_nowait``.
    """

    class _Wedged(_RecordingRunner):
        def __init__(self) -> None:
            super().__init__()
            self.release = threading.Event()

        def veto_for(self, query: str, place: PlaceEvidence) -> VetoAnswer:
            self.release.wait(timeout=5.0)
            return super().veto_for(query, place)

    runner = _Wedged()
    bureau = VerdictBureau(runner, queue_depth=2)
    try:
        for index in range(12):
            answer = bureau.read(f"thing-{index}", _place(place_id=f"p{index}"))
            assert answer.verdict == VETO_UNAVAILABLE
        counts = bureau.counts()
        assert counts["dropped"] >= 1, counts
        assert counts["requested"] <= 3, counts
    finally:
        runner.release.set()
        bureau.close()


def test_a_declined_gpu_moment_asks_and_then_backs_off() -> None:
    """Budget-declined is an ASK, and it does not spin the worker.

    SEED: publish an unavailable answer with the full TTL and treat it as usable.
    """

    runner = _RecordingRunner(verdict=VETO_UNAVAILABLE)
    bureau = VerdictBureau(runner, backoff_s=30.0)
    try:
        place = _place()
        bureau.read("bench", place)
        bureau.drain()
        first = len(runner.calls)
        for _ in range(4):
            assert bureau.read("bench", place).verdict == VETO_UNAVAILABLE
        bureau.drain()
        assert len(runner.calls) == first, "the worker was re-asked inside the backoff"
        assert bureau.counts()["unusable"] == 4
        assert bureau.counts()["declined"] >= 1
    finally:
        bureau.close()


def test_the_gate_reads_the_bureau_and_not_the_runner() -> None:
    """``resolve_veto`` must hand the gate the BOARD, not the seat.

    Correction pass: this asserted on ``inspect.getsource``, which passes on
    dead code and fails on a harmless rename. It now RESOLVES a policy and looks
    at the object that comes back — no GPU and no model, because the null seat
    is a bureau too.

    SEED: ``return runner_for(key).veto_callable()``.
    """

    import dataclasses

    from parcel_robot.perception_abstention import (
        AbstentionPolicy,
        clear_veto_cache,
        resolve_veto,
    )
    from parcel_robot.vlm_veto.bureau import VerdictBureau, clear_bureaus

    policy = dataclasses.replace(AbstentionPolicy(), veto_model="")
    clear_veto_cache()
    clear_bureaus()
    try:
        seat = resolve_veto(policy)
        assert callable(seat), seat
        owner = getattr(seat, "__self__", None)
        assert isinstance(owner, VerdictBureau), (
            f"the gate was handed {owner!r}; a VetoRunner here means the mission "
            "path is running inference inside a grounding call again"
        )
        # ...and it answers without blocking on anything.
        assert seat("bench", _place()).verdict == VETO_UNAVAILABLE
    finally:
        clear_bureaus()
        clear_veto_cache()


# ==========================================================================
# 3. DW-2 (c) — ASK-1: THE QUESTION THAT GRANTS NOTHING
# ==========================================================================


class _AskDoors:
    """Records every door. A touched door is a moved body."""

    def __init__(self, ask: dict[str, object] | None = None) -> None:
        self.touched: list[tuple[str, tuple]] = []
        self.validated: list[Any] = []
        self.dispatches = 0
        self.ask = ask or {}
        self.ask_calls = 0
        self.notes: list[str] = []

    def validate(self, call: Any) -> Any:
        from parcel_robot.models import ToolResult

        self.validated.append(call)
        return ToolResult(call.name, True, "approved")

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False}

    def recall(self, query: str) -> str:
        return ""

    def gesture(self, name: str, intensity: float) -> str:
        return ""

    def pose(self, name: str) -> str:
        return ""

    def navigate(self, place: str, relation: str = "") -> str:
        self.touched.append(("navigate", (place, relation)))
        return "Heading out."

    def places(self) -> tuple[str, ...]:
        return ("bench", "lamppost", "sidewalk")

    def on_dispatch(self) -> None:
        self.dispatches += 1

    def note(self, text: str) -> None:
        self.notes.append(text)

    def ask_place(self, place: str) -> dict[str, object]:
        self.ask_calls += 1
        return dict(self.ask)

    def as_doors(self, *, wire_ask: bool = True) -> ToolDoors:
        kwargs: dict[str, Any] = {
            "validate": self.validate,
            "status": self.status,
            "recall": self.recall,
            "gesture": self.gesture,
            "pose": self.pose,
            "navigate": self.navigate,
            "places": self.places,
            "on_dispatch": self.on_dispatch,
            "note": self.note,
        }
        if wire_ask:
            kwargs["ask_place"] = self.ask_place
        return ToolDoors(**kwargs)


def _ask_payload(**overrides: object) -> dict[str, object]:
    verdict = AbstentionVerdict(
        admitted=False,
        query="bench",
        reason="indecisive_ranking",
        alternatives=("lamppost", "sidewalk"),
        place_id="place-7",
        outcome=OUTCOME_ASK,
        candidate="lamppost",
    )
    payload = dict(verdict.as_ask())
    payload["revision"] = "rev-aaaa"
    payload.update(overrides)
    return payload


def _call(broker: RealtimeToolBroker, arguments: dict[str, object]) -> dict[str, Any]:
    return json.loads(
        broker.handle(
            name=TOOL_NAVIGATE_TO, call_id="call_1", arguments=json.dumps(arguments)
        )
    )


def test_an_uncertain_place_asks_and_touches_no_door() -> None:
    """DW-2 (c). No lease, no motion — the question grants nothing.

    SEED: move the ASK arm BELOW ``self._doors.on_dispatch()`` in
    ``_navigate_to``, or delete it.
    """

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    result = _call(broker, {"place": "bench"})
    assert result["status"] == STATUS_UNCERTAIN_PLACE
    assert doors.touched == [], f"the ASK moved something: {doors.touched}"
    assert doors.dispatches == 0, "the ASK claimed an utterance lease"
    assert doors.validated == [], "the ASK asked the supervisor to admit motion"
    assert broker.uncertain_place_asks == 1
    assert broker.uncertain_place_confirms == 0


def test_the_ask_carries_the_verdicts_own_candidate() -> None:
    """CURIO-1 reads ``AbstentionVerdict.candidate``; so does this envelope.

    ``CURIO1_STATUS.md`` §9.1: the one real bug in that card was reading a field
    that does not exist, and two stubs agreeing about it hid the fact. One
    field, one meaning, two consumers.

    SEED: rename ``candidate`` to ``ask_place`` in ``_uncertain_place_result``.
    """

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    result = _call(broker, {"place": "bench"})
    assert result["candidate"] == "lamppost"
    assert result["candidate"] != result["place"], (
        "the candidate must be able to DIFFER from the query, or a build that "
        "speaks the query instead of the candidate is invisible"
    )
    assert result[CONFIRM_TOKEN_KEY] == "rev-aaaa"
    assert "not sure" in str(result["detail"]).lower()


def test_a_matching_confirmation_starts_exactly_one_trip() -> None:
    """The owner said yes about THIS world, and the world has not moved.

    SEED: accept any non-empty ``confirm`` value.
    """

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    asked = _call(broker, {"place": "bench"})
    confirmed = _call(
        broker, {"place": "bench", CONFIRM_KEY: asked[CONFIRM_TOKEN_KEY]}
    )
    assert confirmed["status"] == STATUS_OK
    assert [name for name, _ in doors.touched] == ["navigate"]
    assert doors.dispatches == 1
    assert broker.uncertain_place_confirms == 1


def test_a_confirmation_of_a_revision_that_has_moved_asks_again_and_moves_nothing() -> None:
    """The map learned something between the question and the answer.

    SEED: remember the issued token in the broker instead of recompiling.
    """

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    asked = _call(broker, {"place": "bench"})
    doors.ask = _ask_payload(revision="rev-bbbb")  # the world moved
    again = _call(broker, {"place": "bench", CONFIRM_KEY: asked[CONFIRM_TOKEN_KEY]})
    assert again["status"] == STATUS_UNCERTAIN_PLACE
    assert again[CONFIRM_TOKEN_KEY] == "rev-bbbb"
    assert doors.touched == [], "a stale confirmation moved the robot"
    assert doors.dispatches == 0


def test_a_token_nobody_ever_issued_moves_nothing() -> None:
    """SEED: compare the token case-insensitively, or with ``in`` rather than ``==``."""

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    result = _call(broker, {"place": "bench", CONFIRM_KEY: "made-it-up"})
    assert result["status"] == STATUS_UNCERTAIN_PLACE
    assert doors.touched == []
    assert doors.dispatches == 0


def test_an_empty_revision_can_never_be_confirmed() -> None:
    """A verdict with no digest is a question that cannot be answered yet.

    SEED: treat a missing revision as "no token needed".
    """

    doors = _AskDoors(_ask_payload(revision=""))
    broker = RealtimeToolBroker(doors.as_doors())
    for arguments in ({"place": "bench"}, {"place": "bench", CONFIRM_KEY: ""}):
        result = _call(broker, arguments)
        assert result["status"] == STATUS_UNCERTAIN_PLACE
    assert doors.touched == []


def test_a_host_without_the_ask_door_behaves_exactly_as_before() -> None:
    """Flag-off identity for the broker. ASK-1 adds no question where there is none.

    SEED: make ``_no_ask`` raise, or default ``ask_place`` to ``_unwired``.
    """

    doors = _AskDoors()
    broker = RealtimeToolBroker(doors.as_doors(wire_ask=False))
    result = _call(broker, {"place": "bench"})
    assert result["status"] == STATUS_OK
    assert [name for name, _ in doors.touched] == ["navigate"]
    assert broker.uncertain_place_asks == 0


def test_a_door_that_throws_asks_nothing_and_still_navigates() -> None:
    """A broken map must not turn "go to the bench" into an exception.

    SEED: drop the ``try/except`` in ``_ask_about_place``.
    """

    doors = _AskDoors()

    def explode(place: str) -> dict[str, object]:
        raise RuntimeError("map is mid-write")

    doors.ask_place = explode  # type: ignore[method-assign]
    broker = RealtimeToolBroker(doors.as_doors())
    result = _call(broker, {"place": "bench"})
    assert result["status"] == STATUS_OK
    assert doors.notes and "ask_place failed" in doors.notes[0]


def test_the_model_is_told_how_to_confirm() -> None:
    """A parameter the model cannot send is a parameter it cannot use.

    SEED: remove ``confirm`` from ``navigate_to``'s tool spec.
    """

    from parcel_robot.realtime.tool_broker import build_tool_specs

    spec = next(
        s for s in build_tool_specs() if s.get("name") == TOOL_NAVIGATE_TO
    )
    properties = spec["parameters"]["properties"]  # type: ignore[index]
    assert CONFIRM_KEY in properties
    assert "uncertain_place" in properties[CONFIRM_KEY]["description"]


def test_the_runtime_wires_the_ask_door_without_a_motion_wrapper(tmp_path) -> None:
    """The door is wired ON THE OBJECT, and not gated by voice or by the latch.

    Correction pass: this was a source grep, which passes on dead code and fails
    on a rename. It now builds a real ``RobotRuntime`` (in-memory store, fake
    backend, navigation off) and reads the field the broker will actually call.

    ``__func__ is`` and not a truthiness check: a door wrapped in
    ``_gate_by_voice`` or ``_watch_under_latch`` would still be callable and
    still be wired, and would still be wrong — an ASK starts nothing, and a
    robot that goes quiet about its own uncertainty to a stranger, or while
    stopped, is a worse robot rather than a safer one.

    SEED: delete ``ask_place=self._realtime_ask_place`` from the ``ToolDoors``
    construction — the product then never asks, exactly as it did before P1-D's
    handoff was picked up.
    """

    from parcel_robot.runtime import RobotRuntime

    previous = os.environ.get("PARCEL_REALTIME_CONFIG")
    runtime = _cold_runtime(tmp_path, realtime=True)
    try:
        broker = runtime.realtime_broker
        assert broker is not None, (
            "the realtime lane did not build, so this test would have passed "
            "without ever looking at a door"
        )
        door = broker._doors.ask_place
        assert getattr(door, "__func__", None) is RobotRuntime._realtime_ask_place, (
            f"ask_place is {door!r}; a wrapper here would gate a question behind "
            "a motion authority"
        )
        assert door.__self__ is runtime
    finally:
        runtime.close()
        if previous is None:
            os.environ.pop("PARCEL_REALTIME_CONFIG", None)
        else:
            os.environ["PARCEL_REALTIME_CONFIG"] = previous


# ==========================================================================
# 3b. CORRECTION PASS — the token is about the SUBJECT, and it is one-shot
# ==========================================================================


def _ask_map(tmp_path: Any) -> tuple[Any, Any, Any]:
    """A real ``OnlineSemanticMap`` with one place the gate will ASK about."""

    import dataclasses

    import yaml

    from parcel_robot.online_map import MapObservation, OnlineSemanticMap
    from parcel_robot.perception_abstention import AbstentionPolicy

    # The prototype operating point, minus the VLM seat: this test is about the
    # TOKEN, and a policy that needs a model on the GPU to produce an ASK would
    # make it a GPU test. `vlm_veto` dropped from the roster, everything else
    # exactly as the profile ships it.
    profile = yaml.safe_load(
        (REPO / "configs/navigation/prototype.yaml").read_text(encoding="utf-8")
    )["perception"]["abstention"]
    policy = AbstentionPolicy.from_mapping(profile)
    policy = dataclasses.replace(
        policy,
        signals=tuple(s for s in policy.signals if s != "vlm_veto"),
        veto_model="",
        # Held deliberately out of reach so the place stays an ASK no matter how
        # many times the robot looks at it. That is the point: the token must
        # survive new evidence, so the fixture must keep producing the same
        # QUESTION while the evidence behind it grows. A shortfall the next
        # observation would satisfy would test nothing.
        min_evidence_frames=50,
    )
    provenance = _PROVENANCE
    smap = OnlineSemanticMap(provenance=provenance, policy=policy)

    def observe(visit: str, frame: str) -> None:
        smap.observe(
            MapObservation(
                label="lamppost",
                score=0.8,
                surface_x=4.0,
                surface_y=0.0,
                surface_z=0.4,
                range_m=3.0,
                bearing_rad=0.0,
                depth_m=3.0,
                extent_w_m=0.3,
                extent_h_m=3.2,
                inlier_pixels=5000,
                frame_id=frame,
                visit_id=visit,
                observed_wall_s=1000.0,
                robot_x=0.0,
                robot_y=0.0,
                provenance=provenance,
                thumbnail=b"\x89PNG-fake-crop",
                relief_m=0.2,
                relief_samples=40,
            )
        )

    for index in range(3):
        observe(f"v{index}", f"f{index}")

    from parcel_robot.runtime import RobotRuntime

    class _Host:
        """Exactly what the ASK door touches, and nothing else.

        Two attributes and two helpers, borrowed from ``RobotRuntime`` itself so
        the real implementations are what run — the host supplies the map and
        the lock, which is all ``_realtime_ask_place`` reads off ``self``. If
        the door ever grows a dependency on something heavier, this class stops
        working and that is the signal.
        """

        _p1b_learned_map = smap
        _p1b_map_lock = threading.Lock()
        _ask_subject = RobotRuntime._ask_subject
        _ask_revision = staticmethod(RobotRuntime._ask_revision)

    return smap, _Host(), observe


def test_the_confirm_token_survives_the_robot_looking_at_the_place_again() -> None:
    """CORRECTION PASS, the defect the verifiers found.

    The first token digested the whole verdict, ``signals`` included — and those
    signals are evidence counters that move on **every camera frame that sees
    the place**. So the token changed faster than a person can answer, and the
    owner's "yes" could never be confirmed while the robot could see the thing
    it was asking about. A confirmation gate that cannot be satisfied is not a
    gate.

    One more observation of the same place, between the ASK and the confirm,
    must leave the token alone.

    SEED: put ``verdict.as_dict()`` (or just ``signals``) back into
    ``_ask_revision``.
    """

    from parcel_robot.runtime import RobotRuntime

    _smap, host, observe = _ask_map(None)
    first = RobotRuntime._realtime_ask_place(host, "lamppost")
    assert first, "the fixture place must be an ASK or this test proves nothing"
    token = first["revision"]
    assert token

    # The robot keeps walking and sees the place three more times.
    for index in range(3, 6):
        observe(f"v{index}", f"f{index}")
    again = RobotRuntime._realtime_ask_place(host, "lamppost")
    assert again, "the place stopped being an ASK for an unrelated reason"
    assert again["revision"] == token, (
        "the token changed because the robot LOOKED at the place again; the "
        "owner can never answer fast enough to beat a camera frame"
    )


def test_the_confirm_token_moves_when_the_SUBJECT_moves() -> None:
    """The other half: it must not be a constant either.

    New pixels for the place are a new question — the crop is what the model
    was asked about.

    SEED: drop the thumbnail sha256 from ``_ask_revision``.
    """

    from parcel_robot.runtime import RobotRuntime

    smap, host, _observe = _ask_map(None)
    first = RobotRuntime._realtime_ask_place(host, "lamppost")
    assert first, "the fixture place must be an ASK or this test proves nothing"
    for entry in smap.active_entries():
        entry.thumbnail = b"\x89PNG-a-much-better-view"
    again = RobotRuntime._realtime_ask_place(host, "lamppost")
    assert again["revision"] != first["revision"]


def test_a_confirmation_authorises_exactly_one_trip_and_not_a_standing_grant() -> None:
    """CORRECTION PASS. "Yes, go" is permission for a trip, not for a place.

    The verifiers drove one valid token three times and got three trips: the
    comparison is against a RECOMPUTED digest, and a digest stays put while its
    subject does, so nothing retired it. A token is now spent when it is
    honoured.

    SEED: delete the ``_spend_confirmation`` call, or the ``spent`` term in the
    comparison.
    """

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    asked = _call(broker, {"place": "bench"})
    token = asked[CONFIRM_TOKEN_KEY]

    first = _call(broker, {"place": "bench", CONFIRM_KEY: token})
    assert first["status"] == STATUS_OK
    for _ in range(3):
        replay = _call(broker, {"place": "bench", CONFIRM_KEY: token})
        assert replay["status"] == STATUS_UNCERTAIN_PLACE, (
            "a spent token started a second trip; the model can now walk the "
            "robot to that place as often as it likes on one 'yes'"
        )
    assert [name for name, _ in doors.touched] == ["navigate"]
    assert doors.dispatches == 1
    assert broker.uncertain_place_confirms == 1


def test_the_replay_memory_is_bounded() -> None:
    """A replay guard, not an audit log.

    SEED: drop the eviction loop in ``_spend_confirmation``.
    """

    from parcel_robot.realtime.tool_broker import CONFIRM_REPLAY_MEMORY

    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(doors.as_doors())
    for index in range(CONFIRM_REPLAY_MEMORY * 2):
        broker._spend_confirmation(f"token-{index}")
    assert len(broker._spent_confirmations) <= CONFIRM_REPLAY_MEMORY


def test_an_ask_can_never_reach_the_proactive_motion_counter() -> None:
    """CORRECTION PASS, and the honest version of the verifiers' note.

    The counter's published meaning is "a proactive proposal reached a door",
    and an ``uncertain_place`` result reaches none — so counting it would show
    an owner reading the panel an event in which the robot did not move. The
    guard for that is one line in ``handle``.

    It is also, today, **unreachable**, and this test pins the reason rather
    than pretending to exercise it: ``uncertain_place`` can only come out of
    ``navigate_to``, and ``navigate_to`` is in ``PROACTIVE_MOTION_REFUSED``,
    which no config can buy it out of — a proactive travel tool is the C1 defect
    exactly. If a later card ever moves a travel tool into the allowlist, the
    guard is already there and this test is what says why it was written.

    SEED: move ``navigate_to`` from ``PROACTIVE_MOTION_REFUSED`` into
    ``PROACTIVE_MOTION_ALLOWED`` — this test reddens, and the guard in
    ``handle`` is then the thing keeping the counter honest.
    """

    from parcel_robot.realtime.config import (
        PROACTIVE_MOTION_ALLOWED,
        PROACTIVE_MOTION_REFUSED,
    )
    from parcel_robot.realtime.tool_broker import (
        BROKER_TOOLS,
        STATUS_UNCERTAIN_PLACE,
    )

    assert TOOL_NAVIGATE_TO in PROACTIVE_MOTION_REFUSED
    assert TOOL_NAVIGATE_TO not in PROACTIVE_MOTION_ALLOWED

    # ``uncertain_place`` has exactly one producer, which is what makes the two
    # facts above a proof rather than a coincidence.
    assert STATUS_UNCERTAIN_PLACE == "uncertain_place"
    producers = [
        tool
        for tool in BROKER_TOOLS
        if STATUS_UNCERTAIN_PLACE
        in inspect.getsource(getattr(RealtimeToolBroker, f"_{tool}", lambda: None))
    ]
    assert producers == [TOOL_NAVIGATE_TO], producers

    # Behaviourally, today: a system-initiated navigate_to is refused before it
    # can reach the ASK arm at all, and nothing is counted.
    doors = _AskDoors(_ask_payload())
    broker = RealtimeToolBroker(
        doors.as_doors(), proactive_motion_tools=(TOOL_NAVIGATE_TO,)
    )
    broker.note_response_provenance("system")
    result = _call(broker, {"place": "bench"})
    assert result["status"] != STATUS_OK
    assert doors.touched == []
    assert broker.proactive_motion_admissions == 0


# ==========================================================================
# 4. NM-1 — CONSISTENCY IS NOT CORRECTNESS
# ==========================================================================


def test_the_floor_is_the_detectors_own_shipped_threshold() -> None:
    """Adopted, not fitted — and pinned so the two cannot drift.

    SEED: change ``JUDGE_MIN_SCORE`` to a number tuned on the fixture.
    """

    from parcel_robot.detection_adapter.owlv2_onnx import DEFAULT_OWLV2_THRESHOLD

    assert JUDGE_MIN_SCORE == DEFAULT_OWLV2_THRESHOLD


def test_a_k_agreed_name_the_judge_rejects_never_reaches_known_places() -> None:
    """The card's sentence, as a test.

    P1-D's measured failure: three independent visits agreed on "yellow
    cylinder" for a bollard and it was promoted with full rights.

    SEED: delete the ``hold_at_hypothesis`` call in ``run_naming_pass``, or make
    the rejecting branch fall through.
    """

    entry = _entry()
    judge = _StubJudge(JUDGE_REJECT, strength=0.02)
    reports = _run_three_visits(entry, "yellow cylinder", judge)
    fake = _FakeMap([entry])
    assert "yellow cylinder" not in fake.known_places()
    assert "yellow cylinder" not in entry.admissible_names()
    name = next(n for n in entry.names if n.text == "yellow cylinder")
    assert name.provenance == NAME_VLM_PROPOSED
    assert reports[-1].judge_rejected >= 1
    assert reports[-1].judge_held >= 1
    assert reports[-1].promotions == 0
    assert any(row[1] == HOLD_EVENT for row in entry.history)


def test_a_held_name_keeps_every_visit_it_earned() -> None:
    """A hold is not a demotion: nothing about the visits changed.

    SEED: make the hold drop a supporting visit (i.e. call
    ``demote_disagreed_names`` instead).
    """

    entry = _entry()
    _run_three_visits(entry, "yellow cylinder", _StubJudge(JUDGE_REJECT, strength=0.01))
    name = next(n for n in entry.names if n.text == "yellow cylinder")
    assert name.visits == NAME_PROMOTION_VISITS
    assert len(name.supporting_visit_ids) == NAME_PROMOTION_VISITS
    assert not name.admissible


def test_a_k_agreed_name_the_judge_accepts_is_vocabulary() -> None:
    """The gate must still be able to GROW a vocabulary.

    A gate that promotes nothing is the "safe because blind" failure P1-D
    measured on the 64-px path, wearing a different hat.

    SEED: make ``JUDGE_ACCEPT`` fall into the hold branch.
    """

    entry = _entry(label="bollard")
    judge = _StubJudge(JUDGE_ACCEPT, strength=0.9)
    reports = _run_three_visits(entry, "post box", judge)
    fake = _FakeMap([entry])
    assert "post box" in fake.known_places()
    assert reports[-1].judge_accepted >= 1
    assert reports[-1].promotions == 1
    assert judge.asked, "the judge was never consulted"


def test_an_unavailable_judge_holds_a_new_promotion_and_never_demotes_an_old_one() -> None:
    """Unavailable is a HOLD, in both directions.

    Prototype rule: no new fail-closed defaults. A judge that cannot answer must
    not take vocabulary away that was already granted — but it must not hand out
    new vocabulary on an unchecked name either.

    SEED: treat ``JUDGE_UNAVAILABLE`` as ``JUDGE_ACCEPT``; or make it hold an
    already-promoted name (a silent demotion whenever the GPU is busy).
    """

    # (a) a promotion happening NOW is withheld
    entry = _entry()
    reports = _run_three_visits(entry, "yellow cylinder", NullNamingJudge())
    assert "yellow cylinder" not in entry.admissible_names()
    assert reports[-1].judge_unavailable >= 1
    assert reports[-1].judge_held >= 1

    # (b) a name that already had standing keeps it
    standing = _entry(entry_id="e2")
    standing.names = (
        ProposedName(text="bollard", provenance=NAME_DETECTOR_LABEL),
        ProposedName(
            text="post box",
            provenance=NAME_PROMOTED,
            visits=3,
            supporting_visit_ids=("x", "y", "z"),
        ),
    )
    fake = _FakeMap([standing])

    def describe(_thumb: bytes | None) -> Any:
        return type("A", (), {"text": "post box"})()

    run_naming_pass(
        fake, describe, visit_id="v9", budget_s=0.0, judge=NullNamingJudge(), wall_s=200.0
    )
    assert "post box" in standing.admissible_names(), (
        "an unavailable judge silently demoted an established name"
    )


def test_a_judge_that_raises_holds_it_never_promotes() -> None:
    """SEED: let the exception escape as a promotion (drop the except arm's hold)."""

    class _Broken:
        name = "broken"

        def judge(self, name: str, crop_png: bytes | None, *, entry_id: str = "") -> Any:
            raise RuntimeError("the ONNX session died")

    entry = _entry()
    reports = _run_three_visits(entry, "yellow cylinder", _Broken())
    assert "yellow cylinder" not in entry.admissible_names()
    assert reports[-1].judge_unavailable >= 1


def test_no_judge_configured_reproduces_head_exactly() -> None:
    """Flag-off identity. ``judge=None`` is HEAD, byte for byte.

    Measured on the real fixture too: NM-1's replay of P1-D's full-resolution
    arm with ``judge=None`` gives 2 promotions, 2 false — P1-D's own numbers
    (``NM1_STATUS.md`` row F).

    SEED: default ``judge`` to ``default_naming_judge()``.
    """

    import inspect as _inspect

    signature = _inspect.signature(run_naming_pass)
    assert signature.parameters["judge"].default is None

    entry = _entry()
    reports = _run_three_visits(entry, "yellow cylinder", None)
    assert "yellow cylinder" in entry.admissible_names(), (
        "HEAD promotes this name — that is the defect NM-1 measures, and "
        "flag-off must reproduce it rather than quietly fixing it"
    )
    assert reports[-1].promotions == 1
    assert reports[-1].judged == 0
    assert reports[-1].judge_held == 0


def test_the_judge_is_asked_about_standing_names_not_only_new_promotions() -> None:
    """A name promoted while the judge was down must be re-examined.

    Otherwise "unavailable once" becomes "vocabulary forever".

    SEED: gate the judge call on ``promoted`` instead of ``proposed.admissible``.
    """

    entry = _entry()
    entry.names = (
        ProposedName(text="bollard", provenance=NAME_DETECTOR_LABEL),
        ProposedName(
            text="yellow cylinder",
            provenance=NAME_PROMOTED,
            visits=3,
            supporting_visit_ids=("a", "b", "c"),
        ),
    )
    assert "yellow cylinder" in entry.admissible_names()
    fake = _FakeMap([entry])

    def describe(_thumb: bytes | None) -> Any:
        return type("A", (), {"text": "yellow cylinder"})()

    judge = _StubJudge(JUDGE_REJECT, strength=0.01)
    report = run_naming_pass(
        fake, describe, visit_id="later", budget_s=0.0, judge=judge, wall_s=300.0
    )
    assert judge.asked == ["yellow cylinder"]
    assert report.judge_held == 1
    assert "yellow cylinder" not in entry.admissible_names()


def test_the_detector_label_is_never_held() -> None:
    """The label channel is the map's own index, not a hypothesis.

    SEED: let ``hold_at_hypothesis`` rewrite a ``detector_label``.
    """

    entry = _entry(label="bollard")
    assert hold_at_hypothesis(entry, "bollard", wall_s=1.0) is False
    assert entry.names[0].provenance == NAME_DETECTOR_LABEL
    assert "bollard" in entry.admissible_names()


def test_an_unavailable_judge_reports_no_strength() -> None:
    """"Looked and saw nothing" and "was never asked" are different facts.

    SEED: make the unavailable verdict carry ``strength=0.0``.
    """

    verdict = NullNamingJudge().judge("bench", None)
    assert verdict.outcome == JUDGE_UNAVAILABLE
    assert verdict.strength is None
    with pytest.raises(ValueError):
        JudgeVerdict(JUDGE_ACCEPT, name="bench")  # accepting with no strength


def test_a_judge_with_no_crop_holds_rather_than_rejecting() -> None:
    """An entry with no best view has not been contradicted; it is unexamined.

    SEED: return ``JUDGE_REJECT`` when the crop is missing.
    """

    judge = OwlV2NamingJudge(require_env=True)
    verdict = judge.judge("bench", None, entry_id="e1")
    assert verdict.outcome == JUDGE_UNAVAILABLE
    assert "no crop" in verdict.detail


# ==========================================================================
# 4b. CORRECTION PASS — the four notes, as guards
# ==========================================================================


def test_the_shipped_floor_is_the_pre_registered_one_and_nothing_configures_it() -> None:
    """``PARCEL_NM1_JUDGE_FLOOR`` is a SWEEP knob, not an operating point.

    NM-1 measured the sweep and it is a negative result: no floor separates on
    the dev fixture. An env var that silently re-points a gate is how a fitted
    threshold gets shipped without an eval, so the shipped value is pinned here
    and the repo is checked for anyone setting it.

    SEED: give the env var a default, or set it in a config/launcher.
    """

    from parcel_robot.vlm_veto.judge import JUDGE_FLOOR_ENV, configured_floor

    assert JUDGE_FLOOR_ENV == "PARCEL_NM1_JUDGE_FLOOR"
    assert configured_floor() == JUDGE_MIN_SCORE
    assert configured_floor(0.42) == 0.42  # the default is the caller's, unset

    for pattern in ("configs", "scripts", "src"):
        for path in (REPO / pattern).rglob("*"):
            if path.suffix not in {".yaml", ".yml", ".sh", ".py"} or not path.is_file():
                continue
            if path.name == "judge.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert JUDGE_FLOOR_ENV not in text, f"{path} sets the sweep knob"


def test_a_judge_that_failed_to_build_tries_again_on_the_next_pass() -> None:
    """The module promises "the next pass tries again". Make it true of the BUILD.

    It used to latch: one transient failure (a busy GPU at startup, the env
    switch flipped a second later) retired the judge for the life of the
    process, and every name after that held forever while the log said it would
    retry.

    SEED: restore the ``self._tried`` latch (``if self._tried: return False``).
    """

    judge = OwlV2NamingJudge(require_env=True)
    attempts = []

    def never(*args: Any, **kwargs: Any) -> None:
        attempts.append(1)

    import parcel_robot.detection_adapter.owlv2_onnx as owl

    original = owl.load_owlv2_detector
    owl.load_owlv2_detector = never  # type: ignore[assignment]
    try:
        assert judge.load() is False
        assert judge.load() is False
        assert judge.load() is False
    finally:
        owl.load_owlv2_detector = original  # type: ignore[assignment]
    assert len(attempts) == 3, f"the build latched after {len(attempts)} attempt(s)"
    assert judge.attempts == 3


def test_the_board_evicts_least_recently_USED_not_first_inserted() -> None:
    """A place the robot keeps asking about must not be evicted by one-offs.

    SEED: drop the re-insertion in ``read``'s hit arm.
    """

    runner = _RecordingRunner()
    bureau = VerdictBureau(runner, board_depth=3)
    try:
        places = {name: _place(place_id=name) for name in ("a", "b", "c", "d")}
        for name in ("a", "b", "c"):
            bureau.read(name, places[name])
        bureau.drain()
        # Touch "a" so it is the most recently USED, then publish a fourth.
        assert bureau.read("a", places["a"]).verdict == VETO_PRESENT
        bureau.read("d", places["d"])
        bureau.drain()
        assert bureau.lookup("a", places["a"]) is not None, (
            "the pair the robot just used was evicted by a one-off query"
        )
        assert bureau.lookup("b", places["b"]) is None
    finally:
        bureau.close()


def test_clearing_the_bureaus_does_not_leave_a_dead_reader_installed() -> None:
    """A stopped worker behind a live callable is P1-D's defect, one layer down.

    SEED: drop the ``clear_veto_cache()`` call from ``clear_bureaus``.
    """

    import dataclasses

    from parcel_robot.perception_abstention import (
        AbstentionPolicy,
        clear_veto_cache,
        resolve_veto,
    )
    from parcel_robot.vlm_veto.bureau import clear_bureaus

    policy = dataclasses.replace(AbstentionPolicy(), veto_model="")
    clear_veto_cache()
    clear_bureaus()
    try:
        first = resolve_veto(policy)
        clear_bureaus()
        second = resolve_veto(policy)
        assert second is not first, (
            "resolve_veto handed back a reader bound to a bureau whose worker "
            "was stopped; the gate would ask about everything, forever"
        )
        assert second("bench", _place()).verdict == VETO_UNAVAILABLE
    finally:
        clear_bureaus()
        clear_veto_cache()


# ==========================================================================
# 5. the GPU arm — the real judge, gated
# ==========================================================================


def _owlv2_reason() -> str:
    from parcel_robot.detection_adapter.owlv2_onnx import (
        onnx_enabled,
        owlv2_weights_present,
    )

    if not owlv2_weights_present():
        return "OWLv2 weights are not on this host (scripts/fetch_owlv2.sh)"
    if not onnx_enabled():
        return "PARCEL_OWLV2_ONNX is not set"
    return ""


@pytest.mark.skipif(bool(_owlv2_reason()), reason=_owlv2_reason() or "ok")
def test_the_real_judge_answers_with_a_strength_and_honours_its_floor() -> None:
    """The seat is real, reachable and reports what it decided on.

    Not an accuracy assertion: NM-1 MEASURED the judge's accuracy on the dev
    fixture and it does not separate (``NM1_STATUS.md`` rows J1-J6). Enshrining
    a number here would turn a refuted operating point into a ratchet. What is
    pinned is the contract: a real answer, a real strength, and the floor the
    verdict says it used.

    SEED: build the detector with its own default threshold instead of 0.0 —
    the judge then cannot report a strength below the floor and the sweep in
    the status doc becomes impossible to reproduce.
    """

    import base64

    manifest = json.loads(
        (REPO / "tests/data/p1d_crops/MANIFEST.json").read_text(encoding="utf-8")
    )
    row = next(r for r in manifest["crops"] if r["label"] == "bench")
    crop = (REPO / "tests/data/p1d_crops" / row["file"]).read_bytes()
    assert base64.b64decode(row["thumbnail_b64"])  # the fixture is intact

    judge = OwlV2NamingJudge(require_env=True)
    assert judge.load(), "OWLv2 is present but the judge could not be built"
    verdict = judge.judge("bench", crop, entry_id=row["id"])
    assert verdict.outcome in (JUDGE_ACCEPT, JUDGE_REJECT)
    assert verdict.strength is not None
    assert verdict.floor == JUDGE_MIN_SCORE
    assert verdict.model == "owlv2"
    assert verdict.latency_ms > 0.0
