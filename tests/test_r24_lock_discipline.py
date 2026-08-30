"""Card R24 — lock discipline on the realtime doors and the navigator.

WHY THIS FILE EXISTS
--------------------
Fable's full audit (``scrum/20260820/AUDIT_FULL_FABLE.md``) landed three
findings that are all the same defect at three scales:

* CONFIRMED major, §Architecture — *"The realtime motion doors mutate VoiceAgent
  state without ``_agent_lock``"*: ``_realtime_navigate``, ``_realtime_follow``
  and ``_realtime_orbit`` run on the realtime PUMP thread and wrote agent state
  the lock exists to serialize against the panel/typed thread.
* CONFIRMED minor — ``_navigation_lock`` protected three of the navigator's
  mutating entry points; ``pause`` / ``resume`` / the stop-on-resume ran
  lock-free against ``_step_navigation``, which drives the same object under it.
* CONFIRMED minor — the compound realtime record (``_realtime_pace_intent``,
  ``_realtime_last_route``, ``_realtime_turn_sequence``, and the R15
  ``_narratable_*`` marks) was written cross-thread outside ``_lock`` while its
  readers took ``_lock`` — or, in ``realtime_snapshot``'s case, took nothing.

The same audit's healthy-list says *"lock ordering is a verified DAG"*. That
verification was an AST scan that lived in a session scratchpad and is gone
(§Ops: *"status docs cite /tmp evidence paths that will evaporate"*). This file
REBUILDS it in the repo, and turns it into the ratchet the card asks for: the
next door added without its lock reddens the commit gate.

WHAT EACH LAYER PROVES — AND WHAT IT DOES NOT
---------------------------------------------
1. ``LockOrderScan`` (static, this file) proves the LEXICAL nesting order of
   the six ``RobotRuntime`` locks, closed interprocedurally over ``self.foo()``
   calls, is acyclic. It DOES NOT see edges that cross a collaborator object —
   ``agent._admit_local_sketch`` reaching ``self._accept_plan`` through the
   ``plan_publisher`` callback is invisible to it. That is exactly why layer 3
   exists, and both are asserted rather than one being claimed for the other.
2. The site checks prove the named mutating sites are lexically inside their
   lock. Each one is shown able to FAIL on a seeded violation, so a green run
   here is evidence rather than notation.
3. ``_LockOrderObserver`` (live, this file) wraps the six real lock objects on
   a real runtime and records the acquisition order actually taken by real
   threads under contention. This is the layer that sees the callback edges,
   and it is the one that would catch an inversion the AST cannot.

WHAT NO LAYER HERE PROVES
-------------------------
Absence of deadlock in general (only that the ORDER observed and the order
written are acyclic), anything about locks outside ``RobotRuntime`` (the
lane's, the arbiter's, the controller manager's each have their own),
and anything about the hosted provider — every thread here is local.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time
from collections.abc import Iterable

import pytest
from commissioned_sim import (
    authorize_commissioned_voice_binding,
    commissioned_runtime_kwargs,
)

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
from parcel_robot.runtime import RobotRuntime, _LockedNavigationChannel
from parcel_robot.runtime_channels import NavigationChannel

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PATH = REPO / "src" / "parcel_robot" / "runtime.py"

#: The runtime locks ``RobotRuntime.__init__`` constructs. Named explicitly
#: rather than discovered so that another lock added without a card is itself
#: a finding: ``test_the_lock_roster_is_complete`` fails until it is listed
#: here with an owner and an order.
#:
#: * 2026-08-21 (C-1) — ``_camera_stream_lock`` added, owner: the camera
#:   observation stream. It guards the bounded frame queue, its drop counters,
#:   and the single-slot pose mailbox — one lock for all three deliberately, so
#:   that attaching the eye costs this roster ONE new name and ZERO new
#:   ordering edges (``test_the_lock_order_is_the_pinned_one`` is the proof:
#:   ``PINNED_LOCK_ORDER`` below is unchanged by C-1). It is a leaf: the
#:   camera worker takes it alone, never while holding another runtime lock,
#:   and never across a render, an inference, or an evidence-log offer.
#: * 2026-08-22 (P1-B) — ``_p1b_map_lock`` added, owner: the runtime's own
#:   online semantic map. It guards the map object and this card's ingest
#:   counters. Also a LEAF, and for the same reason C-1's is: the camera worker
#:   takes it alone in ``_p1b_feed_learned_map`` — after ``_camera_stream_lock``
#:   has been RELEASED, never inside it — and ``close()`` takes it alone in
#:   ``_p1b_persist_learned_map`` after the camera worker has been stopped, so
#:   no frame can be in flight against it. It adds exactly ONE ordering edge,
#:   ``_close_lock -> _p1b_map_lock`` (the persist runs inside ``close()``),
#:   and it has NO outgoing edges, so it cannot participate in a cycle — see
#:   ``PINNED_LOCK_ORDER`` below.
RUNTIME_LOCKS: tuple[str, ...] = (
    "_lock",
    "_agent_lock",
    "_navigation_lock",
    "_command_lock",
    "_close_lock",
    "_transcript_lock",
    "_camera_stream_lock",
    "_p1b_map_lock",
    "_audio_effect_lock",
)

#: The three hosted motion doors §Arch-1 names. Each must hold ``_agent_lock``
#: across its WHOLE body — see ``_realtime_navigate``'s docstring for why the
#: section cannot be narrowed to the mutation (the ``last_reasoning_source``
#: read-after-write straddles it).
AGENT_LOCK_DOORS: tuple[str, ...] = (
    "_realtime_navigate",
    "_realtime_follow",
    "_realtime_orbit",
)

#: Methods that take ``_agent_lock`` for a TYPED/panel turn. ``_agent_lock`` is
#: a non-reentrant ``threading.Lock``: a door that reached one of these while
#: holding it would self-deadlock rather than race.
AGENT_LOCK_ENTRY_POINTS: frozenset[str] = frozenset(
    {"set_personality", "handle_text", "handle_text_guarded"}
)

#: Compound cross-thread realtime state. Every WRITE outside ``__init__`` must
#: hold ``_lock`` — the lock its readers take. Each name carries the reason it
#: is compound rather than merely shared, because "compound" is what makes a
#: bare attribute assignment insufficient even under the GIL.
COMPOUND_REALTIME_FIELDS: dict[str, str] = {
    # read-modify-write; the value becomes PlanIR.source_turn_id
    "_realtime_turn_sequence": "increment feeding an admission-matching id",
    # five fields that must describe ONE routing decision
    "_realtime_last_route": "five-field record read whole by realtime_snapshot",
    # value + timestamp, cleared as a pair by the whisperer
    "_realtime_pace_intent": "paired with _realtime_pace_intent_at_s",
    "_realtime_pace_intent_at_s": "paired with _realtime_pace_intent",
    # the panel's copy of the same declaration
    "_realtime_last_pace": "panel copy of the pace the whisperer may clear",
    # R15 one-shot marks: check-then-clear across two threads
    "_narratable_orbit": "one-shot mark set on the pump, claimed on control",
    "_narratable_activity": "one-shot mark set on the pump, claimed on control",
}

#: Navigator mutations. ``self.dog`` proxies the navigator; ``navigator`` is the
#: local name ``_start_or_resume_navigation_locked`` binds it to. Every call
#: listed here must be lexically inside ``_navigation_lock`` in ``runtime.py``.
NAVIGATOR_MUTATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("self.dog", "navigate"),
        ("self.dog", "set_nav_pose"),
        ("self.dog", "stop"),
        ("navigator", "stop"),
        ("navigator", "pause"),
        ("navigator", "resume"),
    }
)

#: THE PINNED LOCK ORDER. Every lexical nesting the runtime states today, as
#: (outer, inner). This is a RATCHET, not a description: adding an edge means a
#: new ordering constraint on six locks across four threads, and that is a
#: decision a card should make deliberately.
#:
#: To update: re-run ``LockOrderScan(...).edges()``, confirm the new edge does
#: not close a cycle (``test_the_lock_order_graph_is_acyclic`` proves it), state
#: the reason in the card's status doc, and add the row here.
#:
#: * 2026-08-21 (R24) — established. R24 added ZERO edges: the doors' new
#:   ``_agent_lock`` sections only reach ``_lock`` lexically (an edge
#:   ``set_personality`` already stated), the navigator override takes no other
#:   lock, and the compound writes are all ``_lock`` under an existing outer.
#: * 2026-08-22 (P1-B) — ONE new edge, ``_close_lock -> _p1b_map_lock``.
#:   ``close()`` holds ``_close_lock`` and calls ``_p1b_persist_learned_map``,
#:   which takes the map lock to write the map out. It cannot close a cycle
#:   because ``_p1b_map_lock`` has no outgoing edges at all: the only two
#:   places that take it (``_p1b_feed_learned_map`` on the camera worker and
#:   the persist above) call nothing that takes another runtime lock, and
#:   nothing anywhere takes ``_close_lock`` — or any other runtime lock —
#:   while holding it. ``test_the_lock_order_graph_is_acyclic`` is the proof.
#:   Note what is deliberately NOT here: ``_camera_stream_lock ->
#:   _p1b_map_lock``. The feed is called from ``_publish_camera_frame`` AFTER
#:   the stream lock is released, precisely so the map cannot be reached while
#:   the camera's own lock is held.
PINNED_LOCK_ORDER: frozenset[tuple[str, str]] = frozenset(
    {
        # Acoustic playback events are serialized with begin/barge-in at their
        # effect boundary. The callback can reach the ordinary event/state
        # sink, and close invalidates that binding before joining the sink.
        # No runtime path takes _close_lock or _audio_effect_lock in reverse.
        ("_audio_effect_lock", "_lock"),
        ("_agent_lock", "_lock"),
        ("_close_lock", "_audio_effect_lock"),
        ("_close_lock", "_command_lock"),
        ("_close_lock", "_lock"),
        ("_close_lock", "_p1b_map_lock"),
        ("_command_lock", "_lock"),
        ("_command_lock", "_navigation_lock"),
    }
)

#: Edges that exist only because a lock is taken across a COLLABORATOR call
#: that re-enters the runtime through a callback. The AST scan cannot see any
#: of them, and the one it could not see is what made the audit's "lock
#: ordering is a verified DAG" false (R24_STATUS.md §4.1):
#:
#: * ``_agent_lock → _command_lock`` — the agent's ``plan_publisher`` callback
#:   re-enters ``self._accept_plan``. ``handle_text`` has taken this path since
#:   long before R24; the doors now take the identical one.
#: * ``_navigation_lock → _lock`` — ``dog.stop()`` under ``_navigation_lock``
#:   reaches ``stop_motion``, which reaches ``_lock``. Pre-existing and
#:   harmless: nothing anywhere takes ``_navigation_lock`` under ``_lock``.
#:
#: NOT listed, because R24 removed it: ``_navigation_lock → _command_lock``.
CALLBACK_LOCK_ORDER: frozenset[tuple[str, str]] = frozenset(
    {
        ("_agent_lock", "_command_lock"),
        ("_navigation_lock", "_lock"),
    }
)

#: THE RE-ENTRY ROSTER. Every ``on_*=self.<method>`` the runtime installs on a
#: collaborator is a door back into the runtime that a static call-graph walk
#: steps straight over — a lock held across ``dog.stop()``, ``motion.walk()`` or
#: a skill dispatch is really held across the runtime method named here.
#:
#: ``motion.on_stop = self.stop_motion`` is the one that made the lock order
#: cyclic before R24. The roster is asserted COMPLETE against ``__init__``'s
#: keyword arguments so a new callback cannot be added silently; each entry
#: names the runtime locks that handler takes, which is what a reviewer needs
#: in order to answer "may I hold a lock across this collaborator call?".
#: ``keyword -> (runtime method, locks that method can reach)``, exactly as
#: ``RobotRuntime.__init__`` wires them. The roster is the authority for which
#: handlers reach each lock.
#: ``_command_lock`` — those are the ones a critical section must not span
#: without already holding it, and ``on_stop`` is the one that was spanned.
REENTRY_CALLBACKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "on_alarm": ("_realtime_pump_alarm", ("_lock",)),
    "on_write_attempt": (
        "_audio_write_attempt",
        ("_audio_effect_lock", "_lock"),
    ),
    "on_command": ("_voice_motion", ("_command_lock", "_lock")),
    "on_dispatch": ("_realtime_thinking_pose", ()),
    "on_error": ("_voice_error", ("_lock",)),
    "on_failure": ("_microphone_failed", ("_lock",)),
    "on_filler_audible": ("_duplex_filler_audible", ()),
    "on_idle_close": ("_realtime_idle_closed", ("_lock",)),
    "on_partial": ("_voice_partial_received", ("_lock",)),
    "on_pose": ("_run_pose", ("_command_lock", "_lock")),
    "on_speech_end": ("_owner_speech_ended", ()),
    "on_speech_start": ("_owner_speech_started", ("_lock",)),
    "on_stage": ("_voice_stage", ("_lock", "_transcript_lock")),
    "on_stop": ("stop_motion", ("_command_lock", "_lock")),
    "on_trajectory": ("_run_trajectory", ("_command_lock", "_lock")),
    "on_turn": ("_voice_turn_completed", ("_lock",)),
    "on_turn_commit": ("_record_turn_commit", ()),
}

#: The LAMBDA half of the same roster: ``on_*=lambda ...`` callbacks, keyed by
#: what the lambda body calls. Rostered separately because a lambda has no name
#: to look up, and counted because "there are only a couple of them and they are
#: harmless" is exactly the kind of claim that goes stale — it was already wrong
#: when first written here (there are seven sites, not two, and five of them
#: reach ``_lock`` through ``_emit``).
#:
#: All of them are safe today for one structural reason worth stating: the only
#: runtime lock any of them reaches is ``_lock``, which is a SINK in the order
#: graph — it has no outgoing edges, so ``X → _lock`` can never close a cycle
#: for any X. If a lambda ever reaches ``_command_lock`` or ``_navigation_lock``
#: that reasoning collapses, and this roster is what surfaces it.
REENTRY_LAMBDAS: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[str, ...]] = {
    ("on_event", (("self", "_emit"),)): ("_lock",),
    # Card R25. The spend ledger's fail-open WARNING sink (``_arm_spend_ledger``).
    # Fired from `SpendLedger.month_to_date`, which the arming path and the
    # narration gate both call, so it re-enters the runtime from the panel
    # thread and from control loops. Same structural argument as ``on_event``:
    # the only lock it reaches is ``_lock``, and ``_lock`` is a sink. Rostered
    # rather than waved through — the roster existing is what turned this from
    # an unremarked new re-entry into a decision.
    ("on_note", (("self", "_emit"),)): ("_lock",),
    ("on_snapshot", ()): (),
    ("on_stop", (("self.arbiter", "cancel"),)): (),
}


# ======================================================== the static scanner
class LockOrderScan:
    """Held-lock analysis over one class's methods.

    Walks each method body carrying the set of ``self.<lock>`` context managers
    currently open. Every ``with self._b:`` seen while ``_a`` is held is an
    ordering edge ``(_a, _b)``. Calls of the form ``self.foo()`` made under a
    held set are closed transitively, so a lock taken three helpers deep still
    lands under the caller's outer lock.

    Deliberate limits, stated because a scanner whose blind spots are unwritten
    is worse than no scanner:

    * Only ``self.<name>`` calls are followed. A lock reached through a
      collaborator (``self.agent.foo()`` → runtime callback) is invisible.
    * Nested functions are analysed under the held set of their *definition*
      site. Every closure in ``runtime.py`` is invoked inline, but a closure
      stashed for later would be analysed pessimistically, not permissively.
    * ``try``/``except``/``finally`` and branches are merged, not path-split:
      a lock taken on any path counts as taken.
    """

    def __init__(self, source: str, *, locks: Iterable[str], class_name: str) -> None:
        self._locks = frozenset(locks)
        tree = ast.parse(source)
        cls = next(
            (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name),
            None,
        )
        if cls is None:  # pragma: no cover - the class is a constant
            raise LookupError(class_name)
        self.methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            node.name: node
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self._edges: set[tuple[str, str]] = set()
        self._direct: dict[str, set[str]] = {}
        self._calls: dict[str, dict[frozenset[str], set[str]]] = {}
        #: (method, held-lock frozenset, node) for every attribute STORE.
        self.stores: list[tuple[str, frozenset[str], ast.Attribute]] = []
        #: (method, held-lock frozenset, node) for every attribute LOAD.
        self.loads: list[tuple[str, frozenset[str], ast.Attribute]] = []
        #: (method, held-lock frozenset, node) for every method CALL.
        self.calls: list[tuple[str, frozenset[str], ast.Call]] = []
        for name, node in self.methods.items():
            self._scan(name, node)
        self._close()

    # ---------------------------------------------------------------- walk
    def _lock_of(self, item: ast.withitem) -> str | None:
        ctx = item.context_expr
        if (
            isinstance(ctx, ast.Attribute)
            and isinstance(ctx.value, ast.Name)
            and ctx.value.id == "self"
            and ctx.attr in self._locks
        ):
            return ctx.attr
        return None

    def _scan(self, method: str, fn: ast.AST) -> None:
        direct = self._direct.setdefault(method, set())
        calls = self._calls.setdefault(method, {})

        def walk(node: ast.AST, held: frozenset[str]) -> None:
            if isinstance(node, (ast.With, ast.AsyncWith)):
                inner = held
                for item in node.items:
                    name = self._lock_of(item)
                    if name is None:
                        walk(item.context_expr, held)
                        continue
                    direct.add(name)
                    for outer in inner:
                        if outer != name:
                            self._edges.add((outer, name))
                    inner = inner | {name}
                for stmt in node.body:
                    walk(stmt, inner)
                return
            if isinstance(node, ast.Call):
                self.calls.append((method, held, node))
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                ):
                    calls.setdefault(held, set()).add(func.attr)
                for child in ast.iter_child_nodes(node):
                    walk(child, held)
                return
            if isinstance(node, ast.Attribute):
                if isinstance(node.ctx, ast.Store):
                    self.stores.append((method, held, node))
                elif isinstance(node.ctx, ast.Load):
                    self.loads.append((method, held, node))
            for child in ast.iter_child_nodes(node):
                walk(child, held)

        for stmt in getattr(fn, "body", []):
            walk(stmt, frozenset())

    # ------------------------------------------------------ interprocedural
    def locks_reachable(self, method: str, _seen: set[str] | None = None) -> frozenset[str]:
        """Every runtime lock ``method`` can take, directly or via ``self.x()``."""

        seen = set() if _seen is None else _seen
        if method in seen or method not in self.methods:
            return frozenset()
        seen.add(method)
        out = set(self._direct.get(method, set()))
        for callees in self._calls.get(method, {}).values():
            for callee in callees:
                out |= self.locks_reachable(callee, seen)
        return frozenset(out)

    def methods_reachable(self, method: str, _seen: set[str] | None = None) -> frozenset[str]:
        seen = set() if _seen is None else _seen
        if method in seen or method not in self.methods:
            return frozenset(seen)
        seen.add(method)
        for callees in self._calls.get(method, {}).values():
            for callee in callees:
                self.methods_reachable(callee, seen)
        return frozenset(seen)

    def _close(self) -> None:
        changed = True
        while changed:
            changed = False
            for method in self.methods:
                for held, callees in self._calls.get(method, {}).items():
                    if not held:
                        continue
                    for callee in callees:
                        for inner in self.locks_reachable(callee):
                            for outer in held:
                                if outer != inner and (outer, inner) not in self._edges:
                                    self._edges.add((outer, inner))
                                    changed = True

    def edges(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._edges)

    def must_hold(self) -> dict[str, frozenset[str]]:
        """Locks held on EVERY path into each method (interprocedural, ∩ over callers).

        A method nobody calls is an entry point and contributes ∅ — the
        pessimistic answer. Used to ask "is this ``self.dog.*`` call ALWAYS
        under ``_command_lock``", which the lexical held set alone cannot
        answer for a helper whose caller holds the lock.
        """

        every = frozenset(self._locks)
        sites: dict[str, list[tuple[str, frozenset[str]]]] = {}
        for method in self.methods:
            for held, callees in self._calls.get(method, {}).items():
                for callee in callees:
                    if callee in self.methods:
                        sites.setdefault(callee, []).append((method, held))
        must = {m: (every if m in sites else frozenset()) for m in self.methods}
        for _ in range(len(self.methods) + 2):
            changed = False
            for method, callers in sites.items():
                new = every
                for caller, held in callers:
                    new = new & (held | must[caller])
                if new != must[method]:
                    must[method] = new
                    changed = True
            if not changed:
                break
        return must

    def takers(self, lock: str) -> frozenset[str]:
        return frozenset(m for m, ls in self._direct.items() if lock in ls)

    def body_is_wholly_inside(self, method: str, lock: str) -> bool:
        """Is every executable statement of ``method`` inside ``with self.<lock>``?

        A docstring is allowed to precede it — it is not executable state.
        Anything else before or after the ``with`` means the door has a
        prologue or an epilogue outside its critical section.
        """

        fn = self.methods.get(method)
        if fn is None:
            return False
        body = list(fn.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.With):
            return False
        return any(self._lock_of(item) == lock for item in body[0].items)


def find_cycle(edges: Iterable[tuple[str, str]]) -> list[str] | None:
    """A cycle in the ordering graph, or ``None``. Deterministic (sorted DFS)."""

    graph: dict[str, set[str]] = {}
    for outer, inner in edges:
        graph.setdefault(outer, set()).add(inner)
        graph.setdefault(inner, set())
    state: dict[str, int] = {}
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in sorted(graph[node]):
            if state.get(nxt, 0) == 0:
                found = dfs(nxt)
                if found is not None:
                    return found
            elif state.get(nxt) == 1:
                return path[path.index(nxt) :] + [nxt]
        path.pop()
        state[node] = 2
        return None

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            found = dfs(node)
            if found is not None:
                return found
    return None


def _call_target(node: ast.Call) -> tuple[str, str] | None:
    """``(receiver, method)`` for ``a.b()`` / ``self.a.b()``; else ``None``."""

    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    value = func.value
    if isinstance(value, ast.Name):
        return (value.id, func.attr)
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "self"
    ):
        return (f"self.{value.attr}", func.attr)
    return None


@pytest.fixture(scope="module")
def scan() -> LockOrderScan:
    return LockOrderScan(
        RUNTIME_PATH.read_text(encoding="utf-8"),
        locks=RUNTIME_LOCKS,
        class_name="RobotRuntime",
    )


# ============================================== 1. the order graph is a DAG
def test_the_lock_roster_is_complete(scan: LockOrderScan) -> None:
    """A seventh lock is a design decision, not a detail. Name it here first."""

    init = scan.methods["__init__"]
    constructed = {
        node.targets[0].attr
        for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
        and isinstance(node.targets[0].value, ast.Name)
        and node.targets[0].value.id == "self"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr in {"Lock", "RLock"}
    }
    assert constructed == set(RUNTIME_LOCKS), (
        "RobotRuntime.__init__ constructs a lock this file does not order: "
        f"{sorted(constructed ^ set(RUNTIME_LOCKS))}"
    )


def test_the_lock_order_graph_is_acyclic(scan: LockOrderScan) -> None:
    """The audit's healthy-list claim, re-verified after R24's change.

    Run over the UNION of what the AST can see and the callback edges it
    cannot, so the answer is about the runtime rather than about the scanner.
    """

    edges = scan.edges() | CALLBACK_LOCK_ORDER
    cycle = find_cycle(edges)
    assert cycle is None, (
        "runtime lock ORDER is no longer a DAG — a deadlock is now constructible: "
        + " -> ".join(cycle or [])
    )


def test_the_lock_order_is_the_pinned_one(scan: LockOrderScan) -> None:
    """The ratchet. A new ordering constraint must be stated, not discovered."""

    assert scan.edges() == PINNED_LOCK_ORDER, (
        "the lexical lock order changed.\n"
        f"  added:   {sorted(scan.edges() - PINNED_LOCK_ORDER)}\n"
        f"  removed: {sorted(PINNED_LOCK_ORDER - scan.edges())}\n"
        "Confirm it does not close a cycle, justify it in the card's status "
        "doc, then update PINNED_LOCK_ORDER."
    )


def test_nothing_takes_the_agent_lock_while_holding_a_lower_lock(
    scan: LockOrderScan,
) -> None:
    """``_agent_lock`` is a SOURCE in the order graph — no back-edge exists.

    This is the property the doors' change depends on: they now hold
    ``_agent_lock`` while reaching ``_lock`` and (via the agent's
    ``plan_publisher`` callback) ``_command_lock``. Either of those taken in the
    other direction anywhere would close the cycle.
    """

    inbound = {outer for outer, inner in scan.edges() if inner == "_agent_lock"}
    assert inbound == set(), f"_agent_lock is acquired under {sorted(inbound)}"
    for method in scan.takers("_agent_lock"):
        for held, callees in scan._calls.get(method, {}).items():
            del callees
            assert "_command_lock" not in held and "_navigation_lock" not in held, (
                f"{method} takes _agent_lock while holding {sorted(held)}"
            )


# ================================================ 2. the doors take the lock
@pytest.mark.parametrize("door", AGENT_LOCK_DOORS)
def test_each_motion_door_holds_the_agent_lock_across_its_whole_body(
    scan: LockOrderScan, door: str
) -> None:
    """§Arch-1, closed and pinned. THE test the card's item 4 asks for."""

    assert scan.body_is_wholly_inside(door, "_agent_lock"), (
        f"{door} does not hold _agent_lock across its whole body — it mutates "
        "VoiceAgent state from the realtime pump thread. See "
        "_realtime_navigate's docstring for why narrowing is not enough."
    )


