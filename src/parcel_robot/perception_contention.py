"""GPU contention admission control for the perception path (card PG-1, item 4).

The finding this exists for
---------------------------
Measured twice, two different ways, agreeing on direction.

**PG-1, the shipping path** (this repo's ``OwlV2Detector`` on
``onnxruntime`` CUDA fp16, 1280x720, 11 queries, n=30, with Qwen3-VL-8B
generating in a **separate process** — the deployment shape, since Parcel's
generator is ``llama-server``):

===============================  ==========  ==========
detector latency, 1280x720        p50 (ms)    p95 (ms)
===============================  ==========  ==========
GPU idle                             76.6        85.5
8B VLM generating (other process)   125.9       131.8
===============================  ==========  ==========

**2026-08-21 bench, in-process** (torch fp16, same GPU,
``results/combined_contention.json``): 43.2 / 56.0 idle -> 80.6 / **150.4** with
the VLM generating in the SAME process, and a resident-but-idle VLM costing
essentially nothing (55.1 vs 56.0 p95).

What follows:

1. **Capacity is not the constraint.** The detector adds 1,366 MiB; the full
   stack with the 8B VLM measured 22,848 MiB of 32,760, leaving 9,912 MiB free.
   A resident-but-idle VLM is free (bench: 55.1 vs 56.0 ms p95).
2. **Concurrency is.** Cross-process, a generating model takes detector p95 from
   85.5 to 131.8 ms — **1.54x end-to-end**. That understates the GPU effect,
   because ~44 ms of the repo detector's time is CPU-side preprocessing that does
   not contend: netting it out, the GPU portion goes ~41 ms -> ~88 ms, about
   **2.1x**, which is the same order as the bench's in-process 2.69x.
3. Against the repo's own freshness contract
   (``contracts.freshness.DEFAULT_DETECTION_TTL_NS`` = 300 ms) that is one
   inference consuming **43.9%** of the entire detection TTL, up from 28.5%.
4. **You cannot optimise your way out of it.** The source-downscale knob does not
   rescue the contended case — measured here it is *slower* in both conditions
   (0.72x idle, 0.76x contended), and the bench found its idle 2.75x collapsing
   to 1.20x under contention. Scheduling is the only lever.

Why an ADMISSION RULE and not CUDA streams
------------------------------------------
The card offered two mechanisms: privileged CUDA streams, or an admission rule.
**Streams cannot work here, and the reason is structural, not a preference.**

CUDA stream priorities (``cudaStreamCreateWithPriority``) order work *within one
CUDA context*. Parcel's generator is not in this process and never has been: it
is ``llama-server``, a separate binary launched from the pinned profile
(``configs/reasoner/llama_cpp_cuda12_oci_b10236.json`` ->
``runtime.cuda_binary``, an ``app/llama-server`` entrypoint). Work submitted by a
different process lands in a different context, and the GPU driver time-slices
between contexts at its own granularity with **no user-space priority knob**
(absent MPS with explicit priority partitioning, which this deployment does not
run). A stream priority set inside the Python process would order the detector
against *itself* and would not order it against the reasoner by one microsecond.

So the mechanism is admission control: **the long-running generation is the thing
that gets refused, because it is the thing that can wait.** The detector never
asks permission; it runs. That asymmetry IS the priority pin.

The rule
--------
While any :meth:`PerceptionContentionGuard.mission_lease` is held, a generation
may start only if its *declared* duration is within
:attr:`ContentionPolicy.max_generation_ms_while_active`. Defaults are
fail-closed:

* the default budget is **0.0 ms**, i.e. no generation starts while a lease is
  held. The measurements justify the strictness: a 64-new-token generation in
  another process moved detector p95 by 1.54x end-to-end (~2.1x on the GPU
  portion), and the bench's in-process 32-token generation moved it 2.69x. There
  is no measured "short enough to be free" generation. The knob exists so the
  owner can loosen it *with evidence*, not so the default can be optimistic.
* an **undeclared** duration (``None``) is treated as unbounded and refused. An
  unknown generation length is not assumed short.
* leases carry a TTL so a crashed holder cannot starve speech forever; expiry is
  logged at WARNING, never silently.

SCOPE — what this does NOT yet protect (read this before trusting it)
---------------------------------------------------------------------
Today the person-yield / reactive-safety path does **not** consume the detector.
It rides the dynamic-agent channel, and the live mission path reads MuJoCo
ground truth (``extract_city_semantics``); ``runtime.attach_camera_ingress()``
has zero non-test call sites. So this guard protects the path the perception
cutover will *create*, not a live regression today. It is landed now because the
measurement exists now and because retrofitting scheduling after a cutover is how
safety paths acquire latency bugs. The consumer half — the generation entry point
calling :meth:`try_admit_generation` — is an owner-gated follow-up: it lives in
``realtime/*``, which card PG-1 must not touch. The exact seam is named in
``PG1_STATUS.md``.

HONESTY (P0)
------------
Both contention numbers used **Qwen3-VL-8B** as the generator, not
``llama-server`` with Parcel's actual reasoner weights. The cross-process run is
the right SHAPE (separate CUDA context, driver-scheduled) but not the right
model: a different architecture, KV-cache size and decode rate would move the
magnitude. The direction and the mechanism argument hold; the specific 1.54x does
not transfer to llama-server and is not claimed to.

Also: the (b) "VLM resident but idle" cell of ``pg1_contention.json`` is NOT a
resident-idle measurement. The hammer process begins generating immediately after
signalling readiness, so (b) and (c) are two samples of the same contended
condition (124.7 vs 125.9 ms p50) and are reported as such. The resident-idle-is-
free finding comes from the 2026-08-21 bench alone.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

logger = logging.getLogger(__name__)

#: Detection freshness budget this guard is sized against. Mirrors
#: ``contracts.freshness.DEFAULT_DETECTION_TTL_NS`` (300 ms); imported as a plain
#: constant to keep this module dependency-free for the safety path.
DETECTION_TTL_MS = 300.0

#: PG-1 measurement on the SHIPPING path: this repo's OwlV2Detector under
#: onnxruntime CUDA fp16, 1280x720, 11 queries, batch 1, n=30, contended by an
#: 8B VLM generating in a SEPARATE PROCESS (results/pg1_contention.json).
MEASURED_P95_IDLE_MS = 85.5
MEASURED_P95_VLM_GENERATING_MS = 131.8

#: The 2026-08-21 bench's IN-PROCESS numbers (torch fp16), kept for provenance.
#: Different runtime and different concurrency shape, same direction; the
#: cross-process figures above are the ones this guard is sized against because
#: they match how Parcel actually deploys its generator.
BENCH_INPROCESS_P95_IDLE_MS = 56.0
BENCH_INPROCESS_P95_VLM_GENERATING_MS = 150.4

#: Default lease TTL. A mission leg that has not renewed its lease within this
#: window is presumed dead, and speech is un-blocked rather than starved. Sized
#: as an order of magnitude above the contended detector p95, not guessed.
DEFAULT_LEASE_TTL_S = 2.0

#: Fail-closed default: no generation may START while a safety lease is held.
DEFAULT_MAX_GENERATION_MS_WHILE_ACTIVE = 0.0


class ContentionPolicyError(ValueError):
    """Raised for a policy that would disable the guard by construction."""


@dataclass(frozen=True, slots=True)
class ContentionPolicy:
    """Admission policy. Validated so it cannot be silently neutered.

    ``max_generation_ms_while_active`` must be finite and non-negative: a policy
    of ``inf`` would admit every generation and turn this module into a no-op
    that still *looks* installed, which is the exact failure mode a deferred
    audit cannot catch by reading call sites.
    """

    max_generation_ms_while_active: float = DEFAULT_MAX_GENERATION_MS_WHILE_ACTIVE
    lease_ttl_s: float = DEFAULT_LEASE_TTL_S

    def __post_init__(self) -> None:
        budget = self.max_generation_ms_while_active
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            raise ContentionPolicyError("max_generation_ms_while_active must be numeric")
        if math.isnan(budget) or math.isinf(budget):
            raise ContentionPolicyError(
                "max_generation_ms_while_active must be finite; an infinite budget "
                "admits every generation and silently disables the guard"
            )
        if budget < 0.0:
            raise ContentionPolicyError("max_generation_ms_while_active must be >= 0")
        if budget >= DETECTION_TTL_MS:
            raise ContentionPolicyError(
                f"max_generation_ms_while_active={budget} exceeds the detection freshness "
                f"TTL ({DETECTION_TTL_MS} ms); admitting it would guarantee a stale detection"
            )
        ttl = self.lease_ttl_s
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0.0:
            raise ContentionPolicyError("lease_ttl_s must be a positive number")
        if math.isnan(ttl) or math.isinf(ttl):
            raise ContentionPolicyError(
                "lease_ttl_s must be finite; a never-expiring lease lets a crashed "
                "mission starve generation forever"
            )


@dataclass(frozen=True, slots=True)
class LeaseInfo:
    """A live safety-relevant lease."""

    lease_id: int
    reason: str
    acquired_monotonic_s: float
    expires_monotonic_s: float


@dataclass(frozen=True, slots=True)
class Admission:
    """The verdict on one generation request."""

    admitted: bool
    reason: str
    blocking_leases: tuple[str, ...] = field(default_factory=tuple)
    retry_after_s: float = 0.0

    def __bool__(self) -> bool:
        return self.admitted


class PerceptionContentionGuard:
    """Thread-safe admission control between safety-relevant inference and generation.

    The detector never calls into this guard to ask permission — it calls
    :meth:`mission_lease` to *declare* that a safety-relevant window is open, and
    then runs. Only :meth:`try_admit_generation` can be refused.
    """

    def __init__(
        self,
        policy: ContentionPolicy | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._policy = policy if policy is not None else ContentionPolicy()
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.RLock()
        self._leases: dict[int, LeaseInfo] = {}
        self._next_id = 1
        self._refusals = 0
        self._admissions = 0
        self._expired = 0

    @property
    def policy(self) -> ContentionPolicy:
        return self._policy

    # -- leases --------------------------------------------------------------
    @contextmanager
    def mission_lease(self, reason: str, *, ttl_s: float | None = None) -> Iterator[LeaseInfo]:
        """Declare a safety-relevant window. Reentrant; always released."""

        lease = self.acquire_lease(reason, ttl_s=ttl_s)
        try:
            yield lease
        finally:
            self.release_lease(lease)

    def acquire_lease(self, reason: str, *, ttl_s: float | None = None) -> LeaseInfo:
        text = str(reason).strip() or "unspecified"
        ttl = float(ttl_s) if ttl_s is not None else self._policy.lease_ttl_s
        if ttl <= 0.0:
            raise ContentionPolicyError("lease ttl_s must be positive")
        now = self._clock()
        with self._lock:
            lease = LeaseInfo(
                lease_id=self._next_id,
                reason=text,
                acquired_monotonic_s=now,
                expires_monotonic_s=now + ttl,
            )
            self._next_id += 1
            self._leases[lease.lease_id] = lease
            return lease

    def release_lease(self, lease: LeaseInfo) -> None:
        with self._lock:
            self._leases.pop(lease.lease_id, None)

    def renew_lease(self, lease: LeaseInfo, *, ttl_s: float | None = None) -> LeaseInfo:
        """Push a lease's expiry out. A long mission leg renews; it does not re-acquire."""

        ttl = float(ttl_s) if ttl_s is not None else self._policy.lease_ttl_s
        with self._lock:
            if lease.lease_id not in self._leases:
                raise KeyError(f"lease {lease.lease_id} is not held (released or expired)")
            renewed = replace(lease, expires_monotonic_s=self._clock() + ttl)
            self._leases[lease.lease_id] = renewed
            return renewed

    def active_leases(self) -> tuple[LeaseInfo, ...]:
        """Live, unexpired leases. Reaps expired ones (loudly) as a side effect."""

        now = self._clock()
        with self._lock:
            dead = [lid for lid, li in self._leases.items() if li.expires_monotonic_s <= now]
            for lid in dead:
                stale = self._leases.pop(lid)
                self._expired += 1
                logger.warning(
                    "perception contention: lease %d (%s) expired after %.2fs without "
                    "release or renewal — generation is no longer blocked by it",
                    stale.lease_id,
                    stale.reason,
                    now - stale.acquired_monotonic_s,
                )
            return tuple(sorted(self._leases.values(), key=lambda li: li.lease_id))

    # -- admission -----------------------------------------------------------
    def try_admit_generation(
        self, *, estimated_ms: float | None, kind: str = "generation"
    ) -> Admission:
        """May a long-running generation start right now?

        ``estimated_ms=None`` means "duration unknown", which is refused whenever
        a lease is held — an undeclared generation length is not assumed short.
        """

        leases = self.active_leases()
        if not leases:
            with self._lock:
                self._admissions += 1
            return Admission(True, f"no safety lease held; {kind} admitted")

        budget = self._policy.max_generation_ms_while_active
        reasons = tuple(li.reason for li in leases)
        now = self._clock()
        retry = max(0.0, max(li.expires_monotonic_s for li in leases) - now)

        if estimated_ms is None:
            with self._lock:
                self._refusals += 1
            return Admission(
                False,
                f"{kind} has an undeclared duration and {len(leases)} safety lease(s) are held; "
                "an unknown generation length is treated as unbounded (fail-closed)",
                blocking_leases=reasons,
                retry_after_s=retry,
            )

        est = float(estimated_ms)
        if math.isnan(est) or est < 0.0:
            with self._lock:
                self._refusals += 1
            return Admission(
                False,
                f"{kind} declared a non-sensical duration {estimated_ms!r}; refused fail-closed",
                blocking_leases=reasons,
                retry_after_s=retry,
            )
        if est <= budget:
            with self._lock:
                self._admissions += 1
            return Admission(
                True,
                f"{kind} estimated {est:.1f} ms is within the {budget:.1f} ms "
                "while-active budget",
                blocking_leases=reasons,
            )
        with self._lock:
            self._refusals += 1
        return Admission(
            False,
            f"{kind} estimated {est:.1f} ms exceeds the {budget:.1f} ms budget while "
            f"{len(leases)} safety lease(s) are held; starting it would put detector p95 on "
            f"the measured contended path ({MEASURED_P95_IDLE_MS:.0f} -> "
            f"{MEASURED_P95_VLM_GENERATING_MS:.0f} ms, {DETECTION_TTL_MS:.0f} ms TTL)",
            blocking_leases=reasons,
            retry_after_s=retry,
        )

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "admitted": self._admissions,
                "refused": self._refusals,
                "expired_leases": self._expired,
                "active_leases": len(self._leases),
            }


_GUARD_LOCK = threading.Lock()
_GUARD: PerceptionContentionGuard | None = None


def default_guard() -> PerceptionContentionGuard:
    """The process-wide guard. Both halves (detector, generator) must share one."""

    global _GUARD
    with _GUARD_LOCK:
        if _GUARD is None:
            _GUARD = PerceptionContentionGuard()
        return _GUARD


def set_default_guard(guard: PerceptionContentionGuard | None) -> None:
    """Install (or reset with ``None``) the process-wide guard. Tests only."""

    global _GUARD
    with _GUARD_LOCK:
        _GUARD = guard


__all__ = [
    "BENCH_INPROCESS_P95_IDLE_MS",
    "BENCH_INPROCESS_P95_VLM_GENERATING_MS",
    "DEFAULT_LEASE_TTL_S",
    "DEFAULT_MAX_GENERATION_MS_WHILE_ACTIVE",
    "DETECTION_TTL_MS",
    "MEASURED_P95_IDLE_MS",
    "MEASURED_P95_VLM_GENERATING_MS",
    "Admission",
    "ContentionPolicy",
    "ContentionPolicyError",
    "LeaseInfo",
    "PerceptionContentionGuard",
    "default_guard",
    "set_default_guard",
]
