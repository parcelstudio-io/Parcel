"""LIT-1 — the well-instrumented loop: sim + runtime + Model B + Realtime voice.

Evidence tier: ``desktop-sim`` for the body/plan hops (MuJoCo static city driven
through the live ``RobotRuntime.handle_text`` product path), ``fake`` for the
scripted-lane voice hops, ``hosted`` for live hosted rows (through the ear
governor, inside the wave's $5 cap shared with MB-1).  Physical motion: NO-GO.

WHAT THIS FILE IS
-----------------
One process that

1. starts the MuJoCo **static city** on a unique short socket under
   ``~/.cache/parcel-0e/lit1/`` inside a ``systemd-run --user --scope``
   (``MemoryMax=12G``, ``MemorySwapMax=0``) and kills its own process group on
   every exit path (amendment **L3**);
2. builds the runtime exactly the way ``tests/test_voice_nav_e2e.py::_LiveRuntime``
   does (``PARCEL_MEMORY_PATH`` → scratch, ``configs/robot.yaml`` copied to a
   scratch file, ``commissioned_runtime_kwargs``, ``build_runtime``,
   ``runtime.start()``).  The test module is never imported;
3. attaches **Model B** — a plan-queue whisper built from executive receipts —
   as the context source for a Realtime lane, injected through the *unbilled
   tail conversation-item seam* with its own purpose tag, replace-not-append
   (amendment **L1**);
4. runs a scripted owner timeline in which **motion authority is always local**
   (``runtime.handle_text``) and the hosted/fake lane receives the same sentence
   for NARRATION only (amendment **L6**);
5. writes ONE JSONL with a monotonic timestamp and a ``provenance`` column
   (``sim | fake | real | hosted``) for every hop (amendment **L10**).

``replay.py`` renders a JSONL into a self-contained HTML timeline.

WHAT IT IS NOT
--------------
No audio hardware is opened (``/dev/bus/usb`` is never touched — the XVF3800 is
the owner's live ear, amendment **L5**), no VLM is called from a runtime
callback, and the held-out scene is never named: every place name that reaches
the JSONL, the lane or the HTML comes from a **positive allowlist** built from
the scenario's alias table plus the scene's own landmark vocabulary
(amendment **L4**).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _extra in (str(REPO), str(REPO / "tests")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

# ---------------------------------------------------------------------------
# Peer modules (READ-ONLY, imported BY PATH, may be absent).
#
# NAV-INT-1's ``harness.py`` already is the ``_LiveRuntime`` pattern plus a
# 20 Hz sampler; re-deriving it here would be a second copy of the same code
# with a second set of teardown bugs.  When it is absent LIT-1 falls back to its
# own minimal session (``_own_session.py`` is not shipped — the run records
# ``harness=missing`` and refuses, because a hand-rolled second sim launcher is
# exactly the orphan risk amendment L3 exists to prevent).
# ---------------------------------------------------------------------------
_NI1 = REPO / "research" / "20260829" / "nav-interrupt-1"
_MB1 = REPO / "research" / "20260829" / "model-b-narration-1"


def _load_by_path(name: str, path: Path):
    """Import a peer executor's module by path without touching ``sys.path``."""

    import importlib.util

    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001 - a peer's half-written file
        sys.stderr.write(f"[lit1] peer module {path.name} failed to import: {error}\n")
        return None
    return module


ni1_harness = _load_by_path("lit1_ni1_harness", _NI1 / "harness.py")
ni1_queue_policy = _load_by_path("lit1_ni1_queue_policy", _NI1 / "queue_policy.py")
mb1_steer = _load_by_path("lit1_mb1_steer", _MB1 / "steer.py")
mb1_narrate = _load_by_path("lit1_mb1_narrate", _MB1 / "narrate.py")

#: Which implementation actually ran, reported verbatim in RESULTS.md.
PROVIDERS: dict[str, str] = {
    "session": "nav-interrupt-1/harness.py::LiveSession" if ni1_harness else "MISSING",
    "steering_rule": (
        "model-b-narration-1/steer.py" if mb1_steer else "sim-loop-1 (LIT-1 own, labelled)"
    ),
    "narration": (
        "model-b-narration-1/narrate.py" if mb1_narrate else "sim-loop-1 (LIT-1 own, labelled)"
    ),
    "queue_policy": (
        "nav-interrupt-1/queue_policy.py" if ni1_queue_policy else "sim-loop-1 (LIT-1 own)"
    ),
}

from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    handshake,
    response_done,
    transcript_delta,
    transcript_done,
)
from parcel_robot.realtime.transport import transport_pair

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

WORKROOT = Path(os.path.expanduser("~/.cache/parcel-0e/lit1"))
WAVE_LEDGER = Path(os.path.expanduser("~/.cache/parcel-0e/wave20260829/spend.jsonl"))
MB1_REALTIME_CONFIG = Path(os.path.expanduser("~/.cache/parcel-0e/mb1/realtime.yaml"))
MB1_ROBOT_CONFIG = Path(os.path.expanduser("~/.cache/parcel-0e/mb1/robot.yaml"))
FORBIDDEN_SOCKET = "/tmp/parcel_sim.sock"

PROV_SIM = "sim"
PROV_FAKE = "fake"
PROV_REAL = "real"
PROV_HOSTED = "hosted"
PROV_HARNESS = "harness"

#: The wave's shared fact vocabulary (README "Registered after the design
#: review" → Shared vocabulary).  Model B narrates only from these.
FACTS = ("accepted", "running", "blocked", "completed", "failed", "cancelled", "resumed")

#: L1 — the whisper's own purpose tag, distinct from the lane's four
#: (``memory tail`` / ``owner turn`` / ``action report`` / ``narration``), so a
#: refusal names the whisper and the billed narration path stays separate.
ITEM_PURPOSE_PLAN_QUEUE = "lit1 plan queue"

#: L9 — "starts turning" = heading error to the new goal decreasing for >= 3
#: consecutive 100 ms samples with |vyaw| > 0.1 rad/s.
TURN_VYAW_MIN = 0.1
TURN_CONSECUTIVE = 3
TURN_SAMPLE_MS = 100.0

#: L9 — the latency instrument's window around the cue.
CUE_WINDOW_BEFORE_S = 2.0
CUE_WINDOW_AFTER_S = 10.0

#: How long the scripted owner is modelled as TAKING to say a sentence.
#: L9 defines speech end as ``handle_text`` entry for a text turn, which leaves
#: speech START undefined — and with start == end the "was the body moving while
#: the owner was speaking" row has a zero-width window and no samples in it.
#: So the harness holds the sentence for a scripted duration before it enters
#: ``handle_text``: ~2.9 words/second, floored at 0.8 s and capped at 6 s.  It
#: is a MODEL of an owner talking, labelled as one, and it is the only place in
#: this file where the harness deliberately waits.
SPEECH_WORDS_PER_S = 2.9
SPEECH_MIN_S = 0.8
SPEECH_MAX_S = 6.0


def speech_duration_s(text: str) -> float:
    words = len(str(text).split())
    return max(SPEECH_MIN_S, min(SPEECH_MAX_S, words / SPEECH_WORDS_PER_S))

#: L10 — the swap table: which hop is faked today and what replaces it.
SWAP_TABLE = (
    ("mic", "fake: text on the scripted timeline", "real: XVF3800 array + ASR"),
    ("voice", "fake: FakeRealtimeServer scripted turns", "hosted: OpenAI Realtime lane"),
    ("body lane", "sim: MuJoCo velocity commands", "real: gateway protocol v1 fake gateway"),
    ("sensors", "sim: MuJoCo static city observations", "real: D455 + Mid-360"),
    ("world", "sim: demo city", "real: the owner's room"),
)


# ===========================================================================
# 1. the JSONL log — one row per hop, monotonic, provenance-stamped
# ===========================================================================


class HopLog:
    """One append-only JSONL, one monotonic clock, one provenance column.

    ``t`` is seconds since the loop's own ``t0`` (three decimals, ~1 ms), taken
    from ``time.monotonic()`` so a wall-clock step cannot reorder the timeline.
    ``t_wall`` is written once, in the header, so a reader can place the run in
    the day without every row carrying a clock that can jump.
    """

    def __init__(self, path: Path, *, t0: float, guard: NameScan) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self._t0 = t0
        self._lock = threading.Lock()
        self._guard = guard
        self.rows = 0
        self.leaks: list[dict] = []

    def now(self) -> float:
        return time.monotonic() - self._t0

    def write(self, hop: str, provenance: str, **fields: Any) -> dict:
        row = {"t": round(self.now(), 3), "hop": hop, "provenance": provenance}
        row.update(fields)
        return self.write_row(row)

    #: Fields that CARRY the scanner's own findings.  Scanning them would make
    #: every leak report a second leak report, forever.
    _SCAN_EXEMPT = ("_name_scan", "name_scan_leaks")

    def write_row(self, row: dict) -> dict:
        row.setdefault("t", round(self.now(), 3))
        scannable = {k: v for k, v in row.items() if k not in self._SCAN_EXEMPT}
        leak = self._guard.scan(scannable)
        if leak:
            # NEVER silently drop the row: an unadmitted name in the log is a
            # finding, and hiding it would hide the finding.  The name is
            # replaced by its category and the violation is counted so
            # RESULTS.md can carry the number.
            exempt = {k: v for k, v in row.items() if k in self._SCAN_EXEMPT}
            row = self._guard.redact(scannable)
            row.update(exempt)
            row["_name_scan"] = leak
            self.leaks.append({"t": row.get("t"), "hop": row.get("hop"), "names": leak})
        with self._lock:
            self._fh.write(json.dumps(row, sort_keys=False, default=str) + "\n")
            self._fh.flush()
            self.rows += 1
        return row

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fh.close()


# ===========================================================================
# 2. the name scan — a POSITIVE allowlist (amendment L4)
# ===========================================================================


