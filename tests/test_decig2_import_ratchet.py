"""DEC-IG-2 — the import ratchet: barrels stay drained, cycles stay named.

Supersedes ``tests/test_decig1_leaf_imports.py`` (deleted): that module pinned
step 1 for one barrel and step 2 for eight symbols; this one pins both steps
for **every** package in ``src/parcel_robot`` and adds the two structural
guards the program's M1 asks for — a named cycle inventory and the ARCH-1
forbidden reverse edges.

Four properties, in the order a reader needs them:

1.  **No module reaches a SYMBOL through a package barrel.**  ``from
    parcel_robot.navigation import pipeline`` is a submodule import and is
    fine; ``from parcel_robot.navigation import DirectiveNavigator`` reaches a
    name the ``__init__`` had to import from somewhere else, and is not.  The
    check does not ask what a barrel re-exports today — it asks whether the
    imported name is a submodule or is *defined in the ``__init__`` itself*, so
    it stays honest even if a barrel is re-filled.

2.  **No ``__init__.py`` under ``src/parcel_robot`` re-exports.**  An import in
    a package ``__init__`` is legitimate only when the ``__init__``'s own code
    uses the name; anything else is a re-export, and a re-export is what
    manufactures the cross-package cycles (DEC-0 measured max SCC 81 with the
    barrels in place and 4 without them).  ``BARRELS_WITH_KEPT_IMPORTS`` is the
    explicit allowlist, one reason per entry.

3.  **Import cycles equal a named grandfather list.**  Every surviving SCC is
    listed with the reason it survives.  A component may SPLIT (that is
    progress); it may not grow, gain a member, or be swapped for a new tangle.

4.  **The ARCH-1 forbidden reverse edges hold.**  Contracts/config never reach
    the runtime, the UI or a vendor backend; domain packages never reach the
    runtime or the UI; the physical adapters never reach sim truth; nothing in
    ``src`` imports ``web_panel``.  All four held when this ratchet landed, so
    every grandfather list here is empty — a violation is a real regression.

Like ``tests/test_dec0_debt_ratchet.py`` this module imports NO product code:
every measurement is pure AST over a ``{repo-relative path: source}`` mapping.
That mapping is also what makes the seeded-failure cells cheap and honest —
each one re-runs the real measurement over the real tree plus one mutant file,
so a check that has gone vacuous cannot hide.
"""

from __future__ import annotations

import ast
import sys
import time
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Trees whose imports are ratcheted.  ``tests/`` and ``evals/`` are IN scope
#: (unlike the DEC-0 debt ratchet): a barrel re-export with only test or
#: eval-runner callers is still a live re-export, and DEC-IG-2's own worklist
#: was 124 test files, 20 scripts and 8 eval runners.  ``scrum/`` is sprint
#: history and is deliberately out of scope.
SCAN_DIRS = ("src", "tests", "scripts", "tools", "examples", "evals")
SKIP_PARTS = {".parcel", "build", "tmp_ci", "third_party", "node_modules", ".git", "__pycache__"}

PACKAGE = "parcel_robot"
SRC_PREFIX = "src/"

#: The only ``src/parcel_robot/**/__init__.py`` files that may import anything
#: from the package at all, and why.  Each one *defines* module-level code that
#: consumes the import; none of them re-export.  A package not listed here must
#: be import-free: docstring, and nothing else.
BARRELS_WITH_KEPT_IMPORTS: dict[str, str] = {
    "parcel_robot.maps": (
        "composes the package-level DOES_NOT_PROVE tuple from its four leaves' "
        "own tuples; tests/test_p3_city_layer.py reads it from the package"
    ),
    "parcel_robot.navigation.models": (
        "not a barrel — a 412-line module that DEFINES StubNavigator and the "
        "build_navigator factory, and imports the types they use"
    ),
    "parcel_robot.route_memory": (
        "composes the package-level DOES_NOT_PROVE tuple from its eight "
        "leaves' own tuples; tests/test_p4_route_memory.py reads it"
    ),
    "parcel_robot.storefront": (
        "composes the package-level DOES_NOT_PROVE tuple from fixtures/ingest "
        "plus the ocr UNVERIFIED note; tests/test_p3_storefront_ocr.py reads it"
    ),
    "parcel_robot.uwb": (
        "composes the package-level DOES_NOT_PROVE tuple from fusion/injector; "
        "tests/test_p2_uwb_noise.py reads it"
    ),
}

