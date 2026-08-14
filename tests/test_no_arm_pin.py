"""PS-O: the ONE no-arm pin for the whole capture stack.

Why this file exists
--------------------
Tomorrow the stack runs on an Orin where ``rclpy`` IS importable and the robot
IS on the wire. On this dev box neither is true, which made it very easy to
write a pin that felt like a guarantee and was not one. An adversarial audit
found three ways it was not, all reproduced twice:

1. **Coverage.** Four modules — ``rosbag2.py``, ``budget.py``, ``rehearse.py``
   and ``scripts/parcel_capture/__init__.py`` — were covered by **no** pin at
   all. The auditor appended a literal ``create_publisher("/cmd_vel")`` and
   ``SportClient().Move(0.5, 0, 0)`` to all four and the entire 795-test capture
   suite passed, and so did ``ci_gate --tier commit`` (4878 tests). ``rosbag2.py``
   is the module that builds the argv an operator types **at the robot**.
2. **Depth and spelling.** The old pin globbed ``PACKAGE.glob("*.py")``, which
   does not descend into subdirectories: a package planted one directory down
   was never read. And its AST scan matched literal symbols, so ordinary
   aliasing walked past it.
3. **The facade.** ``ReadOnlyHandle`` kept the vendor object in
   ``__slots__``, so ``handle._target`` resolved through the ordinary slot
   descriptor and ``__getattr__`` was never consulted.

So this pin is organised around the three things that failed:

* **N0 coverage** — the file set is computed **recursively** over both trees and
  is itself asserted against an independent walk. A pin whose coverage is
  untested is how this happened, so the coverage is the first test in the file.
* **N1 static** — symbols, imports, *folded string literals*, a census of every
  reach builtin, every state-reaching dunder, every mangled attribute, and every
  cross-object private attribute. Constant folding is what turns
  ``"create_" + "publisher"`` back into a name.
* **N2 evasions** — the auditor's spellings, re-run, each one labelled with a
  *measured* verdict per half. All eight are caught statically; seven of eight
  are caught dynamically, and the eighth (``5-unmangled-raw-node``) is recorded
  as **not** caught dynamically, because what stops it is the ``dds.py`` fix
  that deleted the attribute, not the tripwire noticing the attempt.
* **N3 dynamic** — every module is imported in a subprocess with a **fake**
  ``rclpy`` / ``unitree_sdk2py`` / ``pyrealsense2`` / ``unilidar_sdk2`` bolted
  into ``sys.modules`` whose publisher-creating and motion entry points RAISE,
  and then its public API is exercised. This is the only half that sees a name
  assembled at runtime, and it is the first time the live ``rclpy`` branch of
  ``dds.py`` has ever executed at all.
* **N4 residuals** — what is still reachable, asserted out loud, so the comments
  in ``base.py`` cannot quietly become false.

Static analysis cannot beat a determined aliaser and a subprocess probe cannot
reach a branch it does not execute. Neither half is the guarantee; the pair is
the honest bar, and N2 states exactly where the pair still has holes.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Every tree that is part of the capture stack. Both, recursively, always.
CAPTURE_TREES = (
    REPO / "src" / "parcel_robot" / "capture",
    REPO / "scripts" / "parcel_capture",
)

#: The four modules Finding 1 named. Listed by hand so that the coverage test
#: fails loudly if a rename silently drops one of them out of the walk.
FINDING_1_MODULES = (
    "scripts/parcel_capture/rosbag2.py",
    "scripts/parcel_capture/budget.py",
    "scripts/parcel_capture/rehearse.py",
    "scripts/parcel_capture/__init__.py",
)


def capture_stack_files(*roots: Path) -> tuple[Path, ...]:
    """Every ``.py`` file under every root, **recursively**.

    ``rglob``, not ``glob``. The bug this replaces is one character wide.
    """

    found: list[Path] = []
    for root in roots or CAPTURE_TREES:
        found.extend(path for path in root.rglob("*.py") if path.is_file())
    return tuple(sorted(found))


def _relpath(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _sources() -> dict[str, str]:
    return {_relpath(path): path.read_text(encoding="utf-8") for path in capture_stack_files()}


# ---------------------------------------------------------------------------
# N0 — coverage. The first test, because it is the one that was missing.
# ---------------------------------------------------------------------------


def test_the_pin_reads_every_file_in_both_capture_trees_recursively() -> None:
    """The pin's own coverage, asserted against an independent walk.

    ``os.walk`` computed here, ``Path.rglob`` computed in the helper: two
    different traversals must agree on the file set, and the set must be
    non-empty. This is the assertion whose absence let four modules and a whole
    subdirectory sit outside every pin in the tranche.
    """

    import os

    independent: set[str] = set()
    for root in CAPTURE_TREES:
        assert root.is_dir(), root
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if name.endswith(".py"):
                    independent.add(_relpath(Path(dirpath) / name))

    pinned = {_relpath(path) for path in capture_stack_files()}
    assert pinned == independent
    assert len(pinned) >= 19, sorted(pinned)


def test_the_pinned_set_contains_the_four_modules_that_were_covered_by_nothing() -> None:
    pinned = {_relpath(path) for path in capture_stack_files()}
    for name in FINDING_1_MODULES:
        assert name in pinned, f"{name} is outside the pin again"


def test_the_pinned_set_reaches_into_subdirectories() -> None:
    """``ingest/`` is one directory down and the old ``glob("*.py")`` never saw it."""

    pinned = {_relpath(path) for path in capture_stack_files()}
    nested = {name for name in pinned if name.count("/") > 2}
    assert nested, "no nested file in the walk — a subdirectory pin cannot be proven"
    assert "scripts/parcel_capture/ingest/base.py" in pinned


def test_seeded_failure_a_non_recursive_glob_misses_a_planted_subpackage(
    tmp_path: Path,
) -> None:
    """The exact defect, on a synthetic tree, without touching the repo.

    ``glob("*.py")`` returns 1 of 3 files; ``capture_stack_files`` returns 3.
    Run this against the old helper and the second assertion fails.
    """

    root = tmp_path / "stack"
    (root / "deep" / "deeper").mkdir(parents=True)
    (root / "top.py").write_text("x = 1\n", encoding="utf-8")
    (root / "deep" / "middle.py").write_text("x = 2\n", encoding="utf-8")
    (root / "deep" / "deeper" / "planted.py").write_text("x = 3\n", encoding="utf-8")

    non_recursive = sorted(path.name for path in root.glob("*.py"))
    recursive = sorted(path.name for path in capture_stack_files(root))
    assert non_recursive == ["top.py"]
    assert recursive == ["middle.py", "planted.py", "top.py"]


# ---------------------------------------------------------------------------
# N1 — the static half
# ---------------------------------------------------------------------------

#: Case-folded substrings forbidden in any SYMBOL (identifier, attribute, import
#: name, parameter) anywhere in the capture stack.
FORBIDDEN_SYMBOL_SUBSTRINGS = (
    "publish",
    "advertise",
    "sportclient",
    "sport_client",
    "controlmanager",
    "motionswitcher",
    "obstaclesavoid",
    "robotstateclient",
    "cmd_vel",
    "estop",
    "set_target",
    "send_goal",
    "send_request",
    "hardware_reset",
    "set_option",
    "startlidar",
    "stoplidar",
    "setlidarworkmode",
    "attrgetter",
    "methodcaller",
    "channelfactoryinitialize",
)

#: Whole symbols too short to match as substrings without false positives.
FORBIDDEN_SYMBOLS_EXACT = frozenset({"move", "lease", "arm", "disarm"})

#: The only symbols allowed to trip the substring rule, each because it is the
#: name of a field that is READ. ``publish_time`` is MCAP's own per-message
#: timestamp field (``record.py`` parses it out of a bag); reading a field named
#: after a publication is not publishing. Kept as an exact-name exemption so a
#: real ``create_publisher`` in the same file is still caught.
SYMBOL_EXEMPTIONS = frozenset({"publish_time", "publish_time_ns"})

#: Extra exact symbols banned only inside the ingest package, where nothing
#: writes anything, to a file or to a transport. ``record.py`` and
#: ``sidecar.py`` legitimately write files, so the ban cannot be tranche-wide.
INGEST_ONLY_FORBIDDEN_EXACT = frozenset({"write", "send"})
INGEST_PREFIX = "scripts/parcel_capture/ingest/"

#: Modules the capture stack may never import. ``unitree_sdk2py`` ships the
#: motion clients beside its subscriber, and its absence from ``.parcel/`` is
#: the tranche's strongest motion guarantee; the four ``parcel_robot`` entries
#: are the robot itself. ``operator`` is here for a different reason and it is
#: worth stating: it is stdlib and harmless in general, but
#: ``operator.attrgetter("create_publisher")`` is one of the evasions the audit
#: executed, and the capture stack has never needed the module. Zero uses today,
#: so banning it costs nothing and closes a route. If a legitimate need appears,
#: replace this with a ban on ``attrgetter``/``methodcaller`` alone.
FORBIDDEN_IMPORTS = (
    "unitree_sdk2py",
    "parcel_robot.runtime",
    "parcel_robot.control",
    "parcel_robot.navigation",
    "parcel_robot.route_memory",
    "operator",
)

#: Names that, appearing as a STRING (after folding ``"create_" + "publisher"``
#: back into one), mean somebody is assembling a command surface for a computed
#: reach. Exact matches only, on ``/``- and ``.``-separated components.
#:
#: ``sport`` is in here so that ``rt/api/sport/request`` — the topic the handset
#: commands the dog over — cannot be named. Note the foreseeable friction: a
#: later card may want to **subscribe** to that topic, which is legitimate
#: read-only evidence of what was commanded. The answer then is an explicit,
#: reasoned exemption next to :data:`SYMBOL_EXEMPTIONS`, not deleting the token.
#: ``sportmodestate`` is unaffected: components are matched whole, and its
#: components are ``rt``, ``lf`` and ``sportmodestate``.
ARMING_NAME_STRINGS = frozenset(
    {
        "create_publisher",
        "publish",
        "advertise",
        "Publisher",
        "SportClient",
        "sport_client",
        "MotionSwitcherClient",
        "ObstaclesAvoidClient",
        "RobotStateClient",
        "VuiClient",
        "AudioClient",
        "ChannelFactoryInitialize",
        "Move",
        "StopMove",
        "BalanceStand",
        "StandUp",
        "StandDown",
        "Damp",
        "SwitchGait",
        "hardware_reset",
        "set_option",
        "startLidar",
        "stopLidar",
        "setLidarWorkMode",
        "send_goal",
        "send_request",
        "call_async",
        "cmd_vel",
        "sport",
    }
)

#: Builtins that turn a computed string into an attribute, an import or code.
#: Every *call* must be in :data:`VETTED_REACHES`; every *non-call reference*
#: (``f = getattr``) is forbidden outright, because that is the aliasing move
#: the old pin could not see.
REACH_BUILTINS = frozenset(
    {
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "exec",
        "eval",
        "compile",
        "__import__",
        "globals",
        "locals",
    }
)

#: Reach builtins that may not be called AT ALL anywhere in the capture stack.
NEVER_CALLED_BUILTINS = frozenset(
    {"exec", "eval", "compile", "__import__", "globals", "locals", "vars", "delattr"}
)

#: Dunder attributes that reach an object's internal state or its code. Every
#: use must be vetted; the ones not listed in :data:`VETTED_DUNDERS` are the
#: introspection moves that recover a sealed target.
STATE_REACHING_DUNDERS = frozenset(
    {
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__dict__",
        "__mro__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__closure__",
        "__code__",
        "__builtins__",
        "__func__",
        "__self__",
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
    }
)

#: ``(relpath, innermost enclosing function, builtin)``. A census, not a spot
#: check: a reach anywhere else fails the pin.
VETTED_REACHES = frozenset(
    {
        ("scripts/parcel_capture/budget.py", "__post_init__", "getattr"),
        ("scripts/parcel_capture/budget.py", "loads_from_preflight", "getattr"),
        ("scripts/parcel_capture/clockmap.py", "relation_for", "getattr"),
        # The facade itself: the one guarded route from a name to a vendor
        # attribute, the tolerant message-field read, and the sealed bind.
        ("scripts/parcel_capture/ingest/base.py", "__getattribute__", "getattr"),
        ("scripts/parcel_capture/ingest/base.py", "read_field", "getattr"),
        ("scripts/parcel_capture/ingest/base.py", "sealed_call", "getattr"),
        ("scripts/parcel_capture/preflight.py", "__post_init__", "getattr"),
        ("scripts/parcel_capture/preflight.py", "_close_quietly", "getattr"),
        # PS-D's ``--reader-module pkg.mod:attr`` loader. An operator-supplied
        # name reaching an operator-named module: whoever can pass that flag can
        # already run arbitrary code, so the reach adds no authority. Recorded
        # here rather than exempted silently. Not PS-O's code to change.
        ("scripts/parcel_capture/preflight.py", "load_reader_factory", "getattr"),
        ("scripts/parcel_capture/preflight.py", "reader_factory_from_args", "getattr"),
        ("scripts/parcel_capture/preflight.py", "rest_period_from_args", "getattr"),
        ("scripts/parcel_capture/record.py", "<module>", "getattr"),
        ("scripts/parcel_capture/record.py", "__exit__", "getattr"),
        ("scripts/parcel_capture/record.py", "__post_init__", "getattr"),
        ("scripts/parcel_capture/rehearse.py", "__post_init__", "getattr"),
    }
)

#: ``(relpath, innermost enclosing function, dunder)``. ``object.__setattr__``
#: in a frozen dataclass ``__post_init__`` is the bulk of it; ``base.py``'s
#: facade is the rest, and it is the whole reason the facade is auditable.
VETTED_DUNDERS = frozenset(
    {
        ("scripts/parcel_capture/ingest/base.py", "__post_init__", "__setattr__"),
        ("scripts/parcel_capture/ingest/base.py", "__init_subclass__", "__dict__"),
        ("scripts/parcel_capture/preflight.py", "__post_init__", "__setattr__"),
    }
)

_MANGLED = re.compile(r"^_[A-Za-z][A-Za-z0-9]*__[A-Za-z0-9_]+$")


def _innermost(tree: ast.AST) -> dict[int, str]:
    """Map ``id(node) -> innermost enclosing function name``.

    The old census used ``setdefault`` over a BFS walk, which reported the
    *outermost* function — so a reach nested inside a closure was attributed to
    the factory around it. Innermost is the one an auditor can check by eye.
    """

    owner: dict[int, str] = {}

    def descend(node: ast.AST, name: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner[id(child)] = name
                descend(child, child.name)
            else:
                owner[id(child)] = name
                descend(child, name)

    descend(tree, "<module>")
    return owner


def _symbols_and_imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    symbols: set[str] = set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.arg):
            symbols.add(node.arg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                symbols.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            symbols.add(node.module or "")
            symbols.update(alias.name for alias in node.names)
    return symbols, imports


def _module_string_constants(tree: ast.AST) -> dict[str, object]:
    """Module-level ``NAME = "x"`` / ``NAME = ("a", "b")`` bindings, for folding."""

    bound: dict[str, object] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            bound[target.id] = value.value
        elif isinstance(value, (ast.Tuple, ast.List)) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
        ):
            bound[target.id] = tuple(item.value for item in value.elts)  # type: ignore[union-attr]
    return bound


def fold_string(node: ast.AST, bound: dict[str, object]) -> str | None:
    """Best-effort constant folding of a string expression.

    Covers the spellings an evader actually uses: adjacent and ``+``
    concatenation, f-strings of constants, ``"".join((...))``, and a module-level
    tuple of parts. It does **not** cover a name assembled from arithmetic, a
    ``chr()`` sequence, or bytes decoded at runtime, and N2 says so.
    """

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        value = bound.get(node.id)
        return value if isinstance(value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = fold_string(node.left, bound)
        right = fold_string(node.right, bound)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [fold_string(value, bound) for value in node.values]
        return None if any(part is None for part in parts) else "".join(parts)  # type: ignore[arg-type]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
    ):
        sep = fold_string(node.func.value, bound)
        if sep is None:
            return None
        seq = node.args[0]
        items: list[str | None] | None = None
        if isinstance(seq, (ast.Tuple, ast.List)):
            items = [fold_string(item, bound) for item in seq.elts]
        elif isinstance(seq, ast.Name):
            value = bound.get(seq.id)
            if isinstance(value, tuple):
                items = list(value)
        if items is None or any(item is None for item in items):
            return None
        return sep.join(item for item in items if item is not None)
    return None


def _never_allowed_literal_ids(tree: ast.AST) -> set[int]:
    """Constants inside the module-level ``NEVER_ALLOWED`` assignment.

    ``base.py`` names the forbidden surfaces as string literals **on purpose**,
    so a facade can refuse them by name; a literal in a denylist cannot execute.
    That declaration is exempt from the arming-string rule. Anywhere else in the
    same file it is not.
    """

    exempt: set[int] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            targets: tuple[ast.expr, ...] = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        named = any(
            isinstance(target, ast.Name) and target.id == "NEVER_ALLOWED" for target in targets
        )
        if named and node.value is not None:
            for child in ast.walk(node.value):
                exempt.add(id(child))
    return exempt


def arming_strings(source: str, *, exempt_never_allowed: bool = False) -> list[str]:
    """Folded string literals that name a command surface."""

    tree = ast.parse(source)
    bound = _module_string_constants(tree)
    exempt = _never_allowed_literal_ids(tree) if exempt_never_allowed else set()
    hits: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in exempt:
            continue
        text = fold_string(node, bound)
        if text is None or len(text) > 64:
            continue
        parts = [part.strip() for part in text.replace("/", ".").split(".")]
        if any(part in ARMING_NAME_STRINGS for part in parts):
            hits.add(text)
    return sorted(hits)


def static_violations(relpath: str, source: str) -> list[str]:
    """Every static rule, in one place, so a caller cannot run half of them."""

    tree = ast.parse(source)
    owner = _innermost(tree)
    symbols, imports = _symbols_and_imports(tree)
    exact = set(FORBIDDEN_SYMBOLS_EXACT)
    if relpath.startswith(INGEST_PREFIX):
        exact |= INGEST_ONLY_FORBIDDEN_EXACT

    violations: list[str] = []
    for symbol in sorted(symbols):
        if symbol in SYMBOL_EXEMPTIONS:
            continue
        folded = symbol.casefold()
        if folded in exact or any(token in folded for token in FORBIDDEN_SYMBOL_SUBSTRINGS):
            violations.append(f"symbol {symbol!r}")
    for module in sorted(imports):
        if any(module == name or module.startswith(name + ".") for name in FORBIDDEN_IMPORTS):
            violations.append(f"import {module!r}")
    for text in arming_strings(
        source, exempt_never_allowed=relpath.endswith("ingest/base.py")
    ):
        violations.append(f"arming string {text!r}")

    call_func_ids = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in REACH_BUILTINS:
            where = owner.get(id(node), "<module>")
            if id(node) not in call_func_ids:
                violations.append(
                    f"reach builtin {node.id!r} referenced without calling it "
                    f"(aliasing) in {where} at line {node.lineno}"
                )
            elif node.id in NEVER_CALLED_BUILTINS:
                violations.append(f"call to {node.id!r} in {where} at line {node.lineno}")
            elif (relpath, where, node.id) not in VETTED_REACHES:
                violations.append(
                    f"unvetted reach {node.id!r} in {where} at line {node.lineno}"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in STATE_REACHING_DUNDERS:
                where = owner.get(id(node), "<module>")
                if (relpath, where, node.attr) not in VETTED_DUNDERS:
                    violations.append(
                        f"state-reaching dunder .{node.attr} in {where} at line {node.lineno}"
                    )
            if _MANGLED.match(node.attr):
                violations.append(
                    f"name-mangled attribute .{node.attr} at line {node.lineno} — mangling "
                    f"is not privacy, it is a rename"
                )
            if (
                node.attr.startswith("_")
                and not node.attr.startswith("__")
                and not (isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"})
            ):
                violations.append(
                    f"private attribute .{node.attr} reached on another object at "
                    f"line {node.lineno}"
                )
    return violations


@pytest.mark.parametrize("relpath", sorted(_sources()))
def test_no_module_in_the_capture_stack_names_or_assembles_a_command_surface(
    relpath: str,
) -> None:
    """The static half, over every file in both trees, one test per file."""

    assert static_violations(relpath, _sources()[relpath]) == []


def test_the_static_half_catches_every_literal_arming_surface() -> None:
    """Seeded failures. Each of these is a spelling the pin must not miss."""

    mutants = {
        "publisher": "node.create_publisher(Twist, 'cmd_vel', 10)",
        "sport_client": "from unitree_sdk2py.go2.sport.sport_client import SportClient",
        "vendor_sdk": "import unitree_sdk2py",
        "runtime": "import parcel_robot.runtime as rt",
        "navigation": "from parcel_robot.navigation import pipeline",
        "lidar_mode": "reader.setLidarWorkMode(1)",
        "lidar_start": "reader.startLidar()",
        "device_reset": "device.hardware_reset()",
        "camera_option": "sensor.set_option(rs.option.exposure, 100)",
        "move": "def move(self, command):\n    return command\n",
        "topic_literal": "TOPIC = '/cmd_vel'\n",
        "sport_topic": "TOPIC = 'rt/api/sport/request'\n",
        "mangled_reach": "raw = session._SubscribeOnlySession__node\n",
        "private_reach": "raw = handle._target\n",
        "closure_reach": "cells = type(handle).__getattribute__.__closure__\n",
        "exec_call": "exec(payload)\n",
        "vars_call": "vars(type(node))['x']\n",
        "attrgetter": "import operator\nf = operator.attrgetter('x')\n",
    }
    for name, mutant in mutants.items():
        assert static_violations("scripts/parcel_capture/mutant.py", mutant), (
            f"mutant {name!r} slipped the static half"
        )

    # ...and it stays quiet on the sensor vocabulary the stack legitimately uses,
    # which is what makes it a pin rather than noise.
    benign = (
        "topic = '/wirelesscontroller'\n"
        "kind = 'unitree_go/msg/LowState'\n"
        "subscription = session.subscribe(cls, topic, sink, 10)\n"
        "stamp = message.publish_time\n"
        "reader = self._reader\n"
    )
    assert static_violations("scripts/parcel_capture/benign.py", benign) == []


def test_the_only_exempt_arming_strings_are_the_never_allowed_denylist_itself() -> None:
    """The exemption is one assignment in one file, and it is checked, not assumed."""

    from scripts.parcel_capture.ingest.base import NEVER_ALLOWED

    source = (REPO / "scripts" / "parcel_capture" / "ingest" / "base.py").read_text(
        encoding="utf-8"
    )
    unexempted = arming_strings(source, exempt_never_allowed=False)
    exempted = arming_strings(source, exempt_never_allowed=True)
    assert exempted == []
    assert set(unexempted) <= set(NEVER_ALLOWED)
    assert unexempted, "the exemption covers nothing — it should cover NEVER_ALLOWED"

    # A forbidden literal written ANYWHERE ELSE in that same file is still caught.
    planted = source + "\n_LATER = 'create_publisher'\n"
    assert arming_strings(planted, exempt_never_allowed=True) == ["create_publisher"]


def test_the_reach_census_is_exact_and_not_merely_a_subset() -> None:
    """Every vetted entry must still exist. A stale census is a census of nothing."""

    seen: set[tuple[str, str, str]] = set()
    for relpath, source in _sources().items():
        tree = ast.parse(source)
        owner = _innermost(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in REACH_BUILTINS
            ):
                seen.add((relpath, owner.get(id(node.func), "<module>"), node.func.id))
    assert seen == set(VETTED_REACHES)


# ---------------------------------------------------------------------------
# N2 — the auditor's seven evasions, re-run and scored honestly
# ---------------------------------------------------------------------------

#: The spellings the audit executed against the old pin: a literal control plus
#: the six evasions that passed **both** of its halves, and one more (``chr``
#: arithmetic) that no constant folder can ever read. A module written any of
#: these ways created a publisher on ``/cmd_vel`` and called
#: ``SportClient().Move()`` while all 47 pin tests passed.
#:
#: The boolean is what the NEW static half does with the spelling — measured,
#: not hoped for. The dynamic verdict for the same spellings lives in
#: :data:`DYNAMIC_EVASIONS` and is scored separately, because the honest claim
#: is per-half.
EVASIONS: dict[str, tuple[str, bool]] = {
    "0-literal": (
        (
            "def open_reader(node):\n"
            "    return node.create_publisher(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "1-alias-getattr": (
        (
            "_reach = getattr\n"
            "_PARTS = ('create_', 'pub', 'lisher')\n"
            "def open_reader(node):\n"
            "    return _reach(node, ''.join(_PARTS))(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "2-operator-attrgetter": (
        (
            "import operator\n"
            "def open_reader(node):\n"
            "    return operator.attrgetter('create_' 'publisher')(node)(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "3-dunder-getattribute": (
        (
            "def open_reader(node):\n"
            "    name = 'create_' + 'publisher'\n"
            "    return node.__getattribute__(name)(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "4-vars-dict": (
        (
            "def open_reader(node):\n"
            "    name = 'create_' + 'publisher'\n"
            "    return vars(type(node))[name](node, object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "5-unmangled-raw-node": (
        (
            "def open_reader(session):\n"
            "    raw = session._SubscribeOnlySession__node\n"
            "    return raw.__getattribute__('create_' + 'publisher')(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "6-exec-string": (
        (
            "_run = exec\n"
            "def open_reader(node):\n"
            "    ns = {'n': node}\n"
            "    _run('r = n.create_' + 'publisher(object, \"/cmd_vel\", 10)', ns)\n"
            "    return ns['r']\n"
        ),
        True,
    ),
    "7-chr-arithmetic": (
        (
            "def open_reader(node):\n"
            "    name = ''.join(chr(c) for c in _CODES)\n"
            "    return node.__getattr" + "ibute__(name)(object, _TOPIC, 10)\n"
        ),
        True,
    ),
}


@pytest.mark.parametrize(("name", "case"), sorted(EVASIONS.items()))
def test_each_auditor_evasion_is_scored_against_the_new_static_half(
    name: str, case: tuple[str, bool]
) -> None:
    """Every evasion, with its measured verdict pinned.

    If a future edit weakens the static half, the expected verdict stops
    matching and this test says which spelling regressed. The point is not that
    every row is ``True`` — it is that the row is *measured*.
    """

    source, expected_caught = case
    caught = bool(static_violations("scripts/parcel_capture/evasion.py", source))
    assert caught is expected_caught, (
        f"{name}: static half now returns caught={caught}, pin says {expected_caught}"
    )


def test_the_static_half_is_honest_about_what_folding_cannot_reach() -> None:
    """Named holes, so nobody reads N2 as "static analysis is sufficient".

    A name built out of arithmetic, or read from a file, or decoded from bytes,
    is invisible to every static rule in this file. Those spellings are the
    reason N3 exists, and the reason N3 is not optional.
    """

    invisible = (
        "def open_reader(node, codes, topic):\n"
        "    name = ''.join(chr(value) for value in codes)\n"
        "    return getattr(node, name)(object, topic, 10)\n"
    )
    violations = static_violations("scripts/parcel_capture/evasion.py", invisible)
    # It IS caught, but only by the reach census (an unvetted `getattr`), not by
    # anything that understood the name. Remove the census and it is invisible.
    assert any("unvetted reach" in item for item in violations)
    assert not any("arming string" in item for item in violations)


# ---------------------------------------------------------------------------
# N3 — the dynamic half: import under a fake vendor SDK whose arming entry
#      points raise, then exercise the public API
# ---------------------------------------------------------------------------

HARNESS = r'''
"""Import one capture-stack module against a fake vendor SDK and exercise it.

