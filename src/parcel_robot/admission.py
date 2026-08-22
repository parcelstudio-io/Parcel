"""Card CAP-1 — what the product actually admits, in ONE place.

Four times in week 1 a feature was complete at its mechanism and dead at its
door:

* ``TOOL_ROAM`` reached the hosted surface and the safety supervisor answered
  ``Unknown behavior: roam`` — the broker's own tests used a stub validator, so
  nothing could see it (``AUDIT_WEEK1_FABLE.md``, ROAM-1 finding 1);
* ``_roam_limits`` read a ``roam:`` config section the prototype overlay loader
  refused to merge, so no operator could ever put anything in it (finding 6);
* the proactive-motion sets are checked against ``MOTION_TOOLS`` by one card's
  own test and by nothing that outlives that card;
* a navigation YAML can name a semantic candidate source that the process
  never binds, and the run silently reads the MuJoCo oracle instead
  (``backlog/NEXT.md``, "Active worktree delta": *a startup defect to close,
  not a usable shadow/cutover mode*).

Each door is right to exist. What was missing is anything that checks the doors
**against each other** and against what this runtime was configured to run.

**This module is a VIEW, not a gate.** It reads the existing sources of truth —
:data:`parcel_robot.safety.BEHAVIOR_MODES`, the broker's tool table and its
``PROACTIVE_MOTION_ALLOWED`` / ``PROACTIVE_MOTION_REFUSED`` sets,
:data:`parcel_robot.config.OVERLAY_INTRODUCIBLE_KEYS`, and the semantic
candidate-source selection — and answers "is this admitted, and why". It never
edits them, never refuses anything a caller could otherwise do, and a ``False``
row in :func:`admitted` is a REPORT, not a new refusal. The one fatal path here
is :func:`check_required_capabilities`, and it fires only when a profile has
explicitly declared what it requires (see below).

**Why the doors are read out of source rather than restated here.** A
hand-written table of "tool X routes to behavior Y" would have missed ROAM-1
exactly the way the card's stub validator did: whoever adds the tenth tool does
not think to add the row. So the routes, the spatial-behavior names and the
config sections a runtime region reads are derived by AST from the product's
own files. A restated table proves the restatement is self-consistent; a
derived one proves the product is.

Deriving from source means source has to be there. A frozen BARN bundle ships a
``parcel_robot`` tree with the modules but not always beside this file, so
every derivation degrades to "empty, and say so" rather than raising — the view
going quiet must never take a runtime down.
"""

from __future__ import annotations

import ast
import functools
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DOMAIN_BEHAVIOR",
    "DOMAIN_CAPABILITY",
    "DOMAIN_CONFIG_KEY",
    "DOMAIN_PROACTIVE_MOTION",
    "DOMAIN_TOOL",
    "REGISTERED_CAPABILITIES",
    "REQUIRED_CAPABILITIES_KEY",
    "AdmissionEntry",
    "BehaviorRoute",
    "BrokerScan",
    "CapabilityRefused",
    "ConfigScan",
    "UnreadableSite",
    "admission_snapshot",
    "admitted",
    "behavior_entries",
    "broker_behavior_routes",
    "broker_scan",
    "capability_entries",
    "check_required_capabilities",
    "config_key_entries",
    "config_section_scan",
    "navigation_config_mapping",
    "proactive_motion_entries",
    "product_config_sections",
    "render_table",
    "required_capabilities",
    "runtime_config_sections",
    "supervisor_spatial_behaviors",
    "tool_entries",
]

#: The five questions the table answers. They are separate domains because a
#: reader asking "why can't the dog roam" and a reader asking "why did my YAML
#: key do nothing" are looking for different rows, and one flat list of names
#: makes both of them read the whole thing.
DOMAIN_BEHAVIOR = "behavior"
DOMAIN_TOOL = "tool"
DOMAIN_PROACTIVE_MOTION = "proactive_motion"
DOMAIN_CONFIG_KEY = "config_key"
DOMAIN_CAPABILITY = "capability"


@dataclass(frozen=True)
class AdmissionEntry:
    """One admitted-or-not answer, with the reason and where it was read.

    ``source`` names the door, not this module: a row that says
    ``safety.BEHAVIOR_MODES`` sends the reader to the file that decides, which
    is the entire difference between a status panel and a diagnosis.
    """

    domain: str
    name: str
    admitted: bool
    reason: str
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "name": self.name,
            "admitted": self.admitted,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class BehaviorRoute:
    """A ``(tool, door, behavior-name)`` triple derived from the broker source."""

    tool: str
    door: str
    behavior: str