#: Every surviving import cycle, with the reason it is still here.  Measured on
#: the DEC-IG-2 tree.  The package-edge model charges every ancestor package of
#: an imported module (real Python semantics), so a package whose ``__init__``
#: imports its own leaf is a cycle in that model and not in the leaf-only one.
GRANDFATHERED_CYCLES: dict[str, tuple[tuple[frozenset[str], str], ...]] = {
    "with_package_edges": (
        (
            frozenset(
                {
                    "parcel_robot.route_memory",
                    "parcel_robot.route_memory.place_graph",
                    "parcel_robot.route_memory.proposer",
                    "parcel_robot.route_memory.runtime_hook",
                    "parcel_robot.route_memory.teach_repeat",
                }
            ),
            (
                "package __init__ composes DOES_NOT_PROVE from its leaves (see the "
                "allowlist above); the leaves themselves are acyclic"
            ),
        ),
        (
            frozenset(
                {
                    "parcel_robot.camera_channel.backends.physical",
                    "parcel_robot.camera_channel.backends.realsense",
                    "parcel_robot.camera_channel.backends.recorded",
                    "parcel_robot.camera_channel.backends.uvc",
                }
            ),
            (
                "physical.py holds BOTH the shared base classes and the "
                "build_physical_backend factory whose per-kind lazy imports point "
                "back at the three concrete backends; breaking it is a code MOVE "
                "(factory -> backends/factory.py), not an import rewrite"
            ),
        ),
        (
            frozenset(
                {
                    "parcel_robot.perception.abstention",
                    "parcel_robot.vlm_veto.bureau",
                    "parcel_robot.vlm_veto.runner",
                    "parcel_robot.vlm_veto.verifier",
                }
            ),
            (
                "deliberate and pinned: the abstention vocabulary is declared in "
                "perception_abstention so the runtime can import it without "
                "importing a package that can import torch "
                "(tests/test_p1d_vlm_veto.py::test_the_runtime_imports_no_veto_module); "
                "the reverse edge is one guarded function-local import of "
                "vlm_veto.bureau.bureau_for, which needs an M2 Protocol seam to retire"
            ),
        ),
        (
            frozenset(
                {
                    "parcel_robot.storefront",
                    "parcel_robot.storefront.fixtures",
                    "parcel_robot.storefront.ingest",
                    "parcel_robot.storefront.ocr",
                }
            ),
            "package __init__ composes DOES_NOT_PROVE from its leaves",
        ),
        (
            frozenset(
                {
                    "parcel_robot.uwb",
                    "parcel_robot.uwb.fusion",
                    "parcel_robot.uwb.injector",
                    "parcel_robot.uwb.model",
                }
            ),
            "package __init__ composes DOES_NOT_PROVE from its leaves",
        ),
        (
            frozenset(
                {
                    "parcel_robot.maps",
                    "parcel_robot.maps.crossing",
                    "parcel_robot.maps.waypoints",
                }
            ),
            "package __init__ composes DOES_NOT_PROVE from its leaves",
        ),
        (
            frozenset(
                {"parcel_robot.navigation.arrival_semantics", "parcel_robot.navigation.goals"}
            ),
            (
                "goals imports the relation table at module scope; "
                "arrival_semantics reads goals.OWNER_REFERENT_TABLE back through a "
                "documented function-local import so there is ONE authority for "
                "'the owner'. Retiring it means moving the shared table to a third "
                "leaf — a code move, not an import rewrite"
            ),
        ),
        (
            frozenset({"parcel_robot.navigation.grid_navigator", "parcel_robot.navigation.models"}),
            (
                "models/__init__.py defines StubNavigator AND the build_navigator "
                "factory, which lazily builds GridNavigator, which lazily falls "
                "back to StubNavigator — the same factory/implementation knot as "
                "the camera backends"
            ),
        ),
    ),
    "leaf_only": (
        (
            frozenset(
                {
                    "parcel_robot.camera_channel.backends.physical",
                    "parcel_robot.camera_channel.backends.realsense",
                    "parcel_robot.camera_channel.backends.recorded",
                    "parcel_robot.camera_channel.backends.uvc",
                }
            ),
            "factory and base classes share physical.py; see the package-edge entry",
        ),
        (
            frozenset(
                {
                    "parcel_robot.perception.abstention",
                    "parcel_robot.vlm_veto.bureau",
                    "parcel_robot.vlm_veto.runner",
                    "parcel_robot.vlm_veto.verifier",
                }
            ),
            "torch-free abstention vocabulary + one guarded reverse import; see above",
        ),
        (
            frozenset(
                {"parcel_robot.navigation.arrival_semantics", "parcel_robot.navigation.goals"}
            ),
            "one authority for the owner referent table; see above",
        ),
        (
            frozenset({"parcel_robot.navigation.grid_navigator", "parcel_robot.navigation.models"}),
            "navigator factory/implementation knot; see above",
        ),
    ),
}