@pytest.mark.parametrize("door", AGENT_LOCK_DOORS)
def test_no_door_can_reenter_a_non_reentrant_agent_lock(
    scan: LockOrderScan, door: str
) -> None:
    """``_agent_lock`` is a plain ``Lock``: re-entry is a deadlock, not a race.

    The reachable set is seeded with ``_accept_plan`` and the two other runtime
    callbacks the agent invokes during ``_admit_local_sketch``, because those
    run inside the door's critical section even though the AST sees them as
    unreachable from it.
    """

    reachable = set(scan.methods_reachable(door))
    for bridge in (
        "_accept_plan",
        "_build_brain_snapshot",
        "_materialize_brain_planner_output",
    ):
        reachable |= set(scan.methods_reachable(bridge))
    offenders = sorted(reachable & AGENT_LOCK_ENTRY_POINTS)
    assert offenders == [], (
        f"{door} can reach {offenders} while holding the non-reentrant "
        "_agent_lock — that is a self-deadlock, not a race"
    )


# ================================== 3. compound realtime state takes _lock
def test_every_compound_realtime_write_holds_the_lock(scan: LockOrderScan) -> None:
    """Card item 3. ``__init__`` is exempt: nothing else exists yet."""

    offenders: list[str] = []
    for method, held, node in scan.stores:
        if method == "__init__":
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "self"):
            continue
        if node.attr not in COMPOUND_REALTIME_FIELDS:
            continue
        if "_lock" not in held:
            offenders.append(f"{method}:{node.lineno} writes self.{node.attr}")
    assert offenders == [], (
        "compound realtime state written outside _lock — its readers "
        "(realtime_snapshot, _whisperer_digest, _claim_orbit_terminal, "
        "_claim_narratable_activity) all take it:\n  " + "\n  ".join(offenders)
    )


