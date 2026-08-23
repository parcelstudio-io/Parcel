"""Card HW-1 (``scrum/20260822/task_35``) — the product package imports on 3.10.

The dog's onboard Orin NX runs JetPack's system CPython **3.10**
(``WAVE3_HW_DESIGN_FABLE.md`` §5.1, seam S22). This dev box has only 3.14, so
the floor is held by a scan rather than by an interpreter: every module under
``src/parcel_robot`` is parsed with 3.10 grammar semantics and searched for the
stdlib names that do not exist on 3.10.

The capture tree already does this for its own two modules
(``tests/test_clockmap.py`` / ``tests/test_syncevents.py``, the
``feature_version=(3, 10)`` cell plus a substring blocklist). This file is the
same idea made whole-package and symbol-level, because a substring blocklist
cannot tell ``Self`` in a ``TYPE_CHECKING`` block (fine — annotations are
strings under ``from __future__ import annotations``) from ``Self`` imported at
module scope (an ``ImportError`` on 3.10 before anything runs).

**What a finding means.** Not "bad style": the named module raises at import
time on the interpreter the robot will actually run. The remedy per class is in
``task_35/DESIGN.md`` §(c) — a ``timezone.utc`` alias for ``datetime.UTC``, the
``if TYPE_CHECKING:`` form for annotation-only names.

**What this does NOT prove** (``DESIGN.md`` §(g)): stdlib *behaviour*
differences that are not name errors — ``datetime.fromisoformat`` accepts a
trailing ``Z`` only on >=3.11, and ``conversation_store.py:747`` therefore
returns ``None`` on 3.10 where it returns a timestamp here. That is a handoff,
not something a name scan can see.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PRODUCT_ROOT = REPO / "src" / "parcel_robot"

#: The interpreter floor this file defends. Same number as the capture tree's.
PY310 = (3, 10)

#: ``from <module> import <name>`` where ``<name>`` arrived after 3.10, and the
#: version that introduced it. Grouped by the card's census classes: class A is
#: ``datetime.UTC`` (a runtime *value*), class B is ``typing.Self`` (an
#: annotation), and the rest are the classes the card names so the table is a
#: floor for future modules rather than a record of two fixes.
POST_310_MEMBERS: dict[str, dict[str, str]] = {
    "datetime": {"UTC": "3.11"},
    "typing": {
        "Self": "3.11",
        "LiteralString": "3.11",
        "Never": "3.11",
        "NotRequired": "3.11",
        "Required": "3.11",
        "assert_never": "3.11",
        "assert_type": "3.11",
        "reveal_type": "3.11",
        "dataclass_transform": "3.11",
        "TypeVarTuple": "3.11",
        "Unpack": "3.11",
        "get_overloads": "3.11",
        "clear_overloads": "3.11",
        "override": "3.12",
        "TypeAliasType": "3.12",
        "TypeIs": "3.13",
        "ReadOnly": "3.13",
        "NoDefault": "3.13",
    },
    "enum": {
        "StrEnum": "3.11",
        "ReprEnum": "3.11",
        "EnumCheck": "3.11",
        "verify": "3.11",
        "member": "3.11",
        "nonmember": "3.11",
        "global_enum": "3.11",
        "show_flag_values": "3.11",
    },
    "hashlib": {"file_digest": "3.11"},
    "itertools": {"batched": "3.12"},
    "asyncio": {
        "TaskGroup": "3.11",
        "timeout": "3.11",
        "timeout_at": "3.11",
        "Runner": "3.11",
        "Barrier": "3.11",
    },
    "contextlib": {"chdir": "3.11"},
    "math": {"exp2": "3.11", "cbrt": "3.11"},
    "inspect": {"getmembers_static": "3.11"},
    "copy": {"replace": "3.13"},
    "warnings": {"deprecated": "3.13"},
    "os": {"process_cpu_count": "3.13"},
    "operator": {"call": "3.11"},
    "pathlib": {},
}

#: Whole modules that do not exist on 3.10.
POST_310_MODULES: dict[str, str] = {
    "tomllib": "3.11",
    "annotationlib": "3.14",
    "compression": "3.14",
    "concurrent.interpreters": "3.14",
    "dbm.sqlite3": "3.13",
}

#: Builtins that do not exist on 3.10.
POST_310_BUILTINS: dict[str, str] = {
    "ExceptionGroup": "3.11",
    "BaseExceptionGroup": "3.11",
    "PythonFinalizationError": "3.13",
}

#: Attribute accesses on a *dotted* module path (``hashlib.file_digest(...)``)
#: are caught by the same table; this set is the flat lookup for that pass.
_ATTR_LOOKUP: dict[tuple[str, str], str] = {
    (module, name): since
    for module, members in POST_310_MEMBERS.items()
    for name, since in members.items()
}


#: ``ast.TryStar`` (3.11) and ``ast.TypeAlias`` (3.12) do not exist on 3.10 —
#: and this file is one of the two things the 3.10 CI job runs, so the scanner
#: has to work on the interpreter it defends. ``isinstance(x, ())`` is always
#: False, which is exactly right: a 3.10 parser cannot produce those nodes, and
#: a source file that contains their syntax fails the grammar cell instead.
_TRY_STAR: tuple[type, ...] = (ast.TryStar,) if hasattr(ast, "TryStar") else ()
_TYPE_ALIAS: tuple[type, ...] = (ast.TypeAlias,) if hasattr(ast, "TypeAlias") else ()


@dataclass(frozen=True)
class Finding:
    """One place a module would fail to load on CPython 3.10."""

    path: str
    line: int
    symbol: str
    since: str
    guarded: bool

    def __str__(self) -> str:  # pragma: no cover - only rendered on failure
        state = "GUARDED" if self.guarded else "UNGUARDED"
        return f"{self.path}:{self.line} {self.symbol} (since {self.since}) [{state}]"


def _is_type_checking_test(test: ast.expr) -> bool:
    """``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``, and nothing else.

    Deliberately narrow. ``not TYPE_CHECKING``, ``TYPE_CHECKING and x`` and any
    other expression that merely *mentions* the name are NOT this form, and
    crediting them would be a false negative — see ``_guarded_lines``.
    """

    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _version_info_branch(test: ast.expr) -> str | None:
    """Which arm of a bare ``sys.version_info <op> (...)`` runs on the NEW side.

    ``>=``/``>`` put the newer interpreter in the body; ``<``/``<=`` put it in
    the ``else``. Anything else — ``==``, a chained comparison, a negation, a
    call — returns None and is credited nowhere.
    """

    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left = test.left
    if isinstance(left, ast.Attribute):
        name = left.attr
    elif isinstance(left, ast.Name):
        name = left.id
    else:
        return None
    if name != "version_info":
        return None
    if isinstance(test.ops[0], (ast.GtE, ast.Gt)):
        return "body"
    if isinstance(test.ops[0], (ast.LtE, ast.Lt)):
        return "orelse"
    return None


def _guarded_lines(tree: ast.AST) -> set[int]:
    """Lines on the arm that a CPython 3.10 process does not execute.

    Two forms are legitimate. ``if TYPE_CHECKING:`` is never evaluated at
    runtime, so with ``from __future__ import annotations`` the annotation stays
    a string and the name is never looked up; ``commissioning/session.py`` used
    it before this card existed and is the pattern the fixes copy. A bare
    ``sys.version_info`` comparison is an explicit branch.

    **Only the arm that 3.10 skips is credited, and only under a test of
    exactly those two shapes.** The first version of this function credited the
    whole ``If`` node whenever its test *mentioned* either name — so
    ``if not TYPE_CHECKING: from typing import Self`` and a ``Self`` import in
    an ``else:`` arm both passed the guard while a 3.10 process raised
    ``ImportError: cannot import name 'Self' from 'typing'``. Two mutants of
    exactly those shapes are pinned in
    ``test_the_scan_credits_the_type_checking_guard`` and are seeded on disk
    (V1/V2 in ``task_35/evidence/seeds.sh``), on both interpreters.
    """

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if _is_type_checking_test(node.test):
            branch: list[ast.stmt] = node.body
        else:
            side = _version_info_branch(node.test)
            if side is None:
                continue
            branch = node.body if side == "body" else node.orelse
        for statement in branch:
            for sub in ast.walk(statement):
                lineno = getattr(sub, "lineno", None)
                if lineno is not None:
                    guarded.add(lineno)
    return guarded


def scan_source(source: str, *, label: str) -> list[Finding]:
    """Every >3.10 stdlib name used by ``source``, guarded or not."""

    tree = ast.parse(source, filename=label)
    guarded = _guarded_lines(tree)
    findings: list[Finding] = []

    def record(node: ast.AST, symbol: str, since: str) -> None:
        line = getattr(node, "lineno", 0)
        findings.append(
            Finding(path=label, line=line, symbol=symbol, since=since, guarded=line in guarded)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                since = POST_310_MEMBERS.get(node.module, {}).get(alias.name)
                if since is not None:
                    record(node, f"from {node.module} import {alias.name}", since)
            since = _module_since(node.module)
            if since is not None:
                record(node, f"from {node.module} import ...", since)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                since = _module_since(alias.name)
                if since is not None:
                    record(node, f"import {alias.name}", since)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            since = _ATTR_LOOKUP.get((node.value.id, node.attr))
            if since is not None:
                record(node, f"{node.value.id}.{node.attr}", since)
        elif isinstance(node, ast.Name):
            since = POST_310_BUILTINS.get(node.id)
            if since is not None:
                record(node, node.id, since)
        elif isinstance(node, _TRY_STAR):
            record(node, "except* (PEP 654)", "3.11")
        elif isinstance(node, _TYPE_ALIAS):
            record(node, "type X = ... (PEP 695)", "3.12")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(node, "type_params", ()):
                record(node, f"def/class {node.name}[T] (PEP 695)", "3.12")

    return findings


def _module_since(dotted: str) -> str | None:
    if dotted in POST_310_MODULES:
        return POST_310_MODULES[dotted]
    head = dotted.split(".", 1)[0]
    if head in POST_310_MODULES:
        return POST_310_MODULES[head]
    return None


def product_modules() -> list[Path]:
    return sorted(PRODUCT_ROOT.rglob("*.py"))


def scan_product_tree() -> list[Finding]:
    """Scan every product module; a file this interpreter cannot PARSE counts.

    On 3.10 a module carrying 3.12 syntax raises out of ``ast.parse`` before any
    name is looked at. Turning that into a Finding keeps the report the same
    shape on both interpreters — a path and a reason — instead of a raw
    ``SyntaxError`` traceback out of ``ast.py`` (verifier NOTE N3). The grammar
    cell below reports it too; this is the belt.
    """

    findings: list[Finding] = []
    for path in product_modules():
        label = str(path.relative_to(REPO))
        try:
            findings.extend(scan_source(path.read_text(encoding="utf-8"), label=label))
        except SyntaxError as exc:
            findings.append(
                Finding(
                    path=label,
                    line=exc.lineno or 0,
                    symbol=f"<unparseable by CPython {sys.version_info[0]}.{sys.version_info[1]}>",
                    since="?",
                    guarded=False,
                )
            )
    return findings


def test_the_product_package_has_no_unguarded_post_310_names() -> None:
    """The card's gate: nothing in ``src/parcel_robot`` needs >3.10 to import."""

    unguarded = [f for f in scan_product_tree() if not f.guarded]
    assert unguarded == [], "these modules cannot import on the Orin's CPython 3.10:\n" + "\n".join(
        str(f) for f in unguarded
    )


