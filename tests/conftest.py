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


# ---------------------------------------------------------------------------
# BEGIN HY-1 sim guard (card scrum/20260822/task_15) — owned by HY-1.
# Other cards: please add your own hooks in your own marked region rather than
# inside this one. XD-1 (task_14) was told this region exists.
#
# What it does: before and after EVERY test file it takes a census of live
# ``parcel_robot.sim`` processes. A simulator that was not alive before the
# file ran, and still is after, is a leak — the run fails naming the test, the
# pid and the socket path, and (in the default ``reap`` mode) the survivor is
# terminated so the next run starts clean.
#
# What it deliberately does NOT do: touch anything it cannot prove this run
# started. The ownership test lives in ``tests/_sim_guard.started_by_this_run``
# and is pinned by ``tests/test_hy1_sim_guard.py``; the owner's stack on
# ``/tmp/parcel_sim.sock`` / :8765 is excluded twice over.
#
# Cost: two ``/proc`` scans per test FILE (not per test). Test attribution is
# free — it comes from pytest's own report hooks plus the kernel's start time
# for the process, so no scanning happens between tests.
# ---------------------------------------------------------------------------

#: Closed test windows for this session, and the currently-open one. Used only
#: to answer "which test was running when this process appeared".
_HY1_WINDOWS: list = []
_HY1_OPEN: dict = {}


def pytest_runtest_logstart(nodeid: str, location: object) -> None:
    del location
    import time

    _HY1_OPEN[nodeid] = time.time()


def pytest_runtest_logfinish(nodeid: str, location: object) -> None:
    del location
    import time

    import _sim_guard

    started = _HY1_OPEN.pop(nodeid, None)
    if started is not None:
        _HY1_WINDOWS.append(_sim_guard.TestWindow(nodeid, started, time.time()))


@pytest.fixture(scope="module", autouse=True)
def _hy1_sim_guard(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory):
    """Fail the run, by name, when a test file leaks a simulator.

    Module-scoped rather than session-scoped so the report arrives while the
    file that caused it is still on screen, and so one leaking file does not
    make every later file look guilty.
    """

    import time

    import _sim_guard

    guard_mode = _sim_guard.mode()
    if guard_mode == "off":
        yield
        return

    before = _sim_guard.scan()
    yield
    after = _sim_guard.scan()

    ownership = _sim_guard.Ownership(
        session_root=tmp_path_factory.getbasetemp(),
        pytest_pid=os.getpid(),
        before=frozenset(before),
    )
    survivors = [
        proc
        for key, proc in sorted(after.items())
        if key not in before and _sim_guard.started_by_this_run(proc, ownership)
    ]
    if not survivors:
        return

    windows = list(_HY1_WINDOWS)
    windows.extend(
        _sim_guard.TestWindow(nodeid, started, time.time())
        for nodeid, started in _HY1_OPEN.items()
    )
    reaped = []
    if guard_mode == "reap":
        for proc in survivors:
            reaped.append(_sim_guard.reap(proc))
    scope = str(getattr(request.module, "__file__", request.node.name))
    pytest.fail(_sim_guard.format_report(scope, survivors, windows, reaped), pytrace=False)


# END HY-1 sim guard


# ---------------------------------------------------------------------------
# BEGIN XD-1 repo-write census (card scrum/20260822/task_14) — owned by XD-1.
# Other cards: please add your own hooks in your own marked region rather than
# inside this one. Appended strictly BELOW the HY-1 region, which is untouched.
#
# What it does: names any test that writes a path GIT WOULD NOTICE under the
# repository root — the GATE-0 defect class (AUDIT_WEEK1_FABLE §GATE-0), which
# is the reason the commit tier could not be flipped to ``-n auto`` on the
# strength of fixing seven named divergences. A test that writes under the repo
# is correct alone and reddens ITS NEIGHBOURS at one-worker-per-test.
#
# Why an audit hook rather than a per-test ``git status --porcelain``: the
# snapshot misses write-then-delete (the GATE-0 shape exactly — the stray only
# survived a SIGKILL), cannot name the path or the mode, and costs a
# fork/exec per test. The argument, and what the hook cannot see, are in
# ``tests/_repo_write_guard.py``'s module docstring.
#
# Cost, measured: +0.58 us per write-mode ``open`` and +0.26 us per audit
# event; ``git`` is consulted only when a candidate exists, i.e. never on a
# clean tree.
# ---------------------------------------------------------------------------

