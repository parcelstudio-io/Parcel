"""Architecture rule: navigation may not read a robot pose off an observation.

The stratum-1 seam is only worth anything if it is the *only* door. This is the
pytest-archon-style guard the plan asks for: a plain AST walk (no new lint
plugin — a binding anti-goal) that finds every ``observation.position`` /
``observation.heading_deg`` read under ``src/parcel_robot`` and requires it to
be either the seam itself or on a **shrinking** allowlist.

Adding a file to the allowlist is a deliberate act with a written reason.
Removing one is the migration finishing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "parcel_robot"

#: The pose fields a consumer must not read directly.
POSE_FIELDS = frozenset({"position", "heading_deg"})

#: The seam. These files ARE the sanctioned pose read.
SEAM = {
    "pose.py",
    "navigation/base.py",
}

#: Not-yet-migrated call sites, with the reason each is still here.
#: Every entry is a file Lane B does not own this round; each is a concrete,
#: named piece of work, not a permanent exemption.
ALLOWLIST: dict[str, str] = {
    # Approach-pose geometry. Owned by nobody this round; three sites.
    "navigation/approach.py": "safe_approach_pose geometry — migrate with the approach card",
    # Frustum query origin. One site.
    "navigation/semantic_map.py": "ObservationSemanticMap.query frustum origin",
    # InstructNav recovery helpers: memory ingest origin + the SAME
    # position[2]-as-yaw defect pinned in pose.legacy_position_yaw.
    "navigation/instructnav_recovery.py": "memory-ingest origin + legacy position[2] yaw read",
    # StubNavigator point-goal fallback — the degraded controller.
    "navigation/models/__init__.py": "StubNavigator point-goal fallback",
}


#: The seam's own accessor names. A pose read *inside* one of these IS the
#: seam, wherever the function lives — including the small fallback copies
#: ``pipeline.py`` must carry for frozen BARN bundles that ship a pre-seam
#: ``base.py``. The rule is "no pose reads outside the seam", not "no pose
#: reads outside two files".
SEAM_FUNCTIONS = frozenset({"pose_in", "legacy_yaw", "_pose_in", "_legacy_yaw"})


def _seam_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in SEAM_FUNCTIONS
        ):
            ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _reads(path: Path) -> list[tuple[int, str]]:
    """Every ``<obs-ish>.position`` / ``.heading_deg`` read in one file."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seam_ranges = _seam_line_ranges(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in POSE_FIELDS:
            continue
        if any(start <= node.lineno <= end for start, end in seam_ranges):
            continue
        receiver = node.value
        # Only flag reads off something that is plainly an observation; this
        # rule is about the navigation observation contract, not every object
        # in the tree that happens to own a ``position`` field.
        source = ast.unparse(receiver)
        lowered = source.lower()
        if "observation" not in lowered and not lowered.split(".")[-1].startswith("obs"):
            continue
        found.append((node.lineno, f"{source}.{node.attr}"))
    return found


def _all_reads() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        hits = _reads(path)
        if hits:
            out[path.relative_to(SRC).as_posix()] = hits
    return out


def test_no_direct_pose_reads_outside_the_seam_or_the_allowlist() -> None:
    offenders = {
        name: hits
        for name, hits in _all_reads().items()
        if name not in SEAM and name not in ALLOWLIST
    }
    assert offenders == {}, (
        "direct observation-pose reads outside parcel_robot.pose: "
        f"{offenders}. Route them through pose.observation_pose(observation, frame) "
        "and name the REP-105 frame, or add the file to ALLOWLIST with a reason."
    )


@pytest.mark.parametrize("name", sorted(ALLOWLIST))
def test_allowlist_entries_still_have_a_direct_read(name: str) -> None:
    """The allowlist must shrink. An entry with nothing left to excuse is stale."""

    hits = _all_reads().get(name, [])
    assert hits, (
        f"{name} is on the pose allowlist but has no direct pose read left — "
        "delete the entry; the migration for that file is done."
    )


def test_the_migrated_consumers_are_actually_clean() -> None:
    """Pin the files Lane B migrated: a regression here is a silent un-migration."""

    reads = _all_reads()
    for migrated in ("navigation/pipeline.py", "navigation/grid_navigator.py"):
        assert migrated not in reads, f"{migrated} regained a direct pose read"


def test_every_migrated_pose_read_names_its_frame() -> None:
    """``pose_in``/``_pose_in`` is never called without an explicit frame."""

    for name in ("navigation/pipeline.py", "navigation/grid_navigator.py"):
        path = SRC / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"_pose_in", "pose_in"}
        ]
        assert calls, f"{name} makes no seam pose read at all"
        for call in calls:
            assert len(call.args) == 2, f"{name}:{call.lineno} pose read without a frame"
            frame = ast.unparse(call.args[1])
            assert frame in {"MAP_FRAME", "ODOM_FRAME"}, (
                f"{name}:{call.lineno} reads pose in an unnamed frame {frame!r}"
            )
