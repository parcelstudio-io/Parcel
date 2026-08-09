#!/usr/bin/env python
"""Watchable sequential runner for the live voice->nav e2e cases.

WHAT THIS IS
------------
A *viewer*, not a harness. Every case is executed by ``pytest`` against
``tests/test_voice_nav_e2e.py`` exactly as CI runs it — one subprocess per case,
so the sim process and the runtime are torn down between cases and nothing
leaks. This file adds three things and nothing else:

1. a **banner before** each case — instruction(s), what outcome is expected
   (pass / pinned xfail + why), and the goal region the case is scored against;
2. the **verdict and key metrics after** each case — read out of the case's own
   evidence dict, captured by wrapping ``_run_command_to_terminal`` in-process
   (the test file is never edited and never imported by this driver);
3. a **scoreboard** at the end.

It is deliberately not a second eval: no case is re-scored here, no threshold
lives here, and the exit code is pytest's own.

USAGE
-----
::

    scripts/watch_nav_evals.sh                    # all cases, windowed, in file order
    scripts/watch_nav_evals.sh --only sidewalk    # substring filter on the case name
    scripts/watch_nav_evals.sh --pause            # wait for Enter between cases
    scripts/watch_nav_evals.sh --list             # print the plan and exit

The shell wrapper is what selects the native MuJoCo viewer
(``MUJOCO_GL=glfw`` + ``DISPLAY``). Running this module directly inherits
whatever ``MUJOCO_GL`` is already set, which is how the headless verification
run is done (``MUJOCO_GL=egl``).

DUAL ROLE
---------
The same file is also the pytest plugin that captures the evidence
(``-p watch_nav_evals`` with ``scripts/`` on ``PYTHONPATH``). The plugin half
touches only ``_run_command_to_terminal``, wraps it, and writes the evidence
dicts to ``$WATCH_NAV_EVIDENCE`` — it changes no assertion, so a case's verdict
under this driver is the same verdict it has under plain pytest.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
E2E_RELPATH = "tests/test_voice_nav_e2e.py"
E2E_PATH = REPO / E2E_RELPATH

#: Env var the plugin half writes its evidence JSON to.
EVIDENCE_ENV = "WATCH_NAV_EVIDENCE"

_SUMMARY_TOKENS = ("passed", "failed", "xfailed", "xpassed", "error", "skipped")


# ---------------------------------------------------------------------------
# pytest plugin half — evidence capture, zero assertion changes
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(session, config, items) -> None:
    """Wrap the e2e module's own command runner so its evidence is recoverable.

    Runs at collection time, when the test module is already imported, so the
    wrap cannot change import order. A failure to wrap is silent by design: the
    driver still reports pytest's verdict, just without metrics.
    """

    dest = os.environ.get(EVIDENCE_ENV)
    if not dest or not items:
        return
    module = getattr(items[0], "module", None)
    original = getattr(module, "_run_command_to_terminal", None)
    if original is None or getattr(original, "_watch_nav_wrapped", False):
        return
    captured: list[dict[str, Any]] = []

    def wrapper(live, command, **kwargs):
        result = original(live, command, **kwargs)
        goal = kwargs.get("goal")
        captured.append(_evidence_row(command, result, goal))
        return result

    wrapper._watch_nav_wrapped = True  # type: ignore[attr-defined]
    wrapper._watch_nav_captured = captured  # type: ignore[attr-defined]
    module._run_command_to_terminal = wrapper
    config._watch_nav_captured = captured


def pytest_sessionfinish(session, exitstatus) -> None:
    dest = os.environ.get(EVIDENCE_ENV)
    captured = getattr(session.config, "_watch_nav_captured", None)
    if not dest or captured is None:
        return
    Path(dest).write_text(json.dumps(captured, indent=2, default=str), encoding="utf-8")


def _evidence_row(command: str, result: dict, goal: Any) -> dict[str, Any]:
    """The handful of fields worth showing a human, pulled from the case's own dict."""

    start = tuple(result.get("start") or (0.0, 0.0))
    end = tuple(result.get("end") or (0.0, 0.0))
    moved = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    row: dict[str, Any] = {
        "command": command,
        "reply": str(result.get("reply") or "")[:200],
        "start": [round(float(start[0]), 3), round(float(start[1]), 3)],
        "end": [round(float(end[0]), 3), round(float(end[1]), 3)],
        "path_moved_m": round(moved, 3),
        "elapsed_s": round(float(result.get("elapsed_s") or 0.0), 1),
        "states": list(result.get("states") or ()),
        "details": list(result.get("details") or ()),
        "system_arrival": result.get("system_arrival"),
        "scorer_arrival": result.get("scorer_arrival"),
        "authority_category": result.get("authority_category"),
        "plan_steps": list(result.get("plan_steps") or ()),
        "posture": result.get("posture"),
        "resolution_state": (result.get("mission") or {}).get("resolution_state"),
    }
    if goal is not None:
        try:
            row["distance_to_goal_m"] = round(float(goal.distance_to(end[0], end[1])), 3)
        except (AttributeError, TypeError, ValueError):
            # A goal shape with no distance_to is a missing metric, never a
            # crashed watch run.
            row["distance_to_goal_m"] = None
    return row