def test_every_product_module_parses_under_310_grammar() -> None:
    """Syntax, not names: PEP 695 and friends are a ``SyntaxError`` on 3.10."""

    broken: list[str] = []
    for path in product_modules():
        try:
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=PY310,
            )
        except SyntaxError as exc:  # pragma: no cover - the assertion is the report
            broken.append(f"{path.relative_to(REPO)}: {exc}")
    assert broken == [], "3.10 cannot parse:\n" + "\n".join(broken)


def test_the_310_parse_check_really_rejects_newer_syntax() -> None:
    """Negative control for the cell above (the capture tree's own idiom)."""

    for mutant in ("type Alias = int\n", "def f[T](x: T) -> T:\n    return x\n"):
        with pytest.raises(SyntaxError):
            ast.parse(mutant, feature_version=PY310)
    ast.parse("x = 1\n", feature_version=PY310)


@pytest.mark.parametrize(
    ("mutant", "expected", "needs"),
    [
        ("from datetime import UTC, datetime\n", "from datetime import UTC", PY310),
        ("from typing import Any, Self\n", "from typing import Self", PY310),
        ("from enum import StrEnum\n", "from enum import StrEnum", PY310),
        ("import tomllib\n", "import tomllib", PY310),
        ("from hashlib import file_digest\n", "from hashlib import file_digest", PY310),
        ("import hashlib\nd = hashlib.file_digest(f, 'sha256')\n", "hashlib.file_digest", PY310),
        ("from itertools import batched\n", "from itertools import batched", PY310),
        (
            "import itertools\nfor c in itertools.batched(x, 2):\n    pass\n",
            "itertools.batched",
            PY310,
        ),
        ("from typing import override\n", "from typing import override", PY310),
        ("from asyncio import TaskGroup\n", "from asyncio import TaskGroup", PY310),
        ("from contextlib import chdir\n", "from contextlib import chdir", PY310),
        ("raise ExceptionGroup('x', [ValueError()])\n", "ExceptionGroup", PY310),
        ("try:\n    pass\nexcept* ValueError:\n    pass\n", "except* (PEP 654)", (3, 11)),
        ("type Alias = int\n", "type X = ... (PEP 695)", (3, 12)),
        ("def f[T](x: T) -> T:\n    return x\n", "def/class f[T] (PEP 695)", (3, 12)),
    ],
)
def test_seeded_failure_the_scan_catches_every_census_class(
    mutant: str, expected: str, needs: tuple[int, int]
) -> None:
    """A table that is never exercised is decoration. Each class gets a mutant.

    Three mutants are newer *syntax*, so the running interpreter has to be able
    to parse them at all. On 3.10 — where the CI job of this card runs — they
    are skipped by name, and the thing that would have caught them there is the
    grammar cell above, which sees a ``SyntaxError`` instead of a symbol.
    """

    if sys.version_info < needs:
        pytest.skip(
            f"mutant needs CPython {needs[0]}.{needs[1]} grammar to parse; "
            f"running {sys.version_info[0]}.{sys.version_info[1]} — the grammar "
            "cell is what catches this class here"
        )
    symbols = {f.symbol for f in scan_source(mutant, label="<mutant>")}
    assert expected in symbols, f"the scan would not have caught: {mutant!r} (saw {symbols})"


