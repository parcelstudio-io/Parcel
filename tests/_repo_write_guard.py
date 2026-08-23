"""The repo-write census. Card XD-1 (``scrum/20260822/task_14``).

WHY THIS EXISTS
---------------
A test that writes a file **under the repository root** is the single class of
defect that turns a green serial suite into a red parallel one, and it does it
without touching the test that breaks. GATE-0 (``AUDIT_WEEK1_FABLE.md``
§GATE-0) is the recorded instance: ``tests/test_unitree_asset_pack.py``'s
carve-out probe wrote a real ``.obj`` into the vendored simulator pack, and at
one-worker-per-test (``-n auto`` on a 192-core host) **two sibling tests went
spuriously red** — they read the pack while the probe was holding it open. The
probe was correct in isolation and wrong in a suite; nothing about it was
timing-sensitive; no amount of reading the failing tests would have found it.

So the commit tier cannot be flipped to ``-n auto`` on the strength of "the
seven known divergences are fixed". The seven were symptoms. This module is the
check for the *class*: any test that writes a path git would notice is named,
with the path and the open mode, in the run that did it.

WHAT COUNTS AS AN OFFENCE — ``.gitignore`` IS THE AUTHORITY
-----------------------------------------------------------
A write is an offence when git would notice it: the path is **tracked**, or it
is **not ignored**. Both questions are answered by git itself
(``git ls-files`` / ``git check-ignore``), so this module ships **no allowlist
of its own** — there is no per-test exemption table to rot, and a card that
wants a new scratch location says so in ``.gitignore`` where every other tool
can see it. Writes to ``tmp_path``, ``/tmp``, the venv, or anywhere outside the
repo are not writes to the repo and are never recorded.

WHY AN AUDIT HOOK AND NOT A PER-TEST ``git status``
---------------------------------------------------
A ``git status --porcelain`` snapshot per test is the obvious implementation and
it is strictly weaker:

* it **misses write-then-delete** — a probe that writes a file into a tracked
  directory and removes it in teardown leaves no trace in ``git status``, and
  that is *exactly* the GATE-0 shape, where the stray only survived because a
  SIGKILL interrupted the cleanup. The hazard is the window, not the residue.
* it cannot name the **path** or the **mode** that caused it, only the residue.
* it costs a ``fork``/``exec`` per test. At 9k tests and 192 workers that is 9k
  git processes competing with the very parallelism this card exists to buy.

The audit hook sees the ``open()`` itself, in-process, with no subprocess at
all, and hands the census the mode as well as the path. ``git`` is consulted
only when a candidate exists, which on a clean tree is never.

WHAT IT CANNOT SEE
------------------
Writes performed by a **child process** a test spawns (the hook is per
interpreter). Those are caught by the session-level ``git status`` diff that
:func:`session_residue` provides, which names the files but not the test — a
deliberately weaker second net for a rarer case.

MODES
-----
``PARCEL_REPO_WRITE_GUARD`` — ``on`` fails the offending test; ``census``
records and reports without failing; ``off`` never installs the hook.
Fail-closed on anything unrecognised, the same way ``scripts/load_guard.py``
refuses to let a typo choose a mode.

**The default is ``census``**, and that was decided by the rule pre-registered
before the census ran (``PREREGISTRATION.md`` §"Decision rule fixed in advance
for D7's guard"): ON iff the census is empty. It is not — it named 10 tests in
three files, none of them this card's to fix — so the guard records. See
:func:`read_mode`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_REPO_PREFIX = str(REPO) + os.sep

MODE_ENV = "PARCEL_REPO_WRITE_GUARD"
MODE_ON = "on"
MODE_CENSUS = "census"
MODE_OFF = "off"
VALID_MODES = (MODE_ON, MODE_CENSUS, MODE_OFF)

#: Card tag carried in every report, so a failure has an owner.
OWNER = "card XD-1 (scrum/20260822/task_14)"

#: Path fragments filtered inside the hot path itself. Every one of these is
#: ignored by the TRACKED ``.gitignore``, so filtering them here changes no
#: verdict — it only saves the ``os.path.abspath`` and the set insert on the
#: writes that every Python process performs constantly (bytecode caches above
#: all). Verified by ``tests/test_xd1_repo_write_guard.py``.
#:
#: Each fragment carries its trailing separator and is matched against the
#: REPO-RELATIVE path, so it can only ever match a whole directory component.
#: The bare substrings this started as were wrong in one direction that
#: matters: ``".git" in ".github/workflows/ci.yml"`` is true, so a test writing
#: into ``.github/`` — a TRACKED directory — would have been silently exempt.
#:
#: ``.hypothesis`` was the one entry whose premise was FALSE on a fresh clone
#: (found by this card's verifier, 2026-08-23): it is ignored on a developer
#: box only because hypothesis writes its own untracked ``.hypothesis/.gitignore``
#: at first run, so on a clean checkout — GATE-0b's PASS-row premise — this
#: filter WAS a private exemption and
#: ``test_the_hot_path_filter_is_a_speed_trick_and_not_an_exemption_table``
#: was RED. Fixed where the rule belongs: one line, ``.hypothesis/``, in the
#: tracked root ``.gitignore`` (integrator-authorised). Seeded both ways on a
#: scratch checkout with no ``.hypothesis/``: RED before the line, green after.
#:
#: ``.git`` itself was in this tuple and has been REMOVED. It does not belong:
#: ``git check-ignore`` does not report ``.git`` as ignored (git excludes its
#: own metadata structurally, not by a rule), so skipping it here would have
#: been a genuine exemption this module is not allowed to own — and an
#: in-process write into ``.git/`` is a louder problem than the one the guard
#: is for, not a quieter one. Every fragment that remains is covered by
#: ``.gitignore``, so this tuple changes no verdict, only speed;
#: ``tests/test_xd1_repo_write_guard.py`` pins exactly that.
_HOT_SKIP = tuple(
    name + os.sep
    for name in ("__pycache__", ".pytest_cache", ".hypothesis", ".ruff_cache")
)

#: ``os.open`` flags that mean "this may modify the file".
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

#: Audit events other than ``open`` that create, move or delete a path, and —
#: for each — WHICH argument is the path that changes and WHERE the ``dir_fd``
#: for it sits. Both halves were wrong in the first draft and both were caught
#: by measurement, not by reading:
#:
#: 1. **``dir_fd``.** CPython emits these events with the caller's raw
#:    arguments, so ``shutil.rmtree`` — which walks with ``dir_fd`` for safety —
#:    reports BARE ENTRY NAMES ("a.txt"). Resolving those against the process
#:    cwd charged every file of an ``rmtree`` of a ``tmp_path`` tree to the
#:    repository, because the cwd under pytest IS the repository. A path that is
#:    relative to a ``dir_fd`` is not relative to the cwd and this module cannot
#:    resolve it, so it is not recorded. (Found by HY-1's executor, 2026-08-23.)
#: 2. **src vs dst.** For ``symlink``/``link`` the path that gets CREATED is the
#:    second argument; the first is only read. Recording ``args[0]`` named the
#:    wrong path and missed the real one. ``rename`` changes BOTH ends, so both
#:    are recorded.
#:
#: ``dir_fd`` is ``-1`` when the caller did not pass one. Layout verified
#: against CPython by probe, and pinned by ``tests/test_xd1_repo_write_guard.py``.
_PATH_ARGS: dict[str, tuple[tuple[int, int | None], ...]] = {
    "os.mkdir": ((0, 2),),          # (path, mode, dir_fd)
    "os.rmdir": ((0, 1),),          # (path, dir_fd)
    "os.remove": ((0, 1),),         # (path, dir_fd)
    "os.truncate": ((0, None),),    # (path_or_fd, length)
    "os.symlink": ((1, 2),),        # (src, DST, dir_fd)
    "os.link": ((1, 3),),           # (src, DST, src_dir_fd, dst_dir_fd)
    "os.rename": ((0, 2), (1, 3)),  # (SRC, DST, src_dir_fd, dst_dir_fd)
}

#: Kept as a set for readers and for the tests that enumerate the family.
_PATH_EVENTS = frozenset(_PATH_ARGS)

_MODE_CACHE: dict[str, bool] = {}


class RepoWriteGuardMisconfigured(RuntimeError):
    """Raised for an unrecognised :data:`MODE_ENV` value."""


def read_mode(env: dict[str, str] | None = None) -> str:
    """Resolve the guard mode, fail-closed on anything unrecognised."""

    source = os.environ if env is None else env
    raw = (source.get(MODE_ENV) or "").strip().lower()
    if not raw:
        # DEFAULT = census, decided by the D7 rule pre-registered BEFORE the
        # census ran, not by taste: "ON by default iff the census is empty
        # after my fixes; otherwise opt-in, and every offender listed for its
        # owner." The census (XD1_STATUS.md row D7) named 10 tests in three
        # files, none of them this card's to fix -- so the guard RECORDS and
        # does not fail. Failing them would be this card reddening five other
        # cards' tests on its own authority, and the board's standing rule
        # forbids the alternative (a per-test exemption table is an allowlist).
        # ``PARCEL_REPO_WRITE_GUARD=on`` is the one word that turns it into a
        # gate, the day the last offender is fixed.
        return MODE_CENSUS
    if raw not in VALID_MODES:
        raise RepoWriteGuardMisconfigured(
            f"{MODE_ENV}={raw!r} is not one of {VALID_MODES}. Refusing to guess: an "
            "unrecognised value silently choosing a mode is how a guard becomes an "
            "unconditional pass."
        )
    return raw


def _mode_writes(mode: str) -> bool:
    cached = _MODE_CACHE.get(mode)
    if cached is None:
        cached = any(ch in mode for ch in "wxa+")
        _MODE_CACHE[mode] = cached
    return cached


class Recorder:
    """Collects candidate repo-write paths for the test currently running.

    One instance per interpreter (so one per xdist worker). The audit hook is
    installed once and never removed — CPython does not allow removing one —
    so :attr:`active` is what makes it a no-op between tests.
    """

    __slots__ = ("active", "paths")

    def __init__(self) -> None:
        self.active = False
        self.paths: dict[str, str] = {}

    def start(self) -> None:
        self.paths = {}
        self.active = True

    def stop(self) -> dict[str, str]:
        self.active = False
        return self.paths

    # -- the hot path ------------------------------------------------------
    def hook(self, event: str, args: tuple) -> None:
        if not self.active:
            return
        if event == "open":
            path = args[0]
            if type(path) is not str:  # an fd, or bytes: not our business
                return
            mode = args[1]
            if mode is None:
                if not (args[2] & _WRITE_FLAGS):
                    return
                mode = f"os.open flags={args[2]:#o}"
            elif not _mode_writes(mode):
                return
            self._record(path, mode)
            return
        spec = _PATH_ARGS.get(event)
        if spec is None:
            return
        for path_index, dirfd_index in spec:
            if len(args) <= path_index:
                continue
            path = args[path_index]
            if type(path) is not str:
                continue
            if (
                dirfd_index is not None
                and not path.startswith(os.sep)
                and len(args) > dirfd_index
                and args[dirfd_index] not in (None, -1)
            ):
                # Relative to a directory FILE DESCRIPTOR, not to the cwd:
                # unresolvable here, and guessing the cwd is what produced
                # false positives for every ``shutil.rmtree``.
                continue
            self._record(path, event)

    def _record(self, path: str, mode: str) -> None:
        # Cheapest discriminator first: nearly every write a suite performs is
        # to ``tmp_path``, ``/tmp`` or the venv, and leaves after one compare.
        if not path.startswith(os.sep):
            path = os.path.abspath(path)
        if not path.startswith(_REPO_PREFIX):
            return
        relpath = path[len(_REPO_PREFIX) :]
        for fragment in _HOT_SKIP:
            if fragment in relpath:
                return
        self.paths.setdefault(relpath, mode)


def install(recorder: Recorder) -> None:
    """Install ``recorder``'s audit hook. Irreversible, by CPython's design."""

    sys.addaudithook(recorder.hook)


# ---------------------------------------------------------------------------
# Classification — git answers, never a local allowlist
# ---------------------------------------------------------------------------


def _git(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=str(REPO),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def offences(relpaths: dict[str, str]) -> dict[str, str]:
    """Filter ``{relpath: mode}`` down to the writes git would notice.

    A path survives when it is TRACKED, or when no ``.gitignore`` rule covers
    it. Two git invocations for the whole batch, and only when the batch is
    non-empty — which, on a tree with no offender, never happens.
    """

    if not relpaths:
        return {}
    names = sorted(relpaths)
    payload = "\0".join(names) + "\0"
    ignored: set[str] = set()
    proc = _git(["check-ignore", "--stdin", "-z"], stdin=payload)
    if proc.returncode in (0, 1):
        ignored = {name for name in proc.stdout.split("\0") if name}
    tracked: set[str] = set()
    listed = _git(["ls-files", "-z", "--", *names])
    if listed.returncode == 0:
        tracked = {name for name in listed.stdout.split("\0") if name}
    return {
        name: mode
        for name, mode in relpaths.items()
        if name in tracked or name not in ignored
    }


def session_residue(before: str, after: str) -> list[str]:
    """Lines present in ``git status --porcelain`` after a run but not before.

    The second net: it catches a CHILD process writing into the tree, which no
    in-process audit hook can see. It names files, not tests.
    """

    baseline = set(before.splitlines())
    return sorted(line for line in after.splitlines() if line not in baseline)


def porcelain() -> str:
    return _git(["status", "--porcelain"]).stdout


def format_report(nodeid: str, found: dict[str, str]) -> str:
    headline = (
        f"{nodeid} wrote {len(found)} path(s) under the repository root "
        f"that git would notice."
    )
    lines = [
        headline,
        "",
        "A test that writes under the repo is the GATE-0 defect class: it is",
        "correct alone and it reddens ITS NEIGHBOURS under `pytest -n auto`,",
        "because at one-worker-per-test another worker is reading that path.",
        "Write to `tmp_path` instead, or monkeypatch the path the code under",
        "test resolves. Do NOT add an exemption: this guard has no allowlist,",
        "and `.gitignore` is where a legitimate scratch location is declared.",
        "",
    ]
    for relpath, mode in sorted(found.items()):
        lines.append(f"    {relpath}   (opened {mode})")
    lines += ["", f"Owner: {OWNER}. Set {MODE_ENV}=census to report without failing."]
    return "\n".join(lines)


__all__ = [
    "MODE_CENSUS",
    "MODE_ENV",
    "MODE_OFF",
    "MODE_ON",
    "OWNER",
    "VALID_MODES",
    "Recorder",
    "RepoWriteGuardMisconfigured",
    "format_report",
    "install",
    "offences",
    "porcelain",
    "read_mode",
    "session_residue",
]
