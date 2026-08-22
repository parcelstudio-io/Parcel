"""Where the veto is allowed to run, and where it is not (card P1-D, item 1).

The one rule
------------
**The VLM never runs inside the 10 Hz loop.** Every VLM size measured breaches
the 100 ms detector bound while generating (``bench_vlm.md``), so a veto call on
the control thread is a safety regression wearing a perception costume. The rule
is enforced three ways, deliberately overlapping:

1. **Structurally** — nothing in ``RobotRuntime``'s dispatch path imports this
   module, and ``tests/test_p1d_vlm_veto.py`` AST-asserts that the loop calls no
   runner method, the way ``test_c1_camera_stream.py`` asserts the camera
   producer is out of the loop.
2. **At runtime** — :meth:`VetoRunner.veto_for` refuses to run on a thread that
   has declared itself the control loop (:func:`mark_control_thread`). This is
   not belt-and-braces decoration: the AST check can only see the call sites
   that exist today, and the tripwire sees the one somebody adds tomorrow.
3. **By admission** — the runner asks
   :class:`~parcel_robot.perception_contention.PerceptionContentionGuard`
   before every call, so the guard's counters record what ran while a mission
   lease was held.

The lease relaxation, and why it is not a loosening of PG-1's finding
--------------------------------------------------------------------
``perception_contention``'s default is that **no** generation starts while a
safety lease is held, and its docstring argues — correctly — that CUDA stream
priorities cannot help, because Parcel's generator is ``llama-server`` in a
*separate process* and cross-process work lands in a different CUDA context that
the driver time-slices with no user-space priority knob.

An earlier draft of this card claimed the veto escaped that argument by running
on a low-priority CUDA stream in the detector's own context. **That claim was
false and has been removed.** ``torch.cuda.Stream.priority_range()`` returns
least-priority first, so the "low" priority requested was ``0`` — the default
stream's own priority, with nothing below it for the detector to preempt. And
the same-context premise dies anyway the moment P1-A's out-of-process detector
daemon lands.

What actually justifies the second budget is not scheduling, it is **duration**,
and duration is measurable. A veto asks for four tokens; measured on this host,
41.2 ms p50 / 44.9 ms p95 over 80 calls. So P1-D adds
``ContentionPolicy.veto_budget_ms_while_active`` and leaves
``max_generation_ms_while_active`` at 0.0, untouched — the llama-server refusal
is exactly as strict as PG-1 left it — and the runner declares its **own
measured EMA** rather than a constant, so the guard is deciding against what
this seat actually costs today. A COLD seat declares ``inf`` and is therefore
refused under a lease: loading 4.4 GB of weights is seconds, and no budget
covers it. The load is paid at install (:func:`runner_for`), off any lease.

Card §9's instruction was "nothing is refused". This runner's honest version of
that is: nothing is refused *for contention*, and a veto that would exceed its
budget degrades to :data:`~parcel_robot.perception_abstention.VETO_UNAVAILABLE`
— which the gate reads as ASK. The dog asks; it does not refuse, and it does not
push the detector off its frame budget either.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from parcel_robot.perception_abstention import (
    VETO_ABSENT,
    VETO_PRESENT,
    VETO_UNAVAILABLE,
    PlaceEvidence,
)
from parcel_robot.perception_contention import (
    PerceptionContentionGuard,
    default_guard,
)
from parcel_robot.vlm_veto.verifier import (
    MODEL_REPO,
    NullVerifier,
    Qwen3VLVerifier,
    VetoAnswer,
    VetoRequest,
    active_verifier,
    warm_up_png,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_VETO_ESTIMATE_MS",
    "LATENCY_EMA_ALPHA",
    "LOOP_FORBIDDEN_CALLS",
    "NULL_SEAT_NAMES",
    "CropSource",
    "VetoRunner",
    "clear_control_thread",
    "clear_seats",
    "in_control_thread",
    "mark_control_thread",
    "runner_for",
]

#: Seed for the latency estimate, used ONLY until this seat has answered once.
#: From the 2026-08-21 bench: Qwen3-VL-2B answered in 89 ms at 48 new tokens.
#: After the first real answer the estimate is the seat's own measured EMA —
#: see :attr:`VetoRunner.estimated_ms`. A declared constant is a promise the
#: code cannot keep; an EMA is a claim about time that the guard can check.
DEFAULT_VETO_ESTIMATE_MS = 90.0

#: Weight on the newest sample in the latency EMA. 0.25 tracks a slow drift
#: (a longer crop, a busier GPU) within a handful of calls without letting one
#: unlucky call close the gate.
LATENCY_EMA_ALPHA = 0.25

#: A COLD seat has to load 4.4 GB of weights before it can answer, which is
#: seconds, not milliseconds — so a cold call under a held safety lease is the
#: one thing this runner must never do. The seat is warmed at INSTALL, off any
#: lease; a veto requested while the seat is still cold and a lease is held is
#: declined (and therefore asked) rather than run.
COLD_SEAT_ESTIMATE_MS = float("inf")

#: Throwaway answers taken at install. The first pays CUDA kernel selection
#: (measured 719 ms on this host after a load); the second is the seat's real
#: speed (41-48 ms) and is what seeds the latency EMA.
WARM_UP_ANSWERS = 2

#: The runner methods that must never appear in the control loop's call graph.
#: ``tests/test_p1d_vlm_veto.py`` reads this tuple rather than re-typing it, so
#: a method added here is a method the AST assert starts protecting.
LOOP_FORBIDDEN_CALLS = (
    "veto_for",
    "verify",
    "describe",
    "run_batch",
    "load",
)

_CONTROL_THREADS: set[int] = set()
_CONTROL_LOCK = threading.Lock()


def mark_control_thread(thread_id: int | None = None) -> None:
    """Declare the calling thread (or ``thread_id``) to be the 10 Hz loop."""

    tid = int(thread_id) if thread_id is not None else threading.get_ident()
    with _CONTROL_LOCK:
        _CONTROL_THREADS.add(tid)


def clear_control_thread(thread_id: int | None = None) -> None:
    tid = int(thread_id) if thread_id is not None else threading.get_ident()
    with _CONTROL_LOCK:
        _CONTROL_THREADS.discard(tid)


def in_control_thread() -> bool:
    with _CONTROL_LOCK:
        return threading.get_ident() in _CONTROL_THREADS


class ControlLoopViolation(RuntimeError):
    """A veto was requested from the thread that owns the 10 Hz loop."""


#: How the runner gets a best-view crop for a place. C-2 keeps one bounded
#: thumbnail per entry (``MapEntry.thumbnail``); P1-A's camera daemon will keep a
#: fresher one. Either satisfies this, and neither is imported here.
CropSource = Callable[[str], bytes | None]


@dataclass(frozen=True, slots=True)
class VetoStats:
    asked: int = 0
    present: int = 0
    absent: int = 0
    unavailable: int = 0
    budget_declined: int = 0
    loop_refusals: int = 0
    total_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "asked": self.asked,
            "present": self.present,
            "absent": self.absent,
            "unavailable": self.unavailable,
            "budget_declined": self.budget_declined,
            "loop_refusals": self.loop_refusals,
            "mean_ms": round(self.total_ms / self.asked, 3) if self.asked else 0.0,
        }


class VetoRunner:
    """Runs the veto off the control loop, under the contention guard.

    Construct it with the seat and a way to find a crop; hand
    :meth:`veto_callable` to ``assess_place_query`` and the gate gains its
    subtractive signal without ever learning that a GPU exists.
    """

    def __init__(
        self,
        verifier: Any = None,
        *,
        crop_source: CropSource | None = None,
        guard: PerceptionContentionGuard | None = None,
        estimate_ms: float = DEFAULT_VETO_ESTIMATE_MS,
    ) -> None:
        self._verifier = verifier if verifier is not None else active_verifier()
        self._crop_source = crop_source
        self._guard = guard if guard is not None else default_guard()
        self._seed_estimate_ms = float(estimate_ms)
        self._ema_ms: float | None = None
        self._warm = False
        self._lock = threading.Lock()
        self._stats = VetoStats()

    @property
    def verifier(self) -> Any:
        return self._verifier

    @property
    def estimated_ms(self) -> float:
        """What this seat will be admitted against, right now.

        ``inf`` while the seat is COLD, because a cold call pays a multi-second
        weight load and no honest budget covers that. The guard refuses ``inf``
        against any finite budget, so a cold veto under a held lease is declined
        and the gate asks — which costs a question and keeps the detector's
        frames. Once warm it is the seat's own measured EMA, never a constant.
        """

        with self._lock:
            if not self._warm:
                return COLD_SEAT_ESTIMATE_MS
            return self._ema_ms if self._ema_ms is not None else self._seed_estimate_ms

    def warm_up(self) -> bool:
        """Load the seat and take one throwaway answer. **Never under a lease.**

        Called at INSTALL time (see :func:`runner_for`), where no mission lease
        is held, so the cold cost is paid when nothing is depending on the
        detector. Returns whether the seat is now usable.

        A seat with no ``load`` (``NullVerifier``, a stub) is warm by
        definition: it answers instantly and there is nothing to preload.
        """

        with self._lock:
            if self._warm:
                return True
        loader = getattr(self._verifier, "load", None)
        if loader is None:
            with self._lock:
                self._warm = True
            return True
        if self._guard.active_leases():
            logger.warning(
                "vlm_veto: refusing to warm a cold seat while %d safety lease(s) "
                "are held; the load is seconds, not milliseconds",
                len(self._guard.active_leases()),
            )
            return False
        try:
            loader()
        except Exception as exc:  # noqa: BLE001 - an unloadable seat stays cold
            logger.warning("vlm_veto: seat failed to warm (%s)", exc)
            return False
        # ...and ONE THROWAWAY ANSWER. Loading the weights is not the whole cold
        # cost: the first generation also pays CUDA kernel selection and
        # allocator growth. Measured on this host, warming with a load alone
        # left the seat's first real answers averaging 127 ms against a 120 ms
        # budget, so the EMA opened ABOVE the budget and the guard would have
        # started declining vetoes under a lease. With a throwaway answer here
        # the EMA settles near the steady-state 41 ms. The result is discarded;
        # only the latency is kept.
        # TWO throwaway answers, and the EMA is seeded from the SECOND.
        #
        # Loading the weights is not the whole cold cost and neither is the
        # first generation: measured on this host, the first answer after a
        # load takes 719 ms (CUDA kernel selection, allocator growth) and the
        # steady state is 41-48 ms. Seeding the EMA from that first answer left
        # it at 115 ms after eight real vetoes — inside the 120 ms budget but
        # only just, and for a reason that had nothing to do with the seat's
        # actual speed. The second answer is the seat.
        #
        # The VERDICTS are discarded (they are questions about a gradient);
        # only the latency is kept. The warm crop is 64 px, the same size the
        # map's stored thumbnail is, so the seed is representative.
        crop = warm_up_png()
        for attempt in range(WARM_UP_ANSWERS):
            try:
                answer = self._verifier.verify(
                    VetoRequest(noun="warm-up", crop_png=crop)
                )
            except Exception as exc:  # noqa: BLE001 - a failed warm answer is not fatal
                logger.warning("vlm_veto: warm-up answer failed (%s)", exc)
                break
            if attempt == WARM_UP_ANSWERS - 1:
                self._observe_latency(answer.latency_ms)
        return self._mark_warm()

    def _mark_warm(self) -> bool:
        with self._lock:
            self._warm = True
        return True

    def _observe_latency(self, latency_ms: float) -> None:
        value = float(latency_ms)
        if not math.isfinite(value) or value <= 0.0:
            return
        with self._lock:
            # A real answer proves the seat is loaded, whatever warm_up did.
            self._warm = True
            if self._ema_ms is None:
                self._ema_ms = value
            else:
                self._ema_ms = (
                    LATENCY_EMA_ALPHA * value
                    + (1.0 - LATENCY_EMA_ALPHA) * self._ema_ms
                )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return self._stats.as_dict()

    def _record(self, answer: VetoAnswer) -> VetoAnswer:
        self._observe_latency(answer.latency_ms)
        with self._lock:
            s = self._stats
            self._stats = VetoStats(
                asked=s.asked + 1,
                present=s.present + (answer.verdict == VETO_PRESENT),
                absent=s.absent + (answer.verdict == VETO_ABSENT),
                unavailable=s.unavailable + (answer.verdict == VETO_UNAVAILABLE),
                budget_declined=s.budget_declined,
                loop_refusals=s.loop_refusals,
                total_ms=s.total_ms + float(answer.latency_ms),
            )
        return answer

    def _decline(self, detail: str, *, budget: bool = False, loop: bool = False) -> VetoAnswer:
        with self._lock:
            s = self._stats
            self._stats = VetoStats(
                asked=s.asked,
                present=s.present,
                absent=s.absent,
                unavailable=s.unavailable + 1,
                budget_declined=s.budget_declined + budget,
                loop_refusals=s.loop_refusals + loop,
                total_ms=s.total_ms,
            )
        return VetoAnswer(VETO_UNAVAILABLE, detail=detail, model=getattr(self._verifier, "name", ""))

    def veto_for(self, query: str, place: PlaceEvidence) -> VetoAnswer:
        """The gate's entry point. Never call this from the control loop."""

        if in_control_thread():
            self._decline("refused: the control loop may not run a VLM", loop=True)
            raise ControlLoopViolation(
                "vlm_veto.veto_for was called on the 10 Hz control thread; every "
                "measured VLM breaches the 100 ms detector bound while generating"
            )
        admission = self._guard.try_admit_veto(estimated_ms=self.estimated_ms)
        if not admission.admitted:
            # Not a refusal of the QUERY — a refusal of this GPU moment. The gate
            # reads unavailable as ASK, so the owner gets a question and the
            # detector keeps its frame budget.
            return self._decline(f"contention: {admission.reason}", budget=True)
        # The evidence carries the pixels. ``PlaceEvidence.crop_png`` is
        # populated by whichever producer built the candidate (the online map
        # from its stored best-view thumbnail, ``place_evidence_from_mapping``
        # from the candidate metadata), so the runner never has to know where
        # places live. ``crop_source`` remains as the seam P1-A's daemon will
        # use to supply a FRESHER crop than the 64-px one the map stores.
        crop = getattr(place, "crop_png", None)
        if crop is None and self._crop_source is not None:
            try:
                crop = self._crop_source(place.place_id)
            except Exception as exc:  # noqa: BLE001 - a missing crop is unavailable
                return self._decline(f"crop source failed: {exc}")
        request = VetoRequest(
            noun=query, crop_png=crop, place_id=place.place_id, label=place.label
        )
        try:
            answer = self._verifier.verify(request)
        except Exception as exc:  # noqa: BLE001 - a broken seat is unavailable
            return self._decline(f"verifier raised: {exc}")
        return self._record(answer)

    def veto_callable(self) -> Callable[[str, PlaceEvidence], VetoAnswer]:
        """Bind :meth:`veto_for` for ``assess_place_query(veto=...)``."""

        return self.veto_for

    # -- idle-time batch ----------------------------------------------------

    def run_batch(
        self,
        items: Iterable[tuple[str, bytes | None]],
        *,
        describe: bool = True,
        budget_s: float = 0.0,
    ) -> list[tuple[str, Any]]:
        """Name or verify a batch of crops off the loop, with a wall budget.

        ``budget_s <= 0`` means no budget. The batch stops early when the budget
        is spent rather than being interrupted mid-answer, because a half-decoded
        name is not a name.
        """

        if in_control_thread():
            raise ControlLoopViolation("the control loop may not run a VLM batch")
        started = time.monotonic()
        out: list[tuple[str, Any]] = []
        for key, crop in items:
            if budget_s > 0.0 and (time.monotonic() - started) >= budget_s:
                break
            if describe:
                out.append((key, self._verifier.describe(crop)))
            else:
                out.append((key, self._verifier.verify(VetoRequest(noun=key, crop_png=crop))))
        return out