def test_the_scan_does_not_fire_on_benign_source() -> None:
    """Negative control: a scan that fires on everything proves nothing."""

    benign = (
        "from __future__ import annotations\n"
        "from datetime import datetime, timezone\n"
        "from typing import Any\n"
        "import itertools\n"
        "UTC = timezone.utc\n"
        "note = 'the Self of the matter is that UTC and StrEnum appear in prose'\n"
        "pairs = list(itertools.pairwise([1, 2, 3]))\n"
        "def now() -> datetime:\n"
        "    return datetime.now(UTC)\n"
    )
    assert scan_source(benign, label="<benign>") == []


def test_the_scan_credits_the_type_checking_guard() -> None:
    """``Self`` under ``if TYPE_CHECKING`` is a string annotation, not an import."""

    guarded = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from typing import Self\n"
        "class C:\n"
        "    def __enter__(self) -> Self:\n"
        "        return self\n"
    )
    findings = scan_source(guarded, label="<guarded>")
    assert [f.guarded for f in findings] == [True]
    assert [f for f in findings if not f.guarded] == []

    unguarded = guarded.replace("if TYPE_CHECKING:\n    from typing import Self\n", "")
    unguarded = unguarded.replace(
        "from typing import TYPE_CHECKING\n", "from typing import Self\n"
    )
    assert [f.guarded for f in scan_source(unguarded, label="<unguarded>")] == [False]