def test_every_compound_realtime_read_holds_the_lock(scan: LockOrderScan) -> None:
    """A write-side-only fix is half a fix — pin the READ side, per site.

    Seed S13 is why this is a per-site check on the READ itself rather than
    "does the reading method reach ``_lock`` somewhere". ``realtime_snapshot``
    calls ``session_evidence_snapshot()`` and ``_realtime_pump_snapshot()``,
    both of which take ``_lock``, so a reachability question answers "yes" even
    with the compound read left bare — exactly the defect the audit found. The
    seed moved the read outside the lock, the reachability version stayed
    GREEN, and this replaced it.
    """

    offenders: list[str] = []
    for method, held, node in scan.loads:
        if method == "__init__":
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "self"):
            continue
        if node.attr not in COMPOUND_REALTIME_FIELDS:
            continue
        if "_lock" not in held:
            offenders.append(f"{method}:{node.lineno} reads self.{node.attr}")
    assert offenders == [], (
        "compound realtime state read outside _lock — the panel thread can "
        "observe a value the whisperer has already cleared, or a route record "
        "caught mid-replacement:\n  " + "\n  ".join(offenders)
    )
    # The scanner must actually be looking at something.
    covered = {
        node.attr
        for method, _held, node in scan.loads
        if method != "__init__"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in COMPOUND_REALTIME_FIELDS
    }
    assert covered >= {
        "_realtime_pace_intent",
        "_realtime_last_route",
        "_narratable_orbit",
        "_narratable_activity",
        "_realtime_turn_sequence",
    }, f"the read scan matched only {sorted(covered)}"


