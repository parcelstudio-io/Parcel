"""The load guard for wall-clock assertions. Card R26, work item 3.

WHY THIS EXISTS
---------------
A handful of tests in this repo assert on **wall-clock duration** — "the 10 Hz
hot path's median tick is under 176 ms", "this vectorized cost field costs under
2 ms a call". On an idle machine they measure the code. On a contended one they
measure the machine, and they redden a commit gate that has nothing to do with
them. That is not hypothetical: the full audit (``AUDIT_FULL_FABLE.md``
§Tests) recorded them reddening at least six gate runs across four cards, with
no owning card, while the owner's ``llama-server`` was at 1469 % CPU.

WHAT THIS IS NOT
----------------
It is not a retry, and it is not an ``xfail``. Both of those turn a real
regression into a shrug. This guard **skips with a named reason that carries the
measurement**, so a reader of the gate output can tell "we did not measure this,
and here is the load we refused to measure it under" apart from "we measured it
and it was fine". A skip is a gap in evidence and prints like one.

THE THRESHOLD IS DERIVED FROM THE RECORDED REDS, NOT GUESSED
------------------------------------------------------------
Four data points exist in the repo's own status docs, all on the same 192-core
host:

===========================  ====================  =============  =======
Run                          1-min load / CPUs     busy fraction  verdict
===========================  ====================  =============  =======
R8 gate 03:55Z + 04:02Z      66.6 / 192            0.347          RED
R13 gate (first)             65   / 192            0.339          RED
R8 gate (green)              50   / 192            0.260          green
R13 gate (green)             20   / 192            0.104          green
===========================  ====================  =============  =======

``BUSY_FRACTION = 0.30`` is the only round number that separates every recorded
red from every recorded green. It is a measurement-derived pin, and if it is ever
moved the reason belongs next to it, the way ``DIGEST_SENTINELS`` re-pins do.

``MIN_ABSOLUTE_LOAD`` keeps a small machine usable: on a 2-core runner
``0.30 x 2 = 0.6`` would call an ordinary background job "contention" and the
guarded tests would never run anywhere. The effective ceiling is therefore
``max(cpus * BUSY_FRACTION, MIN_ABSOLUTE_LOAD)``.

THE NIGHTLY TURNS IT OFF
------------------------
``PARCEL_LOAD_GUARD=off`` makes :func:`contention_reason` return ``None``
unconditionally, so the guarded tests always run. The nightly tier sets it,
because the nightly is the tier where load is controlled — and because a guard
that can skip in *every* tier is a guard that can silently delete a test. The
variable is fail-closed on anything it does not recognise: a typo raises rather
than quietly choosing a mode.

OWNERSHIP
---------
Card R26 (``scrum/20260821/task_5``) owns this module and the ``load_sensitive``
marker. The tests carrying the marker are enumerated in ``R26_STATUS.md`` §"The
tier map" and in ``docs/CI.md``. They are no longer unowned.
"""

from __future__ import annotations

import os

#: Fraction of the machine's CPUs that may be busy before a wall-clock assertion
#: is considered unmeasurable. Derived from the recorded reds above.
BUSY_FRACTION = 0.30

#: Floor on the ceiling, so a 1-2 core runner is not permanently "contended".
MIN_ABSOLUTE_LOAD = 1.5

#: Environment switch. Unset / ``on`` measures; ``off`` never skips. Anything
#: else raises — a guard whose mode can be set by a typo is not a guard.
MODE_ENV = "PARCEL_LOAD_GUARD"
MODE_ON = "on"
MODE_OFF = "off"
VALID_MODES = (MODE_ON, MODE_OFF)

#: Card tag carried in every skip reason so the skip is traceable to an owner.
OWNER = "card R26 (scrum/20260821/task_5)"


class LoadGuardMisconfigured(RuntimeError):
    """Raised for an unrecognised :data:`MODE_ENV` value."""


def read_mode(env: dict[str, str] | None = None) -> str:
    """Resolve the guard mode, fail-closed on anything unrecognised."""

    source = os.environ if env is None else env
    raw = (source.get(MODE_ENV) or "").strip().lower()
    if not raw:
        return MODE_ON
    if raw not in VALID_MODES:
        raise LoadGuardMisconfigured(
            f"{MODE_ENV}={raw!r} is not one of {VALID_MODES}. Refusing to guess: an "
            "unrecognised value silently choosing a mode is how a guard becomes an "
            "unconditional skip."
        )
    return raw


def ceiling(cpus: int) -> float:
    """The 1-minute load average above which wall-clock assertions are skipped."""

    return max(cpus * BUSY_FRACTION, MIN_ABSOLUTE_LOAD)


def _read_load1() -> float | None:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):  # pragma: no cover - not Linux/macOS
        return None