Every attribute of the fake SDKs is a tripwire. Reaching a name that creates a
publisher, a Sport client, or any motion surface raises ``Armed`` — which
derives from ``BaseException`` on purpose, so the capture stack's own
``except Exception`` handlers cannot swallow it and report the module clean.
"""

import importlib
import inspect
import json
import signal
import sys
import types
from importlib.machinery import ModuleSpec

MODULE = sys.argv[1]
for entry in reversed(sys.argv[2:]):
    sys.path.insert(0, entry)


class Armed(BaseException):
    pass


ARMING_EXACT = {
    "Move", "StopMove", "BalanceStand", "StandUp", "StandDown", "Damp",
    "SwitchGait", "Euler", "publish", "arm", "disarm",
}
ARMING_SUBSTR = (
    "create_publisher", "advertise", "sportclient", "sport_client",
    "motionswitcher", "obstaclesavoid", "controlmanager", "robotstateclient",
    "channelfactoryinitialize", "hardware_reset", "set_option", "startlidar",
    "stoplidar", "setlidarworkmode", "send_goal", "send_request", "call_async",
    "cmd_vel", "set_target", "vuiclient", "audioclient",
)


def is_arming(name):
    if name in ARMING_EXACT:
        return True
    folded = name.casefold()
    return any(token in folded for token in ARMING_SUBSTR)


class ArmingAttribute:
    """A real class-level attribute for each arming name.

    ``__getattr__`` alone is not enough: ``vars(type(node))["create_publisher"]``
    and ``type(node).__dict__[...]`` read the class dictionary directly and never
    consult it. A real vendor class HAS those entries, so the fake one must too,
    and each is a live wire whether it is fetched as a descriptor or pulled out
    of the dict and called.
    """

    def __init__(self, name):
        self.name = name

    def __get__(self, obj, owner=None):
        raise Armed("descriptor %s" % self.name)

    def __call__(self, *args, **kwargs):
        raise Armed("class-dict call %s" % self.name)


PLANTED_ARMING_ATTRS = (
    "create_publisher", "publish", "advertise", "SportClient",
    "MotionSwitcherClient", "ObstaclesAvoidClient", "RobotStateClient",
    "Move", "StopMove", "BalanceStand", "StandUp", "StandDown", "Damp",
    "set_option", "startLidar", "stopLidar", "setLidarWorkMode",
    "hardware_reset", "send_goal", "send_request", "call_async",
)


class Tripwire:
    def __getattribute__(self, name):
        # Dunders and the one bookkeeping field resolve normally so the object
        # still behaves like an object. Everything else is the wire. Overriding
        # __getattribute__ (not just __getattr__) is what makes
        # ``node.__getattribute__("create_publisher")`` trip: that expression
        # fetches THIS method and then calls it with the arming name.
        if name == "trip_path" or (name.startswith("__") and name.endswith("__")):
            return object.__getattribute__(self, name)
        if is_arming(name):
            raise Armed("attribute %s.%s" % (object.__getattribute__(self, "trip_path"), name))
        return Tripwire("%s.%s" % (object.__getattribute__(self, "trip_path"), name))

    def __init__(self, path):
        object.__setattr__(self, "trip_path", path)

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if is_arming(name):
            raise Armed("attribute %s.%s" % (self.trip_path, name))
        return Tripwire("%s.%s" % (self.trip_path, name))

    def __call__(self, *args, **kwargs):
        tail = self.trip_path.rsplit(".", 1)[-1]
        if is_arming(tail):
            raise Armed("call %s()" % self.trip_path)
        return Tripwire("%s()" % self.trip_path)

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __repr__(self):
        return "<Tripwire %s>" % self.trip_path


class FakeModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if is_arming(name):
            raise Armed("attribute %s.%s" % (self.__name__, name))
        return Tripwire("%s.%s" % (self.__name__, name))


FAKE_ROOTS = (
    "rclpy", "rclpy_message_converter", "unitree_sdk2py", "unitree_go",
    "unitree_api", "sensor_msgs", "std_msgs", "geometry_msgs", "nav_msgs",
    "builtin_interfaces", "pyrealsense2", "unilidar_sdk2", "cv2", "cv_bridge",
    "rosbag2_py",
)
ARMING_MODULE_TOKENS = ("sport", "motion_switcher", "obstacles_avoid", "vui", "audio")


class FakeFinder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in FAKE_ROOTS:
            return None
        return ModuleSpec(fullname, self, is_package=True)

    def create_module(self, spec):
        folded = spec.name.casefold()
        if any(token in folded for token in ARMING_MODULE_TOKENS):
            raise Armed("import %s" % spec.name)
        module = FakeModule(spec.name)
        module.__path__ = []
        module.__spec__ = spec
        return module

    def exec_module(self, module):
        return None


for _name in PLANTED_ARMING_ATTRS:
    setattr(Tripwire, _name, ArmingAttribute(_name))

sys.meta_path.insert(0, FakeFinder())

SKIP_CALLABLES = {"main"}
result = {"module": MODULE, "status": "ok", "detail": "", "exercised": []}


def note(text):
    result["exercised"].append(text)


class Slow(Exception):
    """Budget exceeded. An ordinary Exception so a caller's handler may eat it."""


