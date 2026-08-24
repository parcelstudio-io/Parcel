"""AST ratchet: no new literals from the retired embodiment families.

Plain :mod:`ast`, not a ruff plugin — the plan's anti-goals forbid a magic-number
lint, and a lint cannot tell "0.35 is a robot radius" from "0.35 is a
dimensionless comfort scale". This walker scans a fixed set of navigation /
embodiment modules for float constants belonging to the retired families and
compares them against an explicit **shrinking allowlist**.

Two directions are both red:

* a *new* occurrence (a file/value pair that is not allowlisted, or a count
  above its cap) — someone re-introduced a hardcoded family member;
* a *stale* entry (a count below its cap) — someone migrated a site and did not
  tighten the ratchet. Lower the number in :data:`ALLOWLIST`; that edit is the
  visible record that a family shrank.

Files Lane A does not own are allowlisted wholesale with their family tag and
their current owner, which is exactly the migration backlog.
"""

from __future__ import annotations

import ast
import pathlib
from collections import Counter

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "parcel_robot"

#: Card P0-E (scrum/20260822/task_5): the literal ratchet is an evidence guard
#: over the retired constant families, not a product guard. It now runs in the
#: nightly tier with the other ratchets; a new family literal still reddens
#: there, and the shrinking allowlist keeps its one-way semantics.
pytestmark = pytest.mark.slow

#: The retired families, by literal value. ``0.32``/``0.35`` are F-robot-radius
#: (the audit's "one literal, two values"); ``1.2``/``1.25`` are F-proximity
#: (six copies, one drift live); ``1.32`` is F-arrival (the stand-off composite
#: that embedded 0.32 by value).
RETIRED_FAMILY_VALUES: dict[float, str] = {
    0.32: "F-robot-radius",
    0.35: "F-robot-radius",
    1.2: "F-proximity",
    1.25: "F-proximity",
    1.32: "F-arrival",
}

#: Modules that *are* the authority. A retired-family value written here is the
#: single definition, not a duplicate, so they are not scanned.
AUTHORITY_MODULES: frozenset[str] = frozenset(
    {
        "authority.py",
        "core/authority.py",
        "robot_profile.py",
    }
)


def scanned_files() -> list[pathlib.Path]:
    """Navigation + embodiment + PERCEPTION surface, minus the authority modules.

    ``camera_channel`` / ``detection_adapter`` were added 2026-08-10 (lane E3).
    They landed during task_15 carrying safety-adjacent clearances written as bare
    literals — ``camera_channel/ingress.py`` duplicated ``arrival_radius_m``,
    ``target_surface_clearance_m`` and the footprint radius that
    ``DEFAULT_STAND_OFF_ENVELOPE`` already owns — and this scanner never looked at
    them, so nothing watched the new pixel surface. Fable's independent audit
    caught it (``scrum/20260809/task_15/AUDIT_FABLE_INDEPENDENT.md``). The rule is
    that any tree stamping metadata the navigator consumes gets scanned.
    """

    candidates = sorted(PACKAGE_ROOT.glob("navigation/*.py"))
    candidates += sorted(PACKAGE_ROOT.glob("camera_channel/*.py"))
    candidates += sorted(PACKAGE_ROOT.glob("detection_adapter/*.py"))
    candidates += [
        PACKAGE_ROOT / "geometry.py",
        PACKAGE_ROOT / "robot_profile.py",
        PACKAGE_ROOT / "simulation" / "headless_city.py",
        PACKAGE_ROOT / "simulation" / "mujoco_lidar.py",
        PACKAGE_ROOT / "sim.py",
        PACKAGE_ROOT / "instructnav" / "scoring.py",
        PACKAGE_ROOT / "perception" / "city_semantics.py",
    ]
    keep = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        if relative in AUTHORITY_MODULES:
            continue
        keep.append(path)
    return keep