@dataclass(frozen=True)
class UnreadableSite:
    """A door call this module could not read. **Never silently skipped.**

    THE CARD'S OWN BLIND SPOT, caught by the verifier. The first cut of the
    derivation ``continue``d on anything it could not parse, so a route written
    across two statements —

        call = ToolCall("set_behavior", {"mode": "fetch"})
        allowed = self._validated(call, TOOL_FETCH_BALL)

    was simply ABSENT from the table: the tool row still said ``admitted``, with
    the "validated as ..." phrase merely missing, and G1 stayed green on a tool
    that is dead at the supervisor exactly the way ``roam`` was. A FORMATTING
    CHOICE decided whether the headline guard fired on the headline defect
    class.

    So every unreadable site is now reported by file and line, and the guard
    refuses to pass while one exists. "I could not read this" is an answer; it
    is not the same answer as "there is nothing here", and the difference is the
    whole reason this module reads source instead of a table somebody wrote.
    """

    source: str
    lineno: int
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"source": self.source, "lineno": self.lineno, "detail": self.detail}


@dataclass(frozen=True)
class BrokerScan:
    """What the broker's ``_validated`` call sites say, and what could not be read."""

    routes: tuple[BehaviorRoute, ...]
    #: ``tool -> the doors it is validated through``, as sorted pairs so the
    #: whole scan stays hashable and therefore cacheable.
    doors: tuple[tuple[str, tuple[str, ...]], ...]
    unreadable: tuple[UnreadableSite, ...]

    def doors_by_tool(self) -> dict[str, frozenset[str]]:
        return {tool: frozenset(doors) for tool, doors in self.doors}


@dataclass(frozen=True)
class ConfigScan:
    """Config section names read through a ``ConfigStore``, and what could not be read."""

    names: tuple[str, ...]
    unreadable: tuple[UnreadableSite, ...]


class CapabilityRefused(RuntimeError):
    """A declared required capability is not bound. Startup only, never a tick.

    Deliberately a startup-time error and nothing else. The standing prototype
    rule is ask-over-refuse at RUNTIME; this is a configuration-truth check —
    the profile said it needs something, the process does not have it, and the
    honest answer is to say so at the door instead of running a different robot
    than the file describes.
    """


# ======================================================================
# Derivations. Read the product's own source; never restate it.
# ======================================================================

_PACKAGE_DIR = Path(__file__).resolve().parent


def _parse(path: Path) -> ast.Module | None:
    """Parse one product file, or answer ``None`` — never raise.

    A view that can take the runtime down when a source file is absent is worse
    than no view at all. Every caller treats ``None`` as "nothing derived" and
    says so in the reason column.
    """

    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError):  # pragma: no cover - frozen bundle
        return None


@functools.lru_cache(maxsize=8)
def _tree(relative: str) -> ast.Module | None:
    return _parse(_PACKAGE_DIR.joinpath(*relative.split("/")))


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """``TOOL_ROAM = "roam"`` -> ``{"TOOL_ROAM": "roam"}``, module level only."""

    constants: dict[str, str] = {}
    for node in tree.body:
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            constants[node.target.id] = value.value
    return constants


