"""Generate ``CODEBASE_INDEX.md`` — a selective-reading map of this repository.

Why this exists
---------------
The tree is ~2,700 tracked files, ~143k lines under ``src/`` and ~167k under
``tests/``. An agent (or a person) that "reads the directory for context" burns
its whole budget before it starts. This index lets a reader answer *where is X,
what does file Y do, what lives in package Z, which card owns which region*
from one file — and read that file **selectively**: every top-level directory
is a ``## `` section and every package is a ``### `` subsection, so::

    grep -n '^## \\|^### ' CODEBASE_INDEX.md          # the table of contents with line numbers
    sed -n '120,180p' CODEBASE_INDEX.md               # read exactly one section

What goes in
------------
* ``.py`` modules: line count, the first line of the module docstring, the
  top-level classes and functions (each with the first line of its docstring).
  Test modules get the docstring and the number of test functions instead of
  every name — the test *name* convention here is the sentence, and the file
  is the unit a reader opens.
* ``.md`` documents: line count and the first heading.
* Everything else: listed by directory with counts, so a reader knows the data
  and config trees exist without every PNG being a line.
* ``scrum/``: one line per card folder (the README's first heading) and the
  other documents beside it — the sprint record is where "why" lives.
* Card markers: comment lines in the heavily shared product files that name a
  card or a region, with line numbers — the OWNS discipline's map.

Regenerate after every commit that adds or moves files::

    .parcel/bin/python tools/codebase_index.py            # writes CODEBASE_INDEX.md
    .parcel/bin/python tools/codebase_index.py --check    # exit 1 if stale

Only tracked files (``git ls-files``) are indexed, so the index is a function
of the commit, not of whatever scratch happens to be on disk.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "CODEBASE_INDEX.md"
DOC_WIDTH = 110
CARD_RE = re.compile(
    r"\b(?:P[0-3]-[A-F]\d?|MOVE-\d|C-\d|E-\d|W-\d|R\d{1,2}|ROAM-\d|CURIO-\d|TURN-\d|MARK-\d|"
    r"GATE-\d|AIR-\d|DUPLEX-\d|ENV-\d[a-z]?|VENUE-\d|OT-\d|NM-\d|FZ-\d|HY-\d|XD-\d|DOOR-\d|"
    r"PS-[A-Z]|FIX-[A-Z]|AU-[A-Z]\d-\d)\b"
)
REGION_RE = re.compile(r"\bCARD\b|region|owns|seam|BEGIN|\bEND\b", re.IGNORECASE)
# Product files several cards share; their card/region markers are listed.
SHARED_PRODUCT_FILES = (
    "src/parcel_robot/runtime.py",
    "src/parcel_robot/realtime/lane.py",
    "src/parcel_robot/realtime/config.py",
    "src/parcel_robot/realtime/tool_broker.py",
    "src/parcel_robot/realtime/ingress.py",
    "src/parcel_robot/realtime/whisperer.py",
    "src/parcel_robot/realtime/protocol.py",
    "src/parcel_robot/navigation/pipeline.py",
    "src/parcel_robot/ui/index.html",
    "scripts/ci_gate.py",
)
TEST_PREFIX_RE = re.compile(r"^test_([a-z0-9]+?)(?:_|\.py$)")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout
    # A tracked file deleted in the working tree (a decomposition card mid-flight)
    # is still listed by ``git ls-files``; index what exists on disk.
    return [Path(p) for p in out.decode().split("\0") if p and (REPO / p).exists()]


def first_line(doc: str | None) -> str:
    if not doc:
        return ""
    line = doc.strip().splitlines()[0].strip()
    return line if len(line) <= DOC_WIDTH else line[: DOC_WIDTH - 1] + "…"


def count_lines(path: Path) -> int:
    try:
        with (REPO / path).open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


@dataclass
class PyInfo:
    path: Path
    lines: int
    doc: str
    classes: list[tuple[str, str]] = field(default_factory=list)
    functions: list[tuple[str, str]] = field(default_factory=list)
    tests: int = 0
    parse_error: str = ""


def inspect_py(path: Path) -> PyInfo:
    source = (REPO / path).read_text(encoding="utf-8", errors="replace")
    info = PyInfo(path=path, lines=source.count("\n") + (0 if source.endswith("\n") else 1), doc="")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        info.parse_error = f"syntax error line {error.lineno}"
        return info
    info.doc = first_line(ast.get_docstring(tree, clean=True))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            info.classes.append((node.name, first_line(ast.get_docstring(node, clean=True))))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test_"):
                info.tests += 1
            else:
                info.functions.append((node.name, first_line(ast.get_docstring(node, clean=True))))
    return info


def md_heading(path: Path) -> str:
    try:
        with (REPO / path).open(encoding="utf-8", errors="replace") as handle:
            for _ in range(60):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("#"):
                    return first_line(line.lstrip("#"))
    except OSError:
        pass
    return ""


def fmt_py(info: PyInfo, *, is_test: bool) -> str:
    head = f"- `{info.path}` ({info.lines})"
    if info.parse_error:
        return f"{head} — **{info.parse_error}**"
    parts: list[str] = []
    if info.doc:
        parts.append(info.doc)
    if is_test:
        parts.append(f"[{info.tests} tests]")
        return f"{head} — " + " ".join(parts)
    if info.classes:
        parts.append("classes: " + ", ".join(name for name, _ in info.classes))
    if info.functions:
        names = [name for name, _ in info.functions if not name.startswith("_")]
        if names:
            parts.append("funcs: " + ", ".join(names))
    return f"{head} — " + " · ".join(parts) if parts else head


def package_of(path: Path) -> str:
    # src/parcel_robot/realtime/lane.py -> src/parcel_robot/realtime
    return str(path.parent)


def card_markers(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        with (REPO / path).open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped.startswith(("#", "//", "<!--")):
                    continue
                # A delimiter, not prose: an uppercase CARD word with a card id
                # (``# ---- CARD P1-B state``, ``# === END CARD ROAM-1 region``)
                # or the lane's ``MARKED REGION`` phrase.
                is_delimiter = ("MARKED REGION" in stripped) or (
                    re.search(r"\bCARD\b", stripped) is not None
                    and CARD_RE.search(stripped) is not None
                    and REGION_RE.search(stripped) is not None
                )
                if is_delimiter:
                    text = stripped.lstrip("#/<!- ").rstrip("->")
                    hits.append((number, text[:DOC_WIDTH]))
    except OSError:
        pass
    return hits


def build() -> str:
    files = tracked_files()
    by_top: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        by_top[path.parts[0] if len(path.parts) > 1 else "."].append(path)

    py_infos: dict[Path, PyInfo] = {}
    for path in files:
        if path.suffix == ".py":
            py_infos[path] = inspect_py(path)

    total_src = sum(i.lines for p, i in py_infos.items() if p.parts[0] == "src")
    total_tests = sum(i.lines for p, i in py_infos.items() if p.parts[0] == "tests")
    head_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()

    out: list[str] = []
    out.append("# Codebase index\n")
    out.append(
        f"Generated by `tools/codebase_index.py` at commit `{head_sha}` from `git ls-files` "
        f"({len(files)} tracked files; {len(py_infos)} Python modules; "
        f"src ≈ {total_src:,} lines, tests ≈ {total_tests:,} lines). "
        "Regenerate after any commit that adds or moves files: "
        "`.parcel/bin/python tools/codebase_index.py`.\n"
    )
    out.append(
        "**Read this file selectively.** `grep -n '^## \\|^### ' CODEBASE_INDEX.md` prints the "
        "table of contents with line numbers; `sed -n 'A,Bp' CODEBASE_INDEX.md` reads one section. "
        "Each module line is `path (lines) — module docstring · classes · funcs`; test modules show "
        "`[N tests]` instead of names. `scrum/` lists one line per card folder. The **Card markers** "
        "section maps the marked regions cards own inside the shared product files.\n"
    )

    # ---- table of top-level dirs
    out.append("## Top level\n")
    out.append("| dir | files | what |")
    out.append("|---|---:|---|")
    purposes = {
        "src": "the product package `parcel_robot` (runtime, realtime voice lane, navigation, perception, maps)",
        "tests": "pytest suite; commit tier = `-m 'not slow'`, nightly = `-m slow`",
        "scrum": "sprint record by date: one folder per card (README = the card, *_STATUS.md = executor report, AUDIT_* = verifier)",
        "evals": "frozen eval fixtures, manifests, and pinned findings the CI gate reproduces byte-identically",
        "configs": "runtime/navigation/realtime YAML profiles (`*.prototype.yaml` = the owner's loosened prototype profile)",
        "scripts": "operator CLIs (ci_gate, launch_stack, parcel_capture preflight/attest/clockmap)",
        "tools": "owner one-offs (enrollment, voice A/B, this index)",
        "prompts": "persona + function prompts; digest-pinned by `realtime/prompting.py` (SI_VERSION)",
        "docs": "design docs and handbooks (owner/other-session territory for edits)",
        "edu": "educational material / curricula",
        "models": "model manifests and small weights",
        "fixtures": "test fixtures",
        "deploy": "deployment units",
        "backlog": "owner backlog notes",
        "services": "service definitions",
        "maps": "map data",
        "examples": "examples",
        ".github": "CI workflows",
        ".": "root: README, pyproject, requirements-lock, .gitignore",
    }
    for top in sorted(by_top, key=lambda k: (-len(by_top[k]), k)):
        out.append(f"| `{top}` | {len(by_top[top])} | {purposes.get(top, '')} |")
    out.append("")

    # ---- src
    out.append("## src/parcel_robot\n")
    src_by_pkg: dict[str, list[PyInfo]] = defaultdict(list)
    src_other: dict[str, list[Path]] = defaultdict(list)
    for path in by_top.get("src", []):
        if path.suffix == ".py":
            src_by_pkg[package_of(path)].append(py_infos[path])
        else:
            src_other[package_of(path)].append(path)
    for pkg in sorted(src_by_pkg):
        infos = sorted(src_by_pkg[pkg], key=lambda i: i.path.name)
        init = next((i for i in infos if i.path.name == "__init__.py"), None)
        out.append(f"### {pkg}  ({sum(i.lines for i in infos):,} lines, {len(infos)} modules)\n")
        if init and init.doc:
            out.append(f"_{init.doc}_\n")
        for info in infos:
            out.append(fmt_py(info, is_test=False))
        extras = src_other.get(pkg)
        if extras:
            kinds = defaultdict(int)
            for extra in extras:
                kinds[extra.suffix or "(none)"] += 1
            out.append("- non-Python here: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
        out.append("")
    data_dirs = [pkg for pkg in sorted(src_other) if pkg not in src_by_pkg]
    if data_dirs:
        out.append("### src data trees (no Python)\n")
        out.append("One line per directory: file counts by suffix. `runtime_assets/` is the packaged "
                   "copy of configs/prompts/scenes that the release-parity gate keeps byte-identical "
                   "to the canonical sources.\n")
        for pkg in data_dirs:
            extras = src_other[pkg]
            kinds = defaultdict(int)
            for extra in extras:
                kinds[extra.suffix or "(none)"] += 1
            names = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            sample = "; ".join(sorted(e.name for e in extras)[:4]) if len(extras) <= 4 else ""
            out.append(f"- `{pkg}/` — {names}" + (f" ({sample})" if sample else ""))
        out.append("")

    # ---- tests
    out.append("## tests\n")
    groups: dict[str, list[PyInfo]] = defaultdict(list)
    test_other: list[Path] = []
    for path in by_top.get("tests", []):
        if path.suffix == ".py" and path.parent == Path("tests"):
            match = TEST_PREFIX_RE.match(path.name)
            groups[match.group(1) if match else "_support"].append(py_infos[path])
        elif path.suffix == ".py":
            groups[str(path.parent)].append(py_infos[path])
        else:
            test_other.append(path)
    total_tests_n = sum(i.tests for infos in groups.values() for i in infos)
    out.append(f"{sum(len(v) for v in groups.values())} modules, {total_tests_n} test functions. "
               "Grouped by the first name segment after `test_` (usually the card or subsystem).\n")
    for group in sorted(groups):
        infos = sorted(groups[group], key=lambda i: i.path.name)
        out.append(f"### tests · {group}  ({len(infos)} modules, {sum(i.tests for i in infos)} tests)\n")
        for info in infos:
            out.append(fmt_py(info, is_test=True))
        out.append("")
    if test_other:
        by_dir = defaultdict(int)
        for path in test_other:
            by_dir[str(path.parent)] += 1
        out.append("### tests · data\n")
        for directory, count in sorted(by_dir.items()):
            out.append(f"- `{directory}/` — {count} files")
        out.append("")

    # ---- scrum
    out.append("## scrum\n")
    out.append("One line per card folder: the README's first heading, then the other documents beside it.\n")
    scrum_by_date: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for path in by_top.get("scrum", []):
        if len(path.parts) < 2:
            continue
        date = path.parts[1]
        folder = path.parts[2] if len(path.parts) > 3 else "."
        scrum_by_date[date][folder].append(path)
    for date in sorted(scrum_by_date):
        folders = scrum_by_date[date]
        out.append(f"### scrum/{date}  ({sum(len(v) for v in folders.values())} files)\n")
        for top_doc in sorted(folders.get(".", [])):
            if top_doc.suffix == ".md":
                out.append(f"- `{top_doc.name}` ({count_lines(top_doc)}) — {md_heading(top_doc)}")
            else:
                out.append(f"- `{top_doc.name}`")
        def folder_key(name: str) -> tuple[int, str]:
            match = re.match(r"task_(\d+)", name)
            return (int(match.group(1)) if match else 10**6, name)
        for folder in sorted((f for f in folders if f != "."), key=folder_key):
            items = folders[folder]
            readme = next((p for p in items if p.name.lower() == "readme.md"), None)
            heading = md_heading(readme) if readme else ""
            others = sorted(
                p.name for p in items if p is not readme and len(p.parts) == 4 and p.suffix == ".md"
            )
            nested = sum(1 for p in items if len(p.parts) > 4)
            line = f"- `{folder}/` — {heading}" if heading else f"- `{folder}/`"
            if others:
                line += " · " + ", ".join(others)
            if nested:
                line += f" · +{nested} nested (evidence)"
            out.append(line)
        out.append("")

    # ---- docs and other md-heavy dirs
    for top in ("docs", "backlog", "edu", "prompts", "models", "configs", "scripts", "tools",
                "evals", "fixtures", "deploy", "services", "maps", "examples", ".github", "."):
        paths = by_top.get(top)
        if not paths:
            continue
        out.append(f"## {top}\n")
        if top == "evals":
            by_dir = defaultdict(int)
            for path in paths:
                by_dir[str(path.parent)] += 1
            readmes = [p for p in paths if p.name.lower() == "readme.md"]
            for readme in sorted(readmes):
                out.append(f"- `{readme}` — {md_heading(readme)}")
            out.append("- directories (file counts):")
            for directory, count in sorted(by_dir.items()):
                out.append(f"  - `{directory}/` — {count}")
            out.append("")
            continue
        for path in sorted(paths):
            if path.suffix == ".py":
                out.append(fmt_py(py_infos[path], is_test=False))
            elif path.suffix == ".md":
                out.append(f"- `{path}` ({count_lines(path)}) — {md_heading(path)}")
            elif len(paths) <= 60:
                out.append(f"- `{path}`")
        if len(paths) > 60:
            kinds = defaultdict(int)
            for path in paths:
                if path.suffix not in (".py", ".md"):
                    kinds[path.suffix or "(none)"] += 1
            if kinds:
                out.append("- other files: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
        out.append("")

    # ---- card markers
    out.append("## Card markers in shared product files\n")
    out.append("Comment lines that name a card AND a region/owner word, with line numbers — "
               "the map for the OWNS discipline (edit only your region; re-read before every edit).\n")
    for rel in SHARED_PRODUCT_FILES:
        path = Path(rel)
        if path not in set(files):
            continue
        hits = card_markers(path)
        out.append(f"### {rel}  ({count_lines(path)} lines, {len(hits)} markers)\n")
        for number, text in hits:
            out.append(f"- L{number}: {text}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if CODEBASE_INDEX.md is stale")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args(argv)
    text = build()
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""

        def without_stamp(doc: str) -> str:
            # Ignore the commit stamp when comparing.
            return "\n".join(line for line in doc.splitlines() if not line.startswith("Generated by"))

        if without_stamp(current) == without_stamp(text):
            print("CODEBASE_INDEX.md is current")
            return 0
        print("CODEBASE_INDEX.md is STALE — run tools/codebase_index.py")
        return 1
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
