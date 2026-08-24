"""Run the suite as if the calendar had already moved. Card R26, work item 5.

WHY THIS EXISTS
---------------
A test that mixes the REAL clock with a PINNED clock is not flaky. It passes
every run until a calendar boundary and then fails **forever**. On 2026-08-21 the
auditor found and fixed exactly one of these in
``tests/test_scene_and_memory_answers.py``:
``test_a_read_only_store_still_answers_the_owners_question`` wrote its row
through the real ``ConversationMemory.add()`` path — so SQLite stamped it with
its own ``CURRENT_TIMESTAMP`` — and then recalled it against the module's fixed
``PINNED_NOW``. The instant the calendar passed that pin the stored row looked
*future-dated*, ``provenance_phrase`` rightly refused to date a future row, and
the assertion began failing on every run from that day on.

A flake inventory cannot see this class, because the bomb has not gone off yet.
The only way to see it is to **move the calendar** and look. That is all this
plugin does: it shifts the process's idea of "now" forward by a pinned number of
days and runs the suite. Anything that fires was going to fire on that date
anyway — in someone's commit gate, with no warning and no owner.

USE
---
::

    PARCEL_FUTURE_CLOCK_DAYS=400 .parcel/bin/python -m pytest -q \\
        -p scripts.future_clock -m "not slow"

or, the supported form, through the nightly runner::

    .parcel/bin/python scripts/run_nightly.py --future-clock-days 400

FAIL-CLOSED
-----------
Loading this plugin **without** ``PARCEL_FUTURE_CLOCK_DAYS`` set to a non-zero
integer is an error, not a no-op. A "future-clock sweep" that silently ran at the
real clock is worse than no sweep: it reports a green that means nothing. The
same reason ``ci_selftest_seed`` refuses an unknown seed name.

WHAT IT SHIFTS — and what it does not
-------------------------------------
Shifted (these are the clocks the product actually reads):

* ``time.time`` / ``time.time_ns`` / ``time.localtime`` / ``time.gmtime`` /
  ``time.ctime`` / ``time.clock_gettime(CLOCK_REALTIME)``;
* **every** ``datetime.datetime.now()``, ``.utcnow()``, ``.today()`` and
  ``datetime.date.today()`` in every module, however it was imported. The
  mechanism is deliberate and worth understanding: CPython's ``datetime`` is
  normally the C accelerator ``_datetime``, whose ``now()`` reads the system
  clock in C and therefore cannot be reached by patching ``time.time``. This
  plugin blocks ``_datetime`` and re-imports ``datetime``, which falls back to
  the pure-Python implementation in ``Lib/datetime.py`` — and *that* one calls
  ``_time.time()``. Patching ``time.time`` then moves every derived clock at
  once, with no per-module rebinding and no chance of missing a module that did
  ``from datetime import datetime`` before the plugin loaded.
* SQLite's ``CURRENT_TIMESTAMP``, by rewriting that one token in SQL text passed
  through ``sqlite3.connect``-ed connections to a shifted ``datetime('now', …)``.
  This is NOT cosmetic: ``src/parcel_robot/memory/conversation.py`` stamps every conversation
  row with a ``DEFAULT CURRENT_TIMESTAMP`` column, and leaving SQLite on the real
  clock while Python runs 400 days ahead would manufacture a clock split the
  product never has, and drown the real bombs in artefacts of the shim.

NOT shifted, on purpose:

* ``time.monotonic`` / ``time.perf_counter`` / ``time.monotonic_ns`` /
  ``time.perf_counter_ns`` — these measure DURATIONS. Shifting them would make
  every timeout and latency measurement in the suite lie.
* filesystem timestamps (``os.stat`` mtimes), subprocesses, and any clock read
  by a C extension that does not route through ``time.time``. A test that
  compares a file's mtime to ``datetime.now()`` will look 400 days stale under
  this plugin; that is a known blind spot of the shim and is listed in
  ``R26_STATUS.md`` rather than implied.

The offset is applied as a **whole number of days** so that weekday-, month- and
year-boundary logic is exercised rather than merely nudged.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any

#: Environment variable carrying the shift, in whole days. Read once, at import.
DAYS_ENV = "PARCEL_FUTURE_CLOCK_DAYS"

#: SQLite's own clock keyword. Exactly one committed DDL uses it
#: (``src/parcel_robot/memory/conversation.py``: ``created_at TEXT NOT NULL DEFAULT
#: CURRENT_TIMESTAMP``), and it is the write half of the auditor's bomb.
_CURRENT_TIMESTAMP = re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE)

#: Set by :func:`install`; module-level so the pytest header hook can report it
#: and so a test can assert the shim is armed rather than assume it.
OFFSET_SECONDS: float = 0.0
OFFSET_DAYS: int = 0
INSTALLED: bool = False


class FutureClockNotArmed(RuntimeError):
    """Raised when the plugin is loaded without a real shift configured."""


def read_days(env: dict[str, str] | None = None) -> int:
    """Parse the configured shift. Fail-closed: 0/absent/garbage all raise.

    Kept pure and separately testable — the fail-closed behaviour is the whole
    point of the plugin's contract and a seed asserts each rejection.
    """

    source = os.environ if env is None else env
    raw = (source.get(DAYS_ENV) or "").strip()
    if not raw:
        raise FutureClockNotArmed(
            f"{DAYS_ENV} is unset. Loading scripts.future_clock without a shift would "
            "run the suite at the REAL clock and report a green that proves nothing; "
            "set it to a whole number of days (the nightly uses 400)."
        )
    try:
        days = int(raw)
    except ValueError as exc:
        raise FutureClockNotArmed(f"{DAYS_ENV}={raw!r} is not a whole number of days") from exc
    if days == 0:
        raise FutureClockNotArmed(
            f"{DAYS_ENV}=0 is not a sweep. Use a non-zero number of days "
            "(negative is allowed and moves the calendar backwards)."
        )
    return days


def _install_time_shim(offset: float) -> None:
    """Shift the wall clock; leave every monotonic/duration clock alone."""

    real_time = time.time
    real_time_ns = time.time_ns
    real_localtime = time.localtime
    real_gmtime = time.gmtime
    real_ctime = time.ctime
    offset_ns = int(offset * 1_000_000_000)

    time.time = lambda: real_time() + offset  # type: ignore[assignment]
    time.time_ns = lambda: real_time_ns() + offset_ns  # type: ignore[assignment]
    time.localtime = lambda secs=None: real_localtime(  # type: ignore[assignment]
        real_time() + offset if secs is None else secs
    )
    time.gmtime = lambda secs=None: real_gmtime(  # type: ignore[assignment]
        real_time() + offset if secs is None else secs
    )
    time.ctime = lambda secs=None: real_ctime(  # type: ignore[assignment]
        real_time() + offset if secs is None else secs
    )
    real_clock_gettime = getattr(time, "clock_gettime", None)
    if real_clock_gettime is not None:
        realtime_ids = {
            getattr(time, name)
            for name in ("CLOCK_REALTIME", "CLOCK_REALTIME_COARSE")
            if hasattr(time, name)
        }

        def clock_gettime(clk_id: int) -> float:
            value = real_clock_gettime(clk_id)
            return value + offset if clk_id in realtime_ids else value

        time.clock_gettime = clock_gettime  # type: ignore[assignment]


#: Compiled extensions that bind CPython's ``PyDateTimeAPI`` capsule
#: (``datetime.datetime_CAPI``) at IMPORT time. The pure-Python ``datetime``
#: module does not export that capsule, and its objects have different C struct
#: sizes, so an extension that grabs the capsule after the swap either fails to
#: import (numpy) or builds broken objects (msgpack's Cython ``_cmsgpack``:
#: ``TypeError: tzinfo argument must be None or of a tzinfo subclass``).
#:
#: They are therefore imported BEFORE the swap, so they bind the real C module
#: and keep working. The cost is precise and stated: these libraries' own
#: datetime handling is NOT shifted. Nothing in Parcel dates a conversation row
#: or a provenance phrase through numpy or msgpack, so no time bomb hides behind
#: this list — but if the sweep ever errors with ``datetime_CAPI`` or the tzinfo
#: TypeError above, the module that raised belongs here.
# ---- CARD GATE-0b (scrum/20260822/task_30): zoneinfo is a C-API consumer too
# `_zoneinfo` reads `datetime.datetime_CAPI` at import; the pure-Python
# `datetime` this shim installs does not export that capsule, so ANY module
# that first imports `zoneinfo` after the swap dies with
# `AttributeError: module 'datetime' has no attribute 'datetime_CAPI'`.
# `parcel_robot.context.providers:7` does exactly that, so the +400d sweep
# could not even COLLECT `tests/test_scene_and_memory_answers.py` on CPython
# 3.12 (measured in a clean clone, card GATE-0b, 2026-08-23). Preloading it
# here — while the C `datetime` is still in force — is what this list is for.
CAPI_CONSUMERS: tuple[str, ...] = ("numpy", "msgpack", "zoneinfo")
# ---- END CARD GATE-0b

#: Strong references that must outlive the swap — see ``_install_datetime_shim``.
_KEEPALIVE: list[Any] = []


def _preload_capi_consumers() -> list[str]:
    """Import the C-API consumers while the C ``datetime`` is still in force."""

    import importlib

    loaded: list[str] = []
    for name in CAPI_CONSUMERS:
        try:
            importlib.import_module(name)
        except ImportError:  # pragma: no cover - optional dependency
            continue
        loaded.append(name)
    return loaded


#: Card GATE-0b. What ``datetime.datetime.__module__`` reads as once the C
#: accelerator is out of the way — ``"_pydatetime"`` on CPython 3.12 (where the
#: pure bodies live in their own module) and ``"datetime"`` on 3.13+/3.14.
_PURE_DATETIME_MODULES = frozenset({"datetime", "_pydatetime"})


def _install_datetime_shim() -> Any:
    """Force the pure-Python ``datetime`` so ``now()`` routes through ``time``.

    Returns the freshly imported module. Nothing else here rebinds names in
    other modules: because the pure-Python implementation asks ``time.time()``
    at call time, a module that imported ``datetime`` *after* this runs is
    shifted no matter which import form it used.
    """

    _preload_capi_consumers()
    # KEEP THE ORIGINALS ALIVE. Dropping the last reference to the C ``datetime``
    # / ``_datetime`` modules lets CPython finalise them, and the extensions
    # preloaded above are still holding the ``PyDateTimeAPI`` capsule that points
    # into their now-freed static types. Measured, not theorised: without these
    # two lines the +400d sweep ran all 7,455 tests clean and then died with
    # ``Fatal Python error: Segmentation fault`` inside pytest's own
    # ``format_session_duration`` at session finish (2026-08-21, R26). A sweep
    # that segfaults after reporting is a sweep whose exit code nobody can read.
    _KEEPALIVE.append(sys.modules.pop("datetime", None))
    _KEEPALIVE.append(sys.modules.get("_datetime"))
    sys.modules["_datetime"] = None  # type: ignore[assignment]
    import datetime as shifted

    # ---- CARD GATE-0b (scrum/20260822/task_30) -----------------------------
    # THE NAME OF THE PURE IMPLEMENTATION IS VERSION-DEPENDENT. CPython 3.12
    # moved the pure-Python bodies into `_pydatetime.py`, so after the swap
    # above `datetime.datetime.__module__` is `"_pydatetime"` there, and
    # `"datetime"` on the interpreter this repo's `.parcel/` venv happens to
    # run (3.14). Comparing against the single string `"datetime"` therefore
    # made this guard REFUSE TO ARM on CPython 3.12 — which is exactly the
    # interpreter `.github/workflows/ci.yml` pins for the hosted runner, and
    # close to the JetPack CPython on the Orin. Measured in a clean clone on
    # 3.12.13: four `tests/test_future_clock_guard.py` rows red with "the C
    # datetime accelerator is still in force" while the accelerator was in fact
    # already gone. Accept either name; the property being asserted is "not the
    # C accelerator", and `_datetime` is what that would say.
    if shifted.datetime.__module__ not in _PURE_DATETIME_MODULES:  # pragma: no cover
        raise FutureClockNotArmed(
            "the C datetime accelerator is still in force "
            f"(datetime.datetime.__module__ == {shifted.datetime.__module__!r}); "
            "datetime.now() would not follow the shifted clock and the sweep "
            "would be silently vacuous"
        )
    # ---- END CARD GATE-0b --------------------------------------------------
    # sqlite3 keys its default adapters on the exact class object. If it was
    # imported before the swap it holds the C classes and would refuse to bind a
    # pure-Python date; re-register against the classes now in force.
    if "sqlite3" in sys.modules:  # pragma: no branch - sqlite3 is imported early here
        import sqlite3

        sqlite3.register_adapter(shifted.date, lambda value: value.isoformat())
        sqlite3.register_adapter(shifted.datetime, lambda value: value.isoformat(" "))
    return shifted


def _install_sqlite_shim(days: int) -> None:
    """Move SQLite's ``CURRENT_TIMESTAMP`` by the same offset.

    SQLite reads the host clock in C, below anything Python can patch, so the
    shift is applied where the token enters: the SQL text. Only the literal
    keyword is rewritten, and only on connections opened through
    ``sqlite3.connect`` after this plugin loads.
    """

    import sqlite3

    modifier = f"{days:+d} days"
    replacement = f"(datetime('now','{modifier}'))"

    def rewrite(sql: Any) -> Any:
        if isinstance(sql, str) and _CURRENT_TIMESTAMP.search(sql):
            return _CURRENT_TIMESTAMP.sub(replacement, sql)
        return sql

    class _ShiftedCursor(sqlite3.Cursor):
        def execute(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return super().execute(rewrite(sql), *args, **kwargs)

        def executemany(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return super().executemany(rewrite(sql), *args, **kwargs)

        def executescript(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return super().executescript(rewrite(sql), *args, **kwargs)

    class _ShiftedConnection(sqlite3.Connection):
        def cursor(self, factory=None):  # type: ignore[no-untyped-def]
            return super().cursor(factory or _ShiftedCursor)

        def execute(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return self.cursor().execute(sql, *args, **kwargs)

        def executemany(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return self.cursor().executemany(sql, *args, **kwargs)

        def executescript(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            return self.cursor().executescript(sql, *args, **kwargs)

    real_connect = sqlite3.connect

    def connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("factory", _ShiftedConnection)
        return real_connect(*args, **kwargs)

    sqlite3.connect = connect  # type: ignore[assignment]


def install(days: int | None = None) -> int:
    """Arm every shim. Idempotent; returns the offset in days actually applied."""

    global OFFSET_SECONDS, OFFSET_DAYS, INSTALLED
    if INSTALLED:
        return OFFSET_DAYS
    shift = read_days() if days is None else days
    if shift == 0:
        raise FutureClockNotArmed("a zero-day shift is not a sweep")
    offset = shift * 86400.0
    _install_time_shim(offset)
    _install_datetime_shim()
    _install_sqlite_shim(shift)
    OFFSET_SECONDS, OFFSET_DAYS, INSTALLED = offset, shift, True
    return shift


def banner() -> str:
    # Deliberately the POST-swap module, and deliberately the naive local
    # ``today()``: this line exists to show the reader what date the process
    # believes it is, which is exactly the reading a timezone-aware call would
    # hide.
    import datetime

    believes = datetime.date.today().isoformat()  # noqa: DTZ011
    return (
        f"future-clock: {OFFSET_DAYS:+d} day(s) — this process believes it is "
        f"{believes} (card R26). Monotonic clocks are untouched; SQLite "
        "CURRENT_TIMESTAMP is shifted with the rest."
    )


# --- pytest plugin surface -------------------------------------------------
# Installation happens in ``pytest_configure``, NOT at module import. Importing
# this module has to stay inert so ``tests/test_future_clock_guard.py`` can
# import the fail-closed parser and assert on it without moving its own session's
# clock. ``pytest_configure`` still runs before collection — which is when test
# modules and, through them, ``parcel_robot`` are first imported — so the swap is
# in place before any code under test binds a name from ``datetime``.


def pytest_configure(config: Any) -> None:
    install()
    config.addinivalue_line(
        "markers",
        "no_future_clock: test is meaningless under scripts.future_clock "
        "(it measures the real calendar itself)",
    )


def pytest_report_header(config: object) -> str:
    del config
    return banner()


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Skip the handful of tests that assert ON the real calendar.

    Not an escape hatch for a bomb: the marker means "this test's subject IS the
    wall calendar", and every use is named in ``R26_STATUS.md``. It is applied by
    marker only, never by name pattern, so adding one is a visible edit.
    """

    del config
    import pytest

    skip = pytest.mark.skip(
        reason=f"marked no_future_clock; the sweep runs at {OFFSET_DAYS:+d} days"
    )
    for item in items:
        if item.get_closest_marker("no_future_clock"):
            item.add_marker(skip)