#: ARCH-1 DESIGN's forbidden reverse edges.  ``(label, sources, targets,
#: grandfathered)``: no module under any ``sources`` root may import anything
#: under any ``targets`` root.  Every list is EMPTY because every rule already
#: held when this ratchet landed — a hit here is a new regression, never
#: pre-existing debt.
FORBIDDEN_EDGES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], frozenset[str]], ...] = (
    (
        "contracts/config never reach the runtime, the UI or a vendor backend",
        (
            "parcel_robot.contracts",
            "parcel_robot.config",
            "parcel_robot.models",
            "parcel_robot.robot_profile",
            "parcel_robot.authority",
        ),
        (
            "parcel_robot.runtime",
            "parcel_robot.web_panel",
            "parcel_robot.voice.agent",
            "parcel_robot.realtime",
            "parcel_robot.providers",
            "parcel_robot.backends",
        ),
        frozenset(),
    ),
    (
        "domain packages never reach the runtime or the UI",
        ("parcel_robot.navigation", "parcel_robot.core", "parcel_robot.brain"),
        ("parcel_robot.runtime", "parcel_robot.web_panel"),
        frozenset(),
    ),
    (
        "the physical adapters never reach sim truth",
        ("parcel_robot.backends.go2", "parcel_robot.control"),
        (
            "parcel_robot.sim",
            "parcel_robot.simulation.mujoco_lidar",
            "parcel_robot.simulation.headless_city",
            "parcel_robot.backends.mujoco",
        ),
        frozenset(),
    ),
    (
        "web_panel is the top of the graph: nothing in src imports it",
        ("parcel_robot",),
        ("parcel_robot.web_panel",),
        frozenset(),
    ),
)