def test_the_pace_declaration_is_written_as_one_section(scan: LockOrderScan) -> None:
    """``pace_intent`` and its ``_at_s`` stamp are cleared as a pair; write as one.

    Two separate ``with self._lock:`` blocks would let the whisperer observe a
    pace with no timestamp, which is the state its window arithmetic treats as
    "declared infinitely long ago".
    """

    follow = scan.methods["_realtime_follow"]
    sections = [
        node
        for node in ast.walk(follow)
        if isinstance(node, ast.With)
        and any(scan._lock_of(item) == "_lock" for item in node.items)
    ]
    assert len(sections) == 1, "the follow door takes _lock more than once"
    written = {
        target.attr
        for node in ast.walk(sections[0])
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert {
        "_realtime_pace_intent",
        "_realtime_pace_intent_at_s",
        "_realtime_last_pace",
    } <= written


# ====================================== 4. the navigator's entry points
def test_every_navigator_mutation_in_runtime_holds_the_navigation_lock(
    scan: LockOrderScan,
) -> None:
    """The three sites the audit found protected, plus the one it found open."""

    seen: set[tuple[str, str]] = set()
    offenders: list[str] = []
    for method, held, node in scan.calls:
        target = _call_target(node)
        if target not in NAVIGATOR_MUTATIONS:
            continue
        seen.add(target)
        if "_navigation_lock" not in held:
            offenders.append(
                f"{method}:{node.lineno} calls {target[0]}.{target[1]}() "
                f"holding {sorted(held) or 'nothing'}"
            )
    assert offenders == [], (
        "navigator mutated outside _navigation_lock while _step_navigation "
        "drives the same object under it:\n  " + "\n  ".join(offenders)
    )
    assert ("self.dog", "navigate") in seen, "the scanner matched no navigate() at all"


def test_the_navigation_channel_is_the_locked_adapter() -> None:
    """pause/resume are closed at the ADAPTER, so every caller is covered.

    Four callers reach them and two live outside ``runtime.py``
    (``BehaviorChannelRegistry.preempt`` is one). Wrapping call sites would
    leave the fifth one someone adds tomorrow open.
    """

    assert issubclass(_LockedNavigationChannel, NavigationChannel)
    for name in ("pause", "resume"):
        assert name in vars(_LockedNavigationChannel), (
            f"_LockedNavigationChannel no longer overrides {name}"
        )
    assert "stop" not in vars(_LockedNavigationChannel), (
        "stop() must NOT be overridden — it delegates to "
        "_stop_navigation_channel, which already takes _navigation_lock around "
        "dog.stop() and takes _lock on the way; wrapping it would add a "
        "_navigation_lock -> _lock order edge for no defect"
    )


def test_the_runtime_actually_registers_the_locked_adapter(
    stress_runtime: RobotRuntime,
) -> None:
    """Seed S8's answer: DEFINING the adapter is not INSTALLING it.

    The first version of this file asserted only that
    ``_LockedNavigationChannel`` overrode ``pause``/``resume``. S8 changed one
    word at the registration site — ``_LockedNavigationChannel(`` back to
    ``NavigationChannel(`` — reopening every navigator entry point at once, and
    that version stayed GREEN. So the check is now made against a LIVE runtime,
    and it does not stop at the type: it proves the lock is actually held
    while the navigator's pause and resume run, which is the property the card
    asked for and the only one a caller can rely on.
    """

    channel = stress_runtime._channels.get("navigation")
    assert isinstance(channel, _LockedNavigationChannel), (
        f"the navigation channel is a {type(channel).__name__}; "
        "_register_behavior_channels no longer installs the locked adapter and "
        "every navigator pause/resume path is lock-free again"
    )
    assert channel._nav_lock is stress_runtime._navigation_lock, (
        "the adapter holds some OTHER lock than the one _step_navigation takes"
    )

    # Now watch it. ``_navigation_lock`` is an RLock, so "held by this thread"
    # is asked by trying to take it from ANOTHER thread with a zero timeout.
    held_during: dict[str, bool] = {}

    def lock_is_free() -> bool:
        result: list[bool] = []

        def probe() -> None:
            got = stress_runtime._navigation_lock.acquire(blocking=False)
            if got:
                stress_runtime._navigation_lock.release()
            result.append(got)

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=10)
        return result[0] if result else True

    navigator = stress_runtime.dog.navigator
    real_pause, real_resume = navigator.pause, navigator.resume

    def watched_pause() -> None:
        held_during["pause"] = not lock_is_free()
        real_pause()

    def watched_resume() -> None:
        held_during["resume"] = not lock_is_free()
        real_resume()

    navigator.pause = watched_pause  # type: ignore[method-assign]
    navigator.resume = watched_resume  # type: ignore[method-assign]
    try:
        stress_runtime._observation = stress_runtime.backend.observe()
        stress_runtime.start_navigation("go to the sidewalk")
        stress_runtime.pause_navigation(reason="r24 adapter proof")
        stress_runtime._observation = stress_runtime.backend.observe()
        try:
            stress_runtime.resume_navigation()
        except RuntimeError:  # a rejected resume still proves nothing ran bare
            pass
    finally:
        navigator.pause = real_pause  # type: ignore[method-assign]
        navigator.resume = real_resume  # type: ignore[method-assign]

    assert held_during.get("pause") is True, (
        "navigator.pause() ran with _navigation_lock free "
        f"(observed: {held_during}) — the audit's minor finding is back"
    )
    assert held_during.get("resume") is True, (
        "navigator.resume() ran with _navigation_lock free "
        f"(observed: {held_during}) — the audit's minor finding is back"
    )