def _literal_counts(path: pathlib.Path) -> Counter[float]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: Counter[float] = Counter()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and type(node.value) is float
            and node.value in RETIRED_FAMILY_VALUES
        ):
            found[node.value] += 1
    return found


def literal_lines(path: pathlib.Path, value: float) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is float and node.value == value
    )


#: ``(module path relative to parcel_robot, value) -> (cap, family, owner, why)``
#:
#: Census taken 2026-08-07 by this scanner. Every entry is a migration backlog
#: item except the two tagged ``not-a-radius``, which are genuinely different
#: quantities that happen to share the literal 0.35.
ALLOWLIST: dict[tuple[str, float], tuple[int, str, str, str]] = {
    # --- Lane A owns these; the residue is deliberate ----------------------
    # --- AWARE-1 (scrum/20260823/task_4) owns this one; a yaw RATE ------------
    ("navigation/awareness_sweep.py", 0.35): (
        1,
        "not-a-radius",
        "AWARE-1",
        "sweep_vyaw default in rad/s — the idle head-turn yaw rate, not a body radius",
    ),
    ("navigation/approach.py", 0.35): (
        1,
        "not-a-radius",
        "Lane A",
        "upper clamp on the arrival_radius_m metadata read, not a body radius",
    ),
    ("navigation/collision.py", 0.35): (
        1,
        "not-a-radius",
        "Lane A",
        "CollisionPolicy.slow_scale is dimensionless",
    ),
    ("simulation/headless_city.py", 1.2): (
        1,
        "F-proximity",
        "Lane A (deferred)",
        (
            "_reactive_safety_from_store obstacle_slow_m config default; this "
            "round was scoped to the default-argument fix in this file"
        ),
    ),
    ("navigation/collision.py", 1.2): (
        2,
        "F-proximity",
        "coordinator",
        (
            "_FrozenBundleEnvelope pins the exact Go2-scale values for frozen "
            "BARN bundles that predate parcel_robot.authority; these literals "
            "exist BECAUSE the derivation is unavailable there. The live path "
            "still derives from DEFAULT_SAFETY_ENVELOPE — the fallback class "
            "is unreachable when the authority module imports."
        ),
    ),
    # --- other lanes: the migration backlog --------------------------------
    ("navigation/pipeline.py", 0.32): (
        5,
        "F-robot-radius",
        "pipeline owner",
        "forbidden file this round",
    ),
    ("navigation/pipeline.py", 0.35): (
        6,
        "F-robot-radius",
        "pipeline owner",
        "forbidden file this round",
    ),
    ("navigation/pipeline.py", 1.2): (
        1,
        "F-proximity",
        "pipeline owner",
        "forbidden file this round",
    ),
    ("navigation/grid_navigator.py", 0.35): (
        1,
        "F-robot-radius",
        "grid_navigator owner",
        "forbidden file this round",
    ),
    ("navigation/follow.py", 0.35): (
        4,
        "F-robot-radius",
        "unassigned",
        (
            "FollowConfig max_vx / staging_lookahead_rad / heading_smoothing_alpha "
            "/ a yaw-error threshold — mixed meanings, needs a read first"
        ),
    ),
    ("navigation/follow.py", 1.2): (
        1,
        "F-proximity",
        "unassigned",
        "FollowConfig.yaw_gain — not a distance",
    ),
    # ("navigation/follow.py", 1.25) — RESOLVED 2026-08-07 (card F-2,
    # LANE_A_STATUS.md H-1). ``FollowConfig.obstacle_slow_m`` was the last of
    # the six ``obstacle_slow_m`` copies still carrying 1.25 while the other
    # five carried 1.2; it now reads
    # ``DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m``. The entry is deleted
    # rather than capped at 0 because the ratchet's two-way rule wants the
    # shrink visible in the diff, and a zero-cap entry would be indistinguishable
    # from a site that was never there. Paired FOLLOW_BENCH_V1 evidence (shipped
    # features, all 11 scenarios, before/after): follow 9/9 -> 9/9, navigate
    # 2/2 -> 2/2, hard collisions 0 -> 0, pedestrian contacts 0 -> 0,
    # min pedestrian surface 0.35211 m unchanged, reactive gate stops 4 -> 4;
    # the only movement is mean_band_fraction 0.74056 -> 0.74334 (+0.00278),
    # entirely from ``follow_turn_corner`` 0.4375 -> 0.4625, and
    # mean RMS commanded jerk 0.6031 -> 0.6046. Recorded in
    # scrum/20260807/task_2/NAV_FINISH_STATUS.md. (The ledger rows those runs
    # wrote were reverted: appending one moves a duplex pin, which reads the
    # latest shipped row -- see the same record.)
    # ("navigation/reactive_safety.py", 1.2) — RESOLVED 2026-08-09 (card S-B).
    # ReactiveSafetyPolicy.obstacle_slow_m / person bands now derive from
    # DEFAULT_SAFETY_ENVELOPE; the 1.2 literal is gone. Entry deleted so the
    # ratchet's shrink is visible (same discipline as follow.py 1.25 above).
    ("navigation/dynamic_costs.py", 0.35): (
        1,
        "F-robot-radius",
        "unassigned",
        "dynamic-agent Gaussian parameter, not a body radius",
    ),
    ("navigation/dynamic_layer.py", 0.35): (
        2,
        "F-robot-radius",
        "unassigned",
        "dynamic-agent Gaussian parameters",
    ),
    ("navigation/traffic_aware.py", 0.35): (
        3,
        "F-robot-radius",
        "unassigned",
        "dynamic-agent Gaussian parameters",
    ),
    ("navigation/search.py", 0.35): (
        1,
        "F-robot-radius",
        "unassigned",
        "semantic-search yaw rate, not a body radius",
    ),
    ("perception/city_semantics.py", 0.32): (
        2,
        "F-robot-radius",
        "Lane C (vocabulary/sidecar)",
        "scene-metadata stamps; should read the profile once the sidecar lands",
    ),
    ("perception/city_semantics.py", 1.25): (
        1,
        "F-proximity",
        "Lane C (vocabulary/sidecar)",
        (
            "non_target_obstacle_clearance_m — READ 2026-08-07 (card F-2) and "
            "deliberately NOT resolved with follow.py's 1.25: it is a different "
            "quantity in a different family. follow.py's was the obstacle "
            "comfort/slow BAND (SafetyEnvelope.obstacle_comfort_band_m). This "
            "one is a centre-to-surface STAND-OFF composite that "
            "approach.py::safe_approach_pose defaults to "
            "footprint(0.32) + obstacle_stop(0.8) + arrival_radius(0.06) + 0.05 "
            "= 1.23; the scene stamps 1.25, i.e. the composite plus 0.02 of "
            "commissioning margin. Deriving it belongs to the StandOffEnvelope "
            "family, not to obstacle_comfort_band_m, and it is a scene-metadata "
            "value whose owner is the sidecar"
        ),
    ),
    # --- perception surface: census taken 2026-08-10 (lane E3) --------------
    ("camera_channel/ingress.py", 1.25): (
        1,
        "F-proximity",
        "Lane C (vocabulary/sidecar)",
        (
            "non_target_obstacle_clearance_m stamped on PIXEL candidates, the "
            "twin of city_semantics.py's 1.25 above and owned with it. It cannot "
            "derive without breaking oracle/pixel parity: the authority's "
            "canonical association DEFAULT_STAND_OFF_ENVELOPE.stand_off(0.0) is "
            "1.2200000000000002, so composite + 0.03 commissioning margin is "
            "1.2500000000000002 != the 1.25 city_semantics stamps, and a pixel "
            "candidate would compare unequal to a GT-oracle candidate for the "
            "same object. Reassociating the sum until it lands on 1.25 would be "
            "derivation theatre. Retire both copies together when the sidecar "
            "owns the stamp. The other three ingress clearances (arrival_radius, "
            "target_surface_clearance, terminal_support = footprint radius) DO "
            "derive from DEFAULT_STAND_OFF_ENVELOPE as of 2026-08-10"
        ),
    ),
    ("camera_channel/d455.py", 0.35): (
        1,
        "not-a-radius",
        "camera_channel owner",
        (
            "MOUNT_HEIGHT_M — the D455 rig's height above ground on the Go2 head "
            "mount. A camera extrinsic in the Z axis, not a body footprint "
            "radius; it shares the literal by coincidence of dog geometry"
        ),
    ),
    ("camera_channel/frames.py", 0.35): (
        4,
        "not-a-radius",
        "camera_channel owner",
        (
            "mount_height_m defaults on ColorFrameMeta / DepthFrameMeta / "
            "SegFrameMeta plus default_color_meta's keyword — the same camera "
            "extrinsic as d455.py MOUNT_HEIGHT_M. Should read that one symbol "
            "rather than re-defaulting four times, which is the camera_channel "
            "owner's cleanup, not an authority-family migration"
        ),
    ),
    ("detection_adapter/metric_localizer.py", 0.35): (
        3,
        "not-a-radius",
        "detection_adapter owner",
        (
            "parallax_sigma_m is a bearing-triangulation uncertainty in metres, "
            "and the two camera_height_m keyword defaults are the same camera "
            "extrinsic as camera_channel; none is a body radius"
        ),
    ),
}