class NameScan:
    """Every place-shaped token that reaches the log must be on the allowlist.

    A negative blocklist would require this file to CONTAIN the held-out scene's
    name in order to look for it, which is the leak it is supposed to prevent.
    So the gate is positive: the allowlist is the scenario's stand-in names plus
    the demo city's own landmark vocabulary, and anything place-shaped that is
    not on it is redacted and counted.

    ``bind_runtime`` additionally records the runtime's own
    ``_curiosity_admitted_names()`` so RESULTS.md can say whether the product's
    admission gate agreed (on a fresh runtime the learned map is empty and the
    gate returns the empty set — that is reported as observed, not papered over).
    """

    #: The place-shaped vocabulary the scanner polices.  Anything here that is
    #: NOT in ``allowed`` is a leak.  Deliberately small and explicit.
    _PLACE_WORDS = (
        "door",
        "sofa",
        "couch",
        "lamppost",
        "lamp post",
        "bench",
        "tree",
        "planter",
        "building",
        "sidewalk",
        "crosswalk",
        "kitchen",
        "hallway",
        "bedroom",
        "office",
        "garage",
        "porch",
        "stairs",
    )
    #: DELIBERATELY NOT SCANNED: "table", "desk", "chair".  All three appear as
    #: ordinary values inside the navigator's own mission metadata (the arrival
    #: RELATION TABLE, for one), so scanning them redacts product telemetry
    #: without protecting anything: a scene name is a proper place, and these
    #: three are furniture nouns the product says about itself.  The guarantee
    #: this class actually offers is a POSITIVE allowlist over the vocabulary
    #: above — stated plainly here rather than implied.

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = {name.casefold() for name in allowed}
        self.runtime_admitted: frozenset[str] = frozenset()
        self.runtime_admitted_read = False

    def bind_runtime(self, runtime: object) -> None:
        getter = getattr(runtime, "_curiosity_admitted_names", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                self.runtime_admitted = frozenset(str(name) for name in getter())
                self.runtime_admitted_read = True

    def _offenders(self, text: str) -> list[str]:
        low = str(text).casefold()
        return [
            word
            for word in self._PLACE_WORDS
            if word not in self.allowed and word in low
        ]

    def scan(self, row: Any) -> list[str]:
        found: set[str] = set()
        for value in _walk_strings(row):
            found.update(self._offenders(value))
        return sorted(found)

    def redact(self, row: dict) -> dict:
        def _fix(value: Any) -> Any:
            if isinstance(value, str):
                out = value
                for word in self._offenders(value):
                    out = out.replace(word, "[unadmitted-place]")
                    out = out.replace(word.title(), "[unadmitted-place]")
                return out
            if isinstance(value, dict):
                return {key: _fix(item) for key, item in value.items()}
            if isinstance(value, list):
                return [_fix(item) for item in value]
            return value

        return _fix(row)  # type: ignore[return-value]


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


# ===========================================================================
# 3. the executive receipt tap (amendment L7)
# ===========================================================================

#: The receipt KINDS this experiment compares.  ``ReportDisposition.action`` and
#: ``ExecutiveSubmission.disposition`` are the executive's OWN vocabulary; the
#: two harness-authored kinds are labelled as such and never claimed as product
#: receipts.
KIND_SUBMIT = "submit"
KIND_REPLACE = "replace"
KIND_REISSUE = "re_issue"  # HARNESS: NAV-INT-1 N1, never the executive's word
KIND_CONFIRM = "confirm"  # HARNESS: LIT-1's minimal confirm rule


@dataclass
class Receipt:
    """One executive event, timestamped, with its verbatim fields."""

    t: float
    kind: str
    source: str  # "executive" | "harness"
    task_id: str
    action: str  # ReportDisposition.action / ExecutiveSubmission.disposition
    state: str
    plan_revision: int
    last_detail: str
    accepted: bool | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "kind": self.kind,
            "source": self.source,
            "task_id": self.task_id,
            "action": self.action,
            "state": self.state,
            "plan_revision": self.plan_revision,
            "last_detail": self.last_detail,
            "accepted": self.accepted,
            "note": self.note,
        }


class ExecutiveTap:
    """Wrap ONE runtime's ``TaskExecutive`` instance to record every receipt.

    Amendment L7 asks for ``ReportDisposition.action`` and ``last_detail``
    *verbatim*.  ``task_executive.snapshot()`` carries ``last_detail`` but not
    ``action`` — ``action`` only exists on the value ``report()`` /
    ``suspend_task()`` / ``resume_task()`` return — and the suspend that
    ``runtime._apply_goal_amend`` performs lives inside a locked transaction
    that a poller cannot see (NAV-INT-1 measured exactly that: the first live
    amendment showed one task going r1 → r2 with no observable suspended state).

    So the instrument is a per-instance method wrapper, not a poller.  It edits
    nothing in ``src/``: it rebinds attributes on the object this process built,
    and it is removed on ``detach``.  Every wrapper delegates first and records
    after, so a raising executive raises exactly as it did.
    """

    #: (method name, how to read a kind/action out of the return value)
    _WRAPPED = (
        "submit",
        "replace",
        "report",
        "request_interrupt",
        "suspend_task",
        "resume_task",
        "resume_task_running",
        "dispatch_failed",
        "cancel_all",
    )

    def __init__(self, executive: object, *, clock: Callable[[], float]) -> None:
        self._executive = executive
        self._clock = clock
        self._originals: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self.receipts: list[Receipt] = []
        self.on_receipt: Callable[[Receipt], None] | None = None

    # -- lifecycle ---------------------------------------------------------
    def attach(self) -> None:
        for name in self._WRAPPED:
            original = getattr(self._executive, name, None)
            if original is None:
                continue
            self._originals[name] = original
            setattr(self._executive, name, self._wrap(name, original))

    def detach(self) -> None:
        for name, original in self._originals.items():
            with contextlib.suppress(Exception):
                setattr(self._executive, name, original)
        self._originals.clear()

    # -- the wrapper -------------------------------------------------------
    def _wrap(self, name: str, original: Callable) -> Callable:
        def _tapped(*args: object, **kwargs: object):
            outcome = original(*args, **kwargs)
            with contextlib.suppress(Exception):
                self._record(name, outcome)
            return outcome

        return _tapped

    def _snapshot_row(self, task_id: str) -> dict:
        """The task's own row, read from the executive's unwrapped ``snapshot``.

        ``snapshot`` is deliberately NOT one of the wrapped methods — wrapping a
        read that the sampler calls twenty times a second would put a receipt in
        the log for every poll — so this is a plain call.
        """

        with contextlib.suppress(Exception):
            rows = self._executive.snapshot().get("tasks", [])  # type: ignore[attr-defined]
            for row in rows:
                if isinstance(row, dict) and row.get("task_id") == task_id:
                    return row
        return {}

    def _record(self, method: str, outcome: object) -> None:
        task_id = str(getattr(outcome, "task_id", "") or "")
        if not task_id:
            # ``InterruptDecision`` names its tasks ``affected_task_ids`` and has
            # no ``task_id`` at all.  Missing that is how the first draft of this
            # instrument dropped the suspend half of every amendment on the
            # floor: ``runtime._suspend_for_amendment`` does not call
            # ``suspend_task`` — it calls ``request_interrupt(interrupt_now)``
            # and reads ``action == "suspend"`` off the decision.
            affected = getattr(outcome, "affected_task_ids", ()) or ()
            if affected:
                task_id = str(affected[0])
        action = str(
            getattr(outcome, "action", None)
            or getattr(outcome, "disposition", None)
            or method
        )
        accepted = getattr(outcome, "accepted", None)
        if accepted is None:
            accepted = getattr(outcome, "admitted", None)
        row = self._snapshot_row(task_id) if task_id else {}
        kind = _kind_for(method, action, str(row.get("last_detail") or ""))
        receipt = Receipt(
            t=self._clock(),
            kind=kind,
            source="executive",
            task_id=task_id,
            action=action,
            state=str(row.get("state") or getattr(outcome, "state", "") or ""),
            plan_revision=int(
                row.get("plan_revision")
                if isinstance(row.get("plan_revision"), int)
                else (getattr(outcome, "plan_revision", 0) or 0)
            ),
            last_detail=str(row.get("last_detail") or ""),
            accepted=None if accepted is None else bool(accepted),
            note=method,
        )
        # ``report`` fires on every step of every task at ~10 Hz.  Only the
        # transitions are receipts; ``progress_recorded`` is not one.
        if method == "report" and action in {"progress_recorded", "ignored_unknown_task"}:
            return
        if method in {"request_interrupt", "cancel_all"} and not task_id:
            return
        with self._lock:
            self.receipts.append(receipt)
        if self.on_receipt is not None:
            with contextlib.suppress(Exception):
                self.on_receipt(receipt)

    def snapshot(self) -> list[Receipt]:
        with self._lock:
            return list(self.receipts)


def _kind_for(method: str, action: str, last_detail: str) -> str:
    """Map one executive event to the KIND sequence vocabulary of L7."""

    if method == "submit":
        return KIND_SUBMIT
    if method == "replace":
        if last_detail == "replacement_activated":
            return "replacement_activated"
        if last_detail.startswith("replacement_waiting"):
            return "replacement_deferred"
        return KIND_REPLACE
    if method == "suspend_task":
        return "task_suspended"
    if method in {"resume_task", "resume_task_running"}:
        return "task_resumed"
    if method == "request_interrupt":
        # The executive's own words for what the interrupt did.  ``suspend`` is
        # the amendment's suspend receipt (L7's ``task_suspended``); the others
        # keep the executive's vocabulary with an ``interrupt:`` qualifier so a
        # deferral is never read as a cancellation.
        if action == "suspend":
            return "task_suspended"
        if action == "cancel_now":
            return "task_cancelled"
        if action == "defer_to_checkpoint":
            return "cancelled_at_checkpoint"
        return f"interrupt:{action}"
    if method == "cancel_all":
        return "cancel_all"
    if method == "dispatch_failed":
        return "dispatch_failed"
    # report(): action is already the executive's own word.
    if action == "task_succeeded":
        return "task_succeeded"
    if action == "task_failed":
        return "task_failed"
    if action == "task_cancelled":
        if last_detail.startswith("cancelled") or "checkpoint" in last_detail:
            return "cancelled_at_checkpoint"
        return "task_cancelled"
    if action == "step_succeeded":
        return "step_succeeded"
    if action == "replacement_activated":
        return "replacement_activated"
    return action


#: Receipt kinds that are STRUCTURAL for H-LIT1a's equality test.  Step-level
#: chatter (``step_succeeded``) is logged but is not part of the compared
#: sequence: a route with one more waypoint is not a different plan shape.
SEQUENCE_KINDS = frozenset(
    {
        KIND_SUBMIT,
        KIND_REPLACE,
        "replacement_activated",
        "replacement_deferred",
        "task_suspended",
        "task_resumed",
        "task_succeeded",
        "task_failed",
        "task_cancelled",
        "cancelled_at_checkpoint",
        KIND_REISSUE,
        KIND_CONFIRM,
    }
)


# ===========================================================================
# 4. Model B — the plan queue + the whisper (LIT-1's own, LABELLED)
# ===========================================================================


@dataclass
class QueueRecord:
    """The wave's shared queue-record schema (README → Shared vocabulary)."""

    directive_text: str
    grounded_goal: str
    originating_task_id: str
    admitted_at: float
    status: str  # one of FACTS

    def as_dict(self) -> dict:
        return {
            "directive_text": self.directive_text,
            "grounded_goal": self.grounded_goal,
            "originating_task_id": self.originating_task_id,
            "admitted_at": round(self.admitted_at, 3),
            "status": self.status,
        }


