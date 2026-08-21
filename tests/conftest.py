from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from scripts.load_guard import contention_reason

#: Card R25. Where the suite's realtime spend ledger is relocated to. Created
#: in ``pytest_configure`` and removed in ``pytest_unconfigure``; module-level
#: so the teardown can find it.
_SPEND_LEDGER_TMPDIR: str | None = None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: long-running eval suites excluded from the default gate "
        "(run explicitly with -m slow)",
    )
    # Card R26. The wall-clock assertions. They stay IN the commit tier — the
    # coverage is real and removing it would be the easy, wrong fix — but they
    # refuse to report a number they cannot trust, and the nightly runs them
    # with the guard off so they can never be skipped everywhere at once.
    config.addinivalue_line(
        "markers",
        "load_sensitive: asserts on wall-clock duration; skipped with a named, "
        "measured reason under machine contention (scripts/load_guard.py, card "
        "R26). PARCEL_LOAD_GUARD=off forces it to run — the nightly sets that.",
    )
    # Card R26. Registered HERE as well as in scripts/future_clock.py so that an
    # ordinary run does not warn about an unknown marker. The marker means "this
    # test's subject IS the wall calendar" — it compares the parent process's
    # real clock against a child's shifted one — and the sweep skips it rather
    # than reading its own reflection. It is NOT an escape hatch for a time bomb:
    # every use is enumerated in R26_STATUS.md §5.
    config.addinivalue_line(
        "markers",
        "no_future_clock: meaningless under scripts.future_clock; the test "
        "measures the real calendar itself (card R26)",
    )
    # Card EV-1. The per-session evidence log is ON by default in a real stack
    # and writes one folder per hosted session. A test suite that constructs
    # hundreds of realtime runtimes would leave hundreds of folders under the
    # repo root, so the SUITE opts out and the tests that exercise the log opt
    # back in explicitly (``monkeypatch.setenv``) with a ``tmp_path`` root.
    # ``setdefault``: a developer who exports it keeps their choice.
    os.environ.setdefault("PARCEL_SESSION_EVIDENCE", "0")
    # Card R25. The durable monthly spend ledger defaults to
    # ``<repo>/recordings/spend.jsonl`` and is written on every hosted
    # ``response.done``. Left alone, a suite that drives fake responses through
    # a runtime-built lane would (a) leave a file in the repo and (b) — the
    # part that actually bites — accumulate a REAL month-to-date total across
    # runs until it crossed ``monthly_budget_usd`` and the arming gate started
    # refusing sessions in unrelated tests, months later, for no visible
    # reason. It is RELOCATED rather than switched off, so the production wiring
    # (arm the ledger, write rows, read the ceiling) is the code the suite
    # actually exercises. Tests that assert on ledger contents point the same
    # variable at their own ``tmp_path``.
    global _SPEND_LEDGER_TMPDIR
    if not os.environ.get("PARCEL_REALTIME_SPEND_LEDGER", "").strip():
        _SPEND_LEDGER_TMPDIR = tempfile.mkdtemp(prefix="parcel-spend-ledger-")
        os.environ["PARCEL_REALTIME_SPEND_LEDGER"] = os.path.join(
            _SPEND_LEDGER_TMPDIR, "spend.jsonl"
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Card R26. Refuse to measure wall-clock duration on a contended machine.

    Deliberately in ``setup`` and not in ``collection_modifyitems``: the load
    that matters is the load at the moment the test runs, which on a 300-second
    suite is not the load at collection.
    """

    if item.get_closest_marker("load_sensitive") is None:
        return
    reason = contention_reason()
    if reason:
        pytest.skip(reason)


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    global _SPEND_LEDGER_TMPDIR
    if _SPEND_LEDGER_TMPDIR:
        shutil.rmtree(_SPEND_LEDGER_TMPDIR, ignore_errors=True)
        _SPEND_LEDGER_TMPDIR = None
