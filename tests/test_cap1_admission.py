"""Card CAP-1 — the four doors, checked against each other.

Week 1 shipped the same defect four times: a feature complete at its mechanism
and dead at its door. The guards below are pre-registered in
``scrum/20260822/task_31/PREREGISTRATION.md`` and each one is seeded RED against
the PRODUCT on a scratch copy of ``src/`` — never against the test.

* **G1** every behavior name the hosted broker routes to is admitted by the real
  ``SafetySupervisor`` (ROAM-1 finding 1: ``Unknown behavior: roam``);
* **G2** every config section a runtime region reads is loadable by a profile
  overlay (ROAM-1 finding 6: the ``roam:`` block the loader refused);
* **G3** every motion tool has exactly one proactive verdict;
* **G4** the candidate source bound at startup is the one the YAML names — the
  backlog's "a YAML value can disable the demo POI oracle while the
  process-global semantic candidate source remains the default oracle".

Plus the startup-fatal ``required_capabilities:`` check, measured through
``RobotRuntime.start()`` in three arms (refuses / starts / inert).

Offline. Nothing here starts a simulator, opens a socket, spends on a hosted
model, or opens the owner's ``parcel_memory.sqlite3``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from parcel_robot import admission
from parcel_robot.admission import (
    DOMAIN_BEHAVIOR,
    DOMAIN_CAPABILITY,
    DOMAIN_CONFIG_KEY,
    DOMAIN_PROACTIVE_MOTION,
    DOMAIN_TOOL,
    CapabilityRefused,
)
from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import ToolCall, VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.safety import BEHAVIOR_MODES, SafetySupervisor

REPO = Path(__file__).resolve().parents[1]
DEFAULT_NAV_CONFIG = REPO / "configs" / "navigation" / "default.yaml"


# ======================================================================
# G1 — the supervisor's allowlist vs the broker's tool table
# ======================================================================


def test_g1_every_behavior_the_broker_routes_to_is_in_the_supervisors_allowlist() -> None:
    """ROAM-1 finding 1, as a standing guard.

    The routes are DERIVED from ``tool_broker.py`` by AST rather than restated
    here, because the defect was precisely that nobody thought to write the row
    down: the card wired ``TOOL_ROAM`` through the right door and the allowlist
    behind that door had never heard of ``roam``.
    """

    scan = admission.broker_scan()
    routes = scan.routes
    assert routes, "no behavior routes derived from tool_broker.py"

    # THE CARD'S OWN BLIND SPOT, closed (verifier, correction pass). A door call
    # the derivation cannot read used to be ABSENT rather than flagged, so a
    # route written across two statements —
    #
    #     call = ToolCall("set_behavior", {"mode": "fetch"})
    #     allowed = self._validated(call, TOOL_FETCH_BALL)
    #
    # — left the tool row saying ``admitted`` with the "validated as ..." phrase
    # merely missing, and this guard stayed GREEN on a tool as dead at the
    # supervisor as ``roam`` was. A formatting choice decided whether the
    # headline guard fired on the headline defect class. It cannot now.
    assert not scan.unreadable, (
        "tool_broker.py has door calls this cross-check cannot read, so the "
        "behavior names behind them are UNCHECKED: "
        + "; ".join(f"{site.source}:{site.lineno} {site.detail}" for site in scan.unreadable)
    )

    # Coverage, not one tool. Every tool the broker answers must be visible at
    # some door — a de-inlined route makes a tool vanish from this map, and the
    # motion subset is the half where vanishing is a body that moves without the
    # supervisor having been asked.
    from parcel_robot.realtime.tool_broker import BROKER_TOOLS, MOTION_TOOLS

    doors = scan.doors_by_tool()
    assert set(BROKER_TOOLS) <= set(doors), (
        "these tools reach no derivable supervisor door: "
        f"{sorted(set(BROKER_TOOLS) - set(doors))}"
    )
    assert set(MOTION_TOOLS) <= set(doors), (
        "a MOTION tool with no derivable door: "
        f"{sorted(set(MOTION_TOOLS) - set(doors))}"
    )

    # The two behavior doors the broker uses, and both are covered.
    assert {route.door for route in routes} == {"set_behavior", "run_spatial_behavior"}

    spatial = admission.supervisor_spatial_behaviors()
    unknown: list[str] = []
    for route in routes:
        if route.door == "set_behavior" and route.behavior not in BEHAVIOR_MODES:
            unknown.append(f"{route.tool} -> set_behavior(mode={route.behavior!r})")
        if route.door == "run_spatial_behavior" and route.behavior not in spatial:
            unknown.append(f"{route.tool} -> run_spatial_behavior({route.behavior!r})")
    assert not unknown, (
        "hosted tools route to behavior names the SafetySupervisor does not admit; "
        "the tool is dead on the product path: " + ", ".join(unknown)
    )

    # The week-1 tool specifically, so the guard is anchored to the incident.
    assert {"roam", "roam_stop"} <= set(BEHAVIOR_MODES)
    assert {route.behavior for route in routes if route.tool == "roam"} == {
        "roam",
        "roam_stop",
    }


def test_g1_the_real_supervisor_approves_every_routed_mode() -> None:
    """The same property through the PRODUCT door, not a set-membership check.

    ROAM-1's broker tests used a stub validator that approved everything, which
    is why they could not see the refusal. So this constructs the real
    ``SafetySupervisor`` and asks it.
    """

    supervisor = SafetySupervisor(poses={}, skill_ids=[])
    refused: list[str] = []
    for route in admission.broker_behavior_routes():
        if route.door != "set_behavior":
            continue
        result = supervisor.validate(ToolCall("set_behavior", {"mode": route.behavior}))
        if not result.accepted:
            refused.append(f"{route.tool}: {result.message}")
    assert not refused, "the product supervisor refuses a routed behavior: " + ", ".join(
        refused
    )

    # And the door still refuses what it always refused: this card adds no
    # permission, so an invented mode is still unknown.
    denied = supervisor.validate(ToolCall("set_behavior", {"mode": "wander_off"}))
    assert not denied.accepted
    assert "Unknown behavior" in denied.message


def test_g1_the_admission_table_names_the_tool_that_would_be_dead() -> None:
    """A refused behavior row must say WHICH tool dies, not merely that one does."""

    entries = [row for row in admission.admitted() if row.domain == DOMAIN_BEHAVIOR]
    assert entries
    assert all(row.admitted for row in entries), [row.reason for row in entries if not row.admitted]
    roam = next(row for row in entries if row.name == "roam")
    assert "roam" in roam.reason
    assert roam.source == "safety.BEHAVIOR_MODES"


# ======================================================================
# G2 — the config sections a runtime region reads vs the overlay loader
# ======================================================================


def test_g2_every_config_section_a_runtime_region_reads_is_overlay_loadable() -> None:
    """ROAM-1 finding 6, as a standing guard.

    ``_roam_limits`` read ``store.section("roam")`` while ``check_overlay_keys``
    refused a ``roam:`` block, so the knob existed and no operator could ever
    set it. The base config is SHA-locked, so "the base defines it" and "the
    loader may introduce it" are the only two ways a section can be reachable.
    """

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS
    from parcel_robot.paths import resolve_config_yaml

    sections = admission.runtime_config_sections()
    assert "roam" in sections and "navigation" in sections, sections

    base = yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}
    unreachable = [
        name
        for name in sections
        if name not in base and name not in OVERLAY_INTRODUCIBLE_KEYS
    ]
    assert not unreachable, (
        "a runtime region reads these config sections, the SHA-locked base does not "
        "define them, and no profile overlay may introduce them — the knobs cannot "
        f"be turned: {unreachable}"
    )


def test_g2_the_shipped_prototype_overlay_still_loads() -> None:
    """The other half: the loader must actually accept the shipped profile.

    A membership check over key names would pass while the real file refused for
    a reason the names do not carry, so the file is loaded through the product
    loader.
    """

    from parcel_robot.config import ConfigStore
    from parcel_robot.paths import resolve_config_yaml

    store = ConfigStore(resolve_config_yaml(), profile="prototype")
    assert store.overlay_path is not None
    assert store.section("roam"), "the prototype overlay's roam block did not merge"


def test_g2_config_key_rows_carry_the_reason_and_the_door() -> None:
    rows = {row.name: row for row in admission.admitted() if row.domain == DOMAIN_CONFIG_KEY}
    assert rows
    assert "OVERLAY_INTRODUCIBLE_KEYS" in rows["roam"].reason
    assert "configs/robot.yaml" in rows["navigation"].reason
    # Every section the RUNTIME REGIONS read is admitted; the table is wider
    # than that (see the survey test below), and the difference is a finding.
    for name in admission.runtime_config_sections():
        assert rows[name].admitted, (name, rows[name].reason)


def test_g2_the_section_derivation_reads_every_call_site() -> None:
    """The same blind spot as G1's, on the config half.

    ``store.section("ro" + "am")`` used to be skipped in silence, which would
    have made the whole guard a formatting preference. Both receiver shapes are
    matched now — ``self.store`` and a bare local ``store`` — which is also what
    makes "this guard covers its own author" true: ``admission.py`` reads
    ``store.section("navigation")`` through a local name.
    """

    for sources in (
        admission._RUNTIME_REGION_SOURCES,
        admission._PRODUCT_CONFIG_SOURCES,
    ):
        scan = admission.config_section_scan(sources)
        assert not scan.unreadable, (
            "config sections are read with names this cross-check cannot resolve, "
            "so they are UNCHECKED against the overlay loader: "
            + "; ".join(f"{s.source}:{s.lineno}" for s in scan.unreadable)
        )

    # The guard covers its own author, provably: this module's own read is in
    # the derived set and it is written `store.section(...)`, not `self.store`.
    assert "navigation" in admission.runtime_config_sections()
    assert "store.section(" in (REPO / "src/parcel_robot/admission.py").read_text(
        encoding="utf-8"
    )


def test_the_product_survey_names_every_file_that_reads_a_config_section() -> None:
    """The static source list cannot silently go stale.

    ``_PRODUCT_CONFIG_SOURCES`` is a hand-written list rather than a glob because
    globbing would AST-parse 50+ modules on the first ``/api/state`` poll. The
    cost of that choice is exactly this test: a plain text scan of the package,
    failing the moment a new file reads a section and is not in the list.
    """

    package = REPO / "src" / "parcel_robot"
    reading = {
        str(path.relative_to(package)).replace("\\", "/")
        for path in package.rglob("*.py")
        if "store.section(" in path.read_text(encoding="utf-8")
    }
    missing = sorted(reading - set(admission._PRODUCT_CONFIG_SOURCES))
    assert not missing, (
        "these product files read a config section and are outside the survey, so "
        f"their keys are never checked against the overlay loader: {missing}"
    )


def test_the_wider_survey_finds_one_unreachable_section_and_names_it() -> None:
    """A finding this card REPORTS — owner: `web_panel.py` / the `config.py` door.

    Widening the survey past G2's pre-registered scope found ROAM-1 finding 6 a
    SECOND time, in the product launcher: ``web_panel.build_runtime`` reads
    ``store.section("planner_model")`` to decide whether to construct a separate
    planner LLM, and ``planner_model`` is absent from the SHA-locked
    ``configs/robot.yaml`` AND absent from ``OVERLAY_INTRODUCIBLE_KEYS``. So with
    no profile the block reads ``{}`` and the planner can never be enabled, and a
    profile that tries to set it makes the whole config load REFUSE.

    CAP-1 does not patch it: `web_panel.py` is not this card's OWNS and the fix
    is one entry in another card's frozenset. What is pinned here is that the
    set of unreachable sections is EXACTLY this one — so a second instance
    reddens, and so does the fix, which is the signal to delete this test.
    """

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS
    from parcel_robot.paths import resolve_config_yaml

    base = yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}
    unreachable = {
        name
        for name in admission.product_config_sections()
        if name not in base and name not in OVERLAY_INTRODUCIBLE_KEYS
    }
    assert unreachable == {"planner_model"}, (
        "the set of product-read config sections no overlay can introduce has "
        f"changed: {sorted(unreachable)}"
    )

    row = next(
        r
        for r in admission.admitted()
        if r.domain == DOMAIN_CONFIG_KEY and r.name == "planner_model"
    )
    assert row.admitted is False
    assert "can never be turned" in row.reason


# ======================================================================
# G3 — one proactive verdict per motion tool
# ======================================================================


def test_g3_the_proactive_sets_partition_the_motion_tools_exactly() -> None:
    from parcel_robot.realtime.config import (
        PROACTIVE_MOTION_ALLOWED,
        PROACTIVE_MOTION_REFUSED,
    )
    from parcel_robot.realtime.tool_broker import MOTION_TOOLS, PROACTIVE_MOTION_CEILING

    allowed, refused = set(PROACTIVE_MOTION_ALLOWED), set(PROACTIVE_MOTION_REFUSED)
    assert len(allowed) == len(PROACTIVE_MOTION_ALLOWED), "duplicate in the allowed tuple"
    assert len(refused) == len(PROACTIVE_MOTION_REFUSED), "duplicate in the refused tuple"
    assert not (allowed & refused), f"a tool with two verdicts: {sorted(allowed & refused)}"
    assert allowed | refused == set(MOTION_TOOLS), (
        "every motion tool needs exactly one proactive verdict; missing="
        f"{sorted(set(MOTION_TOOLS) - allowed - refused)} extra="
        f"{sorted((allowed | refused) - set(MOTION_TOOLS))}"
    )
    # The config-load door and the hand-constructed-broker ceiling must agree,
    # or a broker built in code admits what a YAML cannot.
    assert allowed == set(PROACTIVE_MOTION_CEILING)


def test_g3_the_table_flags_a_motion_tool_with_no_verdict() -> None:
    rows = {
        row.name: row for row in admission.admitted() if row.domain == DOMAIN_PROACTIVE_MOTION
    }
    assert rows["roam"].admitted is False
    assert "travel tool" in rows["roam"].reason
    assert rows["play_gesture"].admitted is True
    assert "in place" in rows["play_gesture"].reason


def test_the_tool_domain_covers_every_tool_the_broker_answers() -> None:
    from parcel_robot.realtime.tool_broker import BROKER_TOOLS

    rows = {row.name: row for row in admission.admitted() if row.domain == DOMAIN_TOOL}
    assert set(rows) == set(BROKER_TOOLS)
    assert "validated as set_behavior('roam')" in rows["roam"].reason
    assert "read-only surface" in rows["get_status"].reason


# ======================================================================
# The product path — G4 and the startup check
# ======================================================================


class _Backend:
    """The smallest backend a runtime can turn against. No simulator, no socket."""

    name = "cap1-fake"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend="cap1-fake",
            nearest_obstacle_m=10.0,
        )

    def observe(self) -> SimObservation:
        with self._lock:
            return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


@pytest.fixture
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture(autouse=True)
def _restore_process_globals(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The candidate source is a PROCESS global; leaking it would poison the suite.

    ``PARCEL_ONLINE_MAP_PATH`` is pinned to ``:memory:`` for the same reason the
    rest of the suite pins it: a learned-map arm must never touch a store on
    disk, and it must certainly never find the owner's.
    """

    monkeypatch.setenv("PARCEL_ONLINE_MAP_PATH", ":memory:")
    try:
        yield
    finally:
        from parcel_robot.perception_source import use_learned_map, use_semantic_source

        use_semantic_source(None)
        use_learned_map(None)