#: LIT-1's own minimal confirm→re-issue rule, shipped because
#: ``model-b-narration-1/steer.py`` does not exist at run time.  LABELLED as
#: harness logic; it is not a product seam and gains no authority.
#:
#: N1 (NAV-INT-1, binding): the shipped stack has no resume for a displaced
#: goal — ``runtime._apply_goal_amend`` parks the amendable work as a
#: ``ResumeIntent`` and ``_close_amendment_window("committed")`` CONSUMES it.
#: So "resume the door goal" is a RE-ISSUE of the remembered directive TEXT
#: through ``handle_text``.
#:
#: L7 (binding): the closed-intent RESUME set is {resume, continue, keep going,
#: carry on}; **"yes" resumes nothing by itself**.  A bare confirmation is only
#: a re-issue trigger when the ROBOT has just offered to go back — the offer is
#: what carries the referent, and the offer is a fact the harness recorded, not
#: something the voice invented.
_CONFIRM_WORDS = frozenset(
    {"yes", "yeah", "yep", "yes please", "please do", "sure", "ok", "okay", "go ahead", "do it"}
)
_RESUME_WORDS = frozenset({"resume", "continue", "keep going", "carry on"})


def classify_confirm(text: str, *, offer_open: bool) -> tuple[str, str]:
    """Return ``(label, reason)`` for a post-terminal owner utterance.

    ``re_issue`` only when a confirmation lands on an OPEN offer, or when the
    owner used one of the closed RESUME words.  Everything else is ``none``.
    """

    clean = " ".join(str(text).lower().split()).strip(" .!?,")
    if clean in _RESUME_WORDS:
        return (KIND_REISSUE, "closed-intent RESUME word")
    if clean in _CONFIRM_WORDS:
        if offer_open:
            return (KIND_REISSUE, "confirmation on an open offer (LIT-1 confirm rule)")
        return ("none", "bare confirmation with no open offer — 'yes' resumes nothing (L7)")
    return ("none", "not a confirmation")


class PlanQueueWhisper:
    """Model B's narration side: executive receipts → one plan-queue context item.

    Amendment L1 — the whisper takes the **unbilled tail conversation-item
    seam**: a ``conversation.item.create`` with LIT-1's own purpose tag and NO
    ``response.create``.  It is *replace-not-append*: exactly one whisper slot
    is live, and a new item goes up only when the rendered digest CHANGES.  This
    protocol build exposes no ``conversation.item.delete``, so the superseded
    item stays in the provider's transcript — the new item therefore opens by
    saying it supersedes the previous one, and the JSONL records
    ``supersedes`` so the replace semantics are auditable rather than assumed.

    The billed path (``lane.narrate_event`` → ``response.create``) is separate
    and driven by the TRIGGER TABLE below, never by this method.
    """

    #: L1/L6 — WHICH receipt kinds are worth spending a billed ``response.create``
    #: on.  Everything else refreshes the unbilled context item only.  Only an
    #: ACCEPTED terminal receipt may say "arrived"/"done" (README → Narration
    #: authority; MB-1 M7).
    TRIGGER_TABLE: ClassVar[dict[str, str]] = {
        "task_succeeded": "respond",  # a terminal the owner is waiting on
        "task_failed": "respond",
        "cancelled_at_checkpoint": "respond",
        "replacement_activated": "respond",  # the switch the owner just asked for
        KIND_SUBMIT: "context_only",
        KIND_REPLACE: "context_only",
        "replacement_deferred": "context_only",
        "task_suspended": "context_only",
        "task_resumed": "context_only",
        "step_succeeded": "context_only",
        "task_cancelled": "context_only",
    }

    def __init__(self, *, labels: dict[str, str], log: HopLog) -> None:
        self.labels = labels  # stand-in name -> pretty replay label (never sent)
        self.log = log
        self.queue: list[QueueRecord] = []
        self.history: list[QueueRecord] = []
        self._last_text: str | None = None
        self._item_seq = 0
        self.injections = 0
        self.offer_open = False

    # -- queue bookkeeping -------------------------------------------------
    def admit(self, *, directive: str, goal: str, task_id: str, t: float) -> QueueRecord:
        """Admit one directive, DISPLACING any live record on the same task.

        NAV-INT-1's N1 finding, made visible in the queue: a mid-task amendment
        reaches the executive as ``replace()`` on the SAME task id, so the goal
        that was running is not paused — it is gone.  Leaving both records live
        under one task id would let a single ``task_succeeded`` mark both
        "completed", which is the precise false claim MB-1's grounding row
        exists to catch.  The displaced record is marked ``cancelled`` and moved
        to history, where the narration layer can still say "I dropped the
        lamppost" truthfully.
        """

        for existing in self.queue:
            if existing.originating_task_id == task_id and existing.status not in {
                "completed",
                "failed",
                "cancelled",
            }:
                existing.status = "cancelled"
                self.history.append(existing)
        record = QueueRecord(directive, goal, task_id, t, "accepted")
        self.queue.append(record)
        return record

    def note_receipt(self, receipt: Receipt) -> None:
        """Apply one receipt to the NEWEST live record on its task."""

        status = _status_for(receipt.kind)
        if status is None:
            return
        for record in reversed(self.queue):
            if record.originating_task_id != receipt.task_id:
                continue
            if record.status in {"completed", "failed", "cancelled"}:
                continue
            record.status = status
            if status in {"completed", "failed", "cancelled"}:
                self.history.append(record)
            return

    # -- the digest --------------------------------------------------------
    def digest(self) -> str:
        """The whole plan queue in the executive's vocabulary, as one item.

        Deliberately a FACT LIST and not a script.  Every clause names a status
        drawn from the wave's shared fact set, so the hosted model can only
        narrate states the executive actually reported.
        """

        if not self.queue:
            return "Robot plan queue: empty. No goal is accepted or running."
        lines = ["Robot plan queue (facts from the robot's own task executive):"]
        for index, record in enumerate(self.queue, start=1):
            lines.append(
                f"{index}. goal={record.grounded_goal} status={record.status} "
                f'(owner said: "{record.directive_text}")'
            )
        lines.append(
            "Only these statuses are true. Do not claim any action that is not "
            "listed. The robot has no camera and cannot look for or find objects."
        )
        return "\n".join(lines)

    # -- the injection -----------------------------------------------------
    def refresh(self, lane: object | None) -> dict | None:
        """Send the digest as ONE tail-seam item, only when it changed."""

        text = self.digest()
        if text == self._last_text:
            return None
        supersedes = None if self._last_text is None else f"lit1_pq{self._item_seq}"
        self._item_seq += 1
        item_id = f"lit1_pq{self._item_seq}"
        payload = text
        if supersedes is not None:
            payload = (
                f"[plan-queue update {item_id}; this REPLACES {supersedes}, "
                f"ignore the earlier plan-queue item]\n{text}"
            )
        tokens = _rough_tokens(payload)
        delivered = False
        if lane is not None:
            sender = getattr(lane, "_send_item", None)
            if callable(sender):
                with contextlib.suppress(Exception):
                    delivered = bool(
                        sender(role="system", text=payload, purpose=ITEM_PURPOSE_PLAN_QUEUE)
                    )
        self._last_text = text
        self.injections += 1
        row = self.log.write(
            "whisper_injection",
            PROV_FAKE if lane is not None else PROV_HARNESS,
            item_id=item_id,
            supersedes=supersedes,
            purpose=ITEM_PURPOSE_PLAN_QUEUE,
            billed=False,
            response_create=False,
            approx_tokens=tokens,
            chars=len(payload),
            delivered=delivered,
            queue=[record.as_dict() for record in self.queue],
            text=payload,
        )
        return row

    def trigger_for(self, receipt: Receipt) -> str:
        return self.TRIGGER_TABLE.get(receipt.kind, "context_only")


def _status_for(kind: str) -> str | None:
    """Receipt KIND → the wave's shared fact vocabulary."""

    return {
        KIND_SUBMIT: "accepted",
        "step_succeeded": "running",
        "replacement_activated": "running",
        "replacement_deferred": "blocked",
        "task_suspended": "blocked",
        "task_resumed": "resumed",
        "task_succeeded": "completed",
        "task_failed": "failed",
        "task_cancelled": "cancelled",
        "cancelled_at_checkpoint": "cancelled",
    }.get(kind)


def _rough_tokens(text: str) -> int:
    """~4 chars/token.  Labelled ``approx_`` everywhere it is written."""

    return max(1, round(len(text) / 4))


# ===========================================================================
# 5. the voice lanes
# ===========================================================================