# ------------------------------------------------------------------ the tree
@lru_cache(maxsize=1)
def tree_sources() -> Mapping[str, str]:
    """``{repo-relative posix path: source text}`` for every scanned file."""
    out: dict[str, str] = {}
    for directory in SCAN_DIRS:
        root = REPO / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO)
            if SKIP_PARTS & set(rel.parts):
                continue
            out[rel.as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return out


@lru_cache(maxsize=4096)
def _parse_one(text: str) -> ast.Module | None:
    """Parse one source, memoised by its text.

    The memo is what keeps the ratchet cheap: every cell below re-measures the
    whole tree, and the seeded-failure cells re-measure it plus one mutant, so
    the same ~900 sources would otherwise be parsed a dozen times over.
    """
    try:
        return ast.parse(text)
    except SyntaxError:  # pragma: no cover - a broken file is another test's problem
        return None


def _parse(sources: Mapping[str, str]) -> dict[str, ast.Module]:
    trees: dict[str, ast.Module] = {}
    for rel, text in sources.items():
        tree = _parse_one(text)
        if tree is not None:
            trees[rel] = tree
    return trees


def _dotted(rel: str) -> str | None:
    """Dotted module name for a repo-relative path under ``src/``."""
    if not rel.startswith(SRC_PREFIX):
        return None
    parts = rel[len(SRC_PREFIX) :].removesuffix(".py").split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or parts[0] != PACKAGE:
        return None
    return ".".join(parts)


def _resolve_relative(current: str, is_init: bool, level: int, module: str | None) -> str | None:
    parts = current.split(".")
    base = parts if is_init else parts[:-1]
    if level > 1:
        drop = level - 1
        if drop > len(base):
            return None
        base = base[: len(base) - drop]
    if not base:
        return None
    return ".".join([*base, module]) if module else ".".join(base)


def _module_index(sources: Mapping[str, str]) -> tuple[set[str], set[str]]:
    """(every dotted module name, the subset that are packages)."""
    modules: set[str] = set()
    packages: set[str] = set()
    for rel in sources:
        dotted = _dotted(rel)
        if dotted is None:
            continue
        modules.add(dotted)
        if rel.endswith("/__init__.py"):
            packages.add(dotted)
    return modules, packages


def _names_defined_in(tree: ast.Module) -> set[str]:
    """Module-level names a file BINDS by defining them, not by importing."""
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    return defined


# ------------------------------------------------------- 1. barrel symbols
def barrel_symbol_imports(sources: Mapping[str, str]) -> list[str]:
    """Every import that takes a SYMBOL through a package ``__init__``."""
    trees = _parse(sources)
    modules, packages = _module_index(sources)
    defined_in_init: dict[str, set[str]] = {
        dotted: _names_defined_in(trees[rel])
        for rel, dotted in ((r, _dotted(r)) for r in trees)
        if dotted is not None and rel.endswith("/__init__.py")
    }
    offenders: list[str] = []
    for rel, tree in trees.items():
        self_mod = _dotted(rel)
        is_init = rel.endswith("/__init__.py")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                if self_mod is None:
                    continue
                base = _resolve_relative(self_mod, is_init, node.level, node.module)
            else:
                base = node.module
            if base is None or base not in packages or base == self_mod:
                continue
            for alias in node.names:
                if alias.name == "*":
                    offenders.append(f"{rel}:{node.lineno}: star-import from {base}")
                    continue
                if f"{base}.{alias.name}" in modules:
                    continue  # a submodule reference, always allowed
                if alias.name in defined_in_init.get(base, set()):
                    continue  # defined IN the __init__, not re-exported through it
                offenders.append(f"{rel}:{node.lineno}: {base}.{alias.name}")
    return sorted(offenders)


# ------------------------------------------------------- 2. barrel contents
def barrel_reexports(sources: Mapping[str, str]) -> dict[str, list[str]]:
    """``{package: [name, ...]}`` for names an ``__init__`` imports but never uses."""
    trees = _parse(sources)
    out: dict[str, list[str]] = {}
    for rel, tree in trees.items():
        if not rel.startswith(SRC_PREFIX) or not rel.endswith("/__init__.py"):
            continue
        dotted = _dotted(rel)
        if dotted is None:
            continue
        bound: dict[str, ast.stmt] = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                for alias in node.names:
                    bound[alias.asname or alias.name] = node
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound[alias.asname or alias.name.split(".")[0]] = node
        if not bound:
            continue
        used: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    used.add(inner.id)
                elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    continue
        unused = sorted(name for name in bound if name not in used)
        if unused:
            out[dotted] = unused
    return out


def barrels_importing_anything(sources: Mapping[str, str]) -> set[str]:
    """Packages whose ``__init__`` imports at all (``__future__`` excepted)."""
    trees = _parse(sources)
    out: set[str] = set()
    for rel, tree in trees.items():
        if not rel.startswith(SRC_PREFIX) or not rel.endswith("/__init__.py"):
            continue
        dotted = _dotted(rel)
        if dotted is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                out.add(dotted)
                break
    return out


def all_advertises_unbound(sources: Mapping[str, str]) -> list[str]:
    """``__all__`` entries a package ``__init__`` neither defines nor imports."""
    trees = _parse(sources)
    offenders: list[str] = []
    for rel, tree in trees.items():
        if not rel.startswith(SRC_PREFIX) or not rel.endswith("/__init__.py"):
            continue
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                declared = [
                    element.value
                    for element in getattr(node.value, "elts", [])
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                ]
        if not declared:
            continue
        bound = set(_names_defined_in(tree))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                bound.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                bound.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        offenders += [f"{rel}: {name}" for name in sorted(set(declared) - bound)]
    return sorted(offenders)


# ------------------------------------------------------------- 3. the graph
@lru_cache(maxsize=4096)
def _type_checking_import_ids(tree: ast.Module) -> frozenset[int]:
    """Imports under ``if TYPE_CHECKING:`` never execute, so they are not edges."""
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        guard = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if not guard:
            continue
        for guarded in node.body:
            for inner in ast.walk(guarded):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    skipped.add(id(inner))
    return frozenset(skipped)


def import_graph(sources: Mapping[str, str], *, include_package_edges: bool) -> dict[str, set[str]]:
    """Intra-package import edges, in the two models DEC-0 ratchets."""
    trees = {rel: tree for rel, tree in _parse(sources).items() if _dotted(rel) is not None}
    graph: dict[str, set[str]] = {_dotted(rel): set() for rel in trees}  # type: ignore[misc]

    def add(src: str, dst: str | None) -> None:
        if dst is None or dst == src:
            return
        if dst in graph:
            graph[src].add(dst)
            return
        parent = dst.rsplit(".", 1)[0] if "." in dst else None
        if parent and parent in graph and parent != src:
            graph[src].add(parent)

    for rel, tree in trees.items():
        src = _dotted(rel)
        assert src is not None
        is_init = rel.endswith("/__init__.py")
        skip = _type_checking_import_ids(tree)
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = (
                    _resolve_relative(src, is_init, node.level, node.module)
                    if node.level
                    else node.module
                )
                if base is None:
                    continue
                targets = [base] + [f"{base}.{alias.name}" for alias in node.names]
            else:
                continue
            for target in targets:
                if not target.startswith(PACKAGE):
                    continue
                add(src, target)
                if include_package_edges:
                    parts = target.split(".")
                    for index in range(1, len(parts)):
                        ancestor = ".".join(parts[:index])
                        if ancestor in graph and ancestor != src:
                            graph[src].add(ancestor)
    return graph


def cycle_components(graph: dict[str, set[str]]) -> list[frozenset[str]]:
    """Tarjan's SCC, iterative — the graph is wide and recursion is banned."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    result: list[frozenset[str]] = []
    counter = 0
    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                index[node] = low[node] = counter
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
                    if len(component) > 1:
                        result.append(frozenset(component))
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
    return sorted(result, key=lambda c: (-len(c), sorted(c)))


# ---------------------------------------------------------- 4. direction
def forbidden_edge_violations(sources: Mapping[str, str]) -> dict[str, list[str]]:
    """``{rule label: ["importer -> imported", ...]}`` over the src tree."""
    trees = _parse(sources)
    reached: dict[str, set[str]] = {}
    for rel, tree in trees.items():
        src = _dotted(rel)
        if src is None:
            continue
        is_init = rel.endswith("/__init__.py")
        seen: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = (
                    _resolve_relative(src, is_init, node.level, node.module)
                    if node.level
                    else node.module
                )
                if base and base.startswith(PACKAGE):
                    seen.add(base)
                    seen.update(f"{base}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                seen.update(a.name for a in node.names if a.name.startswith(PACKAGE))
        reached[src] = seen

    def under(module: str, root: str) -> bool:
        return module == root or module.startswith(root + ".")

    out: dict[str, list[str]] = {}
    for label, roots, targets, grandfathered in FORBIDDEN_EDGES:
        hits: list[str] = []
        for module, seen in sorted(reached.items()):
            if not any(under(module, root) for root in roots):
                continue
            for target in sorted(seen):
                if module == target or not any(under(target, t) for t in targets):
                    continue
                if any(under(module, t) for t in targets):
                    continue  # a target package may import itself
                edge = f"{module} -> {target}"
                if edge not in grandfathered:
                    hits.append(edge)
        out[label] = sorted(set(hits))
    return out


# ===================================================================== tests
def test_the_scan_sees_the_whole_tree() -> None:
    """Guards every assertion below: a collapsed scan is a vacuous ratchet."""
    sources = tree_sources()
    assert len(sources) > 700, f"scan collapsed to {len(sources)} files"
    for prefix in ("src/parcel_robot/", "tests/", "scripts/", "evals/"):
        assert any(rel.startswith(prefix) for rel in sources), f"no files under {prefix}"
    modules, packages = _module_index(sources)
    assert len(modules) > 250 and len(packages) > 30
    graph = import_graph(sources, include_package_edges=True)
    assert sum(map(len, graph.values())) > 500, "import-edge scan collapsed"


def test_the_measurement_stays_cheap() -> None:
    """Pure AST over ~900 files; it must stay commit-tier fast."""
    tree_sources.cache_clear()
    _parse_one.cache_clear()
    _type_checking_import_ids.cache_clear()
    start = time.perf_counter()
    sources = tree_sources()
    barrel_symbol_imports(sources)
    barrel_reexports(sources)
    for include in (True, False):
        cycle_components(import_graph(sources, include_package_edges=include))
    forbidden_edge_violations(sources)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"import ratchet took {elapsed:.1f}s; budget is 10s"


def test_no_module_imports_a_symbol_through_a_package_barrel() -> None:
    """Property 1. Submodule imports are fine; re-exported symbols are not."""
    offenders = barrel_symbol_imports(tree_sources())
    assert not offenders, (
        f"{len(offenders)} import(s) reach a SYMBOL through a package "
        "__init__; import the module that defines it instead:\n  " + "\n  ".join(offenders[:40])
    )


def test_no_package_init_re_exports() -> None:
    """Property 2. An __init__ may import only what its own code uses."""
    sources = tree_sources()
    reexports = barrel_reexports(sources)
    assert not reexports, (
        "package __init__(s) bind imported names their own code never uses — "
        f"that is a re-export barrel: {reexports}"
    )
    importing = barrels_importing_anything(sources)
    unlisted = sorted(importing - set(BARRELS_WITH_KEPT_IMPORTS))
    assert not unlisted, (
        f"package __init__(s) import outside the allowlist: {unlisted}. Either "
        "the import belongs in a leaf module, or add the package to "
        "BARRELS_WITH_KEPT_IMPORTS with the reason its own code needs it."
    )
    stale = sorted(set(BARRELS_WITH_KEPT_IMPORTS) - importing)
    assert not stale, f"allowlist names package(s) that no longer import: {stale}"


def test_barrel_all_advertises_only_names_it_binds() -> None:
    """A drained barrel must not keep advertising what it no longer provides."""
    offenders = all_advertises_unbound(tree_sources())
    assert not offenders, f"__all__ advertises unbound names: {offenders}"


def test_import_cycles_match_the_named_grandfather_list() -> None:
    """Property 3. Cycles may split or die; they may not grow or appear."""
    sources = tree_sources()
    for label, include in (("with_package_edges", True), ("leaf_only", False)):
        grandfathered = GRANDFATHERED_CYCLES[label]
        current = cycle_components(import_graph(sources, include_package_edges=include))
        novel = [
            sorted(component)
            for component in current
            if not any(component <= baseline for baseline, _ in grandfathered)
        ]
        assert not novel, (
            f"new or widened import cycle ({label}): {novel}. Every SCC must sit "
            "inside one grandfathered component; splitting an old tangle is "
            "progress, replacing it with a new one is not."
        )
        assert len(current) <= len(grandfathered), (
            f"import cycles ({label}) rose from {len(grandfathered)} to {len(current)}"
        )
        widest = max((len(c) for c in current), default=0)
        ceiling = max((len(c) for c, _ in grandfathered), default=0)
        assert widest <= ceiling, (
            f"largest import cycle ({label}) grew from {ceiling} to {widest} modules"
        )


def test_the_grandfather_list_still_names_real_modules() -> None:
    """Guards the guard: a stale entry silently widens the allowance."""
    sources = tree_sources()
    modules, _ = _module_index(sources)
    for label, entries in GRANDFATHERED_CYCLES.items():
        for component, reason in entries:
            missing = sorted(component - modules)
            assert not missing, f"{label} grandfather entry names missing modules: {missing}"
            assert len(reason) > 30, f"{label} entry {sorted(component)} needs a real reason"


def test_no_forbidden_reverse_edge() -> None:
    """Property 4. ARCH-1's direction rules, measured rather than asserted."""
    sources = tree_sources()
    modules, _ = _module_index(sources)
    for label, roots, targets, _grandfathered in FORBIDDEN_EDGES:
        for root in (*roots, *targets):
            assert root in modules, f"{label}: {root} is not a module — the rule is vacuous"
    violations = {label: hits for label, hits in forbidden_edge_violations(sources).items() if hits}
    assert not violations, f"ARCH-1 forbidden reverse edge(s): {violations}"


def test_the_graph_agrees_with_the_dec0_debt_ratchet() -> None:
    """One measurement, two ratchets: the models must not drift apart.

    DEC-0 ratchets "never worse than the frozen numbers"; this module ratchets
    "exactly this named list, each with a reason". If the two graphs disagreed,
    one of them would be guarding a tree that does not exist.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_dec0_debt_ratchet as dec0

    sources = tree_sources()
    for include in (True, False):
        mine = set(cycle_components(import_graph(sources, include_package_edges=include)))
        theirs = set(dec0.measure_cycle_components(include_package_edges=include))
        assert mine == theirs, (
            f"cycle models disagree (include_package_edges={include}): "
            f"only here {sorted(map(sorted, mine - theirs))}, "
            f"only there {sorted(map(sorted, theirs - mine))}"
        )


# ------------------------------------------------------------- seeded reds
# Each cell re-runs the REAL measurement over the REAL tree plus one mutant
# file, so a check that has gone vacuous cannot pass these.
def _with(mutant: dict[str, str]) -> dict[str, str]:
    return {**tree_sources(), **mutant}


def test_seeded_red_a_barrel_symbol_import_is_caught() -> None:
    seeded = _with(
        {"tests/_seed_decig2.py": "from parcel_robot.navigation import DirectiveNavigator\n"}
    )
    offenders = barrel_symbol_imports(seeded)
    assert any("parcel_robot.navigation.DirectiveNavigator" in o for o in offenders), offenders
    # ...and the submodule form it must NOT confuse with it stays clean.
    clean = _with({"tests/_seed_decig2.py": "from parcel_robot.navigation import pipeline\n"})
    assert barrel_symbol_imports(clean) == []


def test_seeded_red_a_re_export_barrel_is_caught() -> None:
    seeded = _with(
        {
            "src/parcel_robot/navigation/__init__.py": (
                '"""City navigation."""\n\nfrom .pipeline import DirectiveNavigator\n'
            )
        }
    )
    assert barrel_reexports(seeded).get("parcel_robot.navigation") == ["DirectiveNavigator"]
    assert "parcel_robot.navigation" in barrels_importing_anything(seeded)
    assert "parcel_robot.navigation" not in BARRELS_WITH_KEPT_IMPORTS


def test_seeded_red_an_unbound_all_entry_is_caught() -> None:
    seeded = _with(
        {"src/parcel_robot/voice/__init__.py": '"""Voice."""\n\n__all__ = ["RealtimeLane"]\n'}
    )
    assert any("RealtimeLane" in o for o in all_advertises_unbound(seeded)), all_advertises_unbound(
        seeded
    )


def test_seeded_red_a_new_cycle_is_caught() -> None:
    """Two src modules that import each other and sit in no grandfathered set."""
    seeded = _with(
        {
            "src/parcel_robot/_seed_a.py": "from parcel_robot._seed_b import B\n\nA = 1\n",
            "src/parcel_robot/_seed_b.py": "from parcel_robot._seed_a import A\n\nB = 2\n",
        }
    )
    current = cycle_components(import_graph(seeded, include_package_edges=False))
    novel = [
        sorted(c)
        for c in current
        if not any(c <= base for base, _ in GRANDFATHERED_CYCLES["leaf_only"])
    ]
    assert novel == [["parcel_robot._seed_a", "parcel_robot._seed_b"]], novel


def test_seeded_red_a_widened_cycle_is_caught() -> None:
    """A third module joining a grandfathered 2-cycle must not pass as a subset."""
    seeded = _with(
        {
            "src/parcel_robot/navigation/_seed_c.py": (
                "from parcel_robot.navigation.goals import SemanticGoal\n"
                "from parcel_robot.navigation.arrival_semantics import resolve_relation\n"
            ),
            "src/parcel_robot/navigation/goals.py": (
                tree_sources()["src/parcel_robot/navigation/goals.py"]
                + "\nfrom parcel_robot.navigation._seed_c import *\n"
            ),
        }
    )
    current = cycle_components(import_graph(seeded, include_package_edges=False))
    novel = [
        sorted(c)
        for c in current
        if not any(c <= base for base, _ in GRANDFATHERED_CYCLES["leaf_only"])
    ]
    assert novel and any("parcel_robot.navigation._seed_c" in c for c in novel), novel


def test_seeded_red_a_forbidden_reverse_edge_is_caught() -> None:
    seeded = _with(
        {
            "src/parcel_robot/authority.py": (
                tree_sources()["src/parcel_robot/authority.py"]
                + "\nfrom parcel_robot.runtime import RobotRuntime  # seeded\n"
            )
        }
    )
    hits = forbidden_edge_violations(seeded)
    assert "parcel_robot.authority -> parcel_robot.runtime" in hits[FORBIDDEN_EDGES[0][0]], hits