def _on_alarm(signum, frame):
    raise Slow("exercise exceeded its budget")


signal.signal(signal.SIGALRM, _on_alarm)


def bounded(call, budget=3.0):
    """Run ``call`` under a repeating alarm.

    ``preflight.probe_all_channels()`` walks 28 channels at their default probe
    window and takes minutes; the pin needs *entry* into these functions, not
    their completion. The interval repeats so that a target whose own
    ``except Exception`` swallows the first alarm still gets stopped.
    """

    signal.setitimer(signal.ITIMER_REAL, budget, 0.25)
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


try:
    module = importlib.import_module(MODULE)
    note("import")

    from scripts.parcel_capture.ingest.base import IngestAdapter

    for name, obj in sorted(vars(module).items()):
        if not isinstance(obj, type) or not issubclass(obj, IngestAdapter):
            continue
        if obj is IngestAdapter or inspect.isabstract(obj):
            continue
        if obj.__module__ != MODULE:
            continue
        try:
            adapter = obj()
        except Armed:
            raise
        except BaseException:
            continue
        note("adapter %s" % name)
        for probe in ("dependency_report", "capability", "channels"):
            try:
                bounded(getattr(adapter, probe))
            except Armed:
                raise
            except BaseException:
                pass
        try:
            entries = adapter.channels()[:2]
        except Armed:
            raise
        except BaseException:
            entries = ()
        for entry in entries:
            try:
                bounded(lambda e=entry: list(adapter.read(e, 0.01)))
                note("read %s" % entry.channel_id)
            except Armed:
                raise
            except BaseException as error:
                note("read %s (refused: %s)" % (entry.channel_id, type(error).__name__))

    for name, obj in sorted(vars(module).items()):
        if name.startswith("_") or name in SKIP_CALLABLES:
            continue
        if not callable(obj) or isinstance(obj, type):
            continue
        if getattr(obj, "__module__", None) != MODULE:
            continue
        try:
            signature = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        optional = all(
            parameter.default is not inspect.Parameter.empty
            or parameter.kind
            in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for parameter in signature.parameters.values()
        )
        if not optional:
            continue
        try:
            bounded(obj)
            note("call %s()" % name)
        except Armed:
            raise
        except BaseException as error:
            note("call %s() (refused: %s)" % (name, type(error).__name__))

    entry_point = vars(module).get("main")
    if callable(entry_point):
        try:
            bounded(lambda: entry_point(["--help"]))
        except Armed:
            raise
        except SystemExit:
            note("main --help")
        except BaseException as error:
            note("main --help (refused: %s)" % type(error).__name__)
