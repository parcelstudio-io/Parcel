"""Card P0-A — the prototype profile, its overlay loader, and one camera flag.

Three things are pinned here, and the FIRST of them is the one that matters:

1. **The default path did not move.** With no profile named anywhere, the
   resolved config mapping is exactly ``yaml.safe_load`` of ``configs/robot.yaml``
   and nothing else, and the shipped file's own bytes still match the sha256 the
   embodied-plan eval manifest locks. The whole point of a profile is to carry
   relaxations WITHOUT moving that digest, so a test that only proved the
   overlay works would have proved the less interesting half.
2. **The overlay merges and is validated by the same loaders.** Deep merge,
   overlay wins, lists replace; a named profile with no file refuses BY NAME
   (a typo at the command line, answered instead of absorbed).
3. **The camera GROUNDING gate, and only that.** ``perception.camera_ingress``,
   ``camera_ingress.enabled`` and ``PARCEL_CAMERA_INGRESS`` now resolve together
   in ``_camera_ingress_enabled`` instead of refusing each other at startup.
   They are NOT one flag: the C-1 stream attaches on the config key alone, so
   the env var moves grounding and not the stream — pinned in both directions by
   ``test_the_env_alias_reaches_grounding_only_not_the_stream`` so the docs
   cannot quietly overclaim again. Absent from all three is still OFF and still
   byte-identical to the oracle.
4. **A misspelled overlay key refuses.** ``agent.affect.minimum_confidenc: 0.5``
   used to merge cleanly, read as nothing, and boot at the shipped 0.75.

The person-standoff blocker is pinned too (``test_indoor_person_standoff_...``):
the card asked the overlay for ``person_stop_m: 0.7`` and the safety authority
floors it at 1.2, so the refusal is recorded as executable knowledge rather than
as a sentence in a status doc nobody greps.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SimObservation,
)
from parcel_robot.config import (
    OVERLAY_FREEFORM_PATHS,
    OVERLAY_INTRODUCIBLE_KEYS,
    PROFILE_ENV,
    ConfigStore,
    ProfileError,
    check_overlay_keys,
    deep_merge,
    profile_overlay_path,
    resolve_profile,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
ROBOT_YAML = REPO / "configs" / "robot.yaml"
PROTOTYPE_YAML = REPO / "configs" / "robot.prototype.yaml"
REALTIME_PROTOTYPE_EXAMPLE = REPO / "configs" / "realtime.prototype.yaml.example"
LAUNCHER = REPO / "scripts" / "launch_stack.sh"


def _digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file inherits a profile from the shell that ran pytest."""

    monkeypatch.delenv(PROFILE_ENV, raising=False)
    monkeypatch.delenv("PARCEL_CAMERA_INGRESS", raising=False)


# ---------------------------------------------------------------------------
# 1. the default path did not move
# ---------------------------------------------------------------------------


def test_no_profile_resolves_the_shipped_file_and_nothing_else() -> None:
    """Flag-off byte identity: the loader is transparent without a profile."""

    raw = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))
    store = ConfigStore(ROBOT_YAML)
    assert store.profile is None
    assert store.overlay_path is None
    assert store.data == raw
    assert _digest(store.data) == _digest(raw)


