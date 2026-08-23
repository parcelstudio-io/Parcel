"""Card HY-1 — name the test that leaked a simulator, then reap only what we started.

Why this exists
---------------
On 2026-08-22 eighteen ``parcel_robot.sim`` processes were found alive on
pytest scratch sockets under ``/tmp/pytest-of-jaewoo-jang/pytest-3848/``, each
holding a LISTEN unix socket whose directory pytest had already deleted, each
resident at ~840 MB — roughly 15 GB of RAM and eighteen idle MuJoCo steppers
distorting every latency measurement taken afterwards.  They were found by a
verifier with ``pgrep``, hours later.  The suite that produced them reported
success at the shell.

The defect is a fixture that spawns a child *before* the ``try`` that would
tear it down (``tests/test_voice_nav_e2e.py``); an error during the rest of
setup leaves the child parented to init.  That specific bug is fixed at its
source.  This module exists for the *next* one: it makes the suite itself the
thing that notices, and it makes the report actionable — the failing test's
name, the pid, and the socket path, not a count.

The safety argument
-------------------
The standing rule for this tree is *never kill a process you did not start*,
and several agent sessions plus the owner's own stack share the host.  So the
reaper is deliberately narrow.  A process is a candidate only when **all** of:

1. it is a ``parcel_robot.sim`` (same predicate as ``pgrep -af parcel_robot.sim``);
2. it was **not** alive in the snapshot taken before the run — identified by
   ``(pid, starttime)``, so a recycled pid cannot impersonate one;
3. it is either a descendant of *this* pytest process, or its ``--socket`` path
   lies inside *this* session's ``basetemp`` — a concurrent pytest session in
   the same tree has a different basetemp, so its sims are never ours;
4. its socket is not one of :data:`OWNER_SOCKET_PATHS`.

Rule 4 is redundant given 2 and 3 and is kept anyway: the owner's live stack on
``/tmp/parcel_sim.sock`` is the one process on this host that must never be
touched by an automated cleanup, and a guard that relies on a single condition
for that is a guard one refactor away from killing it.

Linux only, by design: it reads ``/proc``.  ``psutil`` is not a dependency of
this project and this file does not add one.
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

#: Sockets that belong to the owner's own running stack, never to a test.
#: ``scripts/launch_sim.sh`` defaults to the first entry and the control deck
#: to port 8765; see the tree's CLAUDE.md ("the owner's live stack ... is never
#: killed").  ``PARCEL_SIM_SOCKET`` is honoured because the owner may relocate
#: it, and a relocated owner socket is still the owner's.
OWNER_SOCKET_PATHS: tuple[str, ...] = (
    "/tmp/parcel_sim.sock",
    os.environ.get("PARCEL_SIM_SOCKET", "").strip() or "/tmp/parcel_sim.sock",
)

#: Environment switch. ``report`` observes and fails without signalling
#: anything; ``reap`` (the default) also terminates the survivors it is
#: certain it started; ``off`` disables the guard entirely.  A leak is a bug
#: either way — ``reap`` does not make the run green, it makes the *next* run
#: clean.
GUARD_MODE_ENV = "PARCEL_SIM_GUARD"

_CLK_TCK = os.sysconf("SC_CLK_TCK")


def _boot_time() -> float:
    """Wall-clock epoch seconds at which this kernel booted.

    ``/proc/stat``'s ``btime`` is the obvious source and it is **not good
    enough**: it is quantised to whole seconds, and a test that leaks a
    simulator often runs for less than one.  Measured on this host on
    2026-08-22, ``btime`` dated a child process **0.633 s early** — more than
    the half-second of slack :func:`attribute` allows — and the guard's first
    live report therefore named the leaking *file* instead of the leaking
    *test*, which is the one thing this card exists to deliver.

    ``/proc/uptime`` is centisecond precision and comes from the same
    boot-time clock the ``starttime`` field in ``/proc/<pid>/stat`` counts
    against; on the same measurement it reproduced the true spawn instant to
    **1 ms**.  ``btime`` stays as a fallback for a kernel without
    ``/proc/uptime``, where a second of error still beats no attribution.
    """

    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    else:
        return time.time() - uptime
    for line in Path("/proc/stat").read_text().splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    raise RuntimeError("/proc has neither uptime nor btime; cannot date processes")


_BOOT_TIME = _boot_time()


def is_parcel_sim(argv: tuple[str, ...]) -> bool:
    """True for a simulator process, by the same shape ``pgrep -af`` matches.

    Both spellings are accepted because both are reachable: ``-m
    parcel_robot.sim`` (every fixture and ``scripts/launch_sim.sh``) and a
    direct path to the module file.
    """

    for token in argv:
        if token == "parcel_robot.sim" or token.endswith("parcel_robot/sim.py"):
            return True
    return False


def socket_of(argv: tuple[str, ...]) -> str | None:
    """The ``--socket`` value in an argv, or ``None`` when it is not given."""

    for index, token in enumerate(argv):
        if token == "--socket" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--socket="):
            return token.split("=", 1)[1]
    return None


@dataclass(frozen=True)
class SimProcess:
    """One live ``parcel_robot.sim``, dated so a recycled pid cannot impersonate it."""

    pid: int
    ppid: int
    starttime_ticks: int
    argv: tuple[str, ...]

    @property
    def key(self) -> tuple[int, int]:
        """Identity that survives pid reuse: the pid *and* when it started."""

        return (self.pid, self.starttime_ticks)

    @property
    def socket(self) -> str | None:
        return socket_of(self.argv)

    @property
    def started_at(self) -> float:
        """Wall-clock epoch seconds at which this process started."""

        return _BOOT_TIME + self.starttime_ticks / _CLK_TCK

    @property
    def is_owner_stack(self) -> bool:
        socket = self.socket
        return socket is not None and socket in OWNER_SOCKET_PATHS

    def describe(self) -> str:
        return (
            f"pid {self.pid} (parent {self.ppid}, started "
            f"{time.strftime('%H:%M:%S', time.localtime(self.started_at))}) "
            f"socket {self.socket or '<none>'}"
        )


def _read(pid: int) -> SimProcess | None:
    """Read one ``/proc`` entry, or ``None`` if it is gone or is not a sim."""

    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        if b"parcel_robot" not in raw:
            return None
        argv = tuple(part.decode("utf-8", "replace") for part in raw.split(b"\0") if part)
        if not is_parcel_sim(argv):
            return None
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    # The comm field is parenthesised and may itself contain spaces and
    # parentheses, so the tail is taken after the LAST ')'.
    tail = stat.rsplit(")", 1)[1].split()
    # tail[0] is state; /proc field 4 (ppid) is tail[1], field 22 (starttime)
    # is tail[19].
    try:
        return SimProcess(pid=pid, ppid=int(tail[1]), starttime_ticks=int(tail[19]), argv=argv)
    except (IndexError, ValueError):
        return None


def scan() -> dict[tuple[int, int], SimProcess]:
    """Every live ``parcel_robot.sim`` on this host, keyed by ``(pid, starttime)``.

    Read-only.  Processes that vanish mid-scan are simply absent from the
    result, which is the correct answer for a census taken at an instant.
    """

    found: dict[tuple[int, int], SimProcess] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        proc = _read(int(entry))
        if proc is not None:
            found[proc.key] = proc
    return found


def _is_descendant(pid: int, ancestor: int, *, limit: int = 64) -> bool:
    """True when ``ancestor`` is on ``pid``'s parent chain.

    Bounded so a ``/proc`` race can never spin.  An orphan reparented to init
    answers False, which is why it is not the only ownership test.
    """

    seen = pid
    for _ in range(limit):
        if seen in (0, 1):
            return False
        if seen == ancestor:
            return True
        proc = _read_ppid(seen)
        if proc is None:
            return False
        seen = proc
    return False


def _read_ppid(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    try:
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (IndexError, ValueError):
        return None


def _under(path: str | None, root: Path | None) -> bool:
    if path is None or root is None:
        return False
    try:
        return Path(path).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


@dataclass(frozen=True)
class Ownership:
    """The facts a reap decision is made from, so the decision can be tested."""

    session_root: Path | None
    pytest_pid: int
    before: frozenset[tuple[int, int]]


def started_by_this_run(proc: SimProcess, ownership: Ownership) -> bool:
    """True only when *this* pytest run is provably responsible for ``proc``.

    The three conditions are ANDed on purpose.  "It looks like a test sim" is
    not ownership: another agent session's pytest run in this same tree also
    launches sims onto pytest scratch sockets, and the owner's stack is a
    ``parcel_robot.sim`` too.
    """

    if proc.key in ownership.before:
        return False  # alive before we started: not ours, whoever owns it.
    if proc.is_owner_stack:
        return False  # belt and braces; see the module docstring.
    if _is_descendant(proc.pid, ownership.pytest_pid):
        return True
    return _under(proc.socket, ownership.session_root)


@dataclass(frozen=True)
class TestWindow:
    """When one test ran, so a survivor's start time can be attributed to it."""

    nodeid: str
    started: float
    finished: float