def test_the_reentry_callback_roster_is_complete(scan: LockOrderScan) -> None:
    """A new ``on_*=self.<method>`` is a new invisible edge. Name it first.

    Every entry here is a door out of a collaborator and straight back into the
    runtime, so a lock held across ``dog.stop()`` or ``motion.walk()`` is really
    held across the runtime method named here. ``motion.on_stop =
    self.stop_motion`` is the one that made the lock order cyclic before R24;
    the roster exists so the next one cannot arrive unnoticed.

    Lambdas are handled by the sibling test below, not ignored: the first draft
    of this file claimed there were two of them and that neither took a runtime
    lock. There are seven sites, and five reach ``_lock``. The claim was wrong
    before anyone relied on it, which is the argument for counting rather than
    asserting.
    """

    found: dict[str, tuple[str, tuple[str, ...]]] = {}
    for node in ast.walk(scan.methods["__init__"]):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg
                and keyword.arg.startswith("on_")
                and isinstance(keyword.value, ast.Attribute)
                and isinstance(keyword.value.value, ast.Name)
                and keyword.value.value.id == "self"
            ):
                handler = keyword.value.attr
                found[keyword.arg] = (
                    handler,
                    tuple(sorted(scan.locks_reachable(handler))),
                )
    assert found == REENTRY_CALLBACKS, (
        "RobotRuntime's re-entry callbacks changed.\n"
        f"  found:  {sorted(found.items())}\n"
        f"  roster: {sorted(REENTRY_CALLBACKS.items())}\n"
        "Each one is a lock-order edge no static call-graph walk can see. "
        "Work out which locks the new handler takes, decide whether any "
        "existing critical section spans a call that fires it, and then update "
        "REENTRY_CALLBACKS."
    )
    # The specific fact ``_stop_navigation_channel``'s R24 comment rests on.
    assert "_command_lock" in REENTRY_CALLBACKS["on_stop"][1], (
        "motion's on_stop handler no longer reaches _command_lock; the "
        "reasoning in _stop_navigation_channel's R24 comment is stale"
    )