def test_an_ambient_profile_env_is_ignorable_by_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``profile=""`` means "the shipped configuration", environment or not."""

    monkeypatch.setenv(PROFILE_ENV, "prototype")
    store = ConfigStore(ROBOT_YAML, profile="")
    assert store.profile is None
    assert store.data == yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))


def test_the_overlay_did_not_move_the_sha_locked_shipped_config() -> None:
    """configs/robot.yaml still hashes to what the eval manifest locks.

    This is the reason the profile exists. It reads the EXISTING lock rather
    than adding one: if a future card edits configs/robot.yaml, this fails in
    the same breath as the eval that owns the digest, not instead of it.
    """

    manifest = json.loads(
        (REPO / "evals" / "companion" / "embodied_plan_v1" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    locked = manifest["locked_inputs"]["robot_config"]
    assert locked["path"] == "configs/robot.yaml"
    assert hashlib.sha256(ROBOT_YAML.read_bytes()).hexdigest() == locked["sha256"]


# ---------------------------------------------------------------------------
# 2. the overlay loader
# ---------------------------------------------------------------------------


def test_deep_merge_recurses_into_mappings_and_replaces_lists() -> None:
    base = {"a": {"x": 1, "y": 2}, "list": [1, 2, 3], "keep": "me"}
    overlay = {"a": {"y": 20, "z": 30}, "list": [9]}
    assert deep_merge(base, overlay) == {
        "a": {"x": 1, "y": 20, "z": 30},
        "list": [9],
        "keep": "me",
    }
    # The inputs are not mutated: a merge that edited the base in place would
    # make a second ConfigStore in the same process see the first one's profile.
    assert base == {"a": {"x": 1, "y": 2}, "list": [1, 2, 3], "keep": "me"}


def test_profile_overlay_path_is_a_sibling_of_the_base_config() -> None:
    assert profile_overlay_path("configs/robot.yaml", "prototype") == Path(
        "configs/robot.prototype.yaml"
    )
    assert profile_overlay_path("/opt/x/robot.yaml", "bench") == Path("/opt/x/robot.bench.yaml")


def _pair(tmp_path: Path, base: str, overlay: str | None) -> Path:
    path = tmp_path / "robot.yaml"
    path.write_text(base, encoding="utf-8")
    if overlay is not None:
        (tmp_path / "robot.demo.yaml").write_text(overlay, encoding="utf-8")
    return path


BASE_YAML = "safety:\n  person_stop_m: 1.2\n  person_slow_m: 2.5\nmetrics:\n  max_turns: 200\n"


def test_overlay_applies_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _pair(tmp_path, BASE_YAML, "safety:\n  person_slow_m: 3.0\n")
    monkeypatch.setenv(PROFILE_ENV, "demo")
    store = ConfigStore(path)
    assert store.profile == "demo"
    assert store.overlay_path == tmp_path / "robot.demo.yaml"
    # merged, not replaced: the untouched sibling key survives
    assert store.section("safety") == {"person_stop_m": 1.2, "person_slow_m": 3.0}
    assert store.section("metrics") == {"max_turns": 200}


def test_overlay_applies_through_the_keyword(tmp_path: Path) -> None:
    path = _pair(tmp_path, BASE_YAML, "metrics:\n  max_turns: 5\n")
    assert ConfigStore(path, profile="demo").section("metrics") == {"max_turns": 5}


def test_an_empty_overlay_is_a_no_op_not_an_error(tmp_path: Path) -> None:
    path = _pair(tmp_path, BASE_YAML, "# nothing but a comment\n")
    assert ConfigStore(path, profile="demo").data == yaml.safe_load(BASE_YAML)


def test_a_named_profile_with_no_file_refuses_by_name(tmp_path: Path) -> None:
    """Seeded RED: without the guard this starts the shipped config silently."""

    path = _pair(tmp_path, BASE_YAML, None)
    with pytest.raises(ProfileError, match=r"robot\.demo\.yaml does not exist"):
        ConfigStore(path, profile="demo")


def test_a_non_mapping_overlay_refuses(tmp_path: Path) -> None:
    path = _pair(tmp_path, BASE_YAML, "- not\n- a\n- mapping\n")
    with pytest.raises(ProfileError, match="must be a mapping"):
        ConfigStore(path, profile="demo")


@pytest.mark.parametrize("name", ["../evil", "a/b", ".hidden", "..", "with space"])
def test_a_profile_may_not_name_a_path(name: str) -> None:
    with pytest.raises(ProfileError, match="invalid config profile name"):
        ConfigStore(ROBOT_YAML, profile=name)


def test_resolve_profile_reads_argv_then_the_environment() -> None:
    assert resolve_profile(["--profile", "prototype"]) == "prototype"
    assert resolve_profile(["--config", "x", "--profile=bench"]) == "bench"
    assert resolve_profile([], {PROFILE_ENV: "prototype"}) == "prototype"
    assert resolve_profile(["--profile", "argv"], {PROFILE_ENV: "env"}) == "argv"
    assert resolve_profile([], {}) is None
    assert resolve_profile([], {PROFILE_ENV: "  "}) is None
    with pytest.raises(ProfileError, match="--profile requires a value"):
        resolve_profile(["--profile"])


# ---------------------------------------------------------------------------
# 2b. a misspelled overlay key is a refusal, not a no-op
# ---------------------------------------------------------------------------


def _real_base(tmp_path: Path, overlay: str) -> Path:
    """The SHIPPED schema as the base, plus an overlay beside it."""

    base = tmp_path / "robot.yaml"
    base.write_text(ROBOT_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "robot.demo.yaml").write_text(overlay, encoding="utf-8")
    return base


@pytest.mark.parametrize(
    ("overlay", "expected_path", "hint"),
    [
        pytest.param(
            "agent:\n  affect:\n    minimum_confidenc: 0.5\n",
            "agent.affect.minimum_confidenc",
            "minimum_confidence",
            id="nested-scalar-typo",
        ),
        pytest.param(
            "safety:\n  person_stop_mm: 0.7\n",
            "safety.person_stop_mm",
            "person_stop_m",
            id="section-key-typo",
        ),
        pytest.param(
            "perceptoin:\n  camera_ingress: true\n",
            "perceptoin",
            "perception",
            id="top-level-section-typo",
        ),
    ],
)
def test_a_misspelled_overlay_key_refuses_instead_of_booting_the_shipped_value(
    tmp_path: Path, overlay: str, expected_path: str, hint: str
) -> None:
    """Seeded RED: without the key walk, all three of these boot silently.

    Each one merges cleanly, adds a key nothing reads, leaves the real setting
    at its shipped value, and starts. The operator gets the production robot
    while the file on disk says otherwise — which is the failure this loader
    refuses to have everywhere else.
    """

    base = _real_base(tmp_path, overlay)
    with pytest.raises(ProfileError) as caught:
        ConfigStore(base, profile="demo")
    message = str(caught.value)
    assert f"unknown key '{expected_path}'" in message
    assert hint in message  # the "did you mean" is the whole point of the refusal


def test_the_shipped_prototype_overlay_passes_its_own_key_walk() -> None:
    """The guard must not refuse the profile it was written alongside."""

    base = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))
    overlay = yaml.safe_load(PROTOTYPE_YAML.read_text(encoding="utf-8"))
    check_overlay_keys(base, overlay, source="configs/robot.prototype.yaml")


def test_freeform_paths_accept_new_children() -> None:
    """Pose names, wifi-card names and owner facts are DATA, not schema."""

    base = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))
    assert OVERLAY_FREEFORM_PATHS == {"poses", "wifi_cards", "prompting.user_profile"}
    check_overlay_keys(
        base,
        {
            "poses": {"a_pose_nobody_shipped": {"joints": {}, "duration": 1.0}},
            "wifi_cards": {"bench": {"interface": "lo", "ros_domain_id": 4}},
            "prompting": {"user_profile": {"cat": "Mochi"}},
        },
    )
    # ...but the free-form exemption does not leak to their siblings.
    with pytest.raises(ProfileError, match="prompting.toolz"):
        check_overlay_keys(base, {"prompting": {"toolz": {"weather": True}}})


def test_introducible_keys_are_exactly_the_three_documented_families() -> None:
    """Every exemption is a real key with its own downstream validator.

    Card ROAM-1 adds the third family. The verdict is written here rather than
    inherited, which is what this test is for: the SHA-locked base omits a
    ``roam:`` section, so without the exemption the prototype overlay refuses
    to carry one — measured, and it is why the roam knobs were unreachable in
    ROAM-1's first pass.
    """

    base = yaml.safe_load(ROBOT_YAML.read_text(encoding="utf-8"))
    assert all(
        key.startswith(
            (
                "perception.camera_ingress",
                "camera_ingress",
                "roam",
                # ---- CARD VENUE-1: the fourth family, two scalars ----------
                # `camera_ingress` is the runtime's CONSENT to a camera;
                # `camera_backend` says WHICH ONE (mujoco/uvc/realsense/
                # recorded) and `detector` says who serves it. They are NOT in
                # the `camera_ingress*` family on purpose: that prefix is
                # `CameraStreamConfig.from_section`'s, and it REFUSES any
                # `camera_ingress*` key it does not know, so borrowing the
                # prefix would have made both of these a startup error. Their
                # values are validated where they are read — `camera_backend`
                # by P1-A's `resolve_backend_kind` (which lists the accepted
                # kinds) and `detector` against {daemon, in_process} — which is
                # the same division of labour the other three families use.
                "perception.camera_backend",
                "perception.detector",
            )
        )
        for key in OVERLAY_INTRODUCIBLE_KEYS
    )
    check_overlay_keys(base, {"camera_ingress": {"enabled": True}})
    # ---- CARD VENUE-1: the fourth family is real, and its VALUES are guarded.
    check_overlay_keys(
        base, {"perception": {"camera_backend": "recorded", "detector": "daemon"}}
    )
    from parcel_robot.camera_channel.backends.physical import resolve_backend_kind

    with pytest.raises(ValueError, match="unknown camera backend"):
        resolve_backend_kind("relasense")
    # A typo INSIDE an introducible family is still caught, by C-1's own loader.
    from parcel_robot.runtime import CameraStreamConfig

    with pytest.raises(ValueError, match="unknown perception camera-ingress keys"):
        CameraStreamConfig.from_section({"camera_ingress": True, "camera_ingress_ratez": 2.0})

    # The roam family exempts the whole SUBTREE — the loader stops descending
    # at an exempt parent — so a typo inside it merges cleanly HERE and is
    # caught downstream instead, exactly as the camera family's is. Both halves
    # are asserted so the division of labour cannot rot.
    assert "roam" in OVERLAY_INTRODUCIBLE_KEYS
    assert not any(key.startswith("roam.") for key in OVERLAY_INTRODUCIBLE_KEYS), (
        "listing roam's children would look like a spelling guard and be inert"
    )
    check_overlay_keys(base, {"roam": {"budget_st": 90.0}})  # merges; not the guard

    from parcel_robot.runtime import RobotRuntime

    assert RobotRuntime.ROAM_CONFIG_KEYS == {
        "budget_s",
        "cruise_vx",
        "turn_vyaw",
        "alternate_turns",
        "tether_m",
    }


def test_a_typo_in_the_overlay_fails_where_a_typo_in_the_base_would(
    tmp_path: Path,
) -> None:
    """The overlay is validated AFTER the merge, by the same fail-closed loader."""

    path = _pair(
        tmp_path,
        "motion:\n  max_vx: 1.0\n  max_vy: 0.5\n  max_vyaw: 1.5\n",
        "motion:\n  max_vx: .nan\n",
    )
    ConfigStore(path).safety_limits()  # base alone is fine
    with pytest.raises(Exception, match="motion.max_vx must be finite"):
        ConfigStore(path, profile="demo").safety_limits()


# ---------------------------------------------------------------------------
# 3. what the shipped prototype overlay actually resolves to
# ---------------------------------------------------------------------------


def test_prototype_overlay_resolves_the_documented_values() -> None:
    plain = ConfigStore(ROBOT_YAML, profile="")
    proto = ConfigStore(ROBOT_YAML, profile="prototype")
    assert proto.overlay_path == PROTOTYPE_YAML

    perception = proto.section("perception")
    assert perception["camera_ingress"] is True
    assert "person" in perception["camera_ingress_queries"]
    # deep merge, not replacement: the base block's other keys survived
    assert perception["spatial_sensors"] == plain.section("perception")["spatial_sensors"]
    assert perception["maps"] == plain.section("perception")["maps"]

    assert proto.section("agent")["affect"]["minimum_confidence"] == 0.5
    # ...and the rest of `agent` is the shipped block
    assert proto.section("agent")["brain"] == plain.section("agent")["brain"]

    # Card P1-E landed the indoor person stand-off P0-A could not, and card
    # DOOR-1 landed the indoor OBSTACLE ring that a doorway actually needs (see
    # the test below): those TWO safety keys move, and the rest of the block is
    # still the shipped one, key by key.
    assert proto.section("safety")["person_stop_m"] == 0.7
    assert plain.section("safety")["person_stop_m"] == 1.2
    assert proto.section("safety")["obstacle_stop_m"] == 0.45
    assert plain.section("safety")["obstacle_stop_m"] == 0.65
    moved = {"person_stop_m", "obstacle_stop_m"}
    assert {
        key: value
        for key, value in proto.section("safety").items()
        if key not in moved
    } == {
        key: value
        for key, value in plain.section("safety").items()
        if key not in moved
    }
    # ...and its paired follow keepout, which is a LITERAL in the base and so
    # cannot re-derive from the number above.
    assert proto.section("owner_follow")["owner_keepout_m"] == 1.25
    assert plain.section("owner_follow")["owner_keepout_m"] == 1.75

    # Untouched by this card, and each owned by another one:
    assert proto.section("navigation") == plain.section("navigation")
    assert proto.section("motion") == plain.section("motion")


def test_indoor_person_standoff_is_floored_by_the_safety_authority() -> None:
    """P0-A's blocker, now CLOSED by card P1-E — and its floor still holds.

    This test used to pin the blocker: an overlay carrying ``person_stop_m:
    0.7`` did not relax the robot, it stopped it from booting, because
    ``ReactiveSafetyPolicy`` floored the configured value at the SHIPPED social
    zone (1.2 m). P1-E changed the SOURCE of that number — config commissions
    the envelope's social zone — and put a named floor underneath it. So the
    test flips: 0.7 constructs, the overlay carries it, and the refusal is
    re-pinned where the floor now is.
    """

    from parcel_robot.authority import PERSON_SOCIAL_ZONE_FLOOR_M
    from parcel_robot.navigation.reactive_safety import (
        DEFAULT_SAFETY_ENVELOPE,
        ReactiveSafetyPolicy,
    )

    # The SHIPPED authority did not move: no profile, no change.
    assert DEFAULT_SAFETY_ENVELOPE.person_stop(0.0) == 1.2
    # The indoor value the card asked for now constructs...
    assert ReactiveSafetyPolicy(person_stop_m=0.7, person_slow_m=2.5).person_stop_m == 0.7
    # ...and the overlay carries it, read off the parsed mapping.
    overlay = yaml.safe_load(PROTOTYPE_YAML.read_text(encoding="utf-8")) or {}
    assert overlay["safety"]["person_stop_m"] == 0.7
    # Below the named floor is still a refusal to boot, and the message names
    # the floor so an operator can read the number they have to clear.
    assert PERSON_SOCIAL_ZONE_FLOOR_M == 0.68
    with pytest.raises(ValueError, match="PERSON_SOCIAL_ZONE_FLOOR_M"):
        ReactiveSafetyPolicy(person_stop_m=0.6, person_slow_m=2.5)


def test_realtime_prototype_example_validates_and_carries_its_departures() -> None:
    """The prototype voice lane loads, and differs only where it says it does."""

    from parcel_robot.realtime.config import realtime_config_from_mapping

    shipped_raw = yaml.safe_load(
        (REPO / "configs" / "realtime.yaml.example").read_text(encoding="utf-8")
    )
    proto_raw = yaml.safe_load(REALTIME_PROTOTYPE_EXAMPLE.read_text(encoding="utf-8"))
    shipped = realtime_config_from_mapping(shipped_raw)
    proto = realtime_config_from_mapping(proto_raw)

    # It is a COPY: it may not invent a key the production example does not
    # have. (The reverse is not asserted — the production example is P0-B's and
    # may gain keys after this file was last re-synced from it.)
    assert set(proto_raw) <= set(shipped_raw)

    assert proto.model == "gpt-realtime-2.1"
    assert proto.idle_close_after_s == 0.0  # never idle-close (card P0-B's spelling)
    assert proto.whisperer.max_updates_per_minute > shipped.whisperer.max_updates_per_minute
    assert proto.whisperer.min_gap_s < shipped.whisperer.min_gap_s
    assert proto.voice_identity.enabled is False
    # The production example is not what this card edited.
    assert shipped.model == "gpt-realtime-2.1-mini"
    assert shipped.idle_close_after_s == 600.0

    # The file's own header lists its departures. That list has been wrong once
    # (it said "four" while carrying five), so it is asserted rather than
    # trusted: every value that differs between the two files must be named.
    # Compared over the paths BOTH files carry, so P0-B adding a key to theirs
    # is a re-sync reminder (the subset check above) and not a false failure.
    def _flat(mapping: dict, prefix: str = "") -> dict[str, object]:
        flat: dict[str, object] = {}
        for key, value in (mapping or {}).items():
            if isinstance(value, dict):
                flat.update(_flat(value, f"{prefix}{key}."))
            else:
                flat[f"{prefix}{key}"] = value
        return flat

    left, right = _flat(shipped_raw), _flat(proto_raw)
    differing = {k for k in set(left) & set(right) if left[k] != right[k]}
    assert differing == {
        "model",
        "idle_close_after_s",
        "unknown_place",
        "proactive_motion_tools",
        "hosted_affect",
        "whisperer.max_updates_per_minute",
        "whisperer.min_gap_s",
        "voice_identity.enabled",
        # Card P2-B's owner-event bands, added to the overlay by P2-B and named
        # here for the reason this assertion exists: the header's departure list
        # has been wrong once already, so a new prototype-only value has to be
        # written down in BOTH places or the gate says so.
        "whisperer.owner_events.enabled",
        "whisperer.owner_events.greeting_interval_s",
    }
    header = REALTIME_PROTOTYPE_EXAMPLE.read_text(encoding="utf-8").split("# ---", 1)[0]
    for dotted in differing:
        assert dotted in header, f"{dotted} departs but the header does not say so"


# ---------------------------------------------------------------------------
# 4. one camera flag, through a live runtime
# ---------------------------------------------------------------------------


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


class _Backend:
    """Minimal in-process backend for a cold runtime construction."""

    name = "fake"

    def __init__(self, observation: SimObservation) -> None:
        self._observation = observation

    def observe(self) -> SimObservation:
        return self._observation

    def move(self, command: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        pass

    def trajectory(self, skill: object) -> None:
        pass

    def move_owner(self, dx: float, dy: float) -> None:
        pass


def _observation() -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(x=1.0, y=-2.0, yaw=0.5),
        owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
        semantic_objects=(
            SemanticObjectTrack(
                object_id="lamp-oracle",
                label="lamppost",
                position=(4.0, 0.0, 0.5),
                confidence=0.9,
                source="oracle",
            ),
        ),
        backend="fake",
    )


MINIMAL = f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
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
# The overlay may only write key paths the BASE defines (check_overlay_keys),
# so a base used with the real configs/robot.prototype.yaml has to carry these
# at their shipped values, exactly as configs/robot.yaml does. `safety` and
# `owner_follow` joined the list when card P1-E landed the indoor person
# stand-off in the overlay; `safety.obstacle_stop_m` / `obstacle_slow_m` joined
# it when card DOOR-1 landed the indoor obstacle ring in the same overlay.
perception:
  spatial_sensors: [camera, lidar]
agent:
  affect:
    minimum_confidence: 0.75
safety:
  person_stop_m: 1.2
  person_slow_m: 2.5
  obstacle_stop_m: 0.65
  obstacle_slow_m: 1.2
owner_follow:
  owner_keepout_m: 1.75
"""