#: The two shapes that a "does the test MENTION ``TYPE_CHECKING``?" scan credits
#: and a 3.10 process does not: the negated test, and the ``else:`` arm. Both
#: raise ``ImportError: cannot import name 'Self' from 'typing'`` on 3.10, and
#: both were found by the HW-1 verifier (V1 on ``bridge/client.py``, V2 on
#: ``providers.py``) against the first version of ``_guarded_lines``.
_V1_NEGATED_TEST = (
    "from __future__ import annotations\n"
    "from typing import TYPE_CHECKING\n"
    "if not TYPE_CHECKING:\n"
    "    from typing import Self\n"
)
_V2_ELSE_ARM = (
    "from __future__ import annotations\n"
    "from typing import TYPE_CHECKING\n"
    "if TYPE_CHECKING:\n"
    "    pass\n"
    "else:\n"
    "    from typing import Self\n"
)


@pytest.mark.parametrize(
    ("label", "source"),
    [("V1-negated-test", _V1_NEGATED_TEST), ("V2-else-arm", _V2_ELSE_ARM)],
)
def test_seeded_failure_a_guard_that_only_mentions_type_checking_is_not_a_guard(
    label: str, source: str
) -> None:
    """The arm 3.10 actually runs is never credited, whatever the test mentions."""

    findings = scan_source(source, label=f"<{label}>")
    assert [f.guarded for f in findings] == [False], (
        f"{label} would have passed the guard while CPython 3.10 raises "
        f"ImportError on it: {findings}"
    )


