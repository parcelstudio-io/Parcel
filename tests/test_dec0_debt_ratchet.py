"""DEC-0 debt ratchet — structural debt may shrink, never grow.

The decomposition program (scrum/20260823/DECOMP_PROGRAM_FABLE.md) splits
god-objects over many cards.  This module is the guard rail that keeps the
program honest between cards: it measures four structural-debt quantities
over the product tree and fails ONLY when a quantity regresses past the
baseline frozen below.  Improvement never fails; the baseline is simply
re-frozen (downward) when a card banks a win.

The four measurements, and why each is keyed the way it is:

1.  Oversized modules (> 1,000 physical lines), keyed by REPO-RELATIVE PATH.
    A new path above the ceiling is new debt.  An existing offender that
    grows is not flagged — the ceiling is a ceiling on *count of offenders*,
    not a per-file budget, because wave cards legitimately churn inside the
    files they are about to split.  M6 sets 600 lines as the target for NEW
    modules; 1,000 is the hard ceiling this ratchet enforces.

2.  Long functions (> 100 physical lines), keyed by LEAF FUNCTION NAME.
    Deliberately NOT keyed by module or qualname: the program's M5 rule
    moves long methods out of god-classes and often demotes
    ``RobotRuntime.foo`` to a module-level ``foo`` in a new module.  Keying
    by leaf name lets debt MOVE without reddening while still catching debt
    that is CREATED.  Leaf-name keying can collide across modules, so a
    per-name and total occurrence counts are asserted alongside the name set.

3.  Import cycles over the intra-package graph, measured two ways:
    ``with_package_edges`` models real Python semantics (importing
    ``pkg.mod`` executes ``pkg/__init__.py`` first), which is how the
    re-exporting barrels manufacture one large multi-domain SCC;
    ``leaf_only`` bypasses the barrels and shows the true module-to-module
    cycles.  DEC-IG-1/IG-2 drive the first number down by thinning barrels;
    both are ratcheted by SCC membership as well as count/size so neither can
    silently grow or be swapped for an equally sized new cycle.

4.  ``# ---- CARD`` region markers in product source.  M7 requires the net
    marker count to fall as marked regions dissolve into owned modules, so
    the total may never rise.

The measurement is pure AST/text over the tree.  This module imports NO
product code, so it cannot be perturbed by import-time side effects in the
very files it is measuring.
"""

from __future__ import annotations

import ast
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Directories measured by the ratchet: the product package plus the shipped
#: script/tool surface (``scripts/ci_gate.py`` is itself a decomposition
#: target).  ``tests/`` is deliberately out of scope — test bulk is not the
#: debt this program is retiring.
SCOPED_DIRS = ("src/parcel_robot", "scripts", "tools")

MODULE_LINE_CEILING = 1000
FUNCTION_LINE_CEILING = 100
CARD_MARKER = "# ---- CARD"

#: The package whose intra-package import graph is measured for cycles.
GRAPH_PACKAGE = "parcel_robot"
GRAPH_ROOT = "src"