def _read_cpus() -> int:
    # ``sched_getaffinity`` is the number of CPUs this process may actually use,
    # which is what a cgroup-limited CI runner has; ``cpu_count`` is the fallback.
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:  # pragma: no cover - not Linux
        return max(1, os.cpu_count() or 1)


def snapshot(
    *, load1: float | None = None, cpus: int | None = None, mode: str | None = None
) -> dict[str, object]:
    """Everything the guard looked at, whether or not it skipped.

    Returned by :func:`contention_reason`'s callers so a nightly run folder can
    record the load the guarded tests were measured under — a green wall-clock
    assertion at an unrecorded load is a number with no error bar.
    """

    resolved_mode = read_mode() if mode is None else mode
    resolved_cpus = _read_cpus() if cpus is None else cpus
    resolved_load = _read_load1() if load1 is None else load1
    limit = ceiling(resolved_cpus)
    return {
        "mode": resolved_mode,
        "cpus": resolved_cpus,
        "load1": resolved_load,
        "ceiling": limit,
        "busy_fraction": (
            None if resolved_load is None else round(resolved_load / resolved_cpus, 4)
        ),
        "busy_fraction_ceiling": BUSY_FRACTION,
        "contended": bool(
            resolved_mode == MODE_ON and resolved_load is not None and resolved_load > limit
        ),
    }


def contention_reason(
    *, load1: float | None = None, cpus: int | None = None, mode: str | None = None
) -> str | None:
    """``None`` when a wall-clock assertion is worth trusting, else why not.

    Pure with respect to its arguments: every reading can be injected, which is
    what lets ``tests/test_load_guard.py`` prove BOTH directions — that an idle
    machine is never skipped and that a contended one always is. A guard only
    ever tested in one direction is indistinguishable from ``pytest.skip()``.
    """

    resolved_mode = read_mode() if mode is None else mode
    if resolved_mode == MODE_OFF:
        return None
    resolved_cpus = _read_cpus() if cpus is None else cpus
    resolved_load = _read_load1() if load1 is None else load1
    if resolved_load is None:  # pragma: no cover - no load average on this platform
        return None
    limit = ceiling(resolved_cpus)
    if resolved_load <= limit:
        return None
    return (
        f"machine contention: 1-minute load average {resolved_load:.2f} over "
        f"{resolved_cpus} usable CPU(s) = busy fraction "
        f"{resolved_load / resolved_cpus:.3f} > {BUSY_FRACTION:.2f} ceiling "
        f"(load ceiling {limit:.2f}). This assertion measures wall-clock duration, so "
        f"under this load it would measure the machine and not the code. It is NOT "
        f"skipped in the nightly tier, which sets {MODE_ENV}={MODE_OFF}. Owner: {OWNER}."
    )


#: Largest stretch :func:`deadline` will apply. Bounded so a wedged thread still
#: fails the suite in seconds rather than hanging a gate: a deadline that grows
#: without limit is ``timeout=None`` wearing a disguise.
MAX_DEADLINE_STRETCH = 8.0


def deadline(
    base_s: float, *, load1: float | None = None, cpus: int | None = None, mode: str | None = None
) -> float:
    """Stretch a thread-join deadline in proportion to measured contention.

    The second kind of load-sensitive test: not a performance assertion, but a
    BEHAVIOUR assertion that happens to wait a fixed number of seconds for a
    worker thread. Skipping one of those loses real coverage, and relaxing its
    deadline unconditionally weakens it on the idle machine where it is
    meaningful. Scaling it by the contention actually present does neither — on
    a quiet machine the number is exactly the number the test author wrote.

    Returns ``base_s`` when the machine is at or below the busy-fraction ceiling,
    and grows linearly with the busy fraction beyond it, capped at
    ``base_s * MAX_DEADLINE_STRETCH``.
    """

    resolved_mode = read_mode() if mode is None else mode
    resolved_cpus = _read_cpus() if cpus is None else cpus
    resolved_load = _read_load1() if load1 is None else load1
    if resolved_mode == MODE_OFF or resolved_load is None or base_s <= 0:
        return base_s
    fraction = resolved_load / resolved_cpus
    if fraction <= BUSY_FRACTION:
        return base_s
    stretch = min(fraction / BUSY_FRACTION, MAX_DEADLINE_STRETCH)
    return base_s * stretch


__all__ = [
    "BUSY_FRACTION",
    "MAX_DEADLINE_STRETCH",
    "MIN_ABSOLUTE_LOAD",
    "MODE_ENV",
    "MODE_OFF",
    "MODE_ON",
    "OWNER",
    "LoadGuardMisconfigured",
    "ceiling",
    "contention_reason",
    "deadline",
    "read_mode",
    "snapshot",
]