@pytest.mark.parametrize(
    ("label", "source", "expect_guarded"),
    [
        (
            "version-ge-body",
            "import sys\nif sys.version_info >= (3, 11):\n    from typing import Self\n",
            True,
        ),
        (
            "version-lt-else",
            (
                "import sys\n"
                "if sys.version_info < (3, 11):\n"
                "    Self = object\n"
                "else:\n"
                "    from typing import Self\n"
            ),
            True,
        ),
        (
            "version-ge-else",
            (
                "import sys\n"
                "if sys.version_info >= (3, 11):\n"
                "    pass\n"
                "else:\n"
                "    from typing import Self\n"
            ),
            False,
        ),
        (
            "version-equality-is-not-a-branch-we-credit",
            "import sys\nif sys.version_info == (3, 11):\n    from typing import Self\n",
            False,
        ),
        (
            "typing-dot-type-checking",
            "import typing\nif typing.TYPE_CHECKING:\n    from typing import Self\n",
            True,
        ),
    ],
)
def test_the_scan_credits_only_the_arm_310_skips(
    label: str, source: str, expect_guarded: bool
) -> None:
    """`version_info` branches: the NEW-interpreter arm is the credited one."""

    findings = scan_source(source, label=f"<{label}>")
    assert [f.guarded for f in findings] == [expect_guarded], label


def test_the_shipped_guarded_site_is_still_credited() -> None:
    """``commissioning/session.py`` carried the pattern before this card."""

    path = PRODUCT_ROOT / "commissioning" / "session.py"
    findings = scan_source(path.read_text(encoding="utf-8"), label=str(path))
    assert [f.symbol for f in findings] == ["from typing import Self"]
    assert findings[0].guarded is True


def test_the_utc_alias_is_the_same_object_the_import_gave() -> None:
    """Class A's fix must not move a single ``tzinfo``.

    ``datetime.UTC`` IS ``datetime.timezone.utc`` on >=3.11 — the alias is not a
    look-alike, it is the same singleton — so every stamp this package writes
    has the same ``tzinfo``, the same ``repr`` and the same ``isoformat`` after
    the fix as before it.
    """

    import datetime as _datetime

    from parcel_robot import observability, runtime
    from parcel_robot.context import builder, models
    from parcel_robot.owner_tracking import gallery

    for module in (runtime, observability, models, builder, gallery):
        assert module.UTC is _datetime.timezone.utc, module.__name__
    if sys.version_info >= (3, 11):
        assert _datetime.UTC is _datetime.timezone.utc


def test_the_self_annotations_are_still_strings() -> None:
    """Class B's fix must not move an annotation's runtime object.

    Every one of these modules starts with ``from __future__ import
    annotations``, so ``__annotations__['return']`` was the *string* ``'Self'``
    before the fix and must still be after it.
    """

    from parcel_robot.bridge.client import FakeGatewayClientV1
    from parcel_robot.camera_channel.backends.physical import PhysicalCameraBackendBase
    from parcel_robot.online_map.store import OnlineMapStore
    from parcel_robot.perception_daemon.client import DaemonClient
    from parcel_robot.perception_daemon.server import PerceptionDaemon
    from parcel_robot.providers import SpeechChunk

    for owner in (
        FakeGatewayClientV1,
        PhysicalCameraBackendBase,
        OnlineMapStore,
        DaemonClient,
        PerceptionDaemon,
    ):
        assert owner.__enter__.__annotations__["return"] == "Self", owner.__name__
    assert SpeechChunk.__new__.__annotations__["return"] == "Self"