def _nav_config(
    tmp_path: Path,
    *,
    semantic_source: str | None = None,
    required: list[str] | None = None,
    name: str = "navigation.yaml",
) -> Path:
    """The shipped navigation profile with at most two keys moved.

    Built from ``configs/navigation/default.yaml`` rather than written from
    scratch so the arms differ from the shipping file only in what they claim
    to differ in.
    """

    data = yaml.safe_load(DEFAULT_NAV_CONFIG.read_text(encoding="utf-8")) or {}
    if semantic_source is not None:
        data.setdefault("perception", {})["semantic_source"] = semantic_source
    if required is not None:
        data[admission.REQUIRED_CAPABILITIES_KEY] = list(required)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _robot_config(
    tmp_path: Path,
    nav_config: Path,
    *,
    name: str = "robot.yaml",
    navigation_enabled: bool = False,
) -> Path:
    path = tmp_path / name
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: {str(navigation_enabled).lower()}
  config: {nav_config}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _runtime(config: Path, audio: AudioDeviceStatus) -> RobotRuntime:
    return RobotRuntime(config, _Backend(), language_model=None, audio_status=audio)


def test_g4_the_bound_candidate_source_is_the_one_the_yaml_names(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """The backlog's startup defect, as a standing guard, on the product path.

    "A YAML value can disable the demo POI oracle while the process-global
    semantic candidate source remains the default oracle. Treat that combination
    as a startup defect to close, not a usable shadow/cutover mode."
    """

    from parcel_robot.perception_source import active_semantic_source

    nav = _nav_config(tmp_path, semantic_source="learned_map")
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        runtime.start()
        bound = active_semantic_source()
        assert bound.source == "learned_map", (
            "the navigation profile names 'learned_map' but the process-global "
            f"candidate source is {bound.source!r} — this run reads the oracle"
        )
        assert bound.drives_from_learned_map is True
        assert bound.poi_grounding_enabled is False
    finally:
        runtime.close()


def test_g4_the_shipped_oracle_profile_binds_the_oracle(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """The other direction, so the guard is not one-sided."""

    from parcel_robot.perception_source import active_semantic_source

    nav = _nav_config(tmp_path, semantic_source="oracle")
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        runtime.start()
        bound = active_semantic_source()
        assert bound.source == "oracle"
        assert bound.poi_grounding_enabled is True
    finally:
        runtime.close()


def test_the_source_binding_now_follows_the_config_in_both_directions(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """This cell pinned a DEFECT until 2026-08-22; it now pins the fix.

    The defect CAP-1 reported: ``RobotRuntime._p1b_install_learned_map`` returns
    before it binds anything when the policy is ``oracle``, so the
    process-global source was never RESET. In a process that had already bound
    ``learned_map`` — a harness, an earlier runtime, an eval driver — a runtime
    whose YAML said ``oracle`` inherited the learned map and read a different
    map than its file described. CAP-1 is a view and did not change another
    card's binding, so what was pinned here was that the view SAW it.

    **Card VENUE-1 took the fix** (`scrum/20260822/task_16`, correction pass,
    routed by the verifier): `RobotRuntime._venue1_bind_semantic_source`, in
    VENUE-1's seam 1a at the top of `_attach_configured_camera_ingress`,
    asserts the configured policy on every started runtime — camera on or off,
    which is why that seam sits above C-1's early return. So the row is now
    True, and the profile that declares the capability starts.

    The guard is NOT retired by that, and the second half is why: the row still
    goes False the moment something rebinds the source behind the runtime's
    back, which is the only way the two can disagree now. A capability view
    that could never report a failure would be furniture.
    """

    from parcel_robot.perception_source import (
        SemanticSourcePolicy,
        active_semantic_source,
        use_semantic_source,
    )

    use_semantic_source(SemanticSourcePolicy(source="learned_map"))

    nav = _nav_config(tmp_path, semantic_source="oracle")
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        runtime.start()
        assert active_semantic_source().source == "oracle"
        rows = {
            row["name"]: row
            for row in runtime.snapshot()["admission"]["entries"]
            if row["domain"] == DOMAIN_CAPABILITY
        }
        assert rows["semantic_source_matches_config"]["admitted"] is True

        # ...and the view still reports a real divergence. Rebind underneath a
        # running runtime and the row tells the truth about the process rather
        # than repeating the file.
        use_semantic_source(SemanticSourcePolicy(source="learned_map"))
        rows = {
            row["name"]: row
            for row in runtime.snapshot()["admission"]["entries"]
            if row["domain"] == DOMAIN_CAPABILITY
        }
        row = rows["semantic_source_matches_config"]
        assert row["admitted"] is False
        assert "names 'oracle'" in row["reason"]
        assert "is 'learned_map'" in row["reason"]
    finally:
        runtime.close()
        use_semantic_source(SemanticSourcePolicy())

    # THE LAST HOP, taken (VENUE-1's handoff 9, back into CAP-1's region).
    #
    # VENUE-1 pinned this block as a FALSE REFUSAL and said so: the gate ran one
    # line BEFORE `_attach_configured_camera_ingress()`, which is where
    # `_venue1_bind_semantic_source()` lives, so a declaring profile was refused
    # for a disagreement the very next line was about to resolve. Their note
    # said taking the fix would turn this assertion red and that both cards
    # should be revisited together. It has been taken — the check now runs
    # AFTER the attach, i.e. after the LAST binder rather than after P1-B — so
    # the assertion is inverted here in the same spirit.
    #
    # This is the one path the card exists to make honest: a profile that says
    # what it needs, over a composition root that provides it, must START.
    use_semantic_source(SemanticSourcePolicy(source="learned_map"))
    declaring = _nav_config(
        tmp_path,
        semantic_source="oracle",
        required=["semantic_source_matches_config"],
        name="nav-declared.yaml",
    )
    runtime = _runtime(
        _robot_config(tmp_path, declaring, name="robot-declared.yaml"), audio_status
    )
    try:
        runtime.start()
        assert active_semantic_source().source == "oracle"
        table = runtime.snapshot()["admission"]
        assert table["required_capabilities"] == ["semantic_source_matches_config"]
        assert table["unmet_capabilities"] == []
    finally:
        runtime.close()
        use_semantic_source(SemanticSourcePolicy())

    # ...and the gate has NOT been softened into a rubber stamp: with nothing
    # binding the declared capability it still refuses, with the table. That is
    # `test_startup_refuses_when_a_declared_capability_is_not_bound` in full;
    # the one-line contrast is kept here so the pair reads together.
    unmet = _nav_config(
        tmp_path,
        semantic_source="oracle",
        required=["learned_map_source"],
        name="nav-unmet.yaml",
    )
    runtime = _runtime(
        _robot_config(tmp_path, unmet, name="robot-unmet.yaml"), audio_status
    )
    try:
        with pytest.raises(CapabilityRefused, match="learned_map_source"):
            runtime.start()
    finally:
        runtime.close()
        use_semantic_source(SemanticSourcePolicy())


def test_startup_refuses_when_a_declared_capability_is_not_bound(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """Arm A — the profile says it needs the learned map; the process bound the oracle.

    This is IG-3 narrowed to the concrete defect: a configuration-truth check at
    the door, with the admission table printed, instead of a run that quietly
    reads a different map than the file describes.
    """

    nav = _nav_config(
        tmp_path, semantic_source="oracle", required=["learned_map_source"]
    )
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        with pytest.raises(CapabilityRefused) as refusal:
            runtime.start()
    finally:
        runtime.close()
    message = str(refusal.value)
    assert "learned_map_source" in message
    # The table is printed, and it names the door each row was read from.
    assert "admission table:" in message
    assert "semantic_source_matches_config" in message
    assert "bound semantic source is 'oracle'" in message


def test_startup_accepts_the_same_declaration_with_the_learned_source_bound(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """Arm B — the same YAML, the capability actually bound, and it starts."""

    nav = _nav_config(
        tmp_path, semantic_source="learned_map", required=["learned_map_source"]
    )
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        runtime.start()
        snapshot = runtime.snapshot()["admission"]
        assert isinstance(snapshot, dict)
        assert snapshot["required_capabilities"] == ["learned_map_source"]
        assert snapshot["unmet_capabilities"] == []
    finally:
        runtime.close()


def test_the_check_holds_with_the_navigator_actually_constructed(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """Both arms again with ``navigation.enabled: true``.

    The arms above run with the navigator off, which is enough to exercise the
    source binding and the door. This one builds the real ``DirectiveNavigator``
    from the same file — model registry, POI arm and all — so the declaration is
    proved not to disturb the navigation config's own loader, and the refusal is
    proved to happen on a runtime that would otherwise have navigated.
    """

    refusing = _nav_config(
        tmp_path,
        semantic_source="oracle",
        required=["learned_map_source"],
        name="nav-refuse.yaml",
    )
    runtime = _runtime(
        _robot_config(tmp_path, refusing, name="robot-nav.yaml", navigation_enabled=True),
        audio_status,
    )
    try:
        with pytest.raises(CapabilityRefused):
            runtime.start()
    finally:
        runtime.close()

    starting = _nav_config(
        tmp_path,
        semantic_source="learned_map",
        required=["learned_map_source"],
        name="nav-start.yaml",
    )
    runtime = _runtime(
        _robot_config(tmp_path, starting, name="robot-nav2.yaml", navigation_enabled=True),
        audio_status,
    )
    try:
        runtime.start()
        assert runtime.snapshot()["admission"]["unmet_capabilities"] == []
    finally:
        runtime.close()


def test_startup_is_inert_when_nothing_is_declared(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """Arm D — the default. Nothing declared, nothing required, nothing changes.

    Standing rule 1 for this wave: no new fail-closed default at runtime. The
    shipped navigation profile declares nothing, so this check is a YAML read
    that has already happened and a return.
    """

    nav = _nav_config(tmp_path)
    assert admission.REQUIRED_CAPABILITIES_KEY not in yaml.safe_load(
        nav.read_text(encoding="utf-8")
    )
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        runtime.start()
    finally:
        runtime.close()

    # And the shipped files declare nothing either, so no tree in the repository
    # today changes behaviour because of this card.
    for shipped in sorted((REPO / "configs" / "navigation").glob("*.yaml")):
        loaded = yaml.safe_load(shipped.read_text(encoding="utf-8")) or {}
        assert admission.required_capabilities(loaded) == (), shipped


def test_an_unknown_required_capability_name_is_refused_by_name(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """A requirement nothing evaluates looks exactly like a requirement that was met."""

    nav = _nav_config(tmp_path, required=["learnd_map_source"])
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        with pytest.raises(CapabilityRefused) as refusal:
            runtime.start()
    finally:
        runtime.close()
    assert "learnd_map_source" in str(refusal.value)
    assert "registered capabilities are" in str(refusal.value)


def test_a_non_list_declaration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CapabilityRefused):
        admission.required_capabilities({"required_capabilities": "learned_map_source"})


# ======================================================================
# /api/state
# ======================================================================


def test_api_state_publishes_the_admission_table_and_the_curiosity_snapshot(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """The operator surface: why a tool or behavior is unavailable, on the panel.

    CURIO-1's ``curiosity_snapshot()`` had no product surface at all — its own
    docstring says so — and rides here. It is ABSENT rather than ``null`` when
    chatter is off, which is the same discipline C-1's ``camera_ingress`` key
    follows.
    """

    nav = _nav_config(tmp_path)
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        state = runtime.snapshot()
    finally:
        runtime.close()

    table = state["admission"]
    assert isinstance(table, dict)
    domains = {row["domain"] for row in table["entries"]}
    assert domains == {
        DOMAIN_BEHAVIOR,
        DOMAIN_TOOL,
        DOMAIN_PROACTIVE_MOTION,
        DOMAIN_CONFIG_KEY,
        DOMAIN_CAPABILITY,
    }
    assert every_row_has_a_reason(table["entries"])
    assert table["required_capabilities"] == []
    assert table["declaration_error"] is None
    assert "learned_map_source" in table["registered_capabilities"]

    # Chatter is off in this profile, so the key is absent, not null.
    assert "curiosity" not in state

    # The panel serves this dict as JSON. A row that cannot serialize would
    # break /api/state for everything else on it, so the wire is proved here
    # rather than assumed.
    import json

    assert json.loads(json.dumps(state))["admission"]["entries"]


def test_the_curiosity_key_appears_once_the_chatter_layer_exists(
    tmp_path: Path, audio_status: AudioDeviceStatus
) -> None:
    """The PRESENT branch of the `/api/state` region (verifier, correction pass).

    The absent branch was pinned and the present branch was not, which meant the
    delivery this card actually makes for CURIO-1 — a snapshot that had no
    product surface at all, its own docstring says so — was asserted nowhere.

    The layer is built through ``_curiosity_layer()``, CURIO-1's own lazy
    constructor and the seam its suite uses (``tests/test_curio1_chatter.py``
    ``_pin_gap``). What this proves is MY region: once the layer exists, the key
    is on the wire and it is CURIO-1's snapshot. Whether the chatter CONFIG
    enables the layer is CURIO-1's own property and its suite owns it.
    """

    nav = _nav_config(tmp_path)
    runtime = _runtime(_robot_config(tmp_path, nav), audio_status)
    try:
        assert "curiosity" not in runtime.snapshot()
        runtime._curiosity_layer()
        state = runtime.snapshot()
        assert state["curiosity"] == runtime.curiosity_snapshot()
        assert set(state["curiosity"]) >= {"scheduler", "counts", "pending", "said"}
        import json

        assert json.loads(json.dumps(state))["curiosity"] is not None
    finally:
        runtime.close()


def every_row_has_a_reason(rows: Any) -> bool:
    return all(str(row["reason"]).strip() and str(row["source"]).strip() for row in rows)


def test_the_table_is_a_view_and_never_raises_without_a_runtime() -> None:
    """``admitted()`` answers with no runtime attached — what makes G1–G3 cheap."""

    entries = admission.admitted()
    assert entries
    capability = {row.name for row in entries if row.domain == DOMAIN_CAPABILITY}
    assert set(admission.REGISTERED_CAPABILITIES) == capability
    rendered = admission.render_table(entries)
    assert "ok  " in rendered