# --------------------------------------------------------------------------
# frozen baseline — measured at DEC-0 authorship (2026-08-23, HEAD 92245a1) and
# RE-FROZEN DOWNWARD by DEC-IG-2 (scrum/20260823/task_16): barrel thinning took
# the package-edge model from 25 cycles / max SCC 81 to 8 / 5 and the leaf-only
# model from 8 / 4 to 4 / 4.  Regenerate from the repo root with:
#     .parcel/bin/python -c "import sys; sys.path.insert(0, 'tests'); \
#         import test_dec0_debt_ratchet as t; t.print_measured_baseline()"
# then paste the output over this dict and re-run `ruff format`.  Only ever
# commit a baseline that is <= the previous one; a card that raises a number
# is a card that added debt, and it needs the reviewer to say so out loud.
# --------------------------------------------------------------------------
BASELINE: dict[str, object] = {
    "oversized_modules": frozenset(
        [
            "scripts/ci_gate.py",
            "scripts/parcel_capture/attest.py",
            "scripts/parcel_capture/budget.py",
            "scripts/parcel_capture/clockmap.py",
            "scripts/parcel_capture/orin_rehearsal.py",
            "scripts/parcel_capture/preflight.py",
            "scripts/parcel_capture/record.py",
            "scripts/parcel_capture/rehearse.py",
            "scripts/parcel_capture/rosbag2.py",
            "scripts/parcel_capture/sidecar.py",
            "scripts/parcel_capture/stage0_addendum.py",
            "scripts/parcel_capture/syncevents.py",
            "src/parcel_robot/admission.py",
            "src/parcel_robot/agent.py",
            "src/parcel_robot/authority.py",
            "src/parcel_robot/backends/go2.py",
            "src/parcel_robot/brain/contracts.py",
            "src/parcel_robot/brain/validator.py",
            "src/parcel_robot/camera_channel/ingress.py",
            "src/parcel_robot/capture/channels.py",
            "src/parcel_robot/contracts/v1.py",
            "src/parcel_robot/control/manager.py",
            "src/parcel_robot/headless_city.py",
            "src/parcel_robot/instructnav/scoring.py",
            "src/parcel_robot/memory.py",
            "src/parcel_robot/navigation/approach.py",
            "src/parcel_robot/navigation/follow.py",
            "src/parcel_robot/navigation/grid_navigator.py",
            "src/parcel_robot/navigation/grid_planner.py",
            "src/parcel_robot/navigation/pipeline.py",
            "src/parcel_robot/online_map/online_map.py",
            "src/parcel_robot/perception_abstention.py",
            "src/parcel_robot/pose.py",
            "src/parcel_robot/providers.py",
            "src/parcel_robot/realtime/audio_gateway.py",
            "src/parcel_robot/realtime/config.py",
            "src/parcel_robot/realtime/lane.py",
            "src/parcel_robot/realtime/tool_broker.py",
            "src/parcel_robot/realtime/voice_identity.py",
            "src/parcel_robot/realtime/whisperer.py",
            "src/parcel_robot/runtime.py",
            "src/parcel_robot/web_panel.py",
            "tools/bargein_through_air.py",
            "tools/run_voice_corpus.py",
            "tools/xvf3800_probe.py",
        ]
    ),
    "long_function_names": frozenset(
        [
            "__init__",
            "__post_init__",
            "_abstention_filtered",
            "_accept_plan",
            "_apply_closed_intent",
            "_assess",
            "_assess_point_cloud",
            "_assess_power",
            "_attach_configured_camera_ingress",
            "_build_read_only_handle",
            "_build_realtime_sink",
            "_commit_semantic_candidate",
            "_control_loop_body",
            "_detect_and_localize",
            "_dispatch_active",
            "_evaluate_dispatch_input_health",
            "_execute",
            "_fit_segment",
            "_handle_text",
            "_hosted_affect",
            "_inject_tail",
            "_navigate_to",
            "_observed_goal_or_frontier_path",
            "_on_function_call",
            "_pace_watch",
            "_plausibility_findings",
            "_realtime_navigate",
            "_remember_fact",
            "_resolve_barge_in_hold",
            "_result_for",
            "_run_navigation",
            "_run_output",
            "_safe_valley_command",
            "_select_safe_valley",
            "_semantic_arrival_verified",
            "_start_navigation_locked",
            "_step_activities",
            "_step_behind",
            "_step_navigation",
            "_step_roam",
            "_step_scan_behavior",
            "_step_search_entity_frontier",
            "_step_semantic_resolution",
            "_t10_section",
            "_t7_section",
            "_t8_section",
            "_t9_section",
            "_tick_once",
            "_try_detection_lock_on",
            "_venue1_attach_physical_ingress",
            "_venue1_reconcile_map_origin",
            "_voice_stage",
            "act",
            "analyze_pcm16",
            "apply_reactive_safety",
            "apply_v8_all_ray_shield",
            "assess_go_record",
            "assess_place_query",
            "audit_reasoner_gpu_readiness",
            "build",
            "build_observation_snapshot",
            "build_report",
            "build_rosbag2_sidecar",
            "build_scorecard",
            "build_sidecar",
            "build_sync_fit",
            "build_tool_specs",
            "build_unitree_sport_commissioning_session",
            "camera_stream_snapshot",
            "capability_entries",
            "classify",
            "close",
            "decide_realtime_arming",
            "decode_low_state",
            "default",
            "detect_audio_devices",
            "detect_ritual_step",
            "do_POST",
            "estimate_pair_offset",
            "evaluate",
            "evaluate_hard_safety",
            "evaluate_pose_drift_arms",
            "evaluate_unitree_assets",
            "execute",
            "from_config",
            "fuse",
            "host_capabilities",
            "imu_cross_check",
            "localize_detection",
            "main",
            "match_trains",
            "narrate_event",
            "observe",
            "plan",
            "probe_builtin_lidar",
            "probe_channel",
            "probe_jetpack",
            "probe_mid360_udp",
            "probe_network",
            "propose_yield_aside",
            "rank_approach_candidates",
            "read_mcap",
            "read_rosbag2_mcap",
            "recall",
            "record_take",
            "render_addendum",
            "render_combined_index",
            "render_document",
            "render_runbook",
            "replay",
            "resample_inside_region",
            "route",
            "run_naming_pass",
            "run_p0_identity",
            "run_p1_environment",
            "run_p3_network",
            "run_p4_sensors",
            "run_p5_recorder",
            "run_simulator",
            "safe_approach_pose",
            "scene_report",
            "score",
            "score_episode",
            "score_episode_with_oracle",
            "score_interrupt_latency",
            "semantic_goal_from_directive",
            "sense_from_snapshot",
            "serve_websocket",
            "snapshot",
            "start",
            "static_loads",
            "step",
            "submit_realtime_transcript",
            "submit_voice_text",
            "synthesize_lowstate_ritual",
            "tick",
            "tool_definitions",
            "verify_scorecard",
            "write_fixture_bag",
            "write_realtime_turn",
        ]
    ),
    "long_function_count": 153,
    "long_function_duplicate_counts": {
        "__init__": 7,
        "act": 2,
        "close": 2,
        "main": 3,
        "observe": 2,
        "snapshot": 2,
        "start": 2,
    },
    "cycles_with_package_edges": 8,
    "max_scc_with_package_edges": 5,
    "cycles_leaf_only": 4,
    "max_scc_leaf_only": 4,
    "card_markers": 176,
    "scoped_files": 364,
}

