"""The time-bomb guard, proved not to be theatre. Card R26, work item 5.

The sweep in ``scripts/future_clock.py`` only earns its place if two things are
true, and neither can be assumed:

1. **It really moves the clock** — every clock the product reads, including the
   one SQLite stamps rows with. A sweep that shifted only ``time.time()`` would
   report green on a suite full of bombs and be worse than nothing.
2. **A bomb of the auditor's exact shape goes off under it.** So this file
   RECONSTRUCTS that bomb — a row written through the real ``ConversationMemory``
   write path, recalled against a pin — and asserts that it is caught by the
   sweep and not by an ordinary run. That is the seeded-regression discipline the
   mutation panel and ``tests/test_ci_gate.py`` already use, applied to a defect
   class instead of to a gate.

These tests run in the ORDINARY (unshifted) suite. They drive the shim in a
subprocess, because installing it in-process would move the clock for every test
that followed it in the same session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.future_clock import (
    _PURE_DATETIME_MODULES,
    DAYS_ENV,
    FutureClockNotArmed,
    read_days,
)

REPO = Path(__file__).resolve().parents[1]
SWEEP_DAYS = 400


def _run_under_shim(body: str, *, days: int = SWEEP_DAYS, extra_env: dict[str, str] | None = None):
    """Execute ``body`` in a fresh interpreter with the shim armed."""

    script = f"import scripts.future_clock as fc\nfc.install()\n{body}"
    env = dict(os.environ)
    env[DAYS_ENV] = str(days)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False, timeout=300,
    )


# --- fail-closed arming ----------------------------------------------------


def test_the_sweep_refuses_to_run_at_the_real_clock() -> None:
    """The seed for "the future-clock variant silently ran unshifted"."""

    with pytest.raises(FutureClockNotArmed):
        read_days({})
    with pytest.raises(FutureClockNotArmed):
        read_days({DAYS_ENV: ""})
    with pytest.raises(FutureClockNotArmed):
        read_days({DAYS_ENV: "0"})
    with pytest.raises(FutureClockNotArmed):
        read_days({DAYS_ENV: "soon"})
    assert read_days({DAYS_ENV: "400"}) == 400
    assert read_days({DAYS_ENV: "-30"}) == -30, "moving backwards is a legitimate sweep"


def test_a_pytest_run_that_loads_the_plugin_unarmed_aborts() -> None:
    """Not "runs unshifted and reports a green": aborts, loudly, non-zero."""

    env = dict(os.environ)
    env.pop(DAYS_ENV, None)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    env.setdefault("MUJOCO_GL", "egl")
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "scripts.future_clock", "tests/test_clockmap.py", "--collect-only",
        ],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False, timeout=300,
    )
    assert proc.returncode != 0
    assert "FutureClockNotArmed" in (proc.stdout + proc.stderr)


# --- it really moves every clock the product reads -------------------------


@pytest.mark.no_future_clock
def test_every_python_clock_moves_together() -> None:
    """Compares the PARENT's real clock with a CHILD's shifted one.

    ``no_future_clock`` because under the sweep the parent is shifted too and the
    test would be checking the shim against its own reflection (+800 days).
    """

    proc = _run_under_shim(
        "import json, time, datetime\n"
        "print(json.dumps({\n"
        " 'today': datetime.date.today().isoformat(),\n"
        " 'now': datetime.datetime.now().isoformat(),\n"
        " 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),\n"
        " 'time_time': time.time(),\n"
        " 'gmtime_year': time.gmtime().tm_year,\n"
        " 'impl': datetime.datetime.__module__,\n"
        "}))"
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    expected = (datetime.now() + timedelta(days=SWEEP_DAYS)).date()  # noqa: DTZ005
    assert payload["today"] == expected.isoformat()
    assert payload["now"].startswith(expected.isoformat())
    real_now = datetime.now().timestamp()  # noqa: DTZ005
    assert abs(payload["time_time"] - (real_now + SWEEP_DAYS * 86400)) < 120
    # ---- CARD GATE-0b (scrum/20260822/task_30): the pure implementation's
    # module name is version-dependent ("_pydatetime" on CPython 3.12, which is
    # what ci.yml pins for the hosted runner; "datetime" on 3.13+). Read the set
    # from the module under test so there is one source of truth for the name.
    assert payload["impl"] in _PURE_DATETIME_MODULES, (
        "the C accelerator must be out of the way"
    )
    # ---- END CARD GATE-0b


def test_monotonic_clocks_are_deliberately_left_alone() -> None:
    """Shifting a duration clock would make every timeout in the suite lie."""

    proc = _run_under_shim(
        "import time\n"
        "a = time.monotonic(); b = time.perf_counter(); time.sleep(0.05)\n"
        "print(time.monotonic() - a, time.perf_counter() - b)"
    )
    assert proc.returncode == 0, proc.stderr
    mono, perf = (float(value) for value in proc.stdout.split())
    assert 0.04 < mono < 5.0, "monotonic must still measure real elapsed seconds"
    assert 0.04 < perf < 5.0


def test_sqlite_current_timestamp_moves_with_python() -> None:
    """The write half of the auditor's bomb.

    If SQLite kept stamping the real clock while Python ran 400 days ahead, the
    sweep would manufacture a clock split the product never has and every
    conversation-memory test would light up with an artefact of the shim.
    """

    proc = _run_under_shim(
        "import sqlite3, datetime\n"
        "c = sqlite3.connect(':memory:')\n"
        "c.execute('create table t (a text not null default CURRENT_TIMESTAMP)')\n"
        "c.execute('insert into t default values')\n"
        "print(c.execute('select a from t').fetchone()[0])\n"
        "print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'))"
    )
    assert proc.returncode == 0, proc.stderr
    stamped, python_utc_day = proc.stdout.strip().splitlines()[-2:]
    assert stamped.startswith(python_utc_day), (
        f"SQLite stamped {stamped!r} while Python believed it was {python_utc_day!r}"
    )


# --- and a bomb of the auditor's exact shape goes off ----------------------


#: The 2026-08-21 defect, reconstructed exactly: a row written through the REAL
#: ``ConversationMemory.add()`` path (so SQLite's ``CURRENT_TIMESTAMP`` dates it)
#: and recalled against a **fixed literal** pin — the shape of the module-level
#: ``PINNED_NOW`` the auditor found. The pin is a LITERAL from the child
#: process's point of view, which is what makes it a bomb; it is computed by the
#: parent at run time so this seed can never go stale and become a real failure
#: of its own.
_SEEDED_BOMB_TEMPLATE = """
import datetime, sys, tempfile
from pathlib import Path
from parcel_robot.memory.conversation import ConversationMemory

