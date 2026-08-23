"""Card GATE-0b (`scrum/20260822/task_30`). What this checkout does not carry.

THE DEFECT THIS CLOSES. A fresh `git clone` + `pip install -e '.[dev,voice]'`
ran the commit tier and got 48 red tests, and 28 of them said nothing more
useful than ``FileNotFoundError`` or ``ValueError: policy bundle root is
missing or unsafe``. None was a product defect: they need an **external
evidence root** that is deliberately not in git (``.cache/external-evals`` is
21 GB on this dev box) or an **optional wheel** the default extras do not
install. A test that cannot run without 21 GB of generated bundles should say
so and skip; failing is a lie about the code under test.

THE CONTRACT, AND WHY IT IS ONE TABLE.

* Every declaration lives in :data:`EXTERNAL_ROOTS` — the target, its kind,
  and the exact command that produces it.
* A test that needs one carries ``@skip_unless("<name>")``. The skip reason is
  DERIVED from the same entry, so the condition and the printed reason cannot
  drift apart the way two copies of a path always eventually do.
* ``scripts/ci_gate.py``'s ``skip-list`` stage reads THIS FILE (statically, by
  ``ast``; it never imports the test tree) and prints, on every run, which
  roots are absent on this host and how many modules will therefore skip. So
  the gate's verdict is honest on the dev box, on the hosted `ubuntu-latest`
  runner (B20) and on the Go2's aarch64 Jetson Orin: a declared root is a
  **path stat**, never a platform test, so nothing here assumes x86, CUDA or a
  particular wheelhouse.

WHY PER-TEST AND NOT PER-MODULE. Most of these files are mixed: three of the
four ``test_barn_v10_planner_profile`` tests need the bundle root and the rest
are pure unit tests that pass in any clone. A module-level ``pytestmark``
would skip the passing ones too, which is silencing, not skipping.

``tests/`` is on ``sys.path`` under pytest, which is how this module is
importable (``tests/conftest.py`` imports ``_repo_write_guard`` the same way).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The token every derived reason starts with, so a skip produced here is
#: greppable in a ``-rs`` report and distinguishable from an ordinary skip.
SKIP_TOKEN = "needs-external-root"

#: name -> {kind, target, hint}. ``kind`` is ``path`` (repo-relative directory
#: or file that must exist) or ``module`` (an importable optional dependency).
#: ``hint`` is the exact thing a reader should run, because "not available" is
#: only half an answer.
#:
#: KEEP THIS A PLAIN LITERAL. ``scripts/ci_gate.py`` reads it with
#: ``ast.literal_eval`` rather than importing this package, so the gate can
#: report the list without starting a pytest.
EXTERNAL_ROOTS: dict[str, dict[str, str]] = {
    "barn-policy-bundles": {
        "kind": "path",
        "target": ".cache/external-evals/runtime/barn-parcel-bundles",
        "hint": (
            "generate it: `python evals/external/barn_v8_policy_bundle.py`, "
            "`barn_v9_policy_bundle.py`, `barn_profile_candidate_bundle.py` "
            "(root .gitignore:14; the external-eval scratch is 21 GB here and "
            "is never vendored into git)"
        ),
    },
    "barn-generator-checkout": {
        "kind": "path",
        "target": ".cache/external-evals/repos/barn_generator",
        "hint": "fetch it: `python evals/external/fetch_sources.py` (pinned upstream checkout)",
    },
    "habitat-challenge-2020-checkout": {
        "kind": "path",
        "target": ".cache/external-evals/repos/habitat_challenge_2020",
        "hint": "fetch it: `python evals/external/fetch_sources.py` (pinned upstream checkout)",
    },
    "pyrealsense2": {
        "kind": "module",
        "target": "pyrealsense2",
        "hint": (
            "install the optional RealSense wheel: `pip install pyrealsense2` "
            "(not in the [dev,voice] extras; the D455 branch of the capture "
            "remedies is only reachable with it installed)"
        ),
    },
}


def _present(name: str) -> bool:
    entry = EXTERNAL_ROOTS[name]
    if entry["kind"] == "module":
        return importlib.util.find_spec(entry["target"]) is not None
    return (REPO / entry["target"]).exists()


def reason(name: str) -> str:
    """The one sentence a reader of the skip report gets."""

    entry = EXTERNAL_ROOTS[name]
    noun = "module" if entry["kind"] == "module" else "path"
    return f"{SKIP_TOKEN}: {entry['target']} ({noun}) is absent — {entry['hint']}"


def skip_unless(name: str) -> pytest.MarkDecorator:
    """Skip this test, with a named reason, unless ``name``'s target is here."""

    if name not in EXTERNAL_ROOTS:
        raise KeyError(
            f"{name!r} is not a declared external root; add it to "
            f"EXTERNAL_ROOTS in tests/_external_roots.py so ci_gate's "
            f"skip-list row can report it"
        )
    return pytest.mark.skipif(not _present(name), reason=reason(name))