#: Frozen SCC membership, not merely aggregate counts.  A current SCC may be
#: a subset of one baseline SCC (a tangle split into smaller tangles), but it
#: may not contain modules from different baseline SCCs or a newly-cyclic
#: module.  That catches a same-size cycle replacing an old one, which the
#: count/max ratchet alone cannot see.
BASELINE_CYCLE_COMPONENTS: dict[str, tuple[frozenset[str], ...]] = {
    "with_package_edges": (
        frozenset(
            [
                "parcel_robot.route_memory",
                "parcel_robot.route_memory.place_graph",
                "parcel_robot.route_memory.proposer",
                "parcel_robot.route_memory.runtime_hook",
                "parcel_robot.route_memory.teach_repeat",
            ]
        ),
        frozenset(
            [
                "parcel_robot.camera_channel.backends.physical",
                "parcel_robot.camera_channel.backends.realsense",
                "parcel_robot.camera_channel.backends.recorded",
                "parcel_robot.camera_channel.backends.uvc",
            ]
        ),
        frozenset(
            [
                "parcel_robot.perception_abstention",
                "parcel_robot.vlm_veto.bureau",
                "parcel_robot.vlm_veto.runner",
                "parcel_robot.vlm_veto.verifier",
            ]
        ),
        frozenset(
            [
                "parcel_robot.storefront",
                "parcel_robot.storefront.fixtures",
                "parcel_robot.storefront.ingest",
                "parcel_robot.storefront.ocr",
            ]
        ),
        frozenset(
            [
                "parcel_robot.uwb",
                "parcel_robot.uwb.fusion",
                "parcel_robot.uwb.injector",
                "parcel_robot.uwb.model",
            ]
        ),
        frozenset(
            [
                "parcel_robot.maps",
                "parcel_robot.maps.crossing",
                "parcel_robot.maps.waypoints",
            ]
        ),
        frozenset(
            [
                "parcel_robot.navigation.arrival_semantics",
                "parcel_robot.navigation.goals",
            ]
        ),
        frozenset(
            [
                "parcel_robot.navigation.grid_navigator",
                "parcel_robot.navigation.models",
            ]
        ),
    ),
    "leaf_only": (
        frozenset(
            [
                "parcel_robot.camera_channel.backends.physical",
                "parcel_robot.camera_channel.backends.realsense",
                "parcel_robot.camera_channel.backends.recorded",
                "parcel_robot.camera_channel.backends.uvc",
            ]
        ),
        frozenset(
            [
                "parcel_robot.perception_abstention",
                "parcel_robot.vlm_veto.bureau",
                "parcel_robot.vlm_veto.runner",
                "parcel_robot.vlm_veto.verifier",
            ]
        ),
        frozenset(
            [
                "parcel_robot.navigation.arrival_semantics",
                "parcel_robot.navigation.goals",
            ]
        ),
        frozenset(
            [
                "parcel_robot.navigation.grid_navigator",
                "parcel_robot.navigation.models",
            ]
        ),
    ),
}


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------
def _scoped_files() -> list[Path]:
    """Every measured .py file, sorted, with build/cache noise excluded."""
    out: list[Path] = []
    for rel in SCOPED_DIRS:
        base = REPO / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            parts = set(path.parts)
            if "__pycache__" in parts or ".parcel" in parts:
                continue
            out.append(path)
    return sorted(out)