PINNED_NOW = datetime.datetime.fromisoformat({pin!r})   # a fixed pin, as in the original
root = Path(tempfile.mkdtemp())
store = ConversationMemory(root / "bomb.sqlite3")
store.add("user", "I walk by the river most evenings")
found = store.recall("river", now=PINNED_NOW)
sys.exit(0 if (found and found[0].when_phrase) else 17)
"""


def _seeded_bomb() -> str:
    """Pin three days past the REAL clock: green today, red once time passes it."""

    return _SEEDED_BOMB_TEMPLATE.format(
        pin=(datetime.now() + timedelta(days=3)).isoformat()  # noqa: DTZ005
    )


@pytest.mark.no_future_clock
def test_the_auditors_bomb_is_invisible_today_and_caught_by_the_sweep() -> None:
    """Both halves, because either alone proves nothing.

    * unshifted: the seeded bomb PASSES — this is why a flake inventory cannot
      see the class;
    * under the sweep: it FAILS — which is the whole reason the nightly variant
      exists.
    """

    bomb = _seeded_bomb()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    env.pop(DAYS_ENV, None)
    today = subprocess.run(
        [sys.executable, "-c", bomb],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False, timeout=300,
    )
    assert today.returncode == 0, (
        "the seeded bomb must be GREEN at the real clock, or it is an ordinary "
        f"failing test and proves nothing: {today.stderr[-2000:]}"
    )

    swept = _run_under_shim(bomb)
    assert swept.returncode != 0, (
        "the +400d sweep did not detonate a bomb of the exact shape the auditor "
        "fixed on 2026-08-21 — the sweep is vacuous"
    )


def test_the_fixed_test_stays_green_under_the_sweep() -> None:
    """The auditor's FIX must survive the sweep, or the sweep is unusable.

    ``test_a_read_only_store_still_answers_the_owners_question`` is the test the
    bomb was found in. If the shim reddened the corrected version it would be
    reporting its own artefacts, and nobody would keep running it.
    """

    env = dict(os.environ)
    env[DAYS_ENV] = str(SWEEP_DAYS)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    env.setdefault("MUJOCO_GL", "egl")
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "scripts.future_clock",
            "tests/test_scene_and_memory_answers.py::test_a_read_only_store_still_answers_the_owners_question",
        ],
        cwd=str(REPO), env=env, capture_output=True, text=True, check=False, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]


def test_the_nightly_runner_arms_the_sweep_by_default() -> None:
    """A sweep nobody runs is the defect this card exists to close."""

    from scripts.run_nightly import DEFAULT_FUTURE_CLOCK_DAYS

    assert DEFAULT_FUTURE_CLOCK_DAYS >= 366, (
        "the sweep must cross a full year, or month/leap-day logic is untested"
    )