def _worker_queue() -> queue.SimpleQueue[Any]:  # pragma: no cover - seam for P1-A
    """Reserved for P1-A's out-of-process detector daemon.

    When that lands the veto moves behind the same IPC the detector uses and
    this process stops holding 4.4 GB of VRAM. Until then the seat is
    in-process, which the card permits ("on the GPU daemon if P1-A has landed,
    else in-process").
    """

    return queue.SimpleQueue()


_DEFAULT_RUNNER_LOCK = threading.Lock()
_DEFAULT_RUNNER: VetoRunner | None = None


def default_runner() -> VetoRunner:
    global _DEFAULT_RUNNER
    with _DEFAULT_RUNNER_LOCK:
        if _DEFAULT_RUNNER is None:
            _DEFAULT_RUNNER = VetoRunner(NullVerifier())
        return _DEFAULT_RUNNER


def use_runner(runner: VetoRunner | None) -> None:
    global _DEFAULT_RUNNER
    with _DEFAULT_RUNNER_LOCK:
        _DEFAULT_RUNNER = runner


# ------------------------------------------------------- the config seam ---
#
# ``perception_abstention.resolve_veto`` calls this and nothing else does. It is
# the ONLY place a model id becomes a running seat, so "what does the config
# name and what did it get" has one answer.