@lru_cache(maxsize=1)
def _parsed() -> tuple[tuple[str, str, ast.Module], ...]:
    """(relative path, source, parsed module) for every scoped file."""
    rows: list[tuple[str, str, ast.Module]] = []
    for path in _scoped_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # A syntactically broken product file is a different test's
            # problem; the ratchet measures what it can parse.
            continue
        rows.append((path.relative_to(REPO).as_posix(), source, tree))
    return tuple(rows)


def measure_oversized_modules() -> frozenset[str]:
    """Repo-relative paths of modules above the line ceiling."""
    return frozenset(
        rel for rel, source, _ in _parsed() if len(source.splitlines()) > MODULE_LINE_CEILING
    )


def _function_lengths() -> list[tuple[str, str, int]]:
    """(relative path, leaf function name, physical line span) per function."""
    out: list[tuple[str, str, int]] = []
    for rel, _, tree in _parsed():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = getattr(node, "end_lineno", None)
            if end is None:
                continue
            out.append((rel, node.name, end - node.lineno + 1))
    return out


def measure_long_functions() -> tuple[frozenset[str], int]:
    """(leaf names above the ceiling, total occurrences above the ceiling)."""
    hits = [row for row in _function_lengths() if row[2] > FUNCTION_LINE_CEILING]
    return frozenset(name for _, name, _ in hits), len(hits)


def measure_long_function_duplicate_counts() -> dict[str, int]:
    """Occurrence counts for leaf names with more than one long function."""
    counts = Counter(
        name for _, name, length in _function_lengths() if length > FUNCTION_LINE_CEILING
    )
    return {name: count for name, count in sorted(counts.items()) if count > 1}


def _module_name(rel: str) -> str | None:
    """Dotted module name for a repo-relative path inside the graph package."""
    prefix = f"{GRAPH_ROOT}/"
    if not rel.startswith(prefix):
        return None
    dotted = rel[len(prefix) :].removesuffix(".py")
    parts = dotted.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or parts[0] != GRAPH_PACKAGE:
        return None
    return ".".join(parts)


