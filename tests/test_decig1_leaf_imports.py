"""DEC-IG-1 — migrated barrels stay migrated.

The decomposition program (scrum/20260823/DECOMP_PROGRAM_FABLE.md §2 M1)
retires the re-exporting subpackage barrels that manufacture parcel_robot's
large import cycles.  A barrel is retired in two steps:

1.  every importer stops reaching a symbol *through* the barrel and imports
    the module that defines it (``from parcel_robot.navigation.pipeline
    import DirectiveNavigator``, not ``from parcel_robot.navigation import
    DirectiveNavigator``);
2.  the barrel's own re-export of that symbol is deleted.

This module locks in step 1 for the barrels DEC-IG-1 migrated and step 2 for
the re-exports it deleted, so a later card cannot silently re-introduce
either.  ``MIGRATED_BARRELS`` and ``THINNED_BARRELS`` are the extension
points: DEC-IG-2 widens them as it migrates runtime.py / agent.py /
web_panel.py and thins the remaining barrels.

Like tests/test_dec0_debt_ratchet.py this module imports NO product code --
it is pure AST over the tree, so import-time side effects in the very files
it measures cannot perturb the measurement.

Scope note: ``from parcel_robot.navigation import goals`` is a SUBMODULE
import, not a barrel re-export, and is deliberately allowed.  Only names the
barrel's ``__init__`` pulls in from elsewhere and rebinds are barrel-mediated.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Trees that may import the package.  ``tests/`` is IN scope here (unlike the
#: DEC-0 ratchet): a barrel re-export with only test importers is still a live
#: re-export, and DEC-0's own worklist was 11/12 test files.
SCAN_DIRS = ("src", "tests", "scripts", "tools", "examples")
SKIP_PARTS = {".parcel", "build", "tmp_ci", "third_party", "node_modules", ".git"}

#: Barrels DEC-IG-1 drained of re-export traffic.  No module anywhere may
#: import a re-exported SYMBOL through these; DEC-IG-2 appends to this tuple.
MIGRATED_BARRELS = ("parcel_robot.navigation",)

#: Barrels DEC-IG-1 thinned, and the symbols it removed from them.  These must
#: stay gone -- re-adding one silently re-couples the package.
THINNED_BARRELS: dict[str, frozenset[str]] = {
    "parcel_robot.realtime": frozenset(
        {
            "GUARDRAILS",
            "RealtimeArmingDecision",
            "RealtimeLane",
            "RealtimeLaneError",
            "SinkOwnershipError",
            "TOOL_REFUSAL_OUTPUT",
            "build_instructions",
            "decide_realtime_arming",
        }
    ),
}


# ---------------------------------------------------------------- AST helpers
def _py_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for d in SCAN_DIRS:
        root = REPO / d
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if SKIP_PARTS & set(p.relative_to(REPO).parts):
                continue
            out.append((p.relative_to(REPO).as_posix(), p))
    return out


def _module_name(rel: str) -> str | None:
    """Dotted name for a repo-relative path under ``src/``."""
    if not rel.startswith("src/"):
        return None
    parts = rel[len("src/") :].removesuffix(".py").split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or parts[0] != "parcel_robot":
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


def _barrel_reexports(dotted: str) -> dict[str, str]:
    """{symbol: defining module} for names ``dotted``'s __init__ re-exports."""
    init = REPO / "src" / dotted.replace(".", "/") / "__init__.py"
    if not init.exists():
        return {}
    tree = ast.parse(init.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = (
            _resolve_relative(dotted, True, node.level, node.module) if node.level else node.module
        )
        if base is None or not base.startswith("parcel_robot"):
            continue
        for alias in node.names:
            if alias.name != "*":
                out[alias.asname or alias.name] = base
    return out


def _is_package(dotted: str) -> bool:
    return (REPO / "src" / dotted.replace(".", "/") / "__init__.py").exists()


def _barrel_symbol_imports(barrel: str) -> list[str]:
    """Every ``from <barrel> import <re-exported symbol>`` in the tree.

    Parenthesized multi-line imports are handled for free: ``ast`` yields one
    ``ImportFrom`` node carrying every alias, which is precisely why a line
    grep undercounts this population.
    """
    reexports = _barrel_reexports(barrel)
    hits: list[str] = []
    for rel, path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - the tree must parse
            continue
        self_mod = _module_name(rel)
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
            if base != barrel or self_mod == barrel:
                continue
            for alias in node.names:
                name = alias.name
                if name == "*":
                    hits.append(f"{rel}:{node.lineno}: star-import from {barrel}")
                    continue
                # `from pkg import submodule` is a module reference, not a
                # barrel re-export -- always allowed.
                if _is_package(f"{barrel}.{name}") or (
                    REPO / "src" / f"{barrel}.{name}".replace(".", "/")
                ).with_suffix(".py").exists():
                    continue
                if name in reexports:
                    hits.append(f"{rel}:{node.lineno}: {name} (defined in {reexports[name]})")
    return sorted(hits)


# --------------------------------------------------------------------- tests
def test_scan_actually_sees_the_tree() -> None:
    """A silent zero-file scan would make every assertion below vacuous."""
    files = _py_files()
    assert len(files) > 300, f"scan collapsed to {len(files)} files"
    assert any(r.startswith("src/parcel_robot/") for r, _ in files)
    assert any(r.startswith("tests/") for r, _ in files)


def test_migrated_barrels_have_reexports_to_protect() -> None:
    """Guards the guard: if a barrel stops re-exporting, the pin is vacuous."""
    for barrel in MIGRATED_BARRELS:
        assert _barrel_reexports(barrel), f"{barrel} re-exports nothing; drop it from the list"


def test_no_module_imports_a_symbol_through_a_migrated_barrel() -> None:
    """Step 1: every importer reaches the defining leaf module directly."""
    for barrel in MIGRATED_BARRELS:
        offenders = _barrel_symbol_imports(barrel)
        assert not offenders, (
            f"{len(offenders)} import(s) still reach a symbol through the "
            f"{barrel} barrel; import the defining module instead:\n  "
            + "\n  ".join(offenders)
        )


def test_thinned_barrels_do_not_re_export_the_removed_symbols() -> None:
    """Step 2: the deleted re-exports stay deleted, in code and in __all__."""
    for barrel, removed in THINNED_BARRELS.items():
        reexports = _barrel_reexports(barrel)
        back = sorted(removed & set(reexports))
        assert not back, f"{barrel} re-exports {back} again; DEC-IG-1 removed them"

        init = REPO / "src" / barrel.replace(".", "/") / "__init__.py"
        tree = ast.parse(init.read_text(encoding="utf-8"))
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                declared = [
                    e.value for e in node.value.elts if isinstance(e, ast.Constant)
                ]  # type: ignore[union-attr]
        assert declared, f"{barrel} has no literal __all__ to check"
        leaked = sorted(removed & set(declared))
        assert not leaked, f"{barrel}.__all__ still advertises {leaked}"


def test_thinned_barrel_all_matches_its_actual_reexports() -> None:
    """``__all__`` is the barrel's advertised surface; keep it honest.

    Every name in ``__all__`` must be something the module actually binds --
    a re-exported symbol or a submodule it imports -- so the thinned list
    cannot drift from what the barrel really provides.
    """
    for barrel in THINNED_BARRELS:
        init = REPO / "src" / barrel.replace(".", "/") / "__init__.py"
        tree = ast.parse(init.read_text(encoding="utf-8"))
        bound = set(_barrel_reexports(barrel))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module is None:
                bound.update(a.asname or a.name for a in node.names)
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                declared = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
        missing = sorted(set(declared) - bound)
        assert not missing, f"{barrel}.__all__ advertises unbound names: {missing}"