except Armed as armed:
    result["status"] = "armed"
    result["detail"] = str(armed)
except BaseException as error:
    result["status"] = "error"
    result["detail"] = "%s: %s" % (type(error).__name__, error)

sys.stderr.write(json.dumps(result) + "\n")
'''


def _module_name(relpath: str) -> str:
    stem = relpath.removesuffix(".py").removesuffix("/__init__").removeprefix("src/")
    return stem.replace("/", ".")


@pytest.fixture(scope="module")
def harness_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("no_arm") / "harness.py"
    path.write_text(HARNESS, encoding="utf-8")
    return path


def run_harness(harness: Path, module_name: str, *, extra_path: str | None = None) -> dict:
    """Run one module through the fake-SDK harness in a fresh interpreter.

    ``cwd`` and ``HOME`` are a scratch directory so that any stray write a
    module makes while being exercised lands there and not in the repo.
    """

    env_path = str(harness.parent)
    argv = [sys.executable, "-B", str(harness), module_name, str(REPO)]
    if extra_path:
        argv.append(extra_path)
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=env_path,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": env_path},
    )
    line = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
    if not line.startswith("{"):
        raise AssertionError(
            f"harness produced no verdict for {module_name}: rc={proc.returncode} "
            f"stdout={proc.stdout[-2000:]!r} stderr={proc.stderr[-2000:]!r}"
        )
    return json.loads(line)


@pytest.mark.parametrize("relpath", sorted(_sources()))
def test_importing_and_exercising_each_module_against_a_fake_sdk_arms_nothing(
    relpath: str, harness_path: Path
) -> None:
    """The dynamic half, over every file in both trees, one test per file.

    A fake ``rclpy`` / ``unitree_sdk2py`` / ``pyrealsense2`` / ``unilidar_sdk2``
    is installed in ``sys.modules`` by a meta-path finder, every attribute of it
    is a tripwire, and reaching a publisher or a motion client raises. Then the
    module is imported and its public API is exercised. Because the fake SDKs
    satisfy ``find_spec``, this is also the **only** execution the live
    ``rclpy``/RealSense/L2 branches ever get: on this box they are otherwise
    unreachable, and on the Orin they are the branches that run.
    """

    verdict = run_harness(harness_path, _module_name(relpath))
    assert verdict["status"] != "armed", verdict["detail"]
    assert verdict["status"] == "ok", verdict["detail"]


def test_the_dynamic_half_reaches_the_live_vendor_branches_it_claims_to(
    harness_path: Path,
) -> None:
    """Coverage of the dynamic half, asserted rather than hoped for.

    If the fake SDK stopped satisfying ``find_spec`` the adapters would refuse
    early and every module would come back ``ok`` having executed nothing. So
    the pin asserts that the DDS, RealSense and L2 read paths were actually
    entered.
    """

    for module_name, expected in (
        ("scripts.parcel_capture.ingest.dds", "go2."),
        ("scripts.parcel_capture.ingest.realsense", "d455."),
        ("scripts.parcel_capture.ingest.l2", "l2."),
    ):
        verdict = run_harness(harness_path, module_name)
        assert verdict["status"] == "ok", verdict["detail"]
        reads = [item for item in verdict["exercised"] if item.startswith("read ")]
        assert reads, f"{module_name} exercised no read at all: {verdict['exercised']}"
        assert any(expected in item for item in reads), reads
        assert any("(refused)" not in item for item in reads), (
            f"{module_name}: every read refused, so the live branch never ran: {reads}"
        )


#: The same eight spellings as :data:`EVASIONS`, rewritten as modules that fetch
#: their own vendor object so the harness's public-callable exercise reaches
#: them. The boolean is whether the DYNAMIC half trips — measured. Seven do.
#: ``5-unmangled-raw-node`` does not, and the reason is worth reading: the
#: attribute it reaches for no longer exists, so the module raises
#: ``AttributeError`` instead of arming. The fix removed the target; the pin did
#: not detect the attempt. If the session class ever grows a raw-node attribute
#: back, that spelling arms again and only the static half stands in its way.
DYNAMIC_EVASIONS: dict[str, tuple[str, bool]] = {
    "0-literal": (
        (
            "import rclpy\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return node.create_publisher(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "1-alias-getattr": (
        (
            "import rclpy\n"
            "_reach = getattr\n"
            "_PARTS = ('create_', 'pub', 'lisher')\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return _reach(node, ''.join(_PARTS))(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "2-operator-attrgetter": (
        (
            "import operator, rclpy\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return operator.attrgetter('create_' 'publisher')(node)"
            "(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "3-dunder-getattribute": (
        (
            "import rclpy\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return node.__getattribute__('create_' + 'publisher')"
            "(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "4-vars-dict": (
        (
            "import rclpy\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return vars(type(node))['create_' + 'publisher']"
            "(node, object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
    "5-unmangled-raw-node": (
        (
            "import rclpy\n"
            "from scripts.parcel_capture.ingest.dds import _SubscribeOnlySession\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    session = _SubscribeOnlySession(rclpy, node, object(), label='x')\n"
            "    raw = session._SubscribeOnlySession__node\n"
            "    return raw.__getattribute__('create_' + 'publisher')"
            "(object, '/cmd_vel', 10)\n"
        ),
        False,
    ),
    "6-exec-string": (
        (
            "import rclpy\n"
            "_run = exec\n"
            "def public_probe():\n"
            "    ns = {'n': rclpy.node.Node('x')}\n"
            "    _run('r = n.create_' + 'publisher(object, \"/cmd_vel\", 10)', ns)\n"
            "    return ns['r']\n"
        ),
        True,
    ),
    "7-chr-arithmetic": (
        (
            "import rclpy\n"
            "_CODES = (99,114,101,97,116,101,95,112,117,98,108,105,115,104,101,114)\n"
            "def public_probe():\n"
            "    node = rclpy.node.Node('x')\n"
            "    return getattr(node, ''.join(chr(c) for c in _CODES))"
            "(object, '/cmd_vel', 10)\n"
        ),
        True,
    ),
}


@pytest.mark.parametrize(("name", "case"), sorted(DYNAMIC_EVASIONS.items()))
def test_each_auditor_evasion_is_scored_against_the_dynamic_half(
    name: str, case: tuple[str, bool], harness_path: Path, tmp_path: Path
) -> None:
    """The other half of the score, on the same eight spellings.

    ``7-chr-arithmetic`` is the case that justifies the whole subprocess: the
    name is built from character codes, so no constant folding can read it, and
    it is caught only because the harness *calls the public function* against a
    fake node whose ``create_publisher`` is a live wire.
    """

    body, expected_armed = case
    module_name = "plant_" + name.replace("-", "_")
    (tmp_path / f"{module_name}.py").write_text(body, encoding="utf-8")
    verdict = run_harness(harness_path, module_name, extra_path=str(tmp_path))
    armed = verdict["status"] == "armed"
    assert armed is expected_armed, f"{name}: dynamic half returned {verdict}"
    if armed:
        assert verdict["detail"]
    else:
        # Not armed must mean the attempt FAILED, not that it was never reached.
        assert any("public_probe" in item for item in verdict["exercised"]), verdict
        assert any("refused" in item for item in verdict["exercised"]), verdict


@pytest.mark.parametrize(
    ("label", "body"),
    [
        (
            "import-time-publisher",
            (
                "import rclpy\nfrom rclpy.node import Node\n"
                "_n = Node('x')\n_p = _n.create_publisher(object, '/cmd_vel', 10)\n"
            ),
        ),
        (
            "import-time-sport-client",
            "from unitree_sdk2py.go2.sport.sport_client import SportClient\n",
        ),
        (
            "motion-through-an-alias",
            (
                "import unitree_sdk2py as sdk\n"
                "def public_probe():\n"
                "    client = getattr(sdk, 'Sport' + 'Client')()\n"
                "    return getattr(client, 'Mo' + 've')(0.5, 0.0, 0.0)\n"
            ),
        ),
    ],
)
def test_seeded_failure_the_dynamic_half_trips_on_a_planted_arming_module(
    label: str, body: str, harness_path: Path, tmp_path: Path
) -> None:
    """Arming at import time, and arming a motion client rather than a topic.

    ``import-time-sport-client`` never executes a line of its own: the fake
    finder refuses to fabricate any module whose name contains ``sport``, so the
    import itself is the trip.
    """

    planted = tmp_path / "planted_module.py"
    planted.write_text(body, encoding="utf-8")
    verdict = run_harness(harness_path, "planted_module", extra_path=str(tmp_path))
    assert verdict["status"] == "armed", f"{label} was not caught: {verdict}"
    assert verdict["detail"]


def test_the_dynamic_half_does_not_fire_on_an_innocent_subscriber_module(
    harness_path: Path, tmp_path: Path
) -> None:
    """The tripwire is a pin, not a smoke alarm that is always on."""

    innocent = tmp_path / "innocent_module.py"
    innocent.write_text(
        "import rclpy\n"
        "from rclpy.node import Node\n"
        "def public_probe():\n"
        "    node = Node('reader')\n"
        "    node.create_subscription(object, '/lowstate', print, 10)\n"
        "    rclpy.spin_once(node, timeout_sec=0.0)\n"
        "    return node.get_name()\n",
        encoding="utf-8",
    )
    verdict = run_harness(harness_path, "innocent_module", extra_path=str(tmp_path))
    assert verdict["status"] == "ok", verdict


# ---------------------------------------------------------------------------
# N4 — residuals, pinned so the comments in base.py cannot drift
# ---------------------------------------------------------------------------


def test_no_reach_through_a_read_only_handle_yields_the_wrapped_object() -> None:
    """Every spelling the auditor executed against the old facade, refused.

    The old ``__slots__ = (..., "_target")`` made ``_target`` an ordinary
    class-level descriptor, so ``handle._target`` resolved through
    ``object.__getattribute__`` and ``__getattr__`` was never consulted. Run
    this against that version and the first case returns the raw node.
    """

    import operator

    from scripts.parcel_capture.ingest.base import IngestRefusedError, ReadOnlyHandle

    class _FakeNode:
        def create_subscription(self, *args: object) -> str:
            return "subscription"

        def create_publisher(self, *args: object) -> str:  # pragma: no cover - never reached
            return "publisher"

    node = _FakeNode()
    handle = ReadOnlyHandle(node, allowed=("create_subscription",), label="fake node")
    assert handle.create_subscription(1, 2, 3, 4) == "subscription"
    assert handle.allowed == frozenset({"create_subscription"})
    assert handle.label == "fake node"

    reaches = {
        "attribute": lambda: handle._target,
        "computed getattr": lambda: getattr(handle, "_" + "target"),
        "getattr with a default": lambda: getattr(handle, "_target", None),
        "__dict__": lambda: handle.__dict__,
        "vars()": lambda: vars(handle),
        "__getattribute__": lambda: handle.__getattribute__("_target"),
        "attrgetter": lambda: operator.attrgetter("_target")(handle),
        "the allowlist itself": lambda: handle._allowed,
        "a command surface": lambda: handle.create_publisher,
        "a computed command surface": lambda: getattr(handle, "create_" + "publisher"),
    }
    for reach in reaches.values():
        with pytest.raises(IngestRefusedError):
            reach()

    # object.__getattribute__ does not find a slot either, because there is none.
    with pytest.raises(AttributeError):
        object.__getattribute__(handle, "_target")
    # and the handle cannot be written to, or emptied.
    with pytest.raises(IngestRefusedError):
        handle.anything = 1
    with pytest.raises(IngestRefusedError):
        del handle.create_subscription


def test_never_allowed_is_enforced_at_access_time_not_only_at_construction() -> None:
    """The construction check alone was undone by one ``object.__setattr__``.

    The old handle stored its allowlist in a slot; widening it in place gave
    ``handle.create_publisher``. Now ``NEVER_ALLOWED`` is consulted on every
    access, ahead of the allowlist, so widening it anywhere changes nothing.
    """

    from scripts.parcel_capture.ingest.base import (
        NEVER_ALLOWED,
        IngestRefusedError,
        ReadOnlyHandle,
    )

    class _FakeNode:
        def create_subscription(self, *args: object) -> str:
            return "subscription"

        def create_publisher(self, *args: object) -> str:  # pragma: no cover
            return "publisher"

    handle = ReadOnlyHandle(_FakeNode(), allowed=("create_subscription",), label="widened")

    # (a) the construction-time check still refuses a widened allowlist up front
    for name in ("create_publisher", "startLidar", "set_option", "SportClient"):
        assert name in NEVER_ALLOWED
        with pytest.raises(IngestRefusedError, match="cannot be configured into a writable one"):
            ReadOnlyHandle(object(), allowed=("get_name", name), label="widened")

    # (b) ...and the old bypass no longer bypasses anything: there is no slot to
    #     write, so this raises before it can widen anything
    with pytest.raises(AttributeError):
        object.__setattr__(handle, "_allowed", frozenset({"create_publisher"}))

    # (c) ...and even reaching the closure state and widening it there fails,
    #     because NEVER_ALLOWED is checked before the allowlist on every access
    state = type(handle).__getattribute__.__closure__[0].cell_contents
    record = state[handle]
    state[handle] = type(record)(
        target=record.target,
        allowed=frozenset({"create_publisher", "create_subscription"}),
        label=record.label,
    )
    with pytest.raises(IngestRefusedError, match="refused at access time"):
        handle.create_publisher  # noqa: B018
    assert handle.create_subscription(1, 2, 3, 4) == "subscription"


def test_the_dds_session_exposes_neither_the_node_nor_the_rclpy_module() -> None:
    """The claim ``test_capture_ingest.py:307-308`` used to make, made true.

    That test asserted the node was "reachable only from inside the class body —
    not from a caller, and not from another module". Name mangling is a rename,
    not privacy: the auditor read ``session._SubscribeOnlySession__node`` from
    another module in one line, and ``_rclpy`` handed out the whole module on a
    single-underscore attribute. Both attributes are gone.
    """

    from scripts.parcel_capture.ingest import dds as dds_module

    class _FakeNode:
        def create_subscription(self, *args: object) -> str:
            return "subscription"

        def create_publisher(self, *args: object) -> str:  # pragma: no cover
            return "publisher"

        def destroy_node(self) -> None:
            return None

    class _FakeRclpy:
        def __init__(self) -> None:
            self.spun = 0
            self.shut = 0

        def spin_once(self, node: object, timeout_sec: float = 0.0) -> None:
            self.spun += 1

        def shutdown(self, context: object = None) -> None:
            self.shut += 1

    rclpy = _FakeRclpy()
    session = dds_module._SubscribeOnlySession(rclpy, _FakeNode(), object(), label="fake")

    assert set(dds_module._SubscribeOnlySession.__slots__) == {
        "_shutdown",
        "_spin",
        "_subscriptions",
        "handle",
    }
    for name in ("_rclpy", "_SubscribeOnlySession__node", "_node", "node", "_context"):
        assert not hasattr(session, name), name

    # the session still works: it spins and shuts down through sealed calls
    session.spin_once(0.01)
    session.close()
    assert (rclpy.spun, rclpy.shut) == (1, 1)


def test_the_residual_introspection_routes_are_documented_and_still_open() -> None:
    """An accurate weaker claim beats a false stronger one.

    ``base.py`` says the facade does not stop an in-process caller who reaches
    for closure cells or ``gc``. This test asserts that residual is REAL. If a
    future change closes it, this test fails — and the right response is to
    strengthen the docstring, not to delete the test.
    """

    import gc

    from scripts.parcel_capture.ingest import dds as dds_module
    from scripts.parcel_capture.ingest.base import IngestRefusedError, ReadOnlyHandle

    class _FakeNode:
        def create_subscription(self, *args: object) -> str:
            return "subscription"

    node = _FakeNode()
    handle = ReadOnlyHandle(node, allowed=("create_subscription",), label="residual")

    # RESIDUAL 1 — the closure cell behind ``__getattribute__`` is the state map,
    # and the state map holds the target. One line, from the class object.
    state = type(handle).__getattribute__.__closure__[0].cell_contents
    assert state[handle].target is node

    # RESIDUAL 2 — ``__init__`` closes over the same map, so removing one method
    # from the reach would not close the route.
    from_init = [cell.cell_contents for cell in type(handle).__init__.__closure__ or ()]
    assert any(candidate is state for candidate in from_init)

    # RESIDUAL 3 — the same shape for a sealed_call: the binding is in the closure.
    sealed = dds_module.sealed_call(node, "create_subscription", label="residual")
    assert any(
        getattr(cell.cell_contents, "__self__", None) is node
        for cell in sealed.__closure__ or ()
    )

    # WHAT IS CLOSED, and it is the part that matters: the handle instance holds
    # no reference to the target at all, so nothing that starts from the object
    # an adapter was handed can reach the vendor object.
    assert all(referent is not node for referent in gc.get_referents(handle))
    for reach in ("_target", "__dict__", "__init__", "__getattribute__", "__class__"):
        with pytest.raises(IngestRefusedError):
            getattr(handle, reach)


def test_this_pin_is_the_one_the_capture_stack_points_at() -> None:
    """Anti-drift: the modules that cite this file must keep citing a real file."""

    citing = [
        REPO / "scripts" / "parcel_capture" / "ingest" / "base.py",
        REPO / "tests" / "test_capture_ingest.py",
    ]
    for path in citing:
        assert "tests/test_no_arm_pin.py" in path.read_text(encoding="utf-8"), path