def test_the_lambda_reentry_callbacks_reach_only_the_sink_lock(
    scan: LockOrderScan,
) -> None:
    """The other half of the re-entry surface, counted rather than assumed.

    ``on_*=lambda ...`` is the same door back into the runtime with no name to
    put in a table. All seven sites are safe today for one structural reason:
    the only runtime lock any of them reaches is ``_lock``, and ``_lock`` is a
    SINK in the order graph — no outgoing edges, so ``X → _lock`` cannot close
    a cycle for any X. A lambda that reached ``_command_lock`` or
    ``_navigation_lock`` would break that argument, and this is what says so.
    """

    found: dict[tuple[str, tuple[tuple[str, str], ...]], set[str]] = {}
    for node in ast.walk(ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if not (keyword.arg or "").startswith("on_"):
                continue
            if not isinstance(keyword.value, ast.Lambda):
                continue
            targets: set[tuple[str, str]] = set()
            for inner in ast.walk(keyword.value.body):
                target = _call_target(inner) if isinstance(inner, ast.Call) else None
                if target is not None:
                    targets.add(target)
            key = (str(keyword.arg), tuple(sorted(targets)))
            locks = found.setdefault(key, set())
            for receiver, method in targets:
                if receiver == "self":
                    locks |= set(scan.locks_reachable(method))

    assert {k: tuple(sorted(v)) for k, v in found.items()} == REENTRY_LAMBDAS, (
        "the lambda re-entry surface changed.\n"
        f"  found:  {sorted((k, tuple(sorted(v))) for k, v in found.items())}\n"
        f"  roster: {sorted(REENTRY_LAMBDAS.items())}"
    )
    outgoing = {inner for outer, inner in scan.edges() | CALLBACK_LOCK_ORDER if outer == "_lock"}
    assert outgoing == set(), (
        f"_lock is no longer a sink (it now precedes {sorted(outgoing)}), so "
        "'every lambda only reaches _lock' has stopped being a safety argument"
    )
    for (keyword, _targets), locks in REENTRY_LAMBDAS.items():
        assert set(locks) <= {"_lock"}, (
            f"the {keyword} lambda reaches {sorted(locks)}; a critical section "
            "spanning the collaborator call that fires it now needs review"
        )


def test_dog_calls_under_the_navigation_lock_cannot_invert_the_command_lock(
    scan: LockOrderScan,
) -> None:
    """THE REGRESSION GUARD for the cycle R24 found and closed.

    ``dog.stop()`` is not a leaf: it reaches ``motion.on_stop``, i.e.
    ``stop_motion``, i.e. ``_command_lock``. Held under ``_navigation_lock``
    with no ``_command_lock`` already in hand, that states
    ``_navigation_lock → _command_lock`` against the
    ``_command_lock → _navigation_lock`` that ``_start_navigation_locked`` and
    ``_step_navigation`` state — a two-lock cycle, reproduced as a real
    deadlock in R24_STATUS.md §4.1.

    "Under ``_command_lock``" is answered interprocedurally: the lock may be
    held by a caller (``_start_navigation_locked`` never takes it itself; every
    path in does).
    """

    must = scan.must_hold()
    offenders = []
    for method, held, node in scan.calls:
        target = _call_target(node)
        if target is None or target[0] != "self.dog" or "_navigation_lock" not in held:
            continue
        if target[1] not in {"stop", "emergency_stop"}:
            continue  # only the calls that reach an on_* re-entry hook
        if "_command_lock" not in (held | must[method]):
            offenders.append(f"{method}:{node.lineno} self.dog.{target[1]}()")
    assert offenders == [], (
        "dog.stop() held under _navigation_lock without _command_lock — it "
        "re-enters stop_motion, which takes _command_lock, and that closes a "
        "two-lock cycle against _start_navigation_locked:\n  "
        + "\n  ".join(offenders)
    )


def test_navigate_under_the_navigation_lock_never_publishes(
    scan: LockOrderScan,
) -> None:
    """The other half of the same hazard, pinned before someone flips a default.

    ``Dog.navigate`` walks the motion router — ``motion.walk()`` → ``on_command``
    → ``_voice_motion`` → ``_command_lock`` — but ONLY when ``publish=True``
    (``skills/api.py``: ``if publish and …``). Both runtime call sites pass
    ``publish=False``, and ``_step_navigation``'s cannot hold ``_command_lock``
    (it is the 10 Hz control tick; taking the command lock there would
    serialize the whole loop against every command). So the safety of that site
    rests entirely on ``publish=False``, and an invariant that load-bearing
    should be a test rather than a habit.
    """

    sites = [
        (method, node)
        for method, held, node in scan.calls
        if _call_target(node) == ("self.dog", "navigate") and "_navigation_lock" in held
    ]
    assert len(sites) == 2, f"expected 2 navigate() sites under the lock, found {len(sites)}"
    for method, node in sites:
        publish = [kw for kw in node.keywords if kw.arg == "publish"]
        assert publish, f"{method}:{node.lineno} dog.navigate() omits publish="
        value = publish[0].value
        assert isinstance(value, ast.Constant) and value.value is False, (
            f"{method}:{node.lineno} dog.navigate(publish=...) is not a literal "
            "False — a publishing navigate under _navigation_lock re-enters "
            "_command_lock through motion.walk/on_command and re-opens the "
            "cycle R24 closed"
        )


def test_no_path_to_the_channel_adapter_runs_under_the_state_lock(
    scan: LockOrderScan,
) -> None:
    """The property that makes the adapter override safe to add.

    Putting ``_navigation_lock`` inside ``pause``/``resume`` is only free of new
    ordering constraints if nothing calls them while holding ``_lock`` — that
    would state ``_lock → _navigation_lock``, and ``_command_lock`` already
    states the reverse-adjacent ``_command_lock → _navigation_lock`` /
    ``_command_lock → _lock``. Every reaching call site is enumerated here
    rather than argued: ``preempt`` reaches the adapter through
    ``BehaviorChannelRegistry``, which the AST cannot follow, so the call sites
    on THIS side of that boundary are what has to be checked.
    """

    reaching = {
        ("self", "preempt"),
        ("self", "_pause_channel"),
        ("self", "_resume_from_store"),
        ("self._channels", "preempt"),
        ("channel", "pause"),
        ("channel_obj", "resume"),
    }
    offenders = [
        f"{method}:{node.lineno} {'.'.join(_call_target(node) or ())}"
        for method, held, node in scan.calls
        if _call_target(node) in reaching and "_lock" in held
    ]
    assert offenders == [], (
        "a navigation pause/resume/preempt path runs under _lock, which would "
        "make the adapter's _navigation_lock an inner lock of _lock:\n  "
        + "\n  ".join(offenders)
    )


# ======================================= 5. the scanner can actually FAIL
#
# Every oracle above is shown able to redden on a seeded violation. Without
# these, a scanner that silently matched nothing would pass forever.
_SEED_CLEAN = '''
import threading

class RobotRuntime:
    def __init__(self):
        self._lock = threading.RLock()
        self._agent_lock = threading.Lock()
        self._navigation_lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._transcript_lock = threading.Lock()

    def _realtime_navigate(self, place):
        """Door."""
        with self._agent_lock:
            with self._lock:
                self._realtime_turn_sequence += 1
            return self._step()

    def _step(self):
        with self._navigation_lock:
            self.dog.navigate("x")

    def set_personality(self, pid):
        with self._agent_lock:
            with self._lock:
                self._personality = pid

    def handle_text(self, text):
        with self._agent_lock:
            return self.agent.handle_text(text)
'''


def _seeded(source: str) -> LockOrderScan:
    return LockOrderScan(source, locks=RUNTIME_LOCKS, class_name="RobotRuntime")


def _mutate(old: str, new: str) -> str:
    """Apply one seed edit to ``_SEED_CLEAN``, refusing to no-op silently.

    A ``str.replace`` whose anchor has drifted returns the original text, and
    the seed test then "passes" having proved nothing. This is the difference
    between a seeded-violation companion and a decoration.
    """

    assert _SEED_CLEAN.count(old) == 1, f"seed anchor is not unique: {old!r}"
    seeded = _SEED_CLEAN.replace(old, new)
    assert seeded != _SEED_CLEAN, "the seed edit changed nothing"
    return seeded


def test_seed_control_the_clean_fixture_passes_every_oracle() -> None:
    """The control arm: the seeds below differ from THIS by one edit each."""

    clean = _seeded(_SEED_CLEAN)
    assert clean.body_is_wholly_inside("_realtime_navigate", "_agent_lock")
    assert find_cycle(clean.edges()) is None
    offenders = [
        node.attr
        for method, held, node in clean.stores
        if method != "__init__"
        and node.attr in COMPOUND_REALTIME_FIELDS
        and "_lock" not in held
    ]
    assert offenders == []


def test_seed_a_door_without_its_lock_reddens() -> None:
    source = _mutate(
        '        """Door."""\n        with self._agent_lock:\n',
        '        """Door."""\n        if True:\n',
    )
    assert not _seeded(source).body_is_wholly_inside("_realtime_navigate", "_agent_lock")


def test_seed_a_door_with_a_prologue_outside_the_lock_reddens() -> None:
    """Narrowing the section to "just the mutation" must not read as compliant."""

    source = _mutate(
        '        """Door."""\n        with self._agent_lock:\n',
        '        """Door."""\n        place = str(place)\n        with self._agent_lock:\n',
    )
    assert not _seeded(source).body_is_wholly_inside("_realtime_navigate", "_agent_lock")


def test_seed_an_inverted_order_is_found_as_a_cycle() -> None:
    source = _mutate(
        "    def set_personality(self, pid):\n        with self._agent_lock:\n"
        "            with self._lock:\n                self._personality = pid\n",
        "    def set_personality(self, pid):\n        with self._lock:\n"
        "            with self._agent_lock:\n                self._personality = pid\n",
    )
    edges = _seeded(source).edges()
    assert ("_lock", "_agent_lock") in edges
    cycle = find_cycle(edges)
    assert cycle is not None, "an inverted acquisition did not show up as a cycle"
    assert set(cycle) == {"_lock", "_agent_lock"}


def test_seed_a_compound_write_moved_outside_the_lock_reddens() -> None:
    source = _mutate(
        "            with self._lock:\n                self._realtime_turn_sequence += 1\n",
        "            self._realtime_turn_sequence += 1\n",
    )
    offenders = [
        node.attr
        for method, held, node in _seeded(source).stores
        if method != "__init__"
        and node.attr in COMPOUND_REALTIME_FIELDS
        and "_lock" not in held
    ]
    assert offenders == ["_realtime_turn_sequence"]


def test_seed_a_navigator_call_outside_the_lock_reddens() -> None:
    source = _mutate(
        "        with self._navigation_lock:\n            self.dog.navigate(\"x\")\n",
        "        self.dog.navigate(\"x\")\n",
    )
    offenders = [
        _call_target(node)
        for _method, held, node in _seeded(source).calls
        if _call_target(node) in NAVIGATOR_MUTATIONS and "_navigation_lock" not in held
    ]
    assert offenders == [("self.dog", "navigate")]


def test_seed_reentry_into_a_typed_turn_is_found() -> None:
    source = _mutate(
        "    def _step(self):\n",
        "    def _step(self):\n        self.handle_text('x')\n",
    )
    scan = _seeded(source)
    assert AGENT_LOCK_ENTRY_POINTS & scan.methods_reachable("_realtime_navigate") == {
        "handle_text"
    }


# ============================================ 6. live concurrency evidence
class _StressBackend:
    """A visible owner and a fresh timestamp — both doors refuse without them."""

    name = "r24-stress"

    def __init__(self) -> None:
        self.x = 0.0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=self.x),
            owner=OwnerTrack(x=2.0, y=0.0, visible=True, confidence=0.95),
            nearest_obstacle_m=10.0,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

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
        del tools, context, transcript
        return AgentDecision("Understood.")