def measured_counts() -> dict[tuple[str, float], int]:
    measured: dict[tuple[str, float], int] = {}
    for path in scanned_files():
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        for value, count in _literal_counts(path).items():
            measured[(relative, value)] = count
    return measured


def test_the_scanner_actually_scans_something() -> None:
    """Guard against a silent no-op (a glob that stops matching is not a pass)."""

    files = scanned_files()
    assert len(files) >= 20
    assert any(path.name == "collision.py" for path in files)
    assert not any(path.name == "authority.py" for path in files)


def test_the_scanner_covers_the_pixel_surface() -> None:
    """The task_15 blind spot, stated as an assertion.

    ``camera_channel`` and ``detection_adapter`` stamp the metadata the navigator
    plans and verifies arrival with. A glob that stops matching them is the exact
    failure this ratchet had, so the coverage is asserted rather than assumed.
    """

    relatives = {path.relative_to(PACKAGE_ROOT).as_posix() for path in scanned_files()}

    assert "camera_channel/ingress.py" in relatives
    assert "detection_adapter/pixel_detections.py" in relatives
    assert sum(name.startswith("camera_channel/") for name in relatives) >= 4
    assert sum(name.startswith("detection_adapter/") for name in relatives) >= 8


def test_the_pixel_candidate_clearances_derive_from_the_authority() -> None:
    """The three derivable ingress clearances read the envelope, by AST.

    Value equality alone would pass a re-hardcoded ``0.06``. Two of these three
    values (``0.06``, ``0.8``) are not even in :data:`RETIRED_FAMILY_VALUES`, so
    the counting ratchet above cannot see them either. This checks the *form* of
    the assignment: an attribute read off ``DEFAULT_STAND_OFF_ENVELOPE``, never a
    constant. Re-hardcode any of them and this reddens.
    """

    from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
    from parcel_robot.camera_channel import ingress

    expected = {
        "_PIXEL_ARRIVAL_RADIUS_M": DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m,
        "_PIXEL_TARGET_MIN_SURFACE_CLEARANCE_M": (
            DEFAULT_STAND_OFF_ENVELOPE.target_surface_clearance_m
        ),
        "_PIXEL_TERMINAL_SUPPORT_CLEARANCE_M": DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m,
    }

    source = pathlib.Path(ingress.__file__).read_text(encoding="utf-8")
    assigned: dict[str, ast.expr] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value

    for name, authority_value in expected.items():
        # Same number as the GT-oracle path stamps, bit-for-bit.
        assert getattr(ingress, name) == authority_value

        value = assigned.get(name)
        assert value is not None, f"{name} is not a module-level assignment"
        assert not isinstance(value, ast.Constant), (
            f"{name} is hardcoded again — derive it from DEFAULT_STAND_OFF_ENVELOPE"
        )
        assert "DEFAULT_STAND_OFF_ENVELOPE" in ast.unparse(value), (
            f"{name} must read the stand-off authority, got {ast.unparse(value)}"
        )


