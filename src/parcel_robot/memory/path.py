"""Which conversation store may this process open, and may it write to it?

CARD R27 — THE OWNER'S MEMORY IS NOT A SCRATCH FILE
===================================================

``configs/robot.yaml`` says ``memory.path: parcel_memory.sqlite3``. That is a
*relative* path, and ``sqlite3.connect`` resolves a relative path against the
**process CWD**. Every executor that started an in-process runtime from the
repo root with the default config therefore opened, and wrote to, the owner's
real conversation database — and then reported isolation in good faith,
because nothing ever told them otherwise.

This was flagged and not built. ``scrum/20260818/task_2/R5_STATUS.md`` open
risk 5, verbatim:

    ``memory.path`` is resolved relative to the process CWD, so any two stacks
    launched from the repo share one conversation memory — which silently made
    my sessions 1-2 non-independent experiments. A ``PARCEL_MEMORY_PATH``
    override would make live proofs repeatable; out of scope here.

It stayed out of scope for four consecutive card-chains, during which **256
synthetic rows** landed in ``parcel_memory.sqlite3`` (ids 2883–3138, measured
2026-08-21). It is user-visible: R18 made ``recall`` read both origins, so the
robot now offers *"find the nearest lamppost"* as something the owner said.

WHY A CONVENTION COULD NOT HAVE WORKED
--------------------------------------

The recipe executors were told to use — copy ``robot.yaml``, edit
``memory.path``, pass ``--config`` — is a *convention*, and it failed exactly
the way conventions fail: it protects the runs you remember to apply it to.
The runs that polluted were the ones nobody thought of as live at all. One of
them is in the committed test suite
(``tests/test_fail_closed_limits.py::test_shipped_config_still_launches``), so
the pollution vector shipped with the repo and fired on every commit gate.

So the rule here is not "remember to isolate". It is: **a process that has not
declared itself the owner's stack cannot open the owner's store for writing,
and finds that out as an exception rather than as a row.**

THE THREE RULES, AND WHY EACH IS THE SHAPE IT IS
------------------------------------------------

1. **An explicit path wins over everything.** :data:`ENV_PATH`
   (``PARCEL_MEMORY_PATH``) overrides whatever the config says. It is R5's own
   ask, and it is the escape hatch that makes this whole guard *usable*: a live
   proof no longer needs a copied config, it needs one exported variable. The
   value must be ``:memory:`` or **absolute** — a relative override would
   re-import the very CWD bug this module exists to close, so it is refused.

2. **A relative path is refused for writing.** Not because relative paths are
   bad, but because a relative path is a *question* ("relative to where?") that
   the answer changes under. The owner's stack is allowed one (its config has
   one, and it is resolved against the repo root rather than the CWD, so it
   names the same file from anywhere); nothing else is.

3. **The owner's store requires an owner declaration, and a test can never
   make one.** :data:`ENV_PURPOSE` (``PARCEL_MEMORY_PURPOSE=owner``) is set by
   ``scripts/launch_stack.sh`` and ``scripts/launch_sim.sh`` — the owner's two
   documented launchers — and by nothing inside the library. That asymmetry is
   the whole mechanism: the declaration lives *outside* the code an executor
   imports, so importing the runtime cannot accidentally acquire it. And under
   pytest the declaration is **ignored**, so a test cannot reach the owner's
   file even if it exports the variable, which is the property
   ``tests/test_owner_store_isolation.py`` pins.

FAIL-CLOSED, IN THE CARD'S SENSE
--------------------------------

The default — no env, default config, any process that is not a launcher — is
a **refusal**, not a fallback to a temp file. A silent temp store would be
kinder and worse: the run would look like it had memory, and the executor
would again learn nothing about which file they were writing. The exception
names the three ways out.

READS ARE NOT THE DANGER
------------------------

``read_only=True`` bypasses these refusals. A ``mode=ro`` connection is one
SQLite itself refuses writes on (``ConversationMemory.__init__``, card R18), so
the failure mode this module exists to prevent cannot occur through it. R18's
recall proof and ``tools/quarantine_synthetic_memory.py``'s dry-run both need
to read the owner's real store, and forcing them through a copy would make the
evidence weaker, not the store safer.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..paths import parcel_roots

#: The override. Absolute path, or ``:memory:``. Wins over any config.
ENV_PATH = "PARCEL_MEMORY_PATH"

#: The declaration. ``owner`` is the only value that unlocks the owner's store,
#: and only the shell launchers set it.
ENV_PURPOSE = "PARCEL_MEMORY_PURPOSE"

#: The file name that IS the owner's conversation memory, at any parcel root.
OWNER_STORE_NAME = "parcel_memory.sqlite3"

#: Declared purposes. ``owner`` = the owner's running stack; ``tool`` = a
#: maintenance tool acting deliberately on a named store; ``test`` = everything
#: else, which is the default precisely because it is the safe one.
PURPOSE_OWNER = "owner"
PURPOSE_TOOL = "tool"
PURPOSE_TEST = "test"
PURPOSES: frozenset[str] = frozenset({PURPOSE_OWNER, PURPOSE_TOOL, PURPOSE_TEST})

#: Card R27 work item 2 — the value stamped into ``messages.writer`` on every
#: new row, so that pollution is **detectable in the data** instead of inferred
#: from a NULL speaker. The 256 known-synthetic rows are indistinguishable from
#: 2,618 genuine legacy rows on every column the schema had; that is what made
#: the quarantine question hard, and it is what this column stops recurring.
WRITER_OWNER_STACK = "owner_stack"
WRITER_TOOL = "tool"
WRITER_TEST = "test"
WRITER_UNKNOWN = "unknown"
WRITERS: frozenset[str] = frozenset(
    {WRITER_OWNER_STACK, WRITER_TOOL, WRITER_TEST, WRITER_UNKNOWN}
)

_PURPOSE_WRITERS = {
    PURPOSE_OWNER: WRITER_OWNER_STACK,
    PURPOSE_TOOL: WRITER_TOOL,
    PURPOSE_TEST: WRITER_TEST,
}

#: SQLite's in-memory database. Never a file, never anybody's data.
IN_MEMORY = ":memory:"


class MemoryPathRefused(RuntimeError):
    """This process may not open that store for writing, and here is why.

    ``RuntimeError`` rather than ``ValueError`` on purpose. ``ValueError`` is
    what ``ConversationMemory`` and ``ConversationStoreError`` already raise for
    *bad arguments*, and several call sites — ``lane._write_ledger`` among them
    — catch ``ValueError`` broadly to keep a turn alive. This refusal must not
    be swallowed by a never-kill-a-turn guard: a stack that cannot name its own
    store has a configuration fault, and it should stop rather than degrade.
    """


@dataclass(frozen=True)
class ResolvedStore:
    """The decision: which file, opened by what class of process."""

    #: What to hand ``sqlite3.connect``. ``:memory:`` or an absolute path.
    path: str
    #: The declared purpose, after the pytest override.
    purpose: str
    #: The ``messages.writer`` stamp for rows this connection writes.
    writer: str
    #: True when :attr:`path` is the owner's real conversation memory.
    is_owner_store: bool
    #: True when the caller asked for a ``mode=ro`` connection.
    read_only: bool


def _pytest_is_loaded() -> bool:
    """The process-wide half of the pytest signal.

    Its own function so a test can neutralise it and exercise the *environment*
    half in isolation — otherwise every assertion about the env→writer mapping
    would be answered by the ambient fact that pytest is running, and the
    mapping itself would never actually be tested.
    """

    return "pytest" in sys.modules


def under_pytest(env: dict[str, str] | os._Environ[str] | None = None) -> bool:
    """Is this process a test run?

    Two signals, because each alone has a hole. ``PYTEST_CURRENT_TEST`` is set
    per-test and is therefore absent during collection and module import — the
    exact moment a module-level ``ConversationMemory(...)`` would fire.
    ``"pytest" in sys.modules`` covers import and collection but would also be
    true of a production process that merely imported pytest, which nothing in
    this repo does. Either is enough to be treated as a test.
    """

    environ = os.environ if env is None else env
    return "PYTEST_CURRENT_TEST" in environ or _pytest_is_loaded()


def declared_purpose(env: dict[str, str] | os._Environ[str] | None = None) -> str:
    """What this process says it is — with ``test`` as the fail-closed default.

    A test run is forced to ``test`` whatever the environment claims. That is
    not paranoia about a rogue test; it is the only way to state the card's
    work item 3 as a *property*: no test, no fixture, no harness and no plugin
    can reach the owner's store, regardless of how it configures itself.
    """

    environ = os.environ if env is None else env
    if under_pytest(environ):
        return PURPOSE_TEST
    declared = str(environ.get(ENV_PURPOSE, "")).strip().lower()
    return declared if declared in PURPOSES else PURPOSE_TEST


def writer_class(env: dict[str, str] | os._Environ[str] | None = None) -> str:
    """The honest ``messages.writer`` label for this process.

    Deliberately NOT the same function as :func:`declared_purpose`, and the
    difference is the point. ``declared_purpose`` answers an *authorization*
    question and defaults to ``test`` because ``test`` is the safe answer to
    "may I write to the owner's file?". This answers a *factual* one — who
    wrote this row — and a bare ``python -c`` is not a test, so labelling it
    ``test`` would put a small lie in the one column whose entire job is to
    stop the next audit from having to guess. An undeclared process is
    :data:`WRITER_UNKNOWN`, which is true and is also a useful thing to find.
    """

    environ = os.environ if env is None else env
    if under_pytest(environ):
        return WRITER_TEST
    declared = str(environ.get(ENV_PURPOSE, "")).strip().lower()
    return _PURPOSE_WRITERS.get(declared, WRITER_UNKNOWN)


def owner_store_paths() -> tuple[Path, ...]:
    """Every absolute path that means "the owner's conversation memory".

    Plural because :func:`~parcel_robot.paths.parcel_roots` is plural: a
    ``PARCEL_ROOT`` bind-mount, the inferred repo root and the packaged asset
    root are all legitimate anchors, and the store must be recognised under
    whichever one is in play rather than under a single hard-coded guess.
    """

    seen: list[Path] = []
    for root in parcel_roots():
        candidate = (root / OWNER_STORE_NAME).resolve()
        if candidate not in seen:
            seen.append(candidate)
    return tuple(seen)


def anchor_root() -> Path:
    """Where a relative ``memory.path`` means. The repo root, never the CWD.

    This is the single line that retires R5 open risk 5's mechanism: two stacks
    launched from different directories with the same config now name the same
    file, so "which store am I on" stops being a function of where somebody
    happened to be standing.
    """

    roots = parcel_roots()
    return roots[0] if roots else Path.cwd()


def is_in_memory(path: object) -> bool:
    """``:memory:`` and its URI spelling, which are the same database."""

    text = str(path).strip()
    return text == IN_MEMORY or text.startswith("file::memory:")


def resolve_memory_path(
    path: str | Path = IN_MEMORY,
    *,
    purpose: str | None = None,
    read_only: bool = False,
    env: dict[str, str] | os._Environ[str] | None = None,
) -> ResolvedStore:
    """Decide the store for this process, or refuse and say why.

    ``purpose`` is an explicit override for a caller that knows what it is —
    ``tools/quarantine_synthetic_memory.py`` passes ``"tool"``. It is still
    subordinate to the pytest rule: a test passing ``purpose="owner"`` is
    treated as a test, which is what makes the guard a property rather than a
    convention with a back door.

    Raises :class:`MemoryPathRefused` — never returns a silent fallback.
    """

    environ = os.environ if env is None else env
    effective = declared_purpose(environ)
    writer = writer_class(environ)
    if purpose is not None and not under_pytest(environ):
        wanted = str(purpose).strip().lower()
        if wanted not in PURPOSES:
            raise MemoryPathRefused(
                f"unknown memory purpose {purpose!r}; known: {sorted(PURPOSES)}"
            )
        effective = wanted
        writer = _PURPOSE_WRITERS[wanted]

    override = str(environ.get(ENV_PATH, "")).strip()
    if override:
        chosen: str | Path = override
        source = f"{ENV_PATH}={override}"
    else:
        chosen = path
        source = f"memory.path={path!r}"

    if is_in_memory(chosen):
        return ResolvedStore(IN_MEMORY, effective, writer, False, bool(read_only))

    candidate = Path(str(chosen)).expanduser()

    # An override that is itself relative would be the original bug wearing a
    # new name, so it is refused even for the owner's stack: the whole value of
    # the override is that it says exactly one file.
    if override and not candidate.is_absolute():
        raise MemoryPathRefused(
            f"{ENV_PATH} must be an absolute path or {IN_MEMORY!r}, got {override!r}.\n"
            f"A relative override resolves against the process CWD, which is the\n"
            f"defect card R27 exists to close. Try:\n"
            f"    export {ENV_PATH}={(Path.cwd() / candidate).as_posix()}"
        )

    absolute = candidate if candidate.is_absolute() else (anchor_root() / candidate)
    resolved = absolute.resolve()
    is_owner = resolved in owner_store_paths()

    if read_only:
        # SQLite refuses the write for us; see the module docstring.
        return ResolvedStore(resolved.as_posix(), effective, writer, is_owner, True)

    if is_owner and effective != PURPOSE_OWNER:
        raise MemoryPathRefused(_owner_refusal(resolved, effective, source, environ))

    if not candidate.is_absolute() and effective != PURPOSE_OWNER:
        raise MemoryPathRefused(_relative_refusal(candidate, resolved, effective, source))

    return ResolvedStore(resolved.as_posix(), effective, writer, is_owner, False)


def _declared_note(environ: dict[str, str] | os._Environ[str]) -> str:
    raw = str(environ.get(ENV_PURPOSE, "")).strip()
    if not raw:
        return "none declared"
    if under_pytest(environ):
        return f"{raw!r} declared, IGNORED — this is a pytest process"
    return f"{raw!r} declared"


def _ways_out() -> str:
    return (
        "Pick one:\n"
        f"  * a scratch file : export {ENV_PATH}=/tmp/parcel_scratch_memory.sqlite3\n"
        f"  * no file at all : export {ENV_PATH}={IN_MEMORY}\n"
        "  * the real stack : scripts/launch_stack.sh   (it declares "
        f"{ENV_PURPOSE}={PURPOSE_OWNER})"
    )


def _owner_refusal(
    resolved: Path,
    effective: str,
    source: str,
    environ: dict[str, str] | os._Environ[str],
) -> str:
    return (
        "card R27: refusing to open the OWNER'S conversation memory for writing.\n"
        f"    store   : {resolved}\n"
        f"    from    : {source}\n"
        f"    purpose : {effective}  ({_declared_note(environ)})\n"
        "\n"
        "That file is the owner's real conversation history. A synthetic turn\n"
        "written into it is one the robot can later recall out loud as something\n"
        "the owner said — 256 such rows were measured on 2026-08-21.\n"
        "\n" + _ways_out()
    )


def _relative_refusal(candidate: Path, resolved: Path, effective: str, source: str) -> str:
    return (
        "card R27: refusing a RELATIVE conversation-store path for writing.\n"
        f"    given   : {candidate}\n"
        f"    from    : {source}\n"
        f"    would be: {resolved}   (anchored at the repo root, not the CWD)\n"
        f"    purpose : {effective}\n"
        "\n"
        "A relative store path means a different file depending on where the\n"
        "process was started, which is how four card-chains wrote into the\n"
        "owner's store while believing they were isolated (R5 open risk 5).\n"
        "\n" + _ways_out()
    )


__all__ = [
    "ENV_PATH",
    "ENV_PURPOSE",
    "IN_MEMORY",
    "OWNER_STORE_NAME",
    "PURPOSES",
    "PURPOSE_OWNER",
    "PURPOSE_TEST",
    "PURPOSE_TOOL",
    "WRITERS",
    "WRITER_OWNER_STACK",
    "WRITER_TEST",
    "WRITER_TOOL",
    "WRITER_UNKNOWN",
    "MemoryPathRefused",
    "ResolvedStore",
    "anchor_root",
    "declared_purpose",
    "is_in_memory",
    "owner_store_paths",
    "resolve_memory_path",
    "under_pytest",
    "writer_class",
]
