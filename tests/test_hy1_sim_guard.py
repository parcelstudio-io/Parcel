"""Card HY-1 — the suite notices when a test leaks a simulator, and says which one.

The defect these tests pin was measured, not imagined. On 2026-08-22 this host
carried eighteen orphaned ``parcel_robot.sim`` processes — 15.3 GB resident,
each holding a LISTEN unix socket under ``/tmp/pytest-of-jaewoo-jang/pytest-3848/``
whose directory pytest had already deleted. Every one came from
``tests/test_voice_nav_e2e.py``, whose fixture spawned the sim *before* the
``try`` that would have torn it down; ``build_runtime`` then raised
``MemoryPathRefused`` and the object never reached the fixture's ``finally``.
The suite exited reporting only "1 error".

Two things are pinned here:

* the fixture bug itself is fixed at its source, and stays fixed
  (:func:`test_live_runtime_setup_error_tears_the_sim_down`);
* the guard in ``tests/conftest.py`` catches the *next* one and names it —
  test, pid, socket — rather than leaving it for a verifier with ``pgrep``.

**The stand-in.** Several tests below need a process that the guard sees as a
simulator. Starting a real one costs ~840 MB and several seconds of MuJoCo, so
they run ``python -m parcel_robot.sim --socket <path>`` against a six-line
stand-in module shadowed onto ``PYTHONPATH``. The argv is therefore *identical
in shape* to the real thing — the same token the predicate matches, the same
``--socket`` flag — and the stand-in binds a real unix socket. What it does not
prove is that the real simulator dies when signalled; that is measured live and
recorded in ``HY1_STATUS.md``.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _sim_guard
import pytest

REPO = Path(__file__).resolve().parents[1]

#: This card's scratch root (the wave's standing rule: not ``/tmp``, and a
#: SHORT path — an inner pytest basetemp nested inside the outer one produces
#: socket paths past the 107-byte ``AF_UNIX`` limit).
SCRATCH = Path.home() / ".cache" / "parcel-hy1" / "inner"

#: A stand-in for ``parcel_robot.sim``: binds the socket it is given, then
#: waits. Shadowed onto ``PYTHONPATH`` so ``python -m parcel_robot.sim`` runs
#: it, which is what makes the spawned process indistinguishable from a real
#: simulator to anything that reads ``/proc/<pid>/cmdline``.
_STANDIN_SIM = '''
"""Card HY-1 test stand-in. Binds the socket, then sleeps. Not the real sim."""

import socket
import sys
import time

path = sys.argv[sys.argv.index("--socket") + 1]
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
server.listen(8)
time.sleep(3600)
'''


#: A second stand-in, for the ownership tests. It wears whatever argv it is
#: given and binds only what ``HY1_BIND_SOCKET`` names — nothing, by default.
#: That is the only honest way to build a record for **the owner's live stack**
#: on this host: every line of code under test identifies a process by its
#: ``/proc`` argv, so a process launched as ``-m parcel_robot.sim --socket
#: /tmp/parcel_sim.sock`` *is* the owner's simulator as far as the guard can
#: tell — while the standing rule that no test may create
#: ``/tmp/parcel_sim.sock`` or listen on :8765 is kept exactly.
_STANDIN_DECOY = '''
"""Card HY-1 test stand-in. Wears an argv; binds only HY1_BIND_SOCKET, if set."""

import os
import socket
import time

bind = os.environ.get("HY1_BIND_SOCKET", "")
if bind:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(bind)
    server.listen(8)
time.sleep(3600)
'''


def _standin_root(root: Path, *, module: str = "sim", source: str | None = None) -> Path:
    """Write a shadow ``parcel_robot.<module>`` and return the ``PYTHONPATH`` entry.

    ``module`` / ``source`` exist for the ownership tests, which need a live
    process whose argv is the owner's stack or the control deck while it binds
    neither.
    """

    package = root / "standin" / "parcel_robot"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / f"{module}.py").write_text(_STANDIN_SIM if source is None else source)
    return root / "standin"


def _wait_cmdline(pid: int, token: str, timeout_s: float = 20.0) -> None:
    """Block until ``/proc/<pid>/cmdline`` carries ``token`` — i.e. the exec happened."""

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if token in Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace"):
                return
        except OSError:
            pass
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} never exec'd anything containing {token!r}")


def _spawn_decoy(
    standin: Path, *, module: str, argv_tail: list[str], bind: Path | None
) -> subprocess.Popen:
    """Start a process whose argv reads ``-m parcel_robot.<module> <argv_tail>``."""

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(standin), env.get("PYTHONPATH", "")) if part
    )
    if bind is None:
        env.pop("HY1_BIND_SOCKET", None)
    else:
        env["HY1_BIND_SOCKET"] = str(bind)
    proc = subprocess.Popen(
        [sys.executable, "-m", f"parcel_robot.{module}", *argv_tail],
        env=env,
        start_new_session=True,
    )
    _wait_cmdline(proc.pid, f"parcel_robot.{module}")
    if bind is not None:
        deadline = time.monotonic() + 20.0
        while not bind.exists():
            assert proc.poll() is None and time.monotonic() < deadline, "decoy never bound"
            time.sleep(0.05)
    return proc


def _reap_pid(pid: int) -> None:
    """Kill a process this test started that is *not* our child, and wait for it."""

    if not pid:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.05)
    raise AssertionError(f"pid {pid} would not die")


def _spawn_standin(standin: Path, socket_path: Path) -> subprocess.Popen:
    """Start a stand-in sim on ``socket_path`` and wait for it to be listening."""

    assert len(os.fsencode(str(socket_path))) < 100, (
        f"unix socket path too long for this test ({socket_path}); unset TMPDIR"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(standin), env.get("PYTHONPATH", "")) if part
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "parcel_robot.sim", "--socket", str(socket_path)],
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20.0
    while not socket_path.exists():
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            raise AssertionError("stand-in sim never bound its socket")
        time.sleep(0.05)
    return proc


def _reap(proc: subprocess.Popen | None) -> None:
    """Unconditional teardown for the stand-ins these tests start.

    Every one of them is spawned with ``start_new_session=True``, so the pid is
    its own process group leader and ``killpg`` cannot reach pytest.
    """

    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=10)


def _remove_tree(root: Path) -> None:
    """Delete a scratch tree naming every path ABSOLUTELY.

    ``shutil.rmtree`` would be the obvious call and it cannot be used here.
    On Linux it takes the fd-relative fast path, so each deletion raises the
    ``os.remove``/``os.rmdir`` audit event with a bare *basename* and a
    ``dir_fd``. XD-1's repo-write census
    (``tests/_repo_write_guard.Recorder._record``) resolves a relative audited
    path with ``os.path.abspath`` — i.e. against pytest's cwd, the repository
    root — and so charges this test with writing ``conftest.py``, ``sim.py``
    and ``test_leaky.py`` into the repo, which it never did. Measured, not
    guessed; reported to XD-1 (``scrum/20260822/task_14``) rather than patched
    here, because that file belongs to another card.

    Walking bottom-up with ``os.path.join`` is correct on its own terms: the
    audit record then carries the true absolute path, which is outside the
    repository, which is what it is.
    """

    for parent, dirs, files in os.walk(root, topdown=False):
        for name in (*files, *dirs):
            target = os.path.join(parent, name)
            with contextlib.suppress(OSError):
                if os.path.isdir(target) and not os.path.islink(target):
                    os.rmdir(target)
                else:
                    os.remove(target)
    with contextlib.suppress(OSError):
        os.rmdir(root)


# ---------------------------------------------------------------------------
# The ownership rule: never touch a process this run did not start.
# ---------------------------------------------------------------------------


def _record(pid: int, socket: str, *, starttime: int = 1234) -> _sim_guard.SimProcess:
    return _sim_guard.SimProcess(
        pid=pid,
        ppid=1,
        starttime_ticks=starttime,
        argv=(sys.executable, "-m", "parcel_robot.sim", "--socket", socket),
    )


def test_the_owners_live_stack_is_never_ours_to_reap(tmp_path: Path) -> None:
    """The one process on this host that must survive every automated cleanup.

    ``/tmp/parcel_sim.sock`` is the owner's running simulator, paired with the
    control deck on :8765. It is excluded twice over — it is not under any
    pytest basetemp, *and* :attr:`SimProcess.is_owner_stack` rejects it — and
    both are asserted, because a guard that depends on one condition for this
    is a guard one refactor away from killing the owner's session.
    """

    owner = _record(424242, "/tmp/parcel_sim.sock")
    assert owner.is_owner_stack is True

    ownership = _sim_guard.Ownership(
        session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
    )
    assert _sim_guard.started_by_this_run(owner, ownership) is False

    # And the reaper refuses it even if a caller hands it over directly.
    assert _sim_guard.reap(owner).action == "refused: owner stack"


def test_a_sim_outside_this_sessions_basetemp_is_not_ours(tmp_path: Path) -> None:
    """Another agent session's pytest run is not this run.

    Five sessions share this working tree. Their sims also sit on
    ``/tmp/pytest-of-<user>/pytest-<n>/`` sockets, so "looks like a test sim"
    cannot be the ownership test — only *this* session's basetemp can.
    """

    stranger = _record(424243, "/tmp/pytest-of-someone/pytest-9999/test_x0/sim.sock")
    ownership = _sim_guard.Ownership(
        session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
    )
    assert _sim_guard.started_by_this_run(stranger, ownership) is False


def test_a_sim_alive_before_the_run_is_not_ours(tmp_path: Path) -> None:
    """Even inside our own basetemp, "was already there" beats every other signal."""

    inherited = _record(424244, str(tmp_path / "test_x0" / "sim.sock"))
    ownership = _sim_guard.Ownership(
        session_root=tmp_path,
        pytest_pid=os.getpid(),
        before=frozenset({inherited.key}),
    )
    assert _sim_guard.started_by_this_run(inherited, ownership) is False

    # The same record, absent from the before-snapshot, IS ours: this asserts
    # the previous line failed for the reason claimed and not by accident.
    fresh = _sim_guard.Ownership(
        session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
    )
    assert _sim_guard.started_by_this_run(inherited, fresh) is True


def test_a_recycled_pid_cannot_impersonate_a_survivor(tmp_path: Path) -> None:
    """Identity is ``(pid, starttime)``, so a reissued pid is a different process."""

    observed = _record(424245, str(tmp_path / "sim.sock"), starttime=1000)
    recycled = _record(424245, str(tmp_path / "sim.sock"), starttime=2000)
    assert observed.key != recycled.key
    ownership = _sim_guard.Ownership(
        session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset({observed.key})
    )
    assert _sim_guard.started_by_this_run(recycled, ownership) is True
    assert _sim_guard.started_by_this_run(observed, ownership) is False


def test_reap_refuses_a_pid_that_is_no_longer_the_process_it_observed(tmp_path: Path) -> None:
    """The re-identification immediately before the signal, on a live process.

    Between a census and a kill, a pid can die and be reissued to something
    else entirely — which on this host might be another agent's work, or the
    owner's. So the record is checked against ``/proc`` again at the moment of
    signalling, and a mismatched start time is a refusal.

    The assertion that matters is the last one: the process is **still alive**
    afterwards. A refusal that still sent a signal would pass every other check
    here.
    """

    proc = None
    try:
        proc = _spawn_standin(_standin_root(tmp_path), tmp_path / "sim.sock")
        live = next(r for r in _sim_guard.scan().values() if r.pid == proc.pid)
        stale = _sim_guard.SimProcess(
            pid=live.pid,
            ppid=live.ppid,
            starttime_ticks=live.starttime_ticks + 1,
            argv=live.argv,
        )
        assert _sim_guard.reap(stale).action == "refused: pid no longer the process we observed"
        assert proc.poll() is None, "a refused reap still signalled the process"

        # A record for a pid that simply does not exist reports that, and
        # signals nothing.
        assert _sim_guard.reap(_record(4_000_000, "/x/sim.sock")).action == "already gone"
    finally:
        _reap(proc)


def test_a_processs_start_time_is_dated_accurately_enough_to_attribute_it() -> None:
    """The clock the whole report rests on, pinned against a known instant.

    :func:`_sim_guard.attribute` allows half a second of slack, so an error
    larger than that silently downgrades every report from "this test leaked
    it" to "somewhere in this file". That is not hypothetical: the first
    implementation read ``/proc/stat``'s whole-second ``btime`` and was
    measured **0.633 s early** on this host, and the guard's first live run
    named the file. This test fails if that regresses, and it is asserted
    against a spawn instant this process observes directly rather than against
    any other reading of the same clock.
    """

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    spawned_at = time.time()
    try:
        stat = Path(f"/proc/{proc.pid}/stat").read_text()
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        record = _sim_guard.SimProcess(
            pid=proc.pid,
            ppid=os.getpid(),
            starttime_ticks=ticks,
            argv=(sys.executable, "-m", "parcel_robot.sim"),
        )
        error = record.started_at - spawned_at
        assert abs(error) < 0.2, (
            f"process start times are {error:+.3f} s out; attribution allows "
            "0.5 s, so this would start charging leaks to the wrong test"
        )
    finally:
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)


def test_the_predicate_matches_what_pgrep_matches() -> None:
    assert _sim_guard.is_parcel_sim(("python", "-m", "parcel_robot.sim", "--socket", "/x")) is True
    assert _sim_guard.is_parcel_sim(("python", "/a/b/parcel_robot/sim.py")) is True
    assert _sim_guard.is_parcel_sim(("python", "-m", "parcel_robot.web_panel")) is False
    assert _sim_guard.socket_of(("x", "--socket", "/a/b.sock")) == "/a/b.sock"
    assert _sim_guard.socket_of(("x", "--socket=/a/b.sock")) == "/a/b.sock"
    assert _sim_guard.socket_of(("x", "--static-city")) is None


def test_scan_finds_a_live_sim_and_forgets_it_once_it_dies(tmp_path: Path) -> None:
    """The census is real: it sees a running stand-in and stops seeing it after."""

    proc = None
    try:
        proc = _spawn_standin(_standin_root(tmp_path), tmp_path / "sim.sock")
        found = _sim_guard.scan()
        mine = [record for record in found.values() if record.pid == proc.pid]
        assert mine, "scan() missed a live parcel_robot.sim it should have found"
        assert mine[0].socket == str(tmp_path / "sim.sock")
        assert _sim_guard.reap(mine[0]).action in {"terminated", "killed"}
        assert not [r for r in _sim_guard.scan().values() if r.pid == proc.pid]
    finally:
        _reap(proc)


# ---------------------------------------------------------------------------
# The same three refusals, on records the SCANNER built from live processes.
#
# The four tests above assert on ``SimProcess`` records constructed by hand.
# That is a real test of the predicate and it is not enough for row R6, which
# was pre-registered as "asserted on a record built from the same code path the
# reaper consumes": a hand-built record cannot catch a bug in ``_read``/``scan``
# — a mis-parsed ``/proc`` field, a dropped argv token — and it is exactly
# ``scan()`` whose output the conftest fixture hands to ``started_by_this_run``
# and then to ``reap``. So each refusal is repeated below against a process
# that really exists, found by the real scan, with the process still alive at
# the end as the proof that nothing was signalled.
# ---------------------------------------------------------------------------


def test_a_live_process_wearing_the_owners_argv_is_refused_by_the_real_scan(
    tmp_path: Path,
) -> None:
    """R6(a). The owner's stack, as the guard would actually meet it.

    The decoy's argv is ``-m parcel_robot.sim --socket /tmp/parcel_sim.sock`` —
    byte for byte what ``scripts/launch_sim.sh`` gives the owner's own
    simulator — so ``scan()`` produces a record indistinguishable from the real
    one. It binds a scratch socket instead, because a test that created
    ``/tmp/parcel_sim.sock`` would be a worse bug than the one this card fixes.

    Note what is deliberately *not* true here: the decoy IS a descendant of
    this pytest process, so the descendant rule alone would claim it. The owner
    check has to win over that, and this is where it is proved.
    """

    owner_socket_before = Path("/tmp/parcel_sim.sock").exists()
    proc = None
    try:
        standin = _standin_root(tmp_path, source=_STANDIN_DECOY)
        proc = _spawn_decoy(
            standin,
            module="sim",
            argv_tail=["--socket", "/tmp/parcel_sim.sock"],
            bind=tmp_path / "decoy.sock",
        )
        record = next(r for r in _sim_guard.scan().values() if r.pid == proc.pid)
        assert record.socket == "/tmp/parcel_sim.sock"
        assert record.is_owner_stack is True
        assert _sim_guard._is_descendant(record.pid, os.getpid()) is True

        ownership = _sim_guard.Ownership(
            session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
        )
        assert _sim_guard.started_by_this_run(record, ownership) is False
        assert _sim_guard.reap(record).action == "refused: owner stack"
        assert proc.poll() is None, "a refused reap still signalled the owner's stack"
    finally:
        _reap(proc)
    assert Path("/tmp/parcel_sim.sock").exists() == owner_socket_before, (
        "this test changed the owner's socket path; it must never touch it"
    )


def test_the_control_deck_on_8765_is_not_even_in_the_census(tmp_path: Path) -> None:
    """R6(a), second half. The panel is not a sim, so it is never a candidate.

    The other half of the owner's stack is ``parcel_robot.web_panel`` on
    :8765. The guard never has to refuse it, because the census never admits
    it — asserted here on a live process rather than on a tuple, and asserted
    twice: the guard's ``scan()`` and the operator tool's ``census()``.

    The decoy binds nothing at all: no test in this tree may listen on 8765.
    """

    proc = None
    try:
        standin = _standin_root(tmp_path, module="web_panel", source=_STANDIN_DECOY)
        proc = _spawn_decoy(standin, module="web_panel", argv_tail=["--port", "8765"], bind=None)
        assert proc.pid not in {record.pid for record in _sim_guard.scan().values()}
        assert proc.pid not in {row["pid"] for row in _census_rows()}

        # And it never listened: the port belongs to the owner's deck.
        listening = subprocess.run(
            ["ss", "-ltnp"], capture_output=True, text=True, check=False
        )
        assert f"pid={proc.pid}" not in listening.stdout, (
            "the control-deck decoy opened a listening socket; it must not"
        )
    finally:
        _reap(proc)


def test_a_live_sim_outside_our_basetemp_and_our_tree_is_not_ours(tmp_path: Path) -> None:
    """R6(b). A genuine, running sim that this run cannot prove it started.

    Started through an intermediate ``sh`` that exits immediately, so the
    process is reparented away from pytest — the shape of every orphan this
    card is about — and put on a socket under this card's own scratch
    directory, i.e. outside any pytest basetemp. Both ownership routes
    therefore answer no, and the guard leaves it alone.

    That cuts both ways and the status doc says so: an orphan like this one is
    invisible to the guard by construction. Proving ownership is the price of
    being allowed to signal anything on a host five sessions share.
    """

    socket_path = SCRATCH.parent / "r6_stranger.sock"
    SCRATCH.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    standin = _standin_root(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(standin), env.get("PYTHONPATH", "")) if part
    )
    # ``>/dev/null 2>&1`` is load-bearing, not tidiness: the background child
    # inherits the captured pipe, and ``subprocess.run`` reads it to EOF — with
    # the child holding the write end for an hour, this call would never return.
    launcher = subprocess.run(
        [
            "sh",
            "-c",
            '"$1" -m parcel_robot.sim --socket "$2" >/dev/null 2>&1 & echo $!',
            "sh",
            sys.executable,
            str(socket_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    stranger_pid = int(launcher.stdout.strip())
    try:
        deadline = time.monotonic() + 20.0
        while not socket_path.exists():
            assert time.monotonic() < deadline, "the stranger sim never bound its socket"
            time.sleep(0.05)

        record = next(r for r in _sim_guard.scan().values() if r.pid == stranger_pid)
        assert record.socket == str(socket_path)
        assert record.is_owner_stack is False
        assert _sim_guard._is_descendant(record.pid, os.getpid()) is False, (
            "the stranger is still parented to pytest; the reparenting trick failed "
            "and this test would prove nothing"
        )
        ownership = _sim_guard.Ownership(
            session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
        )
        assert _sim_guard.started_by_this_run(record, ownership) is False

        # Same record, same run, socket moved under our basetemp: now it IS
        # ours. Without this line the assertion above could pass for any
        # reason at all.
        ours = _sim_guard.SimProcess(
            pid=record.pid,
            ppid=record.ppid,
            starttime_ticks=record.starttime_ticks,
            argv=(sys.executable, "-m", "parcel_robot.sim", "--socket", str(tmp_path / "s.sock")),
        )
        assert _sim_guard.started_by_this_run(ours, ownership) is True
    finally:
        _reap_pid(stranger_pid)
        socket_path.unlink(missing_ok=True)


def test_a_live_sim_alive_before_the_run_is_not_ours_on_the_real_scan(tmp_path: Path) -> None:
    """R6(c). "It was already there" beats every other signal, on a real record.

    The stand-in here is ours by both routes — our descendant, on a socket
    under our basetemp — which is what makes the refusal meaningful: the only
    thing that changes between the two assertions is whether the record was in
    the before-snapshot.
    """

    proc = None
    try:
        proc = _spawn_standin(_standin_root(tmp_path), tmp_path / "sim.sock")
        record = next(r for r in _sim_guard.scan().values() if r.pid == proc.pid)

        fresh = _sim_guard.Ownership(
            session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset()
        )
        assert _sim_guard.started_by_this_run(record, fresh) is True

        inherited = _sim_guard.Ownership(
            session_root=tmp_path, pytest_pid=os.getpid(), before=frozenset({record.key})
        )
        assert _sim_guard.started_by_this_run(record, inherited) is False
        assert proc.poll() is None, "the process was signalled while being classified"
    finally:
        _reap(proc)


# ---------------------------------------------------------------------------
# The fixture bug that actually leaked the eighteen.
# ---------------------------------------------------------------------------


def test_live_runtime_setup_error_tears_the_sim_down(tmp_path: Path, monkeypatch) -> None:
    """Seeded RED for the fix in ``tests/test_voice_nav_e2e.py``.

    The failure is injected exactly where the real one happened: at
    ``build_runtime``, after the simulator is already running. Before the fix
    the spawned process survived this test; that is what produced eighteen
    orphans in one run of eighteen cases, each about a second apart.

    ``subprocess.Popen`` is replaced so the "simulator" is the stand-in rather
    than 840 MB of MuJoCo — but the code under test is the real
    ``_LiveRuntime.__init__``, unmodified, including its process-group
    teardown.
    """

    module = importlib.import_module("test_voice_nav_e2e")
    standin = _standin_root(tmp_path)
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def fake_popen(argv, **kwargs):
        assert "parcel_robot.sim" in argv, "the fixture stopped launching a simulator"
        assert kwargs.get("start_new_session") is True, (
            "the sim must lead its own process group or group teardown would "
            "signal pytest itself"
        )
        socket_path = Path(argv[argv.index("--socket") + 1])
        env = dict(kwargs.get("env") or os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(standin), env.get("PYTHONPATH", "")) if part
        )
        proc = real_popen(
            [sys.executable, "-m", "parcel_robot.sim", "--socket", str(socket_path)],
            env=env,
            start_new_session=True,
        )
        spawned.append(proc)
        return proc

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    def refuse(*args, **kwargs):
        raise RuntimeError("HY-1 seeded setup error (stands in for MemoryPathRefused)")

    monkeypatch.setattr(module, "build_runtime", refuse)

    try:
        with pytest.raises(RuntimeError, match="HY-1 seeded setup error"):
            module._LiveRuntime(tmp_path)

        assert spawned, "the seeded error fired before the sim was even spawned"
        proc = spawned[0]
        # __init__ waits for the child, so this needs no polling: if the
        # process is alive here, the teardown did not happen.
        assert proc.poll() is not None, (
            f"the simulator (pid {proc.pid}) outlived a setup error — this is the "
            "leak that produced 18 orphans on 2026-08-22"
        )
    finally:
        for proc in spawned:
            _reap(proc)


# ---------------------------------------------------------------------------
# The guard names the leak.
# ---------------------------------------------------------------------------


_LEAKY_TEST = '''
"""Generated by tests/test_hy1_sim_guard.py. Deliberately leaks a simulator."""

import os
import subprocess
import sys
import time
from pathlib import Path


def test_this_one_leaks_a_sim(tmp_path):
    socket_path = tmp_path / "sim.sock"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (os.environ["HY1_STANDIN_ROOT"], env.get("PYTHONPATH", "")) if part
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "parcel_robot.sim", "--socket", str(socket_path)],
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20.0
    while not socket_path.exists():
        assert proc.poll() is None and time.monotonic() < deadline, "stand-in never bound"
        time.sleep(0.05)
    Path(os.environ["HY1_LEAK_RECORD"]).write_text(f"{proc.pid}\\n{socket_path}\\n")
    # No teardown. That is the point.
'''


def _run_inner_pytest(*, guard_mode: str) -> tuple[subprocess.CompletedProcess, int, str, Path]:
    """Run a nested pytest session whose only test leaks a sim.

    The real ``tests/conftest.py`` is copied in rather than imitated, so this
    exercises the guard as shipped: if someone deletes the HY-1 region, this
    test goes red.

    The work tree is a SHORT path from ``mkdtemp``, not the caller's
    ``tmp_path``. A nested pytest basetemp inside an outer one produces socket
    paths past the 107-byte ``AF_UNIX`` limit, and the stand-in then fails to
    bind for a reason with nothing to do with what is under test — measured,
    not guessed: the first version of this test died on exactly that.
    """

    SCRATCH.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="r", dir=SCRATCH))
    shutil.copy(REPO / "tests" / "conftest.py", work / "conftest.py")
    (work / "test_leaky.py").write_text(_LEAKY_TEST)
    record = work / "leak_record.txt"

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO), str(REPO / "tests"), env.get("PYTHONPATH", "")) if part
    )
    env["HY1_STANDIN_ROOT"] = str(_standin_root(work))
    env["HY1_LEAK_RECORD"] = str(record)
    env["PARCEL_SIM_GUARD"] = guard_mode
    env.pop("TMPDIR", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(work / "test_leaky.py"),
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            f"--basetemp={work / 'basetemp'}",
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    lines = record.read_text().splitlines() if record.exists() else []
    leaked_pid = int(lines[0]) if lines else 0
    leaked_socket = lines[1] if len(lines) > 1 else ""
    return result, leaked_pid, leaked_socket, work


def _wait_gone(pid: int, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True
        time.sleep(0.1)
    return False


def test_the_guard_fails_the_run_and_names_the_leaking_test() -> None:
    """Seeded RED for the guard: a deliberate leak, caught and named.

    This is the whole point of the card. The assertion is not "the run failed"
    — a count is what the old world already gave us. It is that the failure
    text carries the three facts an engineer needs to fix it without a
    ``pgrep`` expedition: **which test**, **which pid**, **which socket**.
    """

    result, leaked_pid, leaked_socket, work = _run_inner_pytest(guard_mode="reap")
    output = result.stdout + result.stderr
    try:
        assert leaked_pid, f"the inner run never recorded a leaked pid:\n{output[-3000:]}"
        assert result.returncode != 0, f"the guard let a leak through:\n{output[-3000:]}"
        assert "HY-1 sim guard" in output
        # Not merely "the name appears somewhere": pytest's own "ERROR at
        # teardown of <test>" header would satisfy that while the guard's
        # attribution silently fell back to naming the file. It did exactly
        # that on the first live run of this card — the guard's clock was
        # 0.633 s off (see ``_sim_guard._boot_time``) and every survivor
        # landed outside its test's window. So the assertion is on the
        # guard's OWN line.
        assert "leaked by : test_leaky.py::test_this_one_leaks_a_sim" in output, (
            "the guard did not attribute the leak to the test that caused it "
            f"(it printed:\n{output[-3000:]})"
        )
        assert str(leaked_pid) in output, "the report does not carry the pid"
        assert leaked_socket in output, "the report does not carry the socket path"
        # Default mode also cleans up, so the next run starts from a clean host.
        assert _wait_gone(leaked_pid), "the guard reported the leak but left it running"
    finally:
        if leaked_pid and not _wait_gone(leaked_pid, timeout_s=0.1):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(leaked_pid, signal.SIGKILL)
        _remove_tree(work)


def test_without_the_guard_the_same_leak_is_silent() -> None:
    """The control. Without the guard the identical run is GREEN and leaks.

    This is what makes the test above evidence rather than decoration: it shows
    the guard is what turns the run red, and it reproduces — in twenty seconds
    — the exact silence that let eighteen simulators accumulate unnoticed.
    """

    result, leaked_pid, _, work = _run_inner_pytest(guard_mode="off")
    output = result.stdout + result.stderr
    try:
        assert result.returncode == 0, f"expected a green, silent run:\n{output[-3000:]}"
        assert "HY-1 sim guard" not in output
        assert leaked_pid, "the control did not actually leak anything"
        assert not _wait_gone(leaked_pid, timeout_s=0.5), (
            "the control's sim died on its own; the leak was not reproduced"
        )
    finally:
        # This one is ours to clean up: we started it, and nothing else will.
        if leaked_pid:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(leaked_pid, signal.SIGKILL)
            _wait_gone(leaked_pid)
        _remove_tree(work)


# ---------------------------------------------------------------------------
# The operator's tools.
# ---------------------------------------------------------------------------


def _dotted_calls(source: str) -> set[str]:
    """Every dotted name that appears in a call position, e.g. ``os.killpg``."""

    names: set[str] = set()

    def dotted(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = dotted(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return None

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name:
                names.add(name)
    return names


def test_the_census_tool_cannot_signal_anything() -> None:
    """``tools/list_parcel_procs.py`` diagnoses; it must never destroy.

    Asserted over the AST rather than the text so the module docstring, which
    talks about killing at length, cannot make this pass or fail by accident.
    A tool that both reports and kills gets run in a hurry by someone reading
    only its first line.
    """

    source = (REPO / "tools" / "list_parcel_procs.py").read_text()
    called = _dotted_calls(source)
    banned = {
        "os.kill",
        "os.killpg",
        "proc.kill",
        "proc.terminate",
        "subprocess.run",
        "subprocess.Popen",
        "_sim_guard.reap",
    }
    assert not (called & banned), f"the census tool signals processes: {sorted(called & banned)}"
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "signal" not in imported


def test_the_census_tool_agrees_with_ps_on_a_live_sim(tmp_path: Path) -> None:
    """The operator census must agree with ``ps``, on a process we control.

    Asserting against a bare ``pgrep`` of the live host would be a race — five
    agent sessions share this machine and sims come and go mid-test. So the
    agreement is measured on one stand-in this test starts and stops: the tool
    must find it, classify it, and read its socket out of argv exactly as ``ps``
    shows it. A census whose idea of "a simulator" drifts from the tool everyone
    already types hides precisely the leaks it exists to surface.
    """

    proc = None
    try:
        proc = _spawn_standin(_standin_root(tmp_path), tmp_path / "sim.sock")
        rows = {row["pid"]: row for row in _census_rows()}
        assert proc.pid in rows, "the census tool missed a live parcel_robot.sim"
        row = rows[proc.pid]
        assert row["socket"] == str(tmp_path / "sim.sock")
        assert row["socket_exists"] is True
        assert row["kind"] == "pytest-scratch"

        # ``-ww`` is load-bearing and was found the hard way: plain
        # ``ps -o args= -p <pid>`` truncates at 80 columns, which cuts the
        # ``--socket <path>`` right off a Parcel sim's argv. An operator
        # re-identifying a pid before killing it would see
        # "python -m parcel_robot.sim" and no socket at all — and so would not
        # be able to tell a scratch sim from the owner's.
        shown = subprocess.run(
            ["ps", "-ww", "-o", "args=", "-p", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "parcel_robot.sim" in shown.stdout
        assert str(tmp_path / "sim.sock") in shown.stdout

        narrow = subprocess.run(
            ["ps", "-o", "args=", "-p", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert len(narrow.stdout.strip()) <= len(shown.stdout.strip()), (
            "ps without -ww returned MORE than with it; the truncation note above "
            "needs re-measuring"
        )

        # And every other row it reports is really a sim, per ps. One ps call
        # for the whole set, not one per pid: on this host a fork from a large
        # pytest process costs most of a second, and the loop version took 13 s.
        listing = subprocess.run(
            ["ps", "-ww", "-o", "pid=,args=", "-p", ",".join(str(pid) for pid in rows)],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in listing.stdout.splitlines():
            pid_text, _, args_text = line.strip().partition(" ")
            if pid_text.isdigit() and int(pid_text) in rows:
                assert "parcel_robot.sim" in args_text, (
                    f"census reported pid {pid_text}, which ps says is not a sim: {args_text}"
                )
    finally:
        _reap(proc)


def _census_rows() -> list[dict]:
    sys.path.insert(0, str(REPO / "tools"))
    try:
        module = importlib.import_module("list_parcel_procs")
        return module.census()
    finally:
        sys.path.remove(str(REPO / "tools"))


def test_the_census_classifies_the_owners_socket_as_the_owners() -> None:
    sys.path.insert(0, str(REPO / "tools"))
    try:
        module = importlib.import_module("list_parcel_procs")
    finally:
        sys.path.remove(str(REPO / "tools"))
    assert module._pytest_scratch("/tmp/pytest-of-x/pytest-9/t0/sim.sock") is True
    assert module._pytest_scratch("/tmp/parcel_sim.sock") is False
    assert module._pytest_scratch(None) is False


def test_launch_sim_offers_a_pidfile_and_removes_only_its_own() -> None:
    """``scripts/launch_sim.sh --pidfile`` — the harness half of the contract.

    Structural: the live launch is measured once and recorded in
    ``HY1_STATUS.md`` (it starts a real simulator and a real control deck, which
    a unit test on a shared host must not do). What is pinned here is the part
    a later edit could silently drop: that the pid is written, that cleanup
    runs, and that cleanup refuses to delete a pidfile another launch has since
    taken over.
    """

    script = (REPO / "scripts" / "launch_sim.sh").read_text()
    assert "--pidfile PATH" in script, "the flag vanished from --help"
    assert 'printf \'%s\\n\' "$SIM_PID" >| "$PIDFILE"' in script
    assert "cleanup_pidfile" in script
    # Cleanup is wired into the trap, not merely defined.
    cleanup_body = script.split("cleanup() {", 1)[1].split("}", 1)[0]
    assert "cleanup_pidfile" in cleanup_body
    # And it compares before deleting.
    guard_body = script.split("cleanup_pidfile() {", 1)[1].split("\n}", 1)[0]
    assert '[[ "$recorded" == "$SIM_PID" ]] || return 0' in guard_body