def test_no_new_retired_family_literals() -> None:
    """Every retired-family literal is either migrated or explicitly allowlisted."""

    violations: list[str] = []
    for key, count in sorted(measured_counts().items()):
        relative, value = key
        entry = ALLOWLIST.get(key)
        if entry is None:
            violations.append(
                f"{relative}: {count}x {value!r} ({RETIRED_FAMILY_VALUES[value]}) is not "
                f"allowlisted — derive it from parcel_robot.authority, or add an "
                f"entry with its family tag and owner. Lines: "
                f"{literal_lines(PACKAGE_ROOT / relative, value)}"
            )
            continue
        cap = entry[0]
        if count > cap:
            violations.append(
                f"{relative}: {count}x {value!r} exceeds the allowlisted cap of {cap} "
                f"({entry[1]}, owner {entry[2]}). Lines: "
                f"{literal_lines(PACKAGE_ROOT / relative, value)}"
            )
    assert not violations, "retired-family literal drift:\n" + "\n".join(violations)


def test_allowlist_is_not_stale_the_ratchet_only_turns_one_way() -> None:
    """A migrated site must be removed from the allowlist in the same change."""

    measured = measured_counts()
    stale: list[str] = []
    for key, entry in sorted(ALLOWLIST.items()):
        relative, value = key
        count = measured.get(key, 0)
        cap = entry[0]
        if count < cap:
            stale.append(
                f"{relative}: {value!r} is now {count}x but the allowlist still caps "
                f"it at {cap}. Lower the cap (or delete the entry) — the ratchet "
                f"records the shrink."
            )
    assert not stale, "stale allowlist entries:\n" + "\n".join(stale)