class FakeVoice:
    """A real ``RealtimeLane`` against a scripted ``FakeRealtimeServer``.

    The lane is the PRODUCT's lane — the same class the hosted path uses, with
    the same ``_send_item`` tail seam and the same ``narrate_event`` billed
    path.  Only the transport is scripted, which is the whole point of the
    deterministic tier: every hop the hosted run makes is made here too, with a
    reply that is a fixture instead of a purchase.
    """

    def __init__(self, *, log: HopLog, reply_for: Callable[[str, dict], str]) -> None:
        from parcel_robot.realtime.config import RealtimeConfig
        from parcel_robot.realtime.lane import RealtimeLane

        self.log = log
        self._reply_for = reply_for
        self.servers: list[FakeRealtimeServer] = []
        self._turn = 0
        self._pending: str | None = None
        self._context: dict = {}
        self.transcripts: list[str] = []
        self._tail = _TranscriptTail()
        #: Never populated in this tier: the fake lane opens no provider session,
        #: so no ledger row can ever carry one of its ids.  The attribute exists
        #: so the two lanes are the same shape to the caller.
        self.session_ids: set[str] = set()
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="lit1-fake"),
            instructions=(
                "You are the robot's voice. Narrate only facts the plan-queue "
                "items state. Never claim an action the robot did not report."
            ),
            transport_factory=self._factory,
            sink=_DiscardSink(),
            clock=time.monotonic,
            duplex_output_active=lambda: False,
            session_id_factory=lambda: "lit1_fake_session",
        )
        self.provenance = PROV_FAKE

    def _factory(self):
        lane_end, server_end = transport_pair(clock=time.monotonic)
        server = FakeRealtimeServer(
            transport=server_end,
            script=self._script(),
            clock=time.monotonic,
        )
        self.servers.append(server)
        return lane_end

    def _script(self) -> list[Step]:
        # Steps are built lazily by ``say``; the handshake is the only fixed one.
        return list(handshake("sess_lit1_fake"))

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="lit1-token", mic_gesture=True)
        self._pump()
        self.log.write(
            "voice_session_open",
            PROV_FAKE,
            session_id=session,
            provider_session_id=str(getattr(self.lane, "provider_session_id", "")),
        )
        return session

    def _pump(self) -> None:
        if self.servers:
            self.servers[-1].pump()
        self.lane.pump()

    def say(self, text: str, *, context: dict) -> dict:
        """One owner turn to the lane (NARRATION ONLY — never motion, L6)."""

        self._turn += 1
        reply = self._reply_for(text, context)
        response_id = f"resp_lit1_{self._turn}"
        item_id = f"item_lit1_{self._turn}"
        server = self.servers[-1]
        # Scripted: the reply is emitted when the lane asks for a response.
        server.script = list(server.script) + [
            Step(
                "response.create",
                (
                    transcript_delta(response_id, item_id, reply),
                    transcript_done(response_id, item_id, reply),
                    response_done(response_id),
                ),
                label=f"lit1_turn_{self._turn}",
            )
        ]
        t_request = self.log.now()
        self.lane.send_text(text)
        self._pump()
        t_response = self.log.now()
        spoken = self._tail.take(self.lane) or reply
        self.transcripts.append(spoken)
        row = self.log.write(
            "voice_turn",
            PROV_FAKE,
            heard=text,
            spoken=spoken,
            t_request=round(t_request, 3),
            t_first_token=round(t_response, 3),
            ttft_ms=round((t_response - t_request) * 1000.0, 1),
            billed=False,
            approx_tokens_in=_rough_tokens(text),
            approx_tokens_out=_rough_tokens(spoken),
            note="scripted fixture reply — no provider was contacted",
        )
        return row

    def narrate(self, fact: str, *, verbatim: bool = False) -> dict:
        """The BILLED path (``response.create``), fired by the trigger table.

        ``verbatim`` is for a sentence the HARNESS authored and wants said as
        written (the robot's offer to go back).  Without it the fixture renders
        the fact, which is the right default: a narration is the model speaking
        ABOUT a receipt, not the receipt read aloud.
        """

        self._turn += 1
        response_id = f"resp_lit1_n{self._turn}"
        item_id = f"item_lit1_n{self._turn}"
        spoken = fact if verbatim else self._narration_sentence(fact)
        server = self.servers[-1]
        server.script = list(server.script) + [
            Step(
                "response.create",
                (
                    transcript_delta(response_id, item_id, spoken),
                    transcript_done(response_id, item_id, spoken),
                    response_done(response_id),
                ),
                label=f"lit1_narration_{self._turn}",
            )
        ]
        t_request = self.log.now()
        taken = bool(self.lane.narrate_event(fact))
        self._pump()
        t_response = self.log.now()
        said = self._tail.take(self.lane) if taken else ""
        if said:
            self.transcripts.append(said)
        return self.log.write(
            "narration_event",
            PROV_FAKE,
            fact=fact,
            taken=taken,
            spoken=said,
            response_create=taken,
            billed=False,
            latency_ms=round((t_response - t_request) * 1000.0, 1),
        )

    def _narration_sentence(self, fact: str) -> str:
        """Render one executive fact as a sentence, in the fixture tier.

        Grounded by construction: it can only restate the status word the
        receipt carried, and it can never claim an action.  Anything richer
        would be the fixture pretending to be the model.
        """

        matched = self._reply_for(fact, {"narration": True})
        if matched and matched != "Okay.":
            return matched
        return fact

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.lane.close()


class _DiscardSink:
    """``mode: text`` has no mouth on this host; count bytes and drop them."""

    def __init__(self) -> None:
        self.bytes = 0
        self.begin_calls = 0

    def begin_utterance(self) -> None:
        self.begin_calls += 1

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.bytes += len(chunk)

    def interrupt(self) -> None:
        return None


def _transcript_buffer(lane: object) -> str:
    """Everything the lane has transcribed so far, as ONE accumulating string.

    ``_ResponseState.transcript`` joins the deltas of the CURRENT response, but
    the fake transport never rolls the state between scripted turns, so reading
    it directly returns turn 1 + turn 2 + turn 3 concatenated — which is how the
    first run logged "Okay, heading to the lamppost now.Got it — switching to
    the bench instead." as the answer to a single sentence.  Callers take the
    DELTA against what they had already seen (see ``_TranscriptTail``).
    """

    for attribute in ("last_transcript", "_last_transcript"):
        value = getattr(lane, attribute, None)
        if isinstance(value, str) and value:
            return value
    response = getattr(lane, "_response", None)
    text = getattr(response, "transcript", None)
    if isinstance(text, str) and text:
        return text
    rows = getattr(lane, "transcripts", None)
    if isinstance(rows, list) and rows:
        return "".join(str(row) for row in rows)
    return ""


class _TranscriptTail:
    """What the lane said SINCE the last time anybody asked."""

    def __init__(self) -> None:
        self._seen = ""

    def take(self, lane: object) -> str:
        buffer = _transcript_buffer(lane)
        if buffer.startswith(self._seen):
            delta = buffer[len(self._seen) :]
        else:  # the lane rolled its state; the whole buffer is new
            delta = buffer
        self._seen = buffer
        return delta.strip()


class HostedVoice:
    """The live hosted lane, reached ONLY through ``runtime.submit_realtime_text``.

    Amendment L6: the hosted lane narrates.  It never moves the robot — every
    hosted motion door is wrapped by ``_gate_by_voice`` and refuses without a
    voice-identity binding, and a ``navigate_to`` refusal is logged as its own
    JSONL row rather than worked around.

    The governor is asked FIRST and its snapshot is printed before any turn.  A
    refusal is UNMEASURED and the run says so.
    """

    def __init__(self, *, runtime: object, log: HopLog) -> None:
        self.runtime = runtime
        self.log = log
        self.provenance = PROV_HOSTED
        self.refusals: list[dict] = []
        self.transcripts: list[str] = []
        self._tail = _TranscriptTail()
        #: Every provider session this run opened.  The ONLY basis on which a
        #: ledger row is charged to this experiment (the ledger is shared).
        self.session_ids: set[str] = set()

    def governor_snapshot(self) -> dict:
        governor = getattr(self.runtime, "realtime_governor", None)
        if governor is None:
            return {"governor": None, "note": "no governor wired — envelope NOT enforced"}
        with contextlib.suppress(Exception):
            return dict(governor.snapshot())
        return {"governor": "unreadable"}

    def open(self) -> str:
        """Bind the panel token; never raise.

        A missing lane (no ``PARCEL_REALTIME_CONFIG``) and an unarmable lane (no
        credential) are both MEASUREMENTS of the fail-closed path, not reasons
        to abandon an episode whose body half is still worth recording.  Both
        become rows; neither takes the sim down with it.
        """

        lane = getattr(self.runtime, "realtime_lane", None)
        if lane is None:
            self.log.write(
                "voice_session_refused",
                PROV_HOSTED,
                reason="no realtime lane constructed",
                detail="PARCEL_REALTIME_CONFIG absent, or realtime.enabled is false",
            )
            return "no-lane"
        binder = getattr(self.runtime, "bind_panel_token", None)
        if callable(binder):
            with contextlib.suppress(Exception):
                binder("lit1-hosted-token")
        decision = None
        with contextlib.suppress(Exception):
            decision = lane.arm(handshake_token="lit1-hosted-token", mic_gesture=True)
        self.log.write(
            "voice_session_arming",
            PROV_HOSTED,
            armed=bool(getattr(decision, "armed", False)),
            code=str(getattr(decision, "code", "")),
            reason=str(getattr(decision, "reason", "")),
        )
        return "pending"

    def say(self, text: str, *, context: dict) -> dict:
        del context
        t_request = self.log.now()
        try:
            outcome = self.runtime.submit_realtime_text(text)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - a refusal is a measurement
            row = self.log.write(
                "voice_turn_refused",
                PROV_HOSTED,
                heard=text,
                error=f"{type(error).__name__}: {error}",
                billed=False,
            )
            self.refusals.append(row)
            return row
        if isinstance(outcome, dict) and outcome.get("session_id"):
            self.session_ids.add(str(outcome["session_id"]))
        driver = getattr(self.runtime, "realtime_driver", None)
        spoken = ""
        deadline = time.monotonic() + 20.0
        lane = getattr(self.runtime, "realtime_lane", None)
        while time.monotonic() < deadline:
            if driver is None and lane is not None:
                with contextlib.suppress(Exception):
                    lane.pump()
            spoken = self._tail.take(lane) if lane is not None else ""
            if spoken:
                break
            time.sleep(0.1)
        t_response = self.log.now()
        if spoken:
            self.transcripts.append(spoken)
        return self.log.write(
            "voice_turn",
            PROV_HOSTED,
            heard=text,
            spoken=spoken,
            accepted=bool(outcome.get("accepted")) if isinstance(outcome, dict) else None,
            session_id=str(outcome.get("session_id")) if isinstance(outcome, dict) else None,
            t_request=round(t_request, 3),
            t_first_token=round(t_response, 3),
            ttft_ms=round((t_response - t_request) * 1000.0, 1),
            billed=True,
        )

    def narrate(self, fact: str, *, verbatim: bool = False) -> dict:
        del verbatim  # the hosted model composes its own sentence, always
        lane = getattr(self.runtime, "realtime_lane", None)
        if lane is None:
            return self.log.write("narration_event", PROV_HOSTED, fact=fact, taken=False)
        t_request = self.log.now()
        taken = False
        with contextlib.suppress(Exception):
            taken = bool(lane.narrate_event(fact))
        t_response = self.log.now()
        return self.log.write(
            "narration_event",
            PROV_HOSTED,
            fact=fact,
            taken=taken,
            response_create=taken,
            billed=bool(taken),
            latency_ms=round((t_response - t_request) * 1000.0, 1),
        )

    def close(self) -> None:
        lane = getattr(self.runtime, "realtime_lane", None)
        if lane is not None:
            with contextlib.suppress(Exception):
                lane.close()


# ===========================================================================
# 6. the motion instrument (amendment L9)
# ===========================================================================


@dataclass
class MotionSample:
    t: float
    x: float
    y: float
    yaw: float
    vx: float
    vy: float
    vyaw: float
    pace: float

    def as_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw": round(self.yaw, 4),
            "vx": round(self.vx, 4),
            "vy": round(self.vy, 4),
            "vyaw": round(self.vyaw, 4),
            "pace": round(self.pace, 3),
        }