def _literal_or_constant(node: ast.expr, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


#: The argument keys that name a BEHAVIOR at a supervisor door. A door call
#: carrying one of these is a behavior route; a door call carrying neither is a
#: perfectly ordinary non-behavior route (``navigate``, ``run_pose``) and is not
#: a defect.
_BEHAVIOR_KEYS = frozenset({"mode", "behavior"})

_BROKER_SOURCE = "realtime/tool_broker.py"


@functools.lru_cache(maxsize=1)
def broker_scan() -> BrokerScan:
    """Read every ``self._validated(ToolCall(<door>, {...}), <TOOL_*>)`` site.

    Derived from the calls the broker actually makes, because that is the line
    ROAM-1 got right and still shipped dead: the door was correct, the name was
    not in the allowlist behind it, and no table anywhere related the two.

    A site is READ only when all of it is readable — an inline ``ToolCall``
    whose door and tool resolve to a string literal or a module-level ``TOOL_*``
    constant, and whose argument mapping has literal keys with a resolvable
    value for any behavior key. Anything else becomes an
    :class:`UnreadableSite`, which G1 refuses to pass on. See that class for the
    defect this rule exists for.
    """

    tree = _tree(_BROKER_SOURCE)
    if tree is None:  # pragma: no cover - frozen bundle path
        return BrokerScan((), (), ())
    constants = _module_string_constants(tree)
    routes: set[BehaviorRoute] = set()
    doors: dict[str, set[str]] = {}
    unreadable: list[UnreadableSite] = []

    def unread(node: ast.AST, detail: str) -> None:
        unreadable.append(
            UnreadableSite(
                source=_BROKER_SOURCE, lineno=getattr(node, "lineno", 0), detail=detail
            )
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "_validated":
            continue
        if len(node.args) < 2 or node.keywords:
            unread(node, "_validated(...) is not called with two positional arguments")
            continue
        call, tool_node = node.args[0], node.args[1]
        tool = _literal_or_constant(tool_node, constants)
        if tool is None:
            unread(node, "the tool argument is not a literal or a module-level TOOL_* constant")
            continue
        if (
            not isinstance(call, ast.Call)
            or not isinstance(call.func, ast.Name)
            or call.func.id != "ToolCall"
        ):
            unread(node, f"{tool}: the first argument is not an inline ToolCall(...)")
            continue
        if len(call.args) < 2 or call.keywords:
            unread(node, f"{tool}: ToolCall(...) is not called with two positional arguments")
            continue
        door = _literal_or_constant(call.args[0], constants)
        if door is None:
            unread(node, f"{tool}: the door name is not a literal or a module-level constant")
            continue
        doors.setdefault(tool, set()).add(door)
        arguments = call.args[1]
        if not isinstance(arguments, ast.Dict):
            unread(node, f"{tool} -> {door}: the argument mapping is not a dict literal")
            continue
        for key, value in zip(arguments.keys, arguments.values, strict=False):
            if key is None or not isinstance(key, ast.Constant):
                # ``**kwargs`` or a computed key: a behavior name could be
                # hiding in there and this module would never see it.
                unread(node, f"{tool} -> {door}: the argument mapping has a non-literal key")
                continue
            if key.value not in _BEHAVIOR_KEYS:
                continue
            behavior = _literal_or_constant(value, constants)
            if behavior is None:
                unread(
                    node,
                    f"{tool} -> {door}: the {key.value!r} argument is not a literal or a "
                    f"module-level constant, so the behavior name cannot be checked "
                    f"against the supervisor",
                )
                continue
            routes.add(BehaviorRoute(tool=tool, door=door, behavior=behavior))

    return BrokerScan(
        routes=tuple(
            sorted(routes, key=lambda route: (route.door, route.behavior, route.tool))
        ),
        doors=tuple((tool, tuple(sorted(names))) for tool, names in sorted(doors.items())),
        unreadable=tuple(unreadable),
    )


def broker_behavior_routes() -> tuple[BehaviorRoute, ...]:
    """Every behavior name ``realtime/tool_broker.py`` sends to the supervisor."""

    return broker_scan().routes


@functools.lru_cache(maxsize=1)
def supervisor_spatial_behaviors() -> frozenset[str]:
    """The names ``SafetySupervisor._validate_spatial_behavior`` compares against.

    The spatial arm has no named set to read — it is a ladder of
    ``if behavior == "..."`` — so the ladder itself is the source of truth and
    this reads it. Changing that to a constant would be a change to the
    supervisor, which this card does not make.
    """

    tree = _tree("safety.py")
    if tree is None:  # pragma: no cover - frozen bundle path
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_validate_spatial_behavior":
            continue
        for compare in ast.walk(node):
            if not isinstance(compare, ast.Compare):
                continue
            if not isinstance(compare.left, ast.Name) or compare.left.id != "behavior":
                continue
            for comparator in compare.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    names.add(comparator.value)
    return frozenset(names)


#: G2's PRE-REGISTERED scope: the files carrying the runtime regions whose
#: config reads the guard was written for. ``admission.py`` is in it because
#: this module reads a section too, and a guard that exempts its own author is
#: not a guard — which is only true now that the derivation also matches a bare
#: ``store`` receiver, since this module reads through a local name rather than
#: ``self.store``.
_RUNTIME_REGION_SOURCES = ("runtime.py", "admission.py")

#: Every product file in the package whose text contains ``store.section(``.
#: Static rather than globbed because globbing would AST-parse 50+ modules on
#: the first ``/api/state`` poll; ``test_the_product_survey_names_every_file_that
#: _reads_a_config_section`` greps the tree and fails if this list is no longer
#: complete, so the cheap list cannot silently go stale.
#:
#: ``config.py`` is in the list and contributes nothing: its two mentions are
#: inside a docstring and a comment, which the AST does not see. Including it
#: keeps the completeness check a plain text scan.
_PRODUCT_CONFIG_SOURCES = (
    "admission.py",
    "cli.py",
    "config.py",
    "headless_city.py",
    "ros_node.py",
    "runtime.py",
    "sim.py",
    "unitree_control.py",
    "web_panel.py",
)


@functools.lru_cache(maxsize=4)
def config_section_scan(sources: tuple[str, ...]) -> ConfigScan:
    """Config sections read through a ``ConfigStore``, by literal, plus the misses.

    ROAM-1 finding 6 is one entry of this list disagreeing with the overlay
    loader: ``_roam_limits`` read ``store.section("roam")`` while
    ``check_overlay_keys`` refused a ``roam:`` block, so the knob existed and
    could never be set.

    Both receiver shapes are matched — ``self.store.section(...)`` and a local
    ``store.section(...)`` — and a section name that is not a plain string
    literal is reported as unreadable rather than skipped, for the reason
    :class:`UnreadableSite` gives.
    """

    names: set[str] = set()
    unreadable: list[UnreadableSite] = []
    for relative in sources:
        tree = _tree(relative)
        if tree is None:  # pragma: no cover - frozen bundle path
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "section":
                continue
            owner = func.value
            is_store = (isinstance(owner, ast.Attribute) and owner.attr == "store") or (
                isinstance(owner, ast.Name) and owner.id == "store"
            )
            if not is_store:
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
                continue
            unreadable.append(
                UnreadableSite(
                    source=relative,
                    lineno=getattr(node, "lineno", 0),
                    detail=(
                        "store.section(...) is called with a name this module cannot "
                        "read, so the key cannot be checked against the overlay loader"
                    ),
                )
            )
    return ConfigScan(tuple(sorted(names)), tuple(unreadable))


def runtime_config_sections() -> tuple[str, ...]:
    """The sections the runtime regions read — G2's pre-registered scope."""

    return config_section_scan(_RUNTIME_REGION_SOURCES).names


def product_config_sections() -> tuple[str, ...]:
    """Every section any product file reads. Wider than G2 asserts; see the table."""

    return config_section_scan(_PRODUCT_CONFIG_SOURCES).names


# ======================================================================
# The table
#
# The four static domains are memoised. They are functions of source files and
# module constants, which do not change while a process runs, and ``/api/state``
# rebuilds this table on every panel refresh — an uncached view would re-parse
# two YAML files and four ASTs several times a second to answer a question whose
# answer cannot have moved. The capability rows are NOT cached: they are the
# half that describes the live process.
# ======================================================================


@functools.lru_cache(maxsize=1)
def behavior_entries() -> tuple[AdmissionEntry, ...]:
    """Behavior names: what the supervisor admits, and what the broker asks for."""

    from parcel_robot.safety import BEHAVIOR_MODES

    routes = broker_behavior_routes()
    by_behavior: dict[str, list[BehaviorRoute]] = {}
    for route in routes:
        by_behavior.setdefault(route.behavior, []).append(route)

    entries: list[AdmissionEntry] = []
    for mode in sorted(BEHAVIOR_MODES):
        callers = sorted({route.tool for route in by_behavior.get(mode, ())})
        entries.append(
            AdmissionEntry(
                domain=DOMAIN_BEHAVIOR,
                name=mode,
                admitted=True,
                reason=(
                    "the supervisor's set_behavior arm accepts this mode; reached by "
                    + ", ".join(callers)
                    if callers
                    else "the supervisor's set_behavior arm accepts this mode; no "
                    "hosted tool routes to it"
                ),
                source="safety.BEHAVIOR_MODES",
            )
        )

    spatial = supervisor_spatial_behaviors()
    for route in routes:
        if route.door == "set_behavior" and route.behavior not in BEHAVIOR_MODES:
            entries.append(
                AdmissionEntry(
                    domain=DOMAIN_BEHAVIOR,
                    name=route.behavior,
                    admitted=False,
                    reason=(
                        f"tool {route.tool!r} routes set_behavior(mode="
                        f"{route.behavior!r}) and the supervisor's allowlist does not "
                        f"carry it — the call is refused as 'Unknown behavior'"
                    ),
                    source="safety.BEHAVIOR_MODES",
                )
            )
        elif route.door == "run_spatial_behavior" and route.behavior not in spatial:
            entries.append(
                AdmissionEntry(
                    domain=DOMAIN_BEHAVIOR,
                    name=route.behavior,
                    admitted=False,
                    reason=(
                        f"tool {route.tool!r} routes run_spatial_behavior(behavior="
                        f"{route.behavior!r}) and the supervisor's spatial arm does "
                        f"not name it"
                    ),
                    source="safety.SafetySupervisor._validate_spatial_behavior",
                )
            )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def tool_entries() -> tuple[AdmissionEntry, ...]:
    """Every tool the hosted broker will answer, and what class it is in."""

    from parcel_robot.realtime.tool_broker import (
        BROKER_TOOLS,
        MOTION_TOOLS,
        PROACTIVE_MOTION_CEILING,
    )

    # A tool may route to more than one behavior — ``roam`` reaches both ``roam``
    # and ``roam_stop``, and a row that showed only the last one read would hide
    # exactly the half a reader is looking for.
    routes: dict[str, list[BehaviorRoute]] = {}
    for route in broker_behavior_routes():
        routes.setdefault(route.tool, []).append(route)
    entries: list[AdmissionEntry] = []
    for tool in BROKER_TOOLS:
        parts: list[str] = []
        if tool in MOTION_TOOLS:
            parts.append("commits the body (MOTION_TOOLS)")
            parts.append(
                "may run from a robot-initiated reply"
                if tool in PROACTIVE_MOTION_CEILING
                else "owner-initiated replies only"
            )
        else:
            parts.append("read-only surface")
        for route in routes.get(tool, ()):
            parts.append(f"validated as {route.door}({route.behavior!r})")
        entries.append(
            AdmissionEntry(
                domain=DOMAIN_TOOL,
                name=tool,
                admitted=True,
                reason="; ".join(parts),
                source="realtime.tool_broker.BROKER_TOOLS",
            )
        )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def proactive_motion_entries() -> tuple[AdmissionEntry, ...]:
    """Which motion tools a robot-initiated reply may run — one verdict each."""

    from parcel_robot.realtime.config import (
        PROACTIVE_MOTION_ALLOWED,
        PROACTIVE_MOTION_REFUSED,
    )
    from parcel_robot.realtime.tool_broker import MOTION_TOOLS

    allowed = set(PROACTIVE_MOTION_ALLOWED)
    refused = set(PROACTIVE_MOTION_REFUSED)
    entries: list[AdmissionEntry] = []
    for tool in sorted(MOTION_TOOLS | allowed | refused):
        in_allowed, in_refused = tool in allowed, tool in refused
        if in_allowed and not in_refused:
            reason = "on the proactive allowlist: worst case is a body that moved in place"
        elif in_refused and not in_allowed:
            reason = "refused proactively: a travel tool started by nobody (bench finding C1)"
        elif in_allowed and in_refused:
            reason = "IN BOTH SETS — the config door and the broker ceiling disagree"
        else:
            reason = (
                "no proactive verdict: in MOTION_TOOLS but in neither "
                "PROACTIVE_MOTION_ALLOWED nor PROACTIVE_MOTION_REFUSED"
            )
        entries.append(
            AdmissionEntry(
                domain=DOMAIN_PROACTIVE_MOTION,
                name=tool,
                admitted=in_allowed and not in_refused,
                reason=reason,
                source="realtime.config.PROACTIVE_MOTION_ALLOWED/REFUSED",
            )
        )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def config_key_entries() -> tuple[AdmissionEntry, ...]:
    """Config sections a runtime region reads, against what an overlay may set."""

    import yaml

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS
    from parcel_robot.paths import resolve_config_yaml

    base_keys: set[str] = set()
    base_note = ""
    try:
        loaded = yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}
        base_keys = set(loaded) if isinstance(loaded, Mapping) else set()
    except (OSError, ValueError, TypeError) as error:  # pragma: no cover
        base_note = f" (base config unreadable: {type(error).__name__})"

    entries: list[AdmissionEntry] = []
    # The TABLE surveys every product file that reads a section, which is wider
    # than the scope G2 asserts on. That is deliberate: the panel must report
    # what is true, and the guard must assert only what it was pre-registered to
    # assert. Where the two disagree, the disagreement is a finding with a named
    # owner, not a widened guard nobody reviewed.
    for name in product_config_sections():
        if name in base_keys:
            reason = "defined by the shipped configs/robot.yaml, so an overlay may set it"
        elif name in OVERLAY_INTRODUCIBLE_KEYS:
            reason = (
                "absent from the SHA-locked base but listed in "
                "OVERLAY_INTRODUCIBLE_KEYS, so a profile overlay may introduce it"
            )
        else:
            reason = (
                "a runtime region reads this section, the SHA-locked base does not "
                "define it, and it is not in OVERLAY_INTRODUCIBLE_KEYS — a profile "
                "overlay that sets it is REFUSED at load, so the knob can never be "
                "turned" + base_note
            )
        entries.append(
            AdmissionEntry(
                domain=DOMAIN_CONFIG_KEY,
                name=name,
                admitted=name in base_keys or name in OVERLAY_INTRODUCIBLE_KEYS,
                reason=reason,
                source="config.OVERLAY_INTRODUCIBLE_KEYS + configs/robot.yaml",
            )
        )
    return tuple(entries)


# ======================================================================
# Capabilities — the half a profile may declare it REQUIRES
# ======================================================================

#: The candidate source the process actually acts on is the one the navigation
#: YAML names. This is the backlog's "startup defect to close": the YAML can say
#: ``learned_map`` while the process-global stays ``oracle`` and the run reads
#: MuJoCo ground truth with nobody the wiser.
CAPABILITY_SOURCE_MATCHES_CONFIG = "semantic_source_matches_config"
#: The bound source DRIVES from the learned map (``learned_map``; not ``shadow``,
#: where the oracle still drives — that distinction is the whole of shadow mode).
CAPABILITY_LEARNED_MAP_SOURCE = "learned_map_source"
#: An ``OnlineSemanticMap`` instance is installed on the mission path.
CAPABILITY_LEARNED_MAP_INSTALLED = "learned_map_installed"
#: The ``demo_pois.yaml`` second oracle is empty — i.e. a "success" cannot come
#: from a hardcoded lookup table.
CAPABILITY_POI_ORACLE_DISABLED = "poi_oracle_disabled"
#: ``navigation.pipeline``'s soft imports, by their own health field names.
CAPABILITY_INSTRUCTNAV = "instructnav"
CAPABILITY_DETECTION_LOCK_ON = "detection_lock_on"
CAPABILITY_LOCK_ON_VERIFY = "lock_on_verify"
CAPABILITY_ROUTE_MEMORY = "route_memory"

#: Every name a profile may require. A declaration outside this set is a typo
#: and is refused BY NAME at startup, for the reason ``check_overlay_keys``
#: refuses an unknown overlay key: a requirement nothing evaluates looks exactly
#: like a requirement that was met.
REGISTERED_CAPABILITIES: tuple[str, ...] = (
    CAPABILITY_SOURCE_MATCHES_CONFIG,
    CAPABILITY_LEARNED_MAP_SOURCE,
    CAPABILITY_LEARNED_MAP_INSTALLED,
    CAPABILITY_POI_ORACLE_DISABLED,
    CAPABILITY_INSTRUCTNAV,
    CAPABILITY_DETECTION_LOCK_ON,
    CAPABILITY_LOCK_ON_VERIFY,
    CAPABILITY_ROUTE_MEMORY,
)

_SOFT_IMPORT_CAPABILITIES = (
    CAPABILITY_INSTRUCTNAV,
    CAPABILITY_DETECTION_LOCK_ON,
    CAPABILITY_LOCK_ON_VERIFY,
    CAPABILITY_ROUTE_MEMORY,
)

#: The key a navigation profile declares its requirements under.
#:
#: It lives in the NAVIGATION profile — beside ``perception.semantic_source``,
#: the axis whose binding it is about — and not in the robot profile, because
#: the robot base config is SHA-locked and its overlay loader refuses any key
#: the base does not define. Adding a top-level key to the robot profile
#: therefore needs an entry in ``config.OVERLAY_INTRODUCIBLE_KEYS``, which is
#: another card's door; see CAP1_STATUS.md, "findings about other cards' doors".
REQUIRED_CAPABILITIES_KEY = "required_capabilities"


def navigation_config_mapping(runtime: Any) -> Mapping[str, Any]:
    """The navigation config THIS runtime selected, as a mapping.

    Resolves ``navigation.config`` from the robot profile rather than
    hardcoding ``default.yaml``, for the reason
    ``RobotRuntime._p1b_semantic_source`` gives: a profile pointing at
    ``configs/navigation/prototype.yaml`` that silently got the shipped file
    would be "a cutover that never happened looks like the default".
    """

    try:
        from parcel_robot.paths import resolve_navigation_config

        store = getattr(runtime, "store", None)
        section = store.section("navigation") if store is not None else {}
        configured = str(section.get("config") or "configs/navigation/default.yaml")
        path = resolve_navigation_config(configured)
        stamp = path.stat()
    except (OSError, TypeError, KeyError, ImportError, AttributeError):
        return {}
    return _load_navigation_config(str(path), stamp.st_mtime_ns, stamp.st_size)


@functools.lru_cache(maxsize=8)
def _load_navigation_config(path: str, mtime_ns: int, size: int) -> Mapping[str, Any]:
    """One YAML parse per (path, mtime, size). Cached because ``/api/state`` is a poll.

    The stamp is part of the key rather than the path alone: a test — or an
    operator — that rewrites the file it just pointed at must see the new
    content, and a cache that answered from the old bytes would be its own
    version of the defect this card is about.
    """

    del mtime_ns, size  # in the key, not in the body
    try:
        import yaml

        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, ImportError):
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def required_capabilities(navigation_config: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The capabilities a profile declares it needs. **Absent means none.**

    Absent is the default and absent changes nothing: a tree that has never
    heard of this card declares nothing, requires nothing, and starts exactly as
    it did. Only a profile that opts in can fail here.
    """

    if not isinstance(navigation_config, Mapping):
        return ()
    declared = navigation_config.get(REQUIRED_CAPABILITIES_KEY)
    if declared is None:
        return ()
    if isinstance(declared, str) or not isinstance(declared, Sequence):
        raise CapabilityRefused(
            f"{REQUIRED_CAPABILITIES_KEY} must be a list of capability names, got "
            f"{type(declared).__name__}"
        )
    names = tuple(str(item) for item in declared)
    unknown = sorted(set(names) - set(REGISTERED_CAPABILITIES))
    if unknown:
        raise CapabilityRefused(
            f"unknown required capability name(s): {', '.join(unknown)}; registered "
            f"capabilities are {list(REGISTERED_CAPABILITIES)}. A requirement nothing "
            f"evaluates looks exactly like a requirement that was met."
        )
    return names


def _semantic_source_state(runtime: Any) -> tuple[Any, Any, str]:
    """``(configured policy, bound policy, note)`` — both halves of the axis."""

    bound: Any = None
    note = ""
    try:
        from parcel_robot.perception_source import active_semantic_source

        bound = active_semantic_source()
    except ImportError:  # pragma: no cover - frozen bundle path
        note = "perception_source is not importable in this process"
    configured: Any = None
    reader = getattr(runtime, "_p1b_semantic_source", None)
    if callable(reader):
        # The runtime's own reader, called rather than re-implemented: two
        # readers of one YAML key is how the two answers drift apart.
        try:
            configured = reader()
        except Exception as error:  # noqa: BLE001 - a malformed source is a real answer
            note = f"{type(error).__name__}: {error}"
    return configured, bound, note


def capability_entries(
    runtime: Any = None, *, probe_imports: bool = False
) -> tuple[AdmissionEntry, ...]:
    """What this process can actually do, one row per registered capability.

    ``probe_imports`` decides whether the soft-import rows import
    ``navigation.pipeline`` to answer. Off by default: a panel refresh has no
    business dragging the whole InstructNav ladder into a process that never
    needed it, and "not probed" is a truthful row. The startup check turns it on
    for the capabilities a profile actually declared.
    """

    configured, bound, note = _semantic_source_state(runtime)
    configured_source = getattr(configured, "source", None)
    bound_source = getattr(bound, "source", None)

    entries: list[AdmissionEntry] = []
    if bound is None:
        matches, match_reason = False, note or "no semantic source is bound in this process"
    elif configured is None:
        matches = True
        match_reason = (
            f"bound source is {bound_source!r}; no runtime is attached to this view, "
            f"so there is no configured source to disagree with it"
        )
    elif configured_source == bound_source:
        matches = True
        match_reason = f"the navigation profile names {configured_source!r} and it is bound"
    else:
        matches = False
        match_reason = (
            f"the navigation profile names {configured_source!r} but the process-global "
            f"candidate source is {bound_source!r} — this run reads a different map "
            f"than the file describes"
        )
    entries.append(
        AdmissionEntry(
            domain=DOMAIN_CAPABILITY,
            name=CAPABILITY_SOURCE_MATCHES_CONFIG,
            admitted=matches,
            reason=match_reason,
            source="perception_source.active_semantic_source() vs navigation profile",
        )
    )
    entries.append(
        AdmissionEntry(
            domain=DOMAIN_CAPABILITY,
            name=CAPABILITY_LEARNED_MAP_SOURCE,
            admitted=bool(getattr(bound, "drives_from_learned_map", False)),
            reason=(
                f"bound semantic source is {bound_source!r}; the robot acts on the "
                f"learned map only under 'learned_map'"
            ),
            source="perception_source.active_semantic_source()",
        )
    )
    learned_map: Any = None
    try:
        from parcel_robot.perception_source import active_learned_map

        learned_map = active_learned_map()
    except ImportError:  # pragma: no cover - frozen bundle path
        learned_map = None
    entries.append(
        AdmissionEntry(
            domain=DOMAIN_CAPABILITY,
            name=CAPABILITY_LEARNED_MAP_INSTALLED,
            admitted=learned_map is not None,
            reason=(
                f"an OnlineSemanticMap is installed ({type(learned_map).__name__})"
                if learned_map is not None
                else "no learned map is installed on the mission path"
            ),
            source="perception_source.active_learned_map()",
        )
    )
    poi_enabled = getattr(bound, "poi_grounding_enabled", True)
    entries.append(
        AdmissionEntry(
            domain=DOMAIN_CAPABILITY,
            name=CAPABILITY_POI_ORACLE_DISABLED,
            admitted=not poi_enabled,
            reason=(
                "the demo_pois.yaml POI arm is empty, so a mission cannot succeed "
                "through a lookup table"
                if not poi_enabled
                else "the demo_pois.yaml POI arm is armed (the shipped oracle default)"
            ),
            source="perception_source.SemanticSourcePolicy.poi_grounding_enabled",
        )
    )

    health: Mapping[str, Any] | None = None
    if probe_imports or "parcel_robot.navigation.pipeline" in sys.modules:
        try:
            from parcel_robot.navigation.pipeline import soft_import_health

            health = soft_import_health()
        except ImportError:  # pragma: no cover - frozen bundle path
            health = None
    for name in _SOFT_IMPORT_CAPABILITIES:
        if health is None:
            entries.append(
                AdmissionEntry(
                    domain=DOMAIN_CAPABILITY,
                    name=name,
                    admitted=False,
                    reason=(
                        "not probed: navigation.pipeline is not imported in this "
                        "process and no profile required this capability"
                    ),
                    source="navigation.pipeline.soft_import_health()",
                )
            )
            continue
        ok = bool(health.get(name))
        error = health.get(f"{name}_error")
        entries.append(
            AdmissionEntry(
                domain=DOMAIN_CAPABILITY,
                name=name,
                admitted=ok,
                reason=(
                    f"navigation.pipeline imported {name} successfully"
                    if ok
                    else f"navigation.pipeline could not import {name}: {error}"
                ),
                source="navigation.pipeline.soft_import_health()",
            )
        )
    return tuple(entries)


# ======================================================================
# The view, the rendering, and the one startup check
# ======================================================================


def admitted(runtime: Any = None, *, probe_imports: bool = False) -> tuple[AdmissionEntry, ...]:
    """The whole admission table: behaviors, tools, proactive verdicts, config, capabilities.

    ``runtime`` is optional. Without one the four static domains still answer —
    which is what makes the cross-check tests cheap — and the capability rows
    report the process-global state with no configured source to compare to.
    """

    return (
        *behavior_entries(),
        *tool_entries(),
        *proactive_motion_entries(),
        *config_key_entries(),
        *capability_entries(runtime, probe_imports=probe_imports),
    )


def render_table(entries: Iterable[AdmissionEntry]) -> str:
    """The table as text, for a startup refusal and for a log line."""

    rows = list(entries)
    if not rows:
        return "(admission table is empty)"
    width_domain = max(len(row.domain) for row in rows)
    width_name = max(len(row.name) for row in rows)
    lines = []
    for row in rows:
        mark = "ok  " if row.admitted else "NO  "
        lines.append(
            f"  {mark}{row.domain:<{width_domain}}  {row.name:<{width_name}}  {row.reason}"
        )
    return "\n".join(lines)


def admission_snapshot(runtime: Any = None) -> dict[str, object]:
    """What ``/api/state`` publishes: the table, plus what is required and unmet.

    An operator asking "why can't it do that" gets the reason from the panel
    instead of from a log they would have to know to look for.
    """

    entries = admitted(runtime)
    try:
        required = required_capabilities(navigation_config_mapping(runtime))
        declaration_error = None
    except CapabilityRefused as error:
        required, declaration_error = (), str(error)
    states = {row.name: row.admitted for row in entries if row.domain == DOMAIN_CAPABILITY}
    unreadable = [
        *broker_scan().unreadable,
        *config_section_scan(_PRODUCT_CONFIG_SOURCES).unreadable,
    ]
    return {
        "entries": [row.as_dict() for row in entries],
        "refused": [row.as_dict() for row in entries if not row.admitted],
        # "I could not read this door call" is a different answer from "there is
        # nothing here", and the panel says which. Non-empty means the table
        # below is incomplete and the guards say so at test time.
        "unreadable": [site.as_dict() for site in unreadable],
        "required_capabilities": list(required),
        "unmet_capabilities": [name for name in required if not states.get(name, False)],
        "declaration_error": declaration_error,
        "registered_capabilities": list(REGISTERED_CAPABILITIES),
    }


def check_required_capabilities(runtime: Any) -> None:
    """Startup-fatal admission of the capabilities a profile DECLARED it needs.

    IG-3, narrowed to the concrete defect. Nothing is required by default, so
    this is a no-op for every profile in the tree today: the cost of the check
    is one YAML read that has already happened.

    When a profile does declare, the failure is loud at the door and names both
    halves — what was required and what the process actually bound — with the
    whole table attached, because the class of bug this closes is precisely the
    one where the run looked fine and read a different map than the file said.
    """

    required = required_capabilities(navigation_config_mapping(runtime))
    if not required:
        return
    entries = capability_entries(runtime, probe_imports=True)
    by_name = {row.name: row for row in entries}
    unmet = [name for name in required if not by_name[name].admitted]
    if not unmet:
        return
    detail = "\n".join(f"    - {name}: {by_name[name].reason}" for name in unmet)
    raise CapabilityRefused(
        "the navigation profile declares required capabilities this process did "
        f"not bind: {', '.join(unmet)}\n{detail}\n\n"
        "  admission table:\n" + render_table(admitted(runtime, probe_imports=True))
    )