# Imported here rather than at the top of the file so this card's code stays
# inside its own marked region; ``tests/`` is on ``sys.path`` under pytest.
import _repo_write_guard as _xd1_guard

#: ``on`` fails the offending test, ``census`` records without failing, ``off``
#: never installs the hook. Resolved once, at import, and fail-closed on a typo.
#:
#: DEFAULT = ``census``, by the D7 rule this card pre-registered BEFORE running
#: the census: ON iff the census is empty. It named 10 tests in three files —
#: ``test_nav_instruct_scene_gen`` (8, into ``configs/scenes/generated/``),
#: ``test_stage0_command_addendum`` (a TRACKED scrum doc) and
#: ``test_barn_v9_supervisory_gap_s2_bundle`` (a TRACKED evals source) — that
#: this card does not own, so it records instead of reddening three other
#: cards' tests. ``PARCEL_REPO_WRITE_GUARD=on`` is the whole switch, the day
#: the last one is fixed.
_XD1_MODE = _xd1_guard.read_mode()

_XD1_RECORDER = None
if _XD1_MODE != _xd1_guard.MODE_OFF:
    _XD1_RECORDER = _xd1_guard.Recorder()
    _xd1_guard.install(_XD1_RECORDER)

#: Set by the controller only, so the residue net costs two ``git status``
#: calls per RUN and not two per xdist worker.
_XD1_PORCELAIN_AT_START: str | None = None

#: Where ``census`` mode writes its rows — a PATH PREFIX, not a file: the
#: writing process appends ``.<pid>`` to it. Under ``-n auto`` that is what
#: keeps 192 workers from interleaving their rows inside one file; ``cat
#: <prefix>.*`` is the whole merge. Outside the repo, deliberately: a census
#: that wrote its own findings into the tree would be its own offender.
_XD1_CENSUS_OUT = os.environ.get("PARCEL_REPO_WRITE_CENSUS_OUT", "").strip()


def _xd1_record_census(nodeid: str, found: dict) -> None:
    if not _XD1_CENSUS_OUT:
        return
    import json

    row = json.dumps({"nodeid": nodeid, "paths": found}, sort_keys=True)
    with open(f"{_XD1_CENSUS_OUT}.{os.getpid()}", "a", encoding="utf-8") as handle:
        handle.write(row + "\n")


@pytest.fixture(autouse=True)
def _xd1_repo_write_census(request: pytest.FixtureRequest):
    """Fail the test, by name, when it writes a git-visible path under the repo."""

    recorder = _XD1_RECORDER
    if recorder is None:
        yield
        return
    recorder.start()
    try:
        yield
    finally:
        candidates = recorder.stop()
    found = _xd1_guard.offences(candidates)
    if not found:
        return
    _xd1_record_census(request.node.nodeid, found)
    if _XD1_MODE == _xd1_guard.MODE_ON:
        pytest.fail(
            _xd1_guard.format_report(request.node.nodeid, found), pytrace=False
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    """The second net: what a CHILD process left behind, which no hook can see."""

    global _XD1_PORCELAIN_AT_START
    if _XD1_MODE == _xd1_guard.MODE_OFF or hasattr(session.config, "workerinput"):
        return
    _XD1_PORCELAIN_AT_START = _xd1_guard.porcelain()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if _XD1_PORCELAIN_AT_START is None or hasattr(session.config, "workerinput"):
        return
    residue = _xd1_guard.session_residue(_XD1_PORCELAIN_AT_START, _xd1_guard.porcelain())
    if not residue:
        return
    _xd1_record_census("<session: unattributed, a child process>", {r: "porcelain" for r in residue})
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("")
        reporter.write_line(
            f"XD-1 repo-write census: the run left {len(residue)} git-visible "
            f"change(s) behind that no single test could be charged with:",
            red=True,
        )
        for line in residue:
            reporter.write_line(f"    {line}", red=True)


# END XD-1 repo-write census