class MotionInstrument:
    """>= 10 Hz pose + body-lane velocity, sampled off the runtime directly.

    ``runtime._last_sent`` is the ``VelocityCommand`` the runtime last handed
    the body lane — the actual command, not a re-derivation from pose — which is
    what makes ``|vyaw| > 0.1 rad/s`` a statement about what the robot was TOLD
    to do rather than about what the finite difference of a noisy pose says.
    Pose comes from the same live observation the e2e's ``pose()`` reads.
    """

    def __init__(self, *, runtime: object, clock: Callable[[], float], hz: float = 20.0) -> None:
        self.runtime = runtime
        self._clock = clock
        self._period = 1.0 / float(hz)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.samples: list[MotionSample] = []

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while self._running.is_set():
            started = time.monotonic()
            with contextlib.suppress(Exception):
                sample = self._take()
                if sample is not None:
                    with self._lock:
                        self.samples.append(sample)
            delay = self._period - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)

    def _take(self) -> MotionSample | None:
        observation = getattr(self.runtime, "_observation", None)
        if observation is None:
            return None
        command = getattr(self.runtime, "_last_sent", None)
        return MotionSample(
            t=self._clock(),
            x=float(observation.robot.x),
            y=float(observation.robot.y),
            yaw=float(observation.robot.yaw),
            vx=float(getattr(command, "vx", 0.0) or 0.0),
            vy=float(getattr(command, "vy", 0.0) or 0.0),
            vyaw=float(getattr(command, "vyaw", 0.0) or 0.0),
            pace=float(getattr(getattr(self.runtime, "_pace_cap", None), "scale", 1.0) or 1.0),
        )

    def window(self, t_from: float, t_to: float) -> list[MotionSample]:
        with self._lock:
            return [s for s in self.samples if t_from <= s.t <= t_to]

    def all(self) -> list[MotionSample]:
        with self._lock:
            return list(self.samples)


def first_turn_toward(
    samples: list[MotionSample],
    *,
    goal_xy: tuple[float, float],
    t_from: float,
) -> tuple[float | None, dict]:
    """L9's "starts turning" predicate, exactly as amended.

    Heading error to the NEW goal decreasing for >= 3 consecutive 100 ms samples
    with ``|vyaw| > 0.1 rad/s``.  Returns ``(t, evidence)``; ``t`` is the
    timestamp of the FIRST of the three samples, because that is the moment the
    robot began the turn, not the moment the predicate was satisfied.
    """

    window = [s for s in samples if s.t >= t_from]
    decimated: list[MotionSample] = []
    last_t = -1e9
    for sample in window:
        if (sample.t - last_t) * 1000.0 >= TURN_SAMPLE_MS - 5.0:
            decimated.append(sample)
            last_t = sample.t
    run: list[MotionSample] = []
    previous_error: float | None = None
    for sample in decimated:
        error = abs(_wrap_pi(math.atan2(goal_xy[1] - sample.y, goal_xy[0] - sample.x) - sample.yaw))
        turning = abs(sample.vyaw) > TURN_VYAW_MIN
        decreasing = previous_error is not None and error < previous_error - 1e-6
        if turning and decreasing:
            run.append(sample)
            if len(run) >= TURN_CONSECUTIVE:
                return (
                    run[0].t,
                    {
                        "samples_n": len(decimated),
                        "run_start_t": round(run[0].t, 3),
                        "run_vyaw": [round(s.vyaw, 3) for s in run[:TURN_CONSECUTIVE]],
                        "heading_error_rad": round(error, 4),
                    },
                )
        else:
            run = []
        previous_error = error
    return (
        None,
        {
            "samples_n": len(decimated),
            "reason": "no 3 consecutive 100 ms samples with |vyaw|>0.1 and falling heading error",
            "max_abs_vyaw": round(max((abs(s.vyaw) for s in decimated), default=0.0), 4),
        },
    )