def test_the_migrated_files_carry_zero_family_literals() -> None:
    """What Lane A actually migrated this round, stated as an assertion."""

    measured = measured_counts()
    for relative in (
        "instructnav/scoring.py",
        "simulation/mujoco_lidar.py",
        "geometry.py",
        "sim.py",
        "navigation/proxemic_approach.py",
    ):
        found = {key: count for key, count in measured.items() if key[0] == relative}
        assert not found, f"{relative} should be fully derived, found {found}"


def test_collision_and_approach_hold_only_the_documented_non_radius_residue() -> None:
    measured = measured_counts()
    assert measured.get(("navigation/collision.py", 0.35)) == 1
    # The two 1.2s are the _FrozenBundleEnvelope fallback for frozen BARN
    # bundles that predate parcel_robot.authority — deliberately literal
    # because the derivation is unavailable there (see ALLOWLIST entry).
    assert measured.get(("navigation/collision.py", 1.2)) == 2
    assert measured.get(("navigation/approach.py", 1.2)) is None
    assert measured.get(("navigation/approach.py", 0.32)) is None


@pytest.mark.parametrize("key", sorted(ALLOWLIST))
def test_every_allowlist_entry_names_a_family_and_an_owner(key: tuple[str, float]) -> None:
    cap, family, owner, why = ALLOWLIST[key]
    assert cap >= 1
    assert family in {*RETIRED_FAMILY_VALUES.values(), "not-a-radius"}
    assert owner.strip()
    assert len(why) > 20