class _LockOrderObserver:
    """Wraps a real lock and records the order threads actually acquire in.

    This is the layer the AST cannot be: it sees ``_agent_lock`` →
    ``_command_lock`` through the agent's ``plan_publisher`` callback, because
    it watches the acquisition rather than reading the source.
    """

    def __init__(self, name: str, inner, state: _ObserverState) -> None:
        self._name = name
        self._inner = inner
        self._state = state

    def acquire(self, *args, **kwargs):  # pragma: no cover - exercised via `with`
        got = self._inner.acquire(*args, **kwargs)
        if got:
            self._state.push(self._name)
        return got

    def release(self) -> None:  # pragma: no cover - exercised via `with`
        self._state.pop(self._name)
        self._inner.release()

    def __enter__(self):
        self._inner.acquire()
        self._state.push(self._name)
        return self

    def __exit__(self, *exc) -> None:
        self._state.pop(self._name)
        self._inner.release()


class _ObserverState:
    def __init__(self) -> None:
        self._held = threading.local()
        self._guard = threading.Lock()
        self.edges: set[tuple[str, str]] = set()
        self.acquisitions = 0
        self.reentrant = 0

    def _stack(self) -> list[str]:
        stack = getattr(self._held, "stack", None)
        if stack is None:
            stack = []
            self._held.stack = stack
        return stack

    def push(self, name: str) -> None:
        stack = self._stack()
        # A RE-ENTRANT acquisition (this thread already holds ``name``) can
        # never block, so it states no ordering constraint and must not be
        # recorded as an edge. Recording it would report the R24 fix in
        # ``_stop_navigation_channel`` — ``_command_lock`` outside,
        # ``_navigation_lock`` inside, ``stop_motion`` re-entering
        # ``_command_lock`` — as the very cycle that fix removes.
        reentrant = name in stack
        with self._guard:
            self.acquisitions += 1
            if reentrant:
                self.reentrant += 1
            else:
                for outer in stack:
                    if outer != name:
                        self.edges.add((outer, name))
        stack.append(name)

    def pop(self, name: str) -> None:
        stack = self._stack()
        for index in range(len(stack) - 1, -1, -1):
            if stack[index] == name:
                del stack[index]
                return


@pytest.fixture()
def stress_runtime(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    # The lane is enabled in TEXT mode and no credential is needed: without a
    # constructed lane ``realtime_snapshot()`` returns the four-key "not
    # enabled" dict and this whole test would pass vacuously, never having read
    # ``last_route`` at all.
    lane_config = tmp_path / "realtime.yaml"
    lane_config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(lane_config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    path = tmp_path / "r24.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    runtime = RobotRuntime(
        path,
        _StressBackend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r24 stress fixture",
        ),
        **commissioned_runtime_kwargs(path),
    )
    authorize_commissioned_voice_binding(runtime)
    runtime._observation = runtime.backend.observe()
    assert runtime.realtime_snapshot().get("constructed") is True, (
        "the lane did not construct — realtime_snapshot would not carry "
        "last_route and the contention test would prove nothing"
    )
    try:
        yield runtime
    finally:
        runtime.close()


#: Iterations per door thread. Small ON PURPOSE: the reader threads run with no
#: sleep at all, and a contended lock in CPython costs the waiter a full GIL
#: switch interval, so 25 × 2 door admissions buy hundreds of thousands of
#: panel snapshots and millions of claim cycles against them (measured: 438,329
#: snapshots / 12,930,363 claims for 50 × 2 admissions in 11.3 s on this
#: machine). Interleaving, not throughput, is what makes this evidence.
#:
#: EVERY ASSERTION BELOW IS LOAD-INSENSITIVE. The audit (§Tests) names
#: load-sensitive wall-clock tests inside the hard gate as an unowned defect;
#: this file adds none. Nothing asserts a duration, the join timeouts are
#: deadlock detectors set two orders of magnitude above the measured runtime,
#: and the one count-based floor (50 panel reads) is four orders of magnitude
#: below what the slowest observed run produced.
STRESS_ITERATIONS = 25