C1_BLOCK = """
perception:
  camera_ingress: true
  camera_ingress_queries: [person, lamppost]
"""

LEGACY_BLOCK = """
camera_ingress:
  enabled: true
"""


def _runtime(tmp_path: Path, extra: str = "", *, profile: str | None = None) -> RobotRuntime:
    path = tmp_path / "robot.yaml"
    path.write_text(MINIMAL + extra, encoding="utf-8")
    if profile is not None:
        shutil.copyfile(PROTOTYPE_YAML, tmp_path / f"robot.{profile}.yaml")
    return RobotRuntime(path, _Backend(_observation()), audio_status=_audio())


def test_camera_flag_absent_everywhere_is_off(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime._camera_stream_enabled is False
        assert runtime._camera_ingress_enabled() is False
    finally:
        runtime.close()


def test_the_c1_key_alone_now_arms_the_grounding_flag_too(tmp_path: Path) -> None:
    """The collapse: one key, and it means the camera is on."""

    runtime = _runtime(tmp_path, C1_BLOCK)
    try:
        assert runtime._camera_stream_enabled is True
        assert runtime._camera_ingress_enabled() is True
    finally:
        runtime.close()


def test_the_legacy_section_is_an_alias_and_still_works(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, LEGACY_BLOCK)
    try:
        assert runtime._camera_ingress_enabled() is True
        # No C-1 block ⇒ no stream config to read a rate or a query batch from.
        assert runtime._camera_stream_enabled is False
    finally:
        runtime.close()


def test_both_spellings_on_no_longer_refuse_each_other(tmp_path: Path) -> None:
    """This construction raised ValueError before card P0-A."""

    runtime = _runtime(tmp_path, C1_BLOCK + LEGACY_BLOCK)
    try:
        assert runtime._camera_stream_enabled is True
        assert runtime._camera_ingress_enabled() is True
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("on", True), ("0", False), ("off", False)],
)
def test_the_env_alias_still_wins_in_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", value)
    runtime = _runtime(tmp_path, C1_BLOCK)
    try:
        assert runtime._camera_ingress_enabled() is expected
    finally:
        runtime.close()