def _wrap_pi(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def motion_during_speech(
    samples: list[MotionSample], *, t_start: float, t_stop: float
) -> dict:
    """L9's yield row: was the body moving while the owner was speaking?"""

    window = [s for s in samples if t_start <= s.t <= t_stop]
    if not window:
        return {"n": 0, "moving": None, "note": "no samples in the speech window"}
    speeds = [math.hypot(s.vx, s.vy) for s in window]
    moving = [value for value in speeds if value > 0.02]
    return {
        "n": len(window),
        "moving_samples": len(moving),
        "moving_fraction": round(len(moving) / len(window), 3),
        "max_speed_mps": round(max(speeds), 4),
        "max_abs_vyaw": round(max(abs(s.vyaw) for s in window), 4),
        "yielded": len(moving) == 0,
    }


# ===========================================================================
# 7. the sim + runtime session (amendments L3, L10)
# ===========================================================================


class SimSession:
    """One sim + one runtime, built the e2e way, torn down by process group.

    Delegates to NAV-INT-1's ``LiveSession`` when that peer module is present
    (it already is the ``_LiveRuntime`` pattern under ``systemd-run``, and one
    launcher with one teardown is safer than two).  ``pgrep_proof`` is called on
    EVERY exit path so RESULTS.md can carry the evidence amendment L3 asks for.
    """

    def __init__(self, workdir: Path, *, index: int) -> None:
        if ni1_harness is None:
            raise RuntimeError(
                "nav-interrupt-1/harness.py is absent; LIT-1 will not hand-roll a "
                "second sim launcher (amendment L3 — orphan risk)"
            )
        self.workdir = workdir
        self._inner = ni1_harness.LiveSession(workdir, index=index, static_city=True)
        self.runtime = self._inner.runtime
        self.socket = Path(self._inner.socket)
        if str(self.socket) == FORBIDDEN_SOCKET:
            self.close()
            raise RuntimeError("refusing to run on the owner's socket")
        self.sim_pid = self._inner.sim.pid

    # -- views -------------------------------------------------------------
    def pose(self) -> tuple[float, float]:
        return self._inner.pose()

    def heading(self) -> float:
        return self._inner.heading()

    def tasks(self) -> list[dict]:
        return self._inner.tasks()

    def task_states(self) -> dict[str, tuple[str, int]]:
        return self._inner.task_states()

    def settled(self, **kwargs: object) -> bool:
        return self._inner.settled(**kwargs)  # type: ignore[arg-type]

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._inner.close()

    def pgrep_proof(self) -> dict:
        """Amendment L3 — prove at exit that this run's sim is gone."""

        alive = []
        with contextlib.suppress(Exception):
            out = subprocess.run(
                ["pgrep", "-af", "parcel_robot.sim"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            alive = [line for line in out.splitlines() if str(self.socket) in line]
        return {
            "socket": str(self.socket),
            "sim_pid": self.sim_pid,
            "own_sim_alive": alive,
            "clean": not alive,
        }


# ===========================================================================
# 8. scenarios
# ===========================================================================


def load_scenario(name_or_path: str) -> dict:
    path = Path(name_or_path)
    if not path.exists():
        path = HERE / "scenarios" / f"{name_or_path}.json"
    if not path.exists():
        raise SystemExit(f"scenario not found: {name_or_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def scenario_variant(scenario: dict, variant: str | None) -> dict:
    if not variant or variant == "base":
        return scenario
    for item in scenario.get("variants", []):
        if item.get("id") == variant:
            merged = dict(scenario)
            merged.update(item)
            merged["variants"] = []
            merged["id"] = f"{scenario['id']}:{variant}"
            return merged
    raise SystemExit(f"variant not found: {variant}")


def scenario_allowlist(scenario: dict) -> set[str]:
    """The POSITIVE name allowlist: stand-ins + pretty labels + scene words."""

    names: set[str] = set()
    for key, value in (scenario.get("alias_table") or {}).items():
        names.add(str(key))
        names.add(str(value))
    for value in (scenario.get("replay_labels") or {}).values():
        names.add(str(value))
    if ni1_harness is not None:
        for row in ni1_harness.DERIVED_LANDMARKS.values():
            label = row.get("label")
            if label:
                names.add(str(label))
    names.update({"sidewalk", "crosswalk"})
    return names


# ===========================================================================
# 9. the loop
# ===========================================================================


@dataclass
class RunResult:
    scenario: str
    variant: str
    seed: int
    voice: str
    jsonl: str
    receipt_kinds: list[str] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    latencies: dict = field(default_factory=dict)
    spend_usd: float = 0.0
    refusals: list[dict] = field(default_factory=list)
    provenance_counts: dict = field(default_factory=dict)
    motion_during_speech: dict = field(default_factory=dict)
    name_scan_leaks: list[dict] = field(default_factory=list)
    teardown: dict = field(default_factory=dict)
    ok: bool = False
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "variant": self.variant,
            "seed": self.seed,
            "voice": self.voice,
            "jsonl": self.jsonl,
            "receipt_kinds": self.receipt_kinds,
            "receipts": self.receipts,
            "latencies": self.latencies,
            "spend_usd": self.spend_usd,
            "refusals": self.refusals,
            "provenance_counts": self.provenance_counts,
            "motion_during_speech": self.motion_during_speech,
            "name_scan_leaks": self.name_scan_leaks,
            "teardown": self.teardown,
            "ok": self.ok,
            "error": self.error,
            "notes": self.notes,
        }


def _ledger_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(Exception):
            rows.append(json.loads(line))
    return rows


def _row_usd(row: dict) -> float:
    for key in ("estimated_usd", "usd", "cost_usd", "estimated_cost_usd"):
        if key in row:
            with contextlib.suppress(Exception):
                return float(row[key])
    return 0.0


def _ledger_total(path: Path) -> float:
    return sum(_row_usd(row) for row in _ledger_rows(path))


def _ledger_total_for(path: Path, session_ids: set[str]) -> float:
    """This run's spend, attributed by SESSION ID — never by a before/after diff.

    The wave ledger is SHARED with MB-1 and MB-1 runs concurrently, so a naive
    ``total_after - total_before`` charged this experiment for whatever the
    other one bought while a sim was walking: the first fake run of the base
    scenario, which contacted no provider at all, was recorded at $0.04386 that
    way. Rows carry ``session_id``; only the sessions THIS run opened are
    this run's money.
    """

    if not session_ids:
        return 0.0
    return sum(
        _row_usd(row)
        for row in _ledger_rows(path)
        if str(row.get("session_id") or "") in session_ids
    )


def run_scenario(
    scenario: dict,
    *,
    voice: str,
    seed: int,
    index: int,
    outdir: Path,
    variant: str = "base",
) -> RunResult:
    """One episode of the loop, start to teardown."""

    allow = scenario_allowlist(scenario)
    guard = NameScan(allow)
    t0 = time.monotonic()
    stamp = time.strftime("%Y%m%dT%H%M%S")
    jsonl_path = outdir / f"{scenario['id'].replace(':', '_')}-{voice}-s{seed}-r{index}-{stamp}.jsonl"
    log = HopLog(jsonl_path, t0=t0, guard=guard)
    result = RunResult(
        scenario=str(scenario.get("id")),
        variant=variant,
        seed=seed,
        voice=voice,
        jsonl=str(jsonl_path),
    )
    ledger_before = _ledger_total(WAVE_LEDGER)
    session_ids: set[str] = set()
    session: SimSession | None = None
    instrument: MotionInstrument | None = None
    tap: ExecutiveTap | None = None
    lane_obj: FakeVoice | HostedVoice | None = None
    #: (t_from, t_to) windows the motion log is written at FULL rate for.
    #: Defined before the try so the ``finally`` can read it whatever failed.
    cue_windows: list[tuple[float, float]] = []
    try:
        log.write(
            "run_header",
            PROV_HARNESS,
            scenario=scenario.get("id"),
            variant=variant,
            title=scenario.get("title"),
            seed=seed,
            run_index=index,
            voice=voice,
            t_wall=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            providers=PROVIDERS,
            swap_table=[list(row) for row in SWAP_TABLE],
            alias_table=scenario.get("alias_table"),
            env={
                "TMPDIR": os.environ.get("TMPDIR"),
                "PARCEL_REALTIME_CONFIG": os.environ.get("PARCEL_REALTIME_CONFIG"),
                "PARCEL_REALTIME_SPEND_LEDGER": os.environ.get(
                    "PARCEL_REALTIME_SPEND_LEDGER"
                ),
                "PARCEL_MEMORY_PATH": os.environ.get("PARCEL_MEMORY_PATH"),
            },
        )
        session = SimSession(WORKROOT, index=index)
        runtime = session.runtime
        guard.bind_runtime(runtime)
        # L10 — the two start-of-run assertions, written into the log so a
        # reader does not have to trust that they were made.
        spend_note = str(getattr(runtime, "_realtime_spend_note", ""))
        log.write(
            "preflight",
            PROV_HARNESS,
            socket=str(session.socket),
            socket_is_owner=str(session.socket) == FORBIDDEN_SOCKET,
            spend_note=spend_note,
            spend_note_is_wave_ledger=spend_note == str(WAVE_LEDGER),
            curiosity_admitted_names=sorted(guard.runtime_admitted),
            curiosity_gate_read=guard.runtime_admitted_read,
            name_allowlist=sorted(allow),
        )
        if str(session.socket) == FORBIDDEN_SOCKET:
            raise RuntimeError("socket is the owner's")

        instrument = MotionInstrument(runtime=runtime, clock=log.now)
        instrument.start()
        tap = ExecutiveTap(runtime.task_executive, clock=log.now)
        whisper = PlanQueueWhisper(labels=scenario.get("replay_labels") or {}, log=log)
        pending_narration: list[Receipt] = []

        def _on_receipt(receipt: Receipt) -> None:
            log.write_row({"hop": "receipt", "provenance": PROV_SIM, **receipt.as_dict()})
            whisper.note_receipt(receipt)
            if whisper.trigger_for(receipt) == "respond":
                pending_narration.append(receipt)

        tap.on_receipt = _on_receipt
        tap.attach()

        # -- the voice lane -------------------------------------------------
        if voice == "fake":
            lane_obj = FakeVoice(log=log, reply_for=_fixture_reply(scenario, whisper))
            lane_obj.open()
            whisper_target = lane_obj.lane
        elif voice == "hosted":
            lane_obj = HostedVoice(runtime=runtime, log=log)
            snapshot = lane_obj.governor_snapshot()
            print("[lit1] governor.snapshot() =", json.dumps(snapshot, default=str))
            log.write("governor_snapshot", PROV_HOSTED, snapshot=snapshot)
            lane_obj.open()
            whisper_target = getattr(runtime, "realtime_lane", None)
        else:
            whisper_target = None

        # -- the timeline ---------------------------------------------------
        state = _TimelineState(
            scenario=scenario,
            session=session,
            log=log,
            instrument=instrument,
            tap=tap,
            whisper=whisper,
            whisper_target=whisper_target,
            lane=lane_obj,
            pending_narration=pending_narration,
            cue_windows=cue_windows,
        )
        state.run()
        result.latencies = state.latencies
        result.motion_during_speech = state.motion_rows
        result.notes.extend(state.notes)

        receipts = tap.snapshot()
        result.receipts = [receipt.as_dict() for receipt in receipts]
        result.receipt_kinds = [r.kind for r in receipts if r.kind in SEQUENCE_KINDS]
        result.ok = True
    except Exception as error:  # noqa: BLE001 - a failed episode is a row
        result.error = f"{type(error).__name__}: {error}"
        with contextlib.suppress(Exception):
            log.write("run_error", PROV_HARNESS, error=result.error)
    finally:
        if tap is not None:
            tap.detach()
        if instrument is not None:
            instrument.stop()
            # Amendment L9 asks for >= 10 Hz "in the cue window"; it does not ask
            # for 20 Hz across a five-minute walk, and 6,000 rows of straight-line
            # cruising would push the committed artifact past the 2 MB bar for no
            # information.  So: FULL rate inside every cue window (cue - 2 s to
            # cue + 10 s), 2 Hz outside it.  The windows are recorded in the log
            # so a reader can see which rows are dense and why.
            windows = [list(item) for item in cue_windows]
            log.write("motion_sampling", PROV_HARNESS, full_rate_windows=windows, hz=20.0)
            last_written = -1e9
            for sample in instrument.all():
                dense = any(low <= sample.t <= high for low, high in windows)
                if not dense and sample.t - last_written < 0.5:
                    continue
                last_written = sample.t
                log.write_row(
                    {
                        "hop": "motion",
                        "provenance": PROV_SIM,
                        "dense": dense,
                        **sample.as_dict(),
                    }
                )
        if lane_obj is not None:
            with contextlib.suppress(Exception):
                lane_obj.close()
            if isinstance(lane_obj, HostedVoice):
                result.refusals = list(lane_obj.refusals)
        if session is not None:
            session.close()
            result.teardown = session.pgrep_proof()
            log.write("teardown", PROV_HARNESS, **result.teardown)
        if lane_obj is not None:
            session_ids.update(getattr(lane_obj, "session_ids", set()))
        result.spend_usd = round(_ledger_total_for(WAVE_LEDGER, session_ids), 6)
        result.notes.append(
            f"spend attributed by session_id {sorted(session_ids) or '(none)'}; "
            f"the shared wave ledger moved "
            f"${_ledger_total(WAVE_LEDGER) - ledger_before:.6f} during this run, "
            "which includes MB-1's concurrent hosted turns and is NOT this run's cost"
        )
        result.name_scan_leaks = list(log.leaks)
        result.provenance_counts = _provenance_counts(jsonl_path)
        with contextlib.suppress(Exception):
            log.write(
                "run_footer",
                PROV_HARNESS,
                ok=result.ok,
                error=result.error,
                spend_usd=result.spend_usd,
                receipt_kinds=result.receipt_kinds,
                name_scan_leaks=result.name_scan_leaks,
            )
        log.close()
    return result


def _provenance_counts(path: Path) -> dict:
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(Exception):
            row = json.loads(line)
            key = str(row.get("provenance") or "?")
            counts[key] = counts.get(key, 0) + 1
    return counts


def _fixture_reply(scenario: dict, whisper: PlanQueueWhisper) -> Callable[[str, dict], str]:
    """The fake server's scripted replies — deterministic, grounded, honest.

    They are FIXTURES, not model output: the fake tier proves the loop closes
    and the timing instrument works, never that a model would say this.  They
    are written to be exactly what an honest, capability-grounded narration
    layer should say — including the keys clause (amendment L8): arrival, plus
    "I can't look for keys — I have no camera", plus an offer.
    """

    replies = dict(scenario.get("fixture_replies") or {})

    def _reply(text: str, context: dict) -> str:
        del context
        clean = " ".join(str(text).lower().split()).strip(" .!?,")
        for cue, value in replies.items():
            if cue.lower() in clean:
                return str(value)
        if whisper.queue:
            last = whisper.queue[-1]
            return f"Okay — {last.grounded_goal} is {last.status}."
        return "Okay."

    return _reply


class _TimelineState:
    """Runs one scenario's owner timeline against the live session."""

    def __init__(
        self,
        *,
        scenario: dict,
        session: SimSession,
        log: HopLog,
        instrument: MotionInstrument,
        tap: ExecutiveTap,
        whisper: PlanQueueWhisper,
        whisper_target: object | None,
        lane: FakeVoice | HostedVoice | None,
        pending_narration: list[Receipt],
        cue_windows: list[tuple[float, float]],
    ) -> None:
        self.scenario = scenario
        self.session = session
        self.log = log
        self.instrument = instrument
        self.tap = tap
        self.whisper = whisper
        self.whisper_target = whisper_target
        self.lane = lane
        self.pending = pending_narration
        self.cue_windows = cue_windows
        self._cue_t: float = 0.0
        self.latencies: dict = {}
        self.motion_rows: dict = {}
        self.notes: list[str] = []
        self._goal_xy: dict[str, tuple[float, float]] = {}

    # -- helpers -----------------------------------------------------------
    def goal_xy(self, key: str) -> tuple[float, float]:
        """A single (x, y) to measure progress and heading error against.

        Only ever the TRIGGER and the turn predicate's reference — never the
        arrival authority, which stays NAV-INT-1's K0 region.  Falls back to the
        scene's own landmark table for goals the peer harness's catalogue does
        not carry (the ``tree`` the blocked-route variant aims at).
        """

        if key not in self._goal_xy:
            spec = ni1_harness.GOALS.get(key)  # type: ignore[union-attr]
            if spec is not None:
                self._goal_xy[key] = ni1_harness.goal_reference_xy(spec)  # type: ignore[union-attr]
            else:
                landmark = None
                for entry in ni1_harness.DERIVED_LANDMARKS.values():  # type: ignore[union-attr]
                    if str(entry.get("label")) == key and entry.get("position"):
                        landmark = entry
                        break
                if landmark is None:
                    raise KeyError(f"no reference point for goal {key!r}")
                position = landmark["position"]
                self._goal_xy[key] = (float(position[0]), float(position[1]))
        return self._goal_xy[key]

    def _mark_cue_window(self, t_start: float) -> None:
        """Amendment L9's window: cue - 2 s to cue + 10 s, logged at full rate."""

        self.cue_windows.append(
            (t_start - CUE_WINDOW_BEFORE_S, t_start + CUE_WINDOW_AFTER_S)
        )

    def _flush_narration(self) -> None:
        while self.pending:
            receipt = self.pending.pop(0)
            fact = self._fact_for(receipt)
            if self.lane is not None:
                self.lane.narrate(fact)
            else:
                self.log.write(
                    "narration_event", PROV_HARNESS, fact=fact, taken=False, note="no lane"
                )

    def _fact_for(self, receipt: Receipt) -> str:
        """Only an ACCEPTED terminal receipt may say arrived/done (MB-1 M7)."""

        status = _status_for(receipt.kind) or receipt.kind
        goal = ""
        for record in self.whisper.queue:
            if record.originating_task_id == receipt.task_id:
                goal = record.grounded_goal
        where = f" for {goal}" if goal else ""
        if receipt.kind == "task_succeeded":
            return (
                f"The robot's task executive reports the trip{where} is {status} "
                f"(receipt: {receipt.action}, detail: {receipt.last_detail})."
            )
        return (
            f"The robot's task executive reports the task{where} is {status} "
            f"(receipt: {receipt.action}, detail: {receipt.last_detail})."
        )

    def _speak(self, text: str, *, authority: str, narrate: bool, label: str) -> dict:
        """One owner utterance.  ONE authority per utterance (amendment L6)."""

        t_start = self.log.now()
        self._mark_cue_window(t_start)
        self.log.write(
            "owner_speech_start", PROV_HARNESS, text=text, authority=authority, step=label
        )
        row: dict = {}
        speaking_s = speech_duration_s(text)
        time.sleep(speaking_s)
        if authority == "motion":
            t_in = self.log.now()
            utterance = self.session._inner.issue(text)
            t_out = self.log.now()
            row = self.log.write(
                "utterance_motion",
                PROV_SIM,
                text=text,
                reply=utterance.reply,
                step=label,
                t_handle_text_in=round(t_in, 3),
                t_handle_text_out=round(t_out, 3),
                handle_text_ms=round((t_out - t_in) * 1000.0, 1),
                metrics=utterance.metrics,
                authority="local handle_text (L6)",
                speaking_s=round(speaking_s, 3),
                speech_start_t=round(t_start, 3),
                speech_end_t=round(t_in, 3),
                speech_end_definition="handle_text entry (L9, text turn)",
            )
            self._cue_t = self.log.now()
            self.log.write(
                "cue",
                PROV_SIM,
                step=label,
                text=text,
                t_cue=round(self._cue_t, 3),
                utterance_to_cue_ms=round((self._cue_t - t_in) * 1000.0, 1),
                closed_intent=utterance.metrics.get("closed_intent"),
                reasoning_source=utterance.metrics.get("reasoning_source"),
                goal_amend_ok=utterance.metrics.get("goal_amend_ok"),
                goal_amend_reason=utterance.metrics.get("goal_amend_reason"),
                definition="the cue is the runtime's own intent classification, "
                "read off agent.last_brain_metrics when handle_text returns",
            )
        self.log.write(
            "owner_speech_stop",
            PROV_HARNESS,
            text=text,
            step=label,
            speaking_s=round(speaking_s, 3),
        )
        # The yield row is about the window the owner was SPEAKING in, which
        # ends when the sentence lands in ``handle_text`` — not about the
        # milliseconds the planner then spent, where a stop would be a
        # different (and uninteresting) fact.
        self.motion_rows[label] = motion_during_speech(
            self.instrument.all(), t_start=t_start, t_stop=t_start + speaking_s
        )
        # The SAME sentence to the voice lane, for NARRATION only.
        if narrate and self.lane is not None:
            self.whisper.refresh(self.whisper_target)
            self.lane.say(text, context={"step": label})
        return row

    # -- the run -----------------------------------------------------------
    def run(self) -> None:
        goal_a = str(self.scenario["goal_a"])
        goal_b = self.scenario.get("goal_b")
        timeline = self.scenario.get("timeline") or []
        start_xy = self.session.pose()
        known_before: dict[str, tuple[str, int]] = {}
        #: When the SIM-STATE condition fired.  Deliberately not called "cue":
        #: the cue is the runtime's own intent classification, which happens a
        #: whole spoken sentence later, and calling the trigger a cue is what
        #: made the first run report a NEGATIVE utterance -> cue latency.
        trigger_t: float | None = None

        for entry in timeline:
            step = str(entry.get("step") or entry.get("at") or "step")
            at = str(entry.get("at") or "start")
            text = str(entry.get("text") or "")
            authority = str(entry.get("authority") or "motion")
            narrate = bool(entry.get("narrate", True))

            if at == "trigger":
                reference = self.goal_xy(goal_a)
                trigger = self.scenario.get("trigger") or {}
                outcome = ni1_harness.wait_for_trigger(  # type: ignore[union-attr]
                    self.session._inner,
                    start_xy=start_xy,
                    reference_xy=reference,
                    fraction=trigger.get("fraction"),
                    time_s=trigger.get("time_s"),
                    task_ids=set(self.session.task_states()),
                    max_wait_s=float(trigger.get("max_wait_s", 150.0)),
                )
                self.log.write(
                    "sim_state_trigger",
                    PROV_SIM,
                    step=step,
                    fired=outcome.fired,
                    progress=round(outcome.progress, 4),
                    travelled_m=round(outcome.travelled_m, 3),
                    reference_m=round(outcome.reference_m, 3),
                    note="fraction of the from-rest reference path, measured from pose (L9)",
                )
                if outcome.fired not in {"fraction", "time"}:
                    self.notes.append(
                        f"{step}: trigger fired as {outcome.fired!r} at progress "
                        f"{outcome.progress:.3f} — the cue landed off the pre-registered place"
                    )
                known_before = self.session.task_states()
                trigger_t = self.log.now()

            elif at == "after_terminal":
                ids = set(self.session.task_states())
                ok, states = ni1_harness.wait_terminal(  # type: ignore[union-attr]
                    self.session._inner,
                    ids,
                    deadline_s=float(entry.get("deadline_s", 280.0)),
                )
                self.log.write(
                    "await_terminal", PROV_SIM, step=step, reached=ok, states=states
                )
                self._score_arrival(step, str(self.scenario.get("goal_b") or goal_a), states)
                self._flush_narration()
                # The robot offers to go back — the offer is a HARNESS fact, and
                # it is what makes a later "yes" mean anything (L7).
                if self.scenario.get("offer_return"):
                    # The offer is the ROBOT speaking, so it takes the narration
                    # door (``narrate_event`` -> ``response.create``), not
                    # ``send_text``.  The first draft sent it through ``say``,
                    # which logged the robot's own sentence as something the
                    # OWNER had said — and an owner turn the owner never took is
                    # the one thing a conversation log must never contain.
                    offer = str(self.scenario["offer_return"])
                    self.whisper.offer_open = True
                    self.whisper.refresh(self.whisper_target)
                    self.log.write(
                        "voice_offer",
                        PROV_HARNESS,
                        text=offer,
                        step=step,
                        speaker="robot",
                        grounded_in="the accepted terminal receipt (MB-1 M7)",
                    )
                    if self.lane is not None:
                        self.lane.narrate(offer, verbatim=True)

            if not text:
                continue

            if authority == "voice_only":
                # A voice-only utterance still gets the speech window measured:
                # "did the body keep moving while the owner was talking" is a
                # row about EVERY utterance, not only the ones that steer (L9).
                t_start = self.log.now()
                self._mark_cue_window(t_start)
                self.log.write(
                    "owner_speech_start",
                    PROV_HARNESS,
                    text=text,
                    authority="voice_only (narration lane; no motion authority — L6)",
                    step=step,
                )
                speaking_s = speech_duration_s(text)
                time.sleep(speaking_s)
                label, reason = classify_confirm(text, offer_open=self.whisper.offer_open)
                self.log.write(
                    "steering_decision",
                    PROV_HARNESS,
                    step=step,
                    text=text,
                    label=label,
                    reason=reason,
                    rule=(
                        "LIT-1 minimal confirm→re-issue (labelled, LIT-1's own)"
                        if mb1_steer is None
                        else "LIT-1 minimal confirm→re-issue (authority) + "
                        "model-b-narration-1/steer.py (recorded alongside)"
                    ),
                    mb1_steer=self._mb1_steer(text),
                )
                if self.lane is not None:
                    self.lane.say(text, context={"step": step})
                self.log.write(
                    "owner_speech_stop",
                    PROV_HARNESS,
                    text=text,
                    step=step,
                    speaking_s=round(speaking_s, 3),
                )
                self.motion_rows[step] = motion_during_speech(
                    self.instrument.all(), t_start=t_start, t_stop=t_start + speaking_s
                )
                if label == KIND_REISSUE:
                    reissue = str(entry.get("reissue_text") or "")
                    if reissue:
                        self.tap.receipts.append(
                            Receipt(
                                t=self.log.now(),
                                kind=KIND_REISSUE,
                                source="harness",
                                task_id="",
                                action="re_issue",
                                state="",
                                plan_revision=0,
                                last_detail="",
                                note="NAV-INT-1 N1: the displaced goal is re-issued, "
                                "never resumed — a fresh task, a fresh plan revision",
                            )
                        )
                        self.log.write(
                            "re_issue", PROV_HARNESS, step=step, text=reissue,
                            note="harness re-issue of the remembered directive TEXT (N1)",
                        )
                        self._speak(
                            reissue, authority="motion", narrate=False, label=f"{step}:reissue"
                        )
                        self.whisper.offer_open = False
                        self._record_goal(reissue, goal_a)
                continue

            row = self._speak(text, authority=authority, narrate=narrate, label=step)
            grounded = str(entry.get("goal") or (goal_b if at == "trigger" else goal_a))
            self._record_goal(text, grounded)
            self.whisper.refresh(self.whisper_target)

            if at == "trigger" and trigger_t is not None:
                self._measure_switch(trigger_t, row, grounded, known_before)

            if at == "start":
                ni1_harness.wait_for_tasks(self.session._inner, timeout_s=8.0)

        # Drain to terminal and narrate what is owed.
        ids = set(self.session.task_states())
        ok, states = ni1_harness.wait_terminal(  # type: ignore[union-attr]
            self.session._inner, ids, deadline_s=280.0
        )
        self.log.write("await_terminal", PROV_SIM, step="final", reached=ok, states=states)
        self._score_arrival("final", goal_a, states)
        self._flush_narration()
        self.whisper.refresh(self.whisper_target)
        end_xy = self.session.pose()
        self.log.write(
            "navigator_state",
            PROV_SIM,
            step="final",
            end_xy=[round(end_xy[0], 3), round(end_xy[1], 3)],
            mission=self.session._inner.mission_metadata(),
            tasks=self.session.tasks(),
        )

    def _mb1_steer(self, text: str) -> dict | None:
        """MB-1's ``steer()`` verdict, RECORDED but not the authority.

        LIT-1's own rule stays the authority for the re-issue because L7 is
        binding on this experiment and names the exact semantics ("yes" resumes
        nothing by itself; the re-issue is a harness re-issue of the remembered
        directive text).  MB-1's classifier is logged next to it so the two can
        be compared without either being silently overridden.
        """

        if mb1_steer is None:
            return None
        with contextlib.suppress(Exception):
            events = _load_by_path("lit1_mb1_events", _MB1 / "events.py")
            record_cls = getattr(events, "QueueRecord", None) if events else None
            queue: tuple = ()
            if record_cls is not None:
                queue = tuple(
                    record_cls(
                        directive=item.directive_text,
                        goal=item.grounded_goal,
                        task_id=item.originating_task_id,
                        admitted_at=item.admitted_at,
                        status=item.status,
                    )
                    for item in self.whisper.queue
                )
            return dict(mb1_steer.steer(text, queue).as_dict())
        return {"error": "model-b-narration-1/steer.py refused this input"}

    def _score_arrival(self, step: str, goal_key: str, states: list) -> None:
        """The e2e's DIFFERENTIAL arrival authority, recorded unconditionally.

        Two verdicts, never blended: ``system_arrival`` (every task record went
        to ``succeeded``) and ``scorer_arrival`` (NAV-INT-1's K0 region on the
        final pose).  Their disagreement is the interesting row — NAV-INT-1's
        own bench control measured ``authority_disagreement`` with
        ``distance_to_goal_m == 0.0``, i.e. the robot standing ON the goal while
        the system reported a failure.
        """

        spec = ni1_harness.GOALS.get(goal_key)  # type: ignore[union-attr]
        if spec is None or spec.owner_anchored:
            self.log.write(
                "arrival_authority",
                PROV_SIM,
                step=step,
                goal=goal_key,
                scored=False,
                reason="no static K0 region for this goal in the peer catalogue",
            )
            return
        end_xy = self.session.pose()
        system_arrival = bool(states) and all(str(s) == "succeeded" for s in states)
        with contextlib.suppress(Exception):
            verdict = ni1_harness.score_arrival(  # type: ignore[union-attr]
                spec=spec, end_xy=end_xy, system_arrival=system_arrival
            )
            self.log.write(
                "arrival_authority",
                PROV_SIM,
                step=step,
                goal=goal_key,
                scored=True,
                end_xy=[round(end_xy[0], 3), round(end_xy[1], 3)],
                **verdict,
            )

    def _record_goal(self, text: str, grounded: str) -> None:
        """Bind the directive to the task the executive just accepted.

        The task id comes from the LAST executive receipt with one, not from
        "some row in the snapshot": a ``replace`` keeps the id of the task it
        revised, so picking an arbitrary row would attribute the amended goal to
        whichever task happened to sort last.
        """

        task_id = ""
        for receipt in reversed(self.tap.snapshot()):
            if receipt.task_id:
                task_id = receipt.task_id
                break
        if not task_id:
            states = self.session.task_states()
            task_id = next(iter(states), "")
        self.whisper.admit(
            directive=text, goal=grounded, task_id=task_id, t=self.log.now()
        )

    def _measure_switch(
        self,
        trigger_t: float,
        utterance_row: dict,
        grounded: str,
        known_before: dict[str, tuple[str, int]],
    ) -> None:
        """L9's headline row: owner finishes speaking → robot starts turning."""

        speech_end = float(utterance_row.get("t_handle_text_in") or trigger_t)
        goal_xy = self.goal_xy(grounded)
        # Give the body the L9 window to answer.
        deadline = time.monotonic() + CUE_WINDOW_AFTER_S
        while time.monotonic() < deadline:
            time.sleep(0.1)
        samples = self.instrument.window(
            speech_end - CUE_WINDOW_BEFORE_S, speech_end + CUE_WINDOW_AFTER_S
        )
        turn_t, evidence = first_turn_toward(samples, goal_xy=goal_xy, t_from=speech_end)
        # ``report()`` answers every dispatch, including the ones it drops as
        # stale.  ``ignored_stale_result`` is not a receipt about the owner's
        # sentence, so the cue -> receipt hop is measured against the STRUCTURAL
        # kinds only.
        receipts = [
            r for r in self.tap.snapshot() if r.t >= speech_end and r.kind in SEQUENCE_KINDS
        ]
        first_receipt = receipts[0] if receipts else None
        cue_t = getattr(self, "_cue_t", speech_end)
        self.latencies = {
            "trigger_s": round(trigger_t, 3),
            "speech_start_s": round(utterance_row.get("speech_start_t") or speech_end, 3),
            "speech_end_s": round(speech_end, 3),
            "cue_s": round(cue_t, 3),
            "trigger_to_speech_start_ms": round(
                ((utterance_row.get("speech_start_t") or speech_end) - trigger_t) * 1000.0, 1
            ),
            "utterance_to_cue_ms": round((cue_t - speech_end) * 1000.0, 1),
            "handle_text_ms": utterance_row.get("handle_text_ms"),
            # The hop that is actually about the owner's sentence.  The
            # executive receipt lands INSIDE ``handle_text``, before the harness
            # can read the intent metrics off the agent, so ``cue_to_receipt_ms``
            # is negative by construction — kept, because that ordering is
            # itself a fact about the stack and hiding it would be a choice.
            "speech_end_to_receipt_ms": (
                None
                if first_receipt is None
                else round((first_receipt.t - speech_end) * 1000.0, 1)
            ),
            "cue_to_receipt_ms": (
                None if first_receipt is None else round((first_receipt.t - cue_t) * 1000.0, 1)
            ),
            "first_receipt_kind": None if first_receipt is None else first_receipt.kind,
            "first_receipt_action": None if first_receipt is None else first_receipt.action,
            "switch_ms": None if turn_t is None else round((turn_t - speech_end) * 1000.0, 1),
            "switch_evidence": evidence,
            "known_before": {k: list(v) for k, v in known_before.items()},
            "goal_xy": [round(goal_xy[0], 3), round(goal_xy[1], 3)],
        }
        self.log.write("switch_latency", PROV_SIM, **self.latencies)


# ===========================================================================
# 10. CLI
# ===========================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LIT-1 — the well-instrumented loop")
    parser.add_argument("--scenario", default="door_sofa_keys")
    parser.add_argument("--variant", default="base")
    parser.add_argument("--voice", choices=("fake", "hosted", "none"), default="fake")
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--index", type=int, default=1)
    parser.add_argument("--outdir", default=str(HERE / "artifacts"))
    parser.add_argument("--smoke", action="store_true", help="one handle_text hop only")
    args = parser.parse_args(argv)

    os.environ.pop("TMPDIR", None)
    WORKROOT.mkdir(parents=True, exist_ok=True)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        return _smoke(outdir)

    scenario = scenario_variant(load_scenario(args.scenario), args.variant)
    results = []
    for run_index in range(args.index, args.index + args.runs):
        result = run_scenario(
            scenario,
            voice=args.voice,
            seed=args.seed,
            index=run_index,
            outdir=outdir,
            variant=args.variant,
        )
        results.append(result.as_dict())
        print(json.dumps(result.as_dict()["receipt_kinds"]))
    print(json.dumps(results, indent=2, default=str)[:4000])
    return 0


def _smoke(outdir: Path) -> int:
    """Step 1 of the build: sim + runtime + ONE handle_text hop, receipts printed."""

    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    emit("LIT-1 smoke — sim + runtime + one handle_text hop")
    emit(f"providers: {json.dumps(PROVIDERS)}")
    t0 = time.monotonic()
    guard = NameScan({"lamppost", "bench", "sidewalk", "crosswalk", "door", "sofa"})
    log = HopLog(outdir / "smoke.jsonl", t0=t0, guard=guard)
    session: SimSession | None = None
    instrument: MotionInstrument | None = None
    tap: ExecutiveTap | None = None
    try:
        session = SimSession(WORKROOT, index=99)
        emit(f"socket: {session.socket}  (owner's socket? "
             f"{str(session.socket) == FORBIDDEN_SOCKET})")
        runtime = session.runtime
        guard.bind_runtime(runtime)
        emit(f"_realtime_spend_note: {getattr(runtime, '_realtime_spend_note', '')!r}")
        emit(f"_curiosity_admitted_names(): {sorted(guard.runtime_admitted)}")
        instrument = MotionInstrument(runtime=runtime, clock=log.now)
        instrument.start()
        tap = ExecutiveTap(runtime.task_executive, clock=log.now)
        received: list[Receipt] = []
        tap.on_receipt = received.append
        tap.attach()
        emit("")
        emit("--- issuing: 'go to the lamppost' ---")
        utterance = session._inner.issue("go to the lamppost")
        emit(f"reply: {utterance.reply!r}")
        emit(f"metrics: {json.dumps(utterance.metrics, default=str)}")
        ids = set(session.task_states())
        ok, states = ni1_harness.wait_terminal(session._inner, ids, deadline_s=280.0)
        emit(f"terminal: {ok} states={states}")
        emit("")
        emit("--- receipt timeline (ReportDisposition.action + last_detail verbatim) ---")
        emit(f"{'t':>8}  {'kind':<24} {'action':<24} {'state':<12} {'rev':>3}  last_detail")
        for receipt in tap.snapshot():
            emit(
                f"{receipt.t:8.3f}  {receipt.kind:<24} {receipt.action:<24} "
                f"{receipt.state:<12} {receipt.plan_revision:>3}  {receipt.last_detail}"
            )
        kinds = [r.kind for r in tap.snapshot() if r.kind in SEQUENCE_KINDS]
        emit("")
        emit(f"structural receipt KIND sequence: {kinds}")
        samples = instrument.all()
        emit(f"motion samples: n={len(samples)} "
             f"({len(samples) / max(1e-6, log.now()):.1f} Hz)")
        if samples:
            emit(f"max |vyaw|: {max(abs(s.vyaw) for s in samples):.3f} rad/s; "
                 f"max speed: {max(math.hypot(s.vx, s.vy) for s in samples):.3f} m/s")
        emit(f"end pose: {session.pose()}")
    except Exception as error:  # noqa: BLE001
        emit(f"SMOKE FAILED: {type(error).__name__}: {error}")
        import traceback

        emit(traceback.format_exc())
    finally:
        if tap is not None:
            tap.detach()
        if instrument is not None:
            instrument.stop()
        if session is not None:
            session.close()
            proof = session.pgrep_proof()
            emit("")
            emit(f"teardown pgrep proof: {json.dumps(proof)}")
        log.close()
    (HERE / "sample_run.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {HERE / 'sample_run.txt'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