# ---------------------------------------------------------------------------
# driver half — plan, banner, run, scoreboard
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """One collected e2e case plus everything the banner needs."""

    node_id: str
    name: str
    doc: str
    xfail_reason: str | None
    commands: tuple[str, ...]
    goal_exprs: tuple[str, ...]
    dynamic_city: bool

    @property
    def expectation(self) -> str:
        if self.xfail_reason is None:
            return "PASS (hard gate)"
        return "XFAIL (pinned known failure)"


@dataclass
class Outcome:
    case: Case
    verdict: str
    returncode: int
    wall_s: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    tail: str = ""


def _collect_cases(python: str) -> list[Case]:
    """Ask pytest for the case list, in file order, then enrich from the AST.

    Collection happens in a pytest subprocess (so this driver never imports the
    sim stack); the instruction strings, goal expressions and xfail reasons are
    read straight out of the test source, which keeps the test file the single
    source of truth for all of it.
    """

    proc = subprocess.run(
        [python, "-m", "pytest", E2E_RELPATH, "--collect-only", "-q", "--no-header"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    node_ids = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith(f"{E2E_RELPATH}::")
    ]
    if not node_ids:
        raise SystemExit(
            "collected no cases from "
            f"{E2E_RELPATH}\n--- pytest stdout ---\n{proc.stdout}\n"
            f"--- pytest stderr ---\n{proc.stderr}"
        )
    meta = _static_case_metadata()
    cases: list[Case] = []
    for node_id in node_ids:
        func = node_id.split("::")[1].split("[")[0]
        info = meta.get(func, {})
        cases.append(
            Case(
                node_id=node_id,
                name=node_id.split("::", 1)[1],
                doc=str(info.get("doc") or ""),
                xfail_reason=info.get("xfail_reason"),
                commands=tuple(info.get("commands") or ()),
                goal_exprs=tuple(info.get("goal_exprs") or ()),
                dynamic_city=bool(info.get("dynamic_city")),
            )
        )
    return cases


def _static_case_metadata() -> dict[str, dict[str, Any]]:
    """Per-test docstring, xfail reason, issued commands and goal expressions.

    Read from the test source by AST — never by importing it, and never by
    duplicating a table here that could drift from the file.
    """

    tree = ast.parse(E2E_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        commands: list[str] = []
        goal_exprs: list[str] = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            callee = _callee_name(sub.func)
            if callee in {"_run_command_to_terminal", "handle_text"}:
                for arg in sub.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        commands.append(arg.value)
            if callee and callee.endswith("goal_region") or callee in {
                "_region_goal",
                "_object_goal",
            }:
                goal_exprs.append(ast.unparse(sub))
        out[node.name] = {
            "doc": (ast.get_docstring(node) or "").strip(),
            "xfail_reason": _xfail_reason(node),
            "commands": _dedupe(commands),
            "goal_exprs": _dedupe(goal_exprs),
            "dynamic_city": any(
                isinstance(arg.annotation, ast.Name) or True
                for arg in node.args.args
                if arg.arg == "live_dynamic"
            ),
        }
    return out


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _xfail_reason(node: ast.FunctionDef) -> str | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _callee_name(decorator.func) != "xfail":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "reason":
                try:
                    return str(ast.literal_eval(keyword.value))
                except (ValueError, SyntaxError):
                    return ast.unparse(keyword.value)
        return "(no reason recorded)"
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _goal_summary(expr: str) -> str:
    """Evaluate the pure generator goal builders so the banner shows real geometry.

    Only the two argument-literal builders from the NAV_INSTRUCT generator are
    evaluated (they are pure and sim-free). Anything else is shown as source.
    """

    match = re.match(r"_(region|object)_goal\((.*)\)$", expr, flags=re.DOTALL)
    if match is None:
        return expr
    try:
        from evals.nav_instruct.generator import _object_goal, _region_goal

        builder = _region_goal if match.group(1) == "region" else _object_goal
        node = ast.parse(f"f({match.group(2)})", mode="eval").body
        assert isinstance(node, ast.Call)
        args = [ast.literal_eval(arg) for arg in node.args]
        kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
        entity_id, goal = builder(*args, **kwargs)
    except (
        AssertionError,
        AttributeError,
        ImportError,
        KeyError,
        SyntaxError,
        TypeError,
        ValueError,
    ):
        # A banner is never allowed to stop a run; fall back to the source text.
        return expr
    if goal.kind == "polygon" and goal.polygon:
        xs = [p[0] for p in goal.polygon]
        ys = [p[1] for p in goal.polygon]
        shape = f"polygon x∈[{min(xs)}, {max(xs)}] y∈[{min(ys)}, {max(ys)}]"
    elif goal.kind == "disc":
        shape = f"disc centre {tuple(goal.center or ())} r={goal.radius_m} m"
    else:
        shape = f"{goal.kind} centre {tuple(goal.center or ())} band {tuple(goal.band_m or ())} m"
    return f"{entity_id}: {shape}"


def _banner(index: int, total: int, case: Case) -> str:
    rule = "=" * 78
    lines = [
        "",
        rule,
        f"CASE {index}/{total}   {case.name}",
        rule,
    ]
    for command in case.commands:
        lines.append(f"  instruction     : {command!r}")
    if not case.commands:
        lines.append("  instruction     : (issued inside the case; see docstring)")
    lines.append(f"  expected        : {case.expectation}")
    if case.xfail_reason:
        lines.append(f"  why pinned      : {_wrap(case.xfail_reason, 60)}")
    for expr in case.goal_exprs:
        lines.append(f"  goal region     : {_wrap(_goal_summary(expr), 60)}")
    if not case.goal_exprs:
        lines.append("  goal region     : (case-local; see docstring)")
    lines.append(f"  city            : {'dynamic (pedestrians)' if case.dynamic_city else 'static'}")
    if case.doc:
        lines.append(f"  what it proves  : {_wrap(case.doc, 60)}")
    lines.append(rule)
    return "\n".join(lines)


def _wrap(text: str, width: int, indent: str = " " * 20) -> str:
    words = " ".join(str(text).split()).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return f"\n{indent}".join(lines)


def _verdict_from(stdout: str, returncode: int) -> str:
    for token in _SUMMARY_TOKENS:
        if re.search(rf"\b\d+ {token}\b", stdout):
            counts = {
                name: int(found)
                for name in _SUMMARY_TOKENS
                for found in re.findall(rf"(\d+) {name}\b", stdout)
            }
            for name in ("error", "failed", "xpassed", "xfailed", "passed", "skipped"):
                if counts.get(name):
                    return name.upper()
            break
    return "PASSED" if returncode == 0 else f"NO-VERDICT (rc={returncode})"


def _run_case(case: Case, python: str, scratch: Path, extra: list[str]) -> Outcome:
    evidence_path = scratch / f"evidence-{abs(hash(case.node_id))}.json"
    if evidence_path.exists():
        evidence_path.unlink()
    env = dict(os.environ)
    env[EVIDENCE_ENV] = str(evidence_path)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "scripts"), str(REPO / "src"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    argv = [
        python,
        "-m",
        "pytest",
        case.node_id,
        "-q",
        "--no-header",
        "-p",
        "watch_nav_evals",
        *extra,
    ]
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True, check=False)
    wall_s = time.monotonic() - started
    evidence: list[dict[str, Any]] = []
    if evidence_path.exists():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            evidence = []
    stdout = proc.stdout + proc.stderr
    return Outcome(
        case=case,
        verdict=_verdict_from(stdout, proc.returncode),
        returncode=proc.returncode,
        wall_s=wall_s,
        evidence=evidence,
        tail="\n".join(stdout.strip().splitlines()[-25:]),
    )


def _report(outcome: Outcome) -> str:
    lines = [f"  VERDICT         : {outcome.verdict}   ({outcome.wall_s:.1f} s wall)"]
    for row in outcome.evidence:
        lines.append(f"  ── {row['command']!r}")
        lines.append(f"     reply        : {_wrap(row['reply'], 58, ' ' * 22)}")
        lines.append(
            f"     moved        : {row['start']} -> {row['end']}"
            f"  ({row['path_moved_m']} m in {row['elapsed_s']} s)"
        )
        if row.get("distance_to_goal_m") is not None:
            lines.append(f"     dist to goal : {row['distance_to_goal_m']} m")
        lines.append(f"     task states  : {row['states']}  details={row['details']}")
        lines.append(
            f"     arrival      : system={row['system_arrival']} "
            f"scorer={row['scorer_arrival']} -> {row['authority_category']}"
        )
        if row.get("plan_steps"):
            lines.append(f"     plan steps   : {row['plan_steps']}")
        if row.get("resolution_state"):
            lines.append(f"     grounding    : {row['resolution_state']}")
    if outcome.verdict in {"FAILED", "ERROR", "XPASSED"} or not outcome.evidence:
        lines.append("  ── pytest tail")
        for line in outcome.tail.splitlines():
            lines.append(f"     {line}")
    return "\n".join(lines)


def _scoreboard(outcomes: list[Outcome]) -> str:
    name_w = max((len(o.case.name) for o in outcomes), default=10)
    name_w = min(max(name_w, 20), 62)
    head = f"{'case'.ljust(name_w)}  {'verdict'.ljust(9)}  {'wall':>7}  {'dtg':>7}  authority"
    rule = "-" * len(head)
    rows = [head, rule]
    for outcome in outcomes:
        last = outcome.evidence[-1] if outcome.evidence else {}
        dtg = last.get("distance_to_goal_m")
        rows.append(
            f"{outcome.case.name[:name_w].ljust(name_w)}  "
            f"{outcome.verdict[:9].ljust(9)}  "
            f"{outcome.wall_s:6.1f}s  "
            f"{('-' if dtg is None else f'{dtg:.2f}'):>7}  "
            f"{last.get('authority_category', '-')}"
        )
    tally: dict[str, int] = {}
    for outcome in outcomes:
        tally[outcome.verdict] = tally.get(outcome.verdict, 0) + 1
    rows.append(rule)
    rows.append("  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watch_nav_evals",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only",
        default=None,
        help="run only cases whose node id contains this substring",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="wait for Enter after each case (watch the window before teardown)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the plan (banners only) and exit without running anything",
    )
    parser.add_argument(
        "--python",
        default=str(REPO / ".parcel" / "bin" / "python"),
        help="interpreter used for pytest (default: the .parcel venv)",
    )
    parser.add_argument(
        "--scratch",
        default=None,
        help="directory for per-case evidence JSON (default: a temp dir)",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="extra args forwarded to each per-case pytest invocation",
    )
    args = parser.parse_args(argv)

    cases = _collect_cases(args.python)
    if args.only:
        cases = [case for case in cases if args.only in case.node_id]
        if not cases:
            print(f"no case matches --only {args.only!r}", file=sys.stderr)
            return 2

    print(f"MUJOCO_GL={os.environ.get('MUJOCO_GL', '(unset)')}  "
          f"DISPLAY={os.environ.get('DISPLAY', '(unset)')}  "
          f"cases={len(cases)}  order=file")

    if args.list:
        for index, case in enumerate(cases, start=1):
            print(_banner(index, len(cases), case))
        return 0

    if args.scratch:
        scratch = Path(args.scratch)
        scratch.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="watch-nav-"))

    outcomes: list[Outcome] = []
    for index, case in enumerate(cases, start=1):
        print(_banner(index, len(cases), case), flush=True)
        outcome = _run_case(case, args.python, scratch, list(args.pytest_args))
        outcomes.append(outcome)
        print(_report(outcome), flush=True)
        if args.pause and index < len(cases):
            try:
                input("\n  [enter] next case, [ctrl-c] stop ")
            except (EOFError, KeyboardInterrupt):
                print("\nstopped early by request")
                break

    print("\n" + "=" * 78)
    print("SCOREBOARD")
    print("=" * 78)
    print(_scoreboard(outcomes))
    bad = [o for o in outcomes if o.verdict in {"FAILED", "ERROR"} or o.returncode not in (0, 1)]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