def test_doors_and_the_panel_snapshot_under_contention(
    stress_runtime: RobotRuntime,
) -> None:
    """CONCURRENCY EVIDENCE, not a unit test.

    Two "pump" threads hammer the doors while a "panel" thread reads
    ``realtime_snapshot()`` and a "control" thread claims narration marks — the
    exact three-way cross-thread contact §Arch-1 describes. Three properties:

    * **no hosted turn id is issued twice.** Measured at the SOURCE by wrapping
      ``_next_realtime_turn_sequence``, not by reading the shared
      ``last_route`` afterwards — that read is itself racy and would report
      duplicates that the counter never issued;
    * every ``last_route`` the panel observes is INTERNALLY CONSISTENT (rule,
      directive and turn id describe one routing decision). The five fields
      were always assigned as one dict, but ``realtime_snapshot`` read them
      with no lock at all, so the read could straddle a replacement;
    * no thread raises, and both door threads finish.

    HONEST LIMIT (``does_not_prove``): a passing run does not prove the races
    are impossible — it is a shake-out, and it does not reproduce the pre-fix
    failure either (see R24_STATUS.md §4 for what the seeds do and do not show
    here). The structural claims are the static and observed ORDER graphs; this
    is their empirical companion, and it is the layer that would catch a
    deadlock the graphs cannot predict.
    """

    runtime = stress_runtime
    errors: list[BaseException] = []
    snapshots: list[dict] = []
    stop = threading.Event()
    issued: list[int] = []
    issued_guard = threading.Lock()

    # Record what the counter actually HANDED OUT. Wrapping the bound method
    # leaves the lock discipline it is being asked about entirely intact.
    real_next = runtime._next_realtime_turn_sequence

    def counting_next() -> int:
        value = real_next()
        with issued_guard:
            issued.append(value)
        return value

    runtime._next_realtime_turn_sequence = counting_next  # type: ignore[method-assign]

    def pump(pace: str) -> None:
        try:
            for _ in range(STRESS_ITERATIONS):
                try:
                    runtime._realtime_follow(pace)
                except (RuntimeError, ValueError):
                    # A refusal is a legitimate outcome (plan admission may
                    # decline); a CRASH is not. Only the latter fails this test.
                    pass
        except BaseException as error:  # noqa: BLE001 - the test IS the reporter
            errors.append(error)

    def panel() -> None:
        try:
            while not stop.is_set():
                snapshots.append(runtime.realtime_snapshot())
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    def control() -> None:
        try:
            while not stop.is_set():
                runtime._claim_narratable_activity("paw_wave")
                runtime._claim_orbit_terminal(
                    {"intent": {"behavior": "orbit_owner"}},
                    completed=True,
                    reason="finished",
                )
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    started = time.monotonic()
    workers = [
        threading.Thread(target=pump, args=("run",), name="pump-a"),
        threading.Thread(target=pump, args=("walk",), name="pump-b"),
        threading.Thread(target=panel, name="panel", daemon=True),
        threading.Thread(target=control, name="control", daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers[:2]:
        worker.join(timeout=300)
    stop.set()
    for worker in workers[2:]:
        worker.join(timeout=30)
    elapsed = time.monotonic() - started

    assert errors == [], f"a thread raised under contention: {errors[:3]!r}"
    assert not any(worker.is_alive() for worker in workers[:2]), (
        f"a door thread did not finish in 300 s — deadlock (elapsed {elapsed:.1f}s)"
    )
    assert len(snapshots) > 50, (
        f"the panel thread only managed {len(snapshots)} reads; not enough "
        "contention for this to be evidence of anything"
    )

    assert len(issued) == 2 * STRESS_ITERATIONS, (
        f"expected {2 * STRESS_ITERATIONS} turn ids, counted {len(issued)}"
    )
    duplicates = len(issued) - len(set(issued))
    assert duplicates == 0, (
        f"{duplicates} duplicated hosted turn id(s) out of {len(issued)} — two "
        "admissions could answer each other (_realtime_turn_sequence lost an "
        "increment)"
    )
    assert sorted(issued) == list(range(1, len(issued) + 1)), (
        "the hosted turn counter skipped or repeated a value: "
        f"{sorted(issued)[:8]} …"
    )

    torn = [
        row
        for row in snapshots
        if isinstance(row.get("last_route"), dict)
        and not (
            row["last_route"]["rule"] == "follow_owner"
            and row["last_route"]["directive"] == "follow me"
            and str(row["last_route"]["turn_id"]).startswith("turn-realtime-")
            and set(row["last_route"]) == {
                "turn_id",
                "route",
                "rule",
                "directive",
                "router_version",
            }
        )
    ]
    assert torn == [], f"the panel observed a torn route record: {torn[:2]}"


def test_the_observed_lock_order_is_acyclic(stress_runtime: RobotRuntime) -> None:
    """The order graph, re-verified from REAL acquisitions under contention.

    This is the layer that sees the callback edges the AST cannot — the door's
    ``_agent_lock`` reaching ``_command_lock`` through the agent's
    ``plan_publisher`` — and it is the one the card asks for: "a
    re-verification that the lock ORDER graph is still acyclic" after the
    change. It watches ACQUISITIONS, so a callback, a lambda or a C-level
    caller is all the same to it.
    """

    runtime = stress_runtime
    state = _ObserverState()
    for name in RUNTIME_LOCKS:
        setattr(runtime, name, _LockOrderObserver(name, getattr(runtime, name), state))

    errors: list[BaseException] = []

    def pump(pace: str) -> None:
        """The hosted doors: both siblings, so both critical sections run."""

        try:
            for _ in range(40):
                for door, arg in (
                    (runtime._realtime_follow, pace),
                    (runtime._realtime_navigate, "the sidewalk"),
                ):
                    try:
                        door(arg)
                    except (RuntimeError, ValueError):
                        pass
                runtime.realtime_snapshot()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    def typed() -> None:
        """The panel/typed side: ``_agent_lock`` from the other direction, plus
        every navigator entry point R24 touched."""

        try:
            for index in range(40):
                runtime.handle_text(f"hello {index}")
                try:
                    runtime.start_navigation("go to the sidewalk")
                except (RuntimeError, ValueError):
                    pass
                runtime.pause_navigation(reason="r24 stress")
                try:
                    runtime.resume_navigation()
                except RuntimeError:
                    pass
                runtime.stop_navigation()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    workers = [
        threading.Thread(target=pump, args=("run",), name="obs-pump"),
        threading.Thread(target=typed, name="obs-typed"),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=300)

    assert errors == [], f"a thread raised while observed: {errors[:3]!r}"
    assert not any(worker.is_alive() for worker in workers), "deadlock under observation"
    assert state.acquisitions > 500, (
        f"only {state.acquisitions} lock acquisitions observed — too few to "
        "call this a verification"
    )
    # A run that observed no NESTING observed nothing about ORDER. Without this
    # floor the acyclicity assertion below would pass on an empty graph.
    assert len(state.edges) >= 3, (
        f"only {sorted(state.edges)} nested acquisitions seen — the workload "
        "never exercised the ordering this test exists to verify"
    )
    for lock in ("_agent_lock", "_command_lock", "_navigation_lock", "_lock"):
        assert any(lock in edge for edge in state.edges), (
            f"{lock} never appeared in a nested acquisition; the workload does "
            "not cover it"
        )
    cycle = find_cycle(state.edges)
    assert cycle is None, (
        "the OBSERVED lock order is not a DAG: " + " -> ".join(cycle or [])
    )
    unexpected = state.edges - PINNED_LOCK_ORDER - CALLBACK_LOCK_ORDER
    assert unexpected == set(), (
        "live threads took a lock order this file does not document: "
        f"{sorted(unexpected)}"
    )