def test_the_env_alias_reaches_grounding_only_not_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope of the collapse, pinned so the docs cannot overclaim again.

    Card P0-A merged the two GROUNDING spellings. It did not merge the stream:
    `_attach_configured_camera_ingress` reads `_camera_stream_config.enabled`
    and never consults `_camera_ingress_enabled()`, and that attach site is
    outside this card's region. So the env var moves one of the two consumers
    and the config key moves the other, in both directions.
    """

    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "1")
    runtime = _runtime(tmp_path)  # env on, no perception block
    try:
        assert runtime._camera_ingress_enabled() is True
        assert runtime._camera_stream_enabled is False  # the stream did NOT follow
    finally:
        runtime.close()

    monkeypatch.setenv("PARCEL_CAMERA_INGRESS", "0")
    runtime = _runtime(tmp_path, C1_BLOCK)  # env off, config on
    try:
        assert runtime._camera_ingress_enabled() is False
        assert runtime._camera_stream_enabled is True  # the stream did NOT follow
    finally:
        runtime.close()


def test_the_shipped_prototype_overlay_boots_a_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end on the REAL configs/robot.prototype.yaml, via PARCEL_PROFILE."""

    monkeypatch.setenv(PROFILE_ENV, "prototype")
    runtime = _runtime(tmp_path, profile="prototype")
    try:
        assert runtime.store.profile == "prototype"
        assert runtime._camera_stream_enabled is True
        assert runtime._camera_ingress_enabled() is True
        assert runtime._camera_stream_config is not None
        assert "person" in runtime._camera_stream_config.queries
        assert runtime._affect_minimum_confidence == 0.5
        # The indoor person stand-off, landed by card P1-E: the final gate and
        # the owner keepout ring both move with the overlay's person_stop_m.
        assert runtime.person_stop_m == 0.7
        assert runtime.follow.config.owner_keepout_m == 1.25
        assert runtime.reactive_safety_policy.person_stop_m == 0.7
        assert runtime.reactive_safety_policy.owner_slow_m == pytest.approx(0.80)
        # ...and the number P1-E pinned here as an OPEN HANDOFF, now closed by
        # card DOOR-1. It used to read 1.85 m: `FollowConfig.desired_distance_m`
        # was an IMPORT-TIME constant off DEFAULT_SAFETY_ENVELOPE, so the gate
        # was relaxed to 0.7 m and the FORMATION was not. It now derives per
        # instance from `owner_keepout_m + OWNER_STAND_OFF_MARGIN_M`.
        assert runtime.follow.config.desired_distance_m == pytest.approx(1.35)
        assert runtime.follow.config.desired_distance_m == pytest.approx(1.25 + 0.10)
        # The indoor OBSTACLE ring, landed by card DOOR-1: the doorway half of
        # the same problem. At the shipped 0.65 m the DIRECTIONAL gate refuses
        # every corridor under 2*0.65*sin(1.15) = 1.19 m, which is every
        # interior door; at 0.45 m it refuses under 0.82 m.
        assert runtime.obstacle_stop_m == 0.45
        assert runtime.reactive_safety_policy.obstacle_stop_m == 0.45
        assert (
            runtime.reactive_safety_policy.clearance_profile.obstacle_ring_m == 0.45
        )
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# 5. the launcher
# ---------------------------------------------------------------------------