_SEATS_LOCK = threading.Lock()
_SEATS: dict[str, VetoRunner] = {}

#: Config spellings that mean "no seat, ask instead". ``""`` is what a profile
#: that never mentions ``veto_model`` produces, so the default is a question.
NULL_SEAT_NAMES = frozenset({"", "null", "none", "off", "disabled"})


def runner_for(model_id: str) -> VetoRunner:
    """Build (once) the seat a config named, warmed and ready to be asked.

    The crop comes from the ``PlaceEvidence`` the gate is already holding, so no
    crop source is wired here: the evidence carries the pixels and the runner
    stays ignorant of where places live.

    **Warm-up happens here**, at install, because this is a place where no
    mission lease is held. Doing it lazily on the first veto would put a
    multi-second weight load inside a grounding call that may well be running
    under one, which is the exact failure the contention guard exists to
    prevent. If the seat cannot be warmed the runner is still returned — it will
    answer ``unavailable``, and the gate will ask.
    """

    key = str(model_id or "").strip()
    with _SEATS_LOCK:
        existing = _SEATS.get(key)
        if existing is not None:
            return existing
    if key.lower() in NULL_SEAT_NAMES:
        runner = VetoRunner(NullVerifier(), crop_source=_crop_from_place)
    else:
        runner = VetoRunner(
            Qwen3VLVerifier(weights=None) if key == MODEL_REPO else _named_seat(key),
            crop_source=_crop_from_place,
        )
    runner.warm_up()
    with _SEATS_LOCK:
        return _SEATS.setdefault(key, runner)


def _named_seat(model_id: str) -> Any:
    """A seat for a model id this build knows. Unknown ids get the null seat.

    Deliberately NOT a plugin lookup: an id that resolves to "whatever is
    importable" is how a perception seat gets swapped without an eval, which is
    the 2026-08-21 llmdet lesson written into ``SYNTHESIS.md``'s process
    finding. One id, one class, and an unknown id asks rather than guessing.
    """

    logger.warning(
        "vlm_veto: unknown veto_model %r; the gate will ASK rather than verify. "
        "Known ids: %s",
        model_id,
        MODEL_REPO,
    )
    return NullVerifier()


def _crop_from_place(place_id: str) -> bytes | None:  # pragma: no cover - see below
    """Never called: the crop rides on ``PlaceEvidence.crop_png``.

    Kept as an explicit no-op so the runner's ``crop_source`` seam still exists
    for P1-A's daemon, which WILL want to fetch a fresher crop by place id than
    the 64-px thumbnail the map stores.
    """

    del place_id
    return None


def clear_seats() -> None:
    """Drop every built seat. Tests only."""

    with _SEATS_LOCK:
        _SEATS.clear()