def attribute(proc: SimProcess, windows: list[TestWindow]) -> str | None:
    """The nodeid of the test that was running when ``proc`` started.

    Windows are recorded from pytest's own report hooks and cost a clock read,
    so attribution is exact without scanning ``/proc`` per test.  Returns
    ``None`` when the process started outside every window (for example during
    module import), and the caller then reports the file rather than inventing
    a test.
    """

    started = proc.started_at
    for window in windows:
        # A half-second of slack at the start.  The kernel tick is 100 Hz
        # here and :func:`_boot_time` was measured accurate to 1 ms, so the
        # slack covers tick quantisation and the userspace read of the window
        # with three orders of magnitude to spare.  It is NOT there to absorb
        # a coarse clock: that error was real (see :func:`_boot_time`) and was
        # fixed at its source rather than papered over with a wider window,
        # because a window wide enough to hide it would also start charging
        # leaks to the neighbouring test.
        if window.started - 0.5 <= started <= window.finished + 0.5:
            return window.nodeid
    return None


@dataclass(frozen=True)
class ReapResult:
    proc: SimProcess
    action: str  # "terminated" | "killed" | "already gone" | "refused: <reason>"


def reap(proc: SimProcess, *, timeout_s: float = 10.0) -> ReapResult:
    """Terminate one survivor, re-identifying it immediately before signalling.

    The re-identification is the whole point: between the census and this call
    the pid may have died and been reissued to something unrelated.  If
    ``/proc`` no longer shows the *same* start time and the *same* argv, no
    signal is sent.

    The signal goes to the process group only when the target leads its own
    group (``setsid``/``start_new_session``); otherwise it goes to the pid
    alone.  A test sim that shares pytest's process group must never be
    reaped by ``killpg`` — that would kill the test runner.
    """

    # The owner check comes FIRST, on the record as handed in, before any
    # ``/proc`` read that could fail or race. Refusing to touch the owner's
    # stack must not depend on being able to look the process up.
    if proc.is_owner_stack:
        return ReapResult(proc, "refused: owner stack")
    current = _read(proc.pid)
    if current is None:
        return ReapResult(proc, "already gone")
    if current.key != proc.key or current.argv != proc.argv:
        return ReapResult(proc, "refused: pid no longer the process we observed")
    if current.is_owner_stack:
        return ReapResult(proc, "refused: owner stack")

    try:
        leads_group = os.getpgid(proc.pid) == proc.pid
    except (ProcessLookupError, PermissionError):
        leads_group = False

    def _signal(sig: int) -> None:
        if leads_group:
            os.killpg(proc.pid, sig)
        else:
            os.kill(proc.pid, sig)

    try:
        _signal(signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return ReapResult(proc, "already gone")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _read(proc.pid) is None:
            return ReapResult(proc, "terminated")
        time.sleep(0.1)

    try:
        _signal(signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return ReapResult(proc, "terminated")
    return ReapResult(proc, "killed")


def format_report(
    scope: str,
    survivors: list[SimProcess],
    windows: list[TestWindow],
    reaped: list[ReapResult],
) -> str:
    """The failure text.  It names the test, the pid and the socket.

    A leak report that says "1 process leaked" costs an engineer the same hour
    the verifier spent with ``pgrep``.  This one is meant to be actionable from
    the scrollback alone.
    """

    lines = [
        f"HY-1 sim guard: {len(survivors)} parcel_robot.sim process(es) outlived {scope}.",
        "",
        "A simulator that survives its test holds a unix socket and ~840 MB, and",
        "distorts every timing measurement taken after it. This is a fixture bug:",
        "the process is spawned outside the try/finally that would tear it down.",
        "",
    ]
    actions = {result.proc.key: result.action for result in reaped}
    for proc in survivors:
        nodeid = attribute(proc, windows) or f"{scope} (outside every test window)"
        lines.append(f"  leaked by : {nodeid}")
        lines.append(f"  process   : {proc.describe()}")
        lines.append(f"  argv      : {' '.join(proc.argv)}")
        lines.append(f"  cleanup   : {actions.get(proc.key, 'not attempted (report mode)')}")
        lines.append("")
    lines.append("Set PARCEL_SIM_GUARD=off to disable this guard (and own the consequences).")
    return "\n".join(lines)


def mode() -> str:
    """``reap`` (default), ``report`` or ``off``, from the environment."""

    value = os.environ.get(GUARD_MODE_ENV, "reap").strip().lower()
    return value if value in {"reap", "report", "off"} else "reap"