def test_launcher_is_syntactically_valid() -> None:
    assert subprocess.run(["bash", "-n", str(LAUNCHER)], check=False).returncode == 0


def _fake_root(tmp_path: Path) -> Path:
    """A throwaway repo root so the launcher's $ROOT is not the real checkout."""

    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "configs").mkdir()
    shutil.copyfile(LAUNCHER, root / "scripts" / "launch_stack.sh")
    (root / ".parcel").symlink_to(REPO / ".parcel")
    return root


def _dry_run(root: Path, *args: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARCEL_")}
    env["HOME"] = str(root)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "launch_stack.sh"), "--dry-run", *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return dict(
        line.split("=", 1) for line in result.stdout.splitlines() if line.count("=") and "=" in line
    )


def test_launcher_default_selects_no_profile(tmp_path: Path) -> None:
    """No flag ⇒ the shipped configuration, exactly as before this card."""

    root = _fake_root(tmp_path)
    fields = _dry_run(root)
    assert fields["profile"] == "-"
    assert fields["robot_overlay"] == "-"
    assert fields["realtime_config"] == f"{root}/configs/realtime.yaml"
    assert fields["realtime_config_source"] == "default"


def test_launcher_prototype_flag_selects_the_overlay_and_the_voice_lane(
    tmp_path: Path,
) -> None:
    root = _fake_root(tmp_path)
    shutil.copyfile(PROTOTYPE_YAML, root / "configs" / "robot.prototype.yaml")
    (root / "configs" / "realtime.prototype.yaml").write_text("enabled: true\n", encoding="utf-8")
    fields = _dry_run(root, "--prototype")
    assert fields["profile"] == "prototype"
    assert fields["robot_overlay"] == f"{root}/configs/robot.prototype.yaml"
    assert fields["realtime_config"] == f"{root}/configs/realtime.prototype.yaml"
    assert fields["realtime_config_source"] == "profile"


def test_launcher_falls_back_to_the_shipped_voice_lane_with_a_note(
    tmp_path: Path,
) -> None:
    root = _fake_root(tmp_path)
    shutil.copyfile(PROTOTYPE_YAML, root / "configs" / "robot.prototype.yaml")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARCEL_")}
    env["HOME"] = str(root)
    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "launch_stack.sh"),
            "--profile",
            "prototype",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "realtime.prototype.yaml is absent" in result.stdout
    assert f"realtime_config={root}/configs/realtime.yaml" in result.stdout


def test_launcher_refuses_a_profile_it_cannot_find(tmp_path: Path) -> None:
    root = _fake_root(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARCEL_")}
    result = subprocess.run(
        ["bash", str(root / "scripts" / "launch_stack.sh"), "--profile", "nope", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 1
    assert "robot.nope.yaml does not exist" in result.stderr


def test_launcher_refuses_a_profile_that_names_a_path(tmp_path: Path) -> None:
    root = _fake_root(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARCEL_")}
    result = subprocess.run(
        ["bash", str(root / "scripts" / "launch_stack.sh"), "--profile", "../etc", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 1
    assert "invalid --profile value" in result.stderr