def _resolve_relative(
    current: str, is_pkg_init: bool, level: int, module: str | None
) -> str | None:
    """Resolve a relative ``from .x import y`` to an absolute module name."""
    parts = current.split(".")
    base = parts if is_pkg_init else parts[:-1]
    if level > 1:
        drop = level - 1
        if drop > len(base):
            return None
        base = base[: len(base) - drop]
    if not base:
        return None
    return ".".join([*base, module]) if module else ".".join(base)


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for ``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` guard tests."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _type_checking_import_ids(tree: ast.Module) -> frozenset[int]:
    """Ids of import nodes nested under an ``if TYPE_CHECKING:`` body.

    Such imports never execute, so they cannot create a real import cycle
    (DEC-IG-2's one authorised measurement refinement).  Only the guard's
    ``body`` is skipped — an ``else:`` branch runs at import time and keeps
    its edges.
    """
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_type_checking_test(node.test):
            continue
        for guarded in node.body:
            for inner in ast.walk(guarded):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    skipped.add(id(inner))
    return frozenset(skipped)


def build_import_graph(*, include_package_edges: bool) -> dict[str, set[str]]:
    """Intra-package import edges.

    ``include_package_edges`` models Python's real behaviour — importing
    ``pkg.mod`` first executes ``pkg/__init__.py`` — which is the mechanism
    by which re-exporting barrels manufacture large multi-domain cycles.
    With it off, only direct module-to-module edges are kept, exposing the
    true cycles that survive barrel bypass.

    Imports nested under ``if TYPE_CHECKING:`` are excluded from BOTH models:
    they never execute, so they are annotations, not import-time edges.
    """
    known: dict[str, str] = {}
    for rel, _, _ in _parsed():
        name = _module_name(rel)
        if name is not None:
            known[name] = rel
    graph: dict[str, set[str]] = {name: set() for name in known}

    def add(src: str, dst: str | None) -> None:
        if dst is None or dst == src:
            return
        if dst in graph:
            graph[src].add(dst)
            return
        # `from pkg import name` where `name` is a module -> edge to the
        # module; otherwise the import lands on the package itself.
        parent = dst.rsplit(".", 1)[0] if "." in dst else None
        if parent and parent in graph and parent != src:
            graph[src].add(parent)

    def add_package_chain(src: str, dst: str) -> None:
        """Every ancestor package of `dst` is executed on import."""
        parts = dst.split(".")
        for i in range(1, len(parts)):
            ancestor = ".".join(parts[:i])
            if ancestor in graph and ancestor != src:
                graph[src].add(ancestor)

    for rel, _, tree in _parsed():
        src = _module_name(rel)
        if src is None:
            continue
        is_pkg_init = rel.endswith("/__init__.py")
        type_checking_only = _type_checking_import_ids(tree)
        for node in ast.walk(tree):
            if id(node) in type_checking_only:
                continue
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = _resolve_relative(src, is_pkg_init, node.level, node.module)
                else:
                    base = node.module
                if base is None:
                    continue
                targets = [base] + [f"{base}.{a.name}" for a in node.names]
            else:
                continue
            for target in targets:
                if not target.startswith(GRAPH_PACKAGE):
                    continue
                add(src, target)
                if include_package_edges:
                    add_package_chain(src, target)
    return graph


def strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's SCC, iterative — the graph is wide and recursion is banned."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                index[node] = counter
                low[node] = counter
                counter += 1
                stack.append(node)
                on_stack[node] = True
            children = sorted(graph[node])
            if child_i < len(children):
                work[-1] = (node, child_i + 1)
                child = children[child_i]
                if child not in index:
                    work.append((child, 0))
                elif on_stack.get(child):
                    low[node] = min(low[node], index[child])
            else:
                if low[node] == index[node]:
                    component: list[str] = []
                    while True:
                        popped = stack.pop()
                        on_stack[popped] = False
                        component.append(popped)
                        if popped == node:
                            break
                    result.append(sorted(component))
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
    return result


def measure_cycle_components(*, include_package_edges: bool) -> tuple[frozenset[str], ...]:
    """Stable identities of every non-trivial SCC in the selected graph."""
    graph = build_import_graph(include_package_edges=include_package_edges)
    components = [frozenset(c) for c in strongly_connected_components(graph) if len(c) > 1]
    # A module importing itself is not a cycle worth ratcheting.
    return tuple(sorted(components, key=lambda c: (-len(c), sorted(c))))


def measure_cycles(*, include_package_edges: bool) -> tuple[int, int]:
    """(number of non-trivial SCCs, size of the largest one)."""
    components = measure_cycle_components(include_package_edges=include_package_edges)
    largest = max((len(c) for c in components), default=0)
    return len(components), largest


def measure_card_markers() -> int:
    """Total ``# ---- CARD`` region markers across the measured tree."""
    return sum(source.count(CARD_MARKER) for _, source, _ in _parsed())


def measure_all() -> dict[str, object]:
    """Every ratcheted quantity, measured on the current tree."""
    long_names, long_count = measure_long_functions()
    pkg_cycles, pkg_max = measure_cycles(include_package_edges=True)
    leaf_cycles, leaf_max = measure_cycles(include_package_edges=False)
    return {
        "oversized_modules": measure_oversized_modules(),
        "long_function_names": long_names,
        "long_function_count": long_count,
        "long_function_duplicate_counts": measure_long_function_duplicate_counts(),
        "cycles_with_package_edges": pkg_cycles,
        "max_scc_with_package_edges": pkg_max,
        "cycles_leaf_only": leaf_cycles,
        "max_scc_leaf_only": leaf_max,
        "card_markers": measure_card_markers(),
        "scoped_files": len(_parsed()),
    }


def print_measured_baseline() -> None:
    """Print a BASELINE dict literal for today's tree (maintenance helper)."""
    measured = measure_all()
    print("BASELINE: dict[str, object] = {")
    for key in BASELINE:
        value = measured[key]
        if isinstance(value, frozenset):
            print(f"    {key!r}: frozenset({sorted(value)!r}),")
        else:
            print(f"    {key!r}: {value!r},")
    print("}")


# --------------------------------------------------------------------------
# the ratchet
# --------------------------------------------------------------------------
def test_scope_is_sane() -> None:
    """The measured file set is the product tree, not the virtualenv."""
    files = _parsed()
    assert 200 <= len(files) <= 600, (
        f"scoped file count {len(files)} outside the sane band — the ratchet "
        "is probably scanning a virtualenv or missing the product package"
    )
    assert any(rel == "src/parcel_robot/runtime.py" for rel, _, _ in files)
    assert any(rel == "scripts/ci_gate.py" for rel, _, _ in files)
    assert len(_function_lengths()) > 1_000, "function scan collapsed"
    for include in (True, False):
        graph = build_import_graph(include_package_edges=include)
        assert len(graph) > 200, "import graph lost most product modules"
        assert sum(map(len, graph.values())) > 500, "import-edge scan collapsed"


def test_measurement_is_fast() -> None:
    """The whole scan stays cheap enough to sit in the commit tier."""
    _parsed.cache_clear()
    start = time.perf_counter()
    measure_all()
    elapsed = time.perf_counter() - start
    assert elapsed < 30.0, (
        f"debt-ratchet scan took {elapsed:.1f}s; it is AST-only and must stay "
        "fast enough for the commit tier (target < 10s on an idle host)"
    )


def test_no_new_oversized_module() -> None:
    """No module above 1,000 lines that was not already above it."""
    baseline = BASELINE["oversized_modules"]
    assert isinstance(baseline, frozenset)
    current = measure_oversized_modules()
    added = sorted(current - baseline)
    assert not added, (
        f"new module(s) above {MODULE_LINE_CEILING} lines: {added}. "
        "M6 targets <=600 lines for new modules. Split the module, or — if "
        "this is a deliberate, reviewed exception — add it to BASELINE with "
        "the card that justifies it."
    )


def test_no_new_long_function() -> None:
    """No newly-named function above 100 lines, and no net growth in count."""
    baseline_names = BASELINE["long_function_names"]
    assert isinstance(baseline_names, frozenset)
    names, count = measure_long_functions()
    added = sorted(names - baseline_names)
    assert not added, (
        f"new function(s) above {FUNCTION_LINE_CEILING} lines: {added}. "
        "Long functions may MOVE between modules without reddening this "
        "ratchet (it keys on leaf name), so a hit here is genuinely new bulk."
    )
    baseline_count = BASELINE["long_function_count"]
    assert isinstance(baseline_count, int)
    assert count <= baseline_count, (
        f"count of functions above {FUNCTION_LINE_CEILING} lines rose from "
        f"{baseline_count} to {count} — new long functions reusing an "
        "existing offender's name still count as new debt."
    )
    baseline_duplicates = BASELINE["long_function_duplicate_counts"]
    assert isinstance(baseline_duplicates, dict)
    current_counts = Counter(
        name for _, name, length in _function_lengths() if length > FUNCTION_LINE_CEILING
    )
    excess = {
        name: occurrences
        for name, occurrences in current_counts.items()
        if occurrences > baseline_duplicates.get(name, 1 if name in baseline_names else 0)
    }
    assert not excess, (
        f"per-name count of long functions increased: {excess}. Moving a long "
        "function preserves its leaf-name count; adding another same-named "
        "offender is new debt."
    )


def test_no_new_import_cycle() -> None:
    """Neither cycle model may gain, widen, or replace a cycle."""
    for label, include in (("with_package_edges", True), ("leaf_only", False)):
        components = measure_cycle_components(include_package_edges=include)
        cycles, largest = measure_cycles(include_package_edges=include)
        base_cycles = BASELINE[f"cycles_{label}"]
        base_max = BASELINE[f"max_scc_{label}"]
        baseline_components = BASELINE_CYCLE_COMPONENTS[label]
        assert isinstance(base_cycles, int)
        assert isinstance(base_max, int)
        novel = [
            sorted(component)
            for component in components
            if not any(component <= baseline for baseline in baseline_components)
        ]
        assert not novel, (
            f"new import-cycle membership ({label}): {novel}. A current SCC "
            "must remain inside one frozen baseline SCC; splitting an old "
            "tangle is allowed, replacing it with a same-sized tangle is not."
        )
        assert cycles <= base_cycles, (
            f"import cycles ({label}) rose from {base_cycles} to {cycles}. "
            "Import direction must stay acyclic-or-better; see M1."
        )
        assert largest <= base_max, (
            f"largest import cycle ({label}) grew from {base_max} to "
            f"{largest} modules. A wider SCC means a new module joined an "
            "existing tangle."
        )


def test_no_new_card_markers() -> None:
    """M7: marked regions dissolve into owned modules; the count only falls."""
    baseline = BASELINE["card_markers"]
    assert isinstance(baseline, int)
    current = measure_card_markers()
    assert current <= baseline, (
        f"{CARD_MARKER!r} marker count rose from {baseline} to {current}. "
        "Extraction dissolves markers (M7) — the module docstring carries the "
        "invariant and the history lives in scrum/, not in a new marked region."
    )


def test_baseline_is_reachable() -> None:
    """The baseline names real files — a stale path would silence the ratchet."""
    baseline = BASELINE["oversized_modules"]
    assert isinstance(baseline, frozenset)
    missing = sorted(rel for rel in baseline if not (REPO / rel).exists())
    assert not missing, (
        f"baseline lists module(s) that no longer exist: {missing}. Remove "
        "them from BASELINE — a stale entry is a hole in the ratchet."
    )
    graph_modules = set(build_import_graph(include_package_edges=True))
    for label, components in BASELINE_CYCLE_COMPONENTS.items():
        listed = set().union(*components)
        missing_modules = sorted(listed - graph_modules)
        assert not missing_modules, (
            f"{label} SCC baseline names missing module(s): {missing_modules}. "
            "Re-freeze the membership baseline downward after a move."
        )
        expected_count = BASELINE[f"cycles_{label}"]
        expected_max = BASELINE[f"max_scc_{label}"]
        assert len(components) == expected_count
        assert max(map(len, components), default=0) == expected_max


def test_per_file_debt_report() -> None:
    """Always-green report: the numbers a DEC status doc must quote (M9)."""
    measured = measure_all()
    oversized = measured["oversized_modules"]
    assert isinstance(oversized, frozenset)
    by_dir: dict[str, int] = defaultdict(int)
    for rel in oversized:
        by_dir[rel.split("/")[0]] += 1
    print("\nDEC debt snapshot")
    print(f"  scoped files            {measured['scoped_files']}")
    print(f"  modules >{MODULE_LINE_CEILING} lines      {len(oversized)} {dict(by_dir)}")
    print(f"  functions >{FUNCTION_LINE_CEILING} lines    {measured['long_function_count']}")
    print(
        f"  cycles (pkg edges)      {measured['cycles_with_package_edges']}"
        f" (largest {measured['max_scc_with_package_edges']})"
    )
    print(
        f"  cycles (leaf only)      {measured['cycles_leaf_only']}"
        f" (largest {measured['max_scc_leaf_only']})"
    )
    print(f"  {CARD_MARKER!r} markers  {measured['card_markers']}")
