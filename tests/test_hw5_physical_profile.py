"""Card HW-5 — one profile for the dog that declares what it needs and exposes no truth.

`configs/robot.go2_edu_plus.yaml` is an overlay over the SHA-locked base that
says which rig this run is on (`venue`), which source of facts it observes
through and how its LiDAR is banded (`backend`, in card HW-2's vocabulary),
which eye and ear it has, and — through the navigation file it selects — which
capabilities it cannot run without.

WHAT IS PROVED HERE AND WHAT IS NOT. The rows are pre-registered in
`scrum/20260822/task_41/PREREGISTRATION.md`.

* The DESKTOP REFUSAL is real and it is VENUE-1's, not CAP-1's. Card design
  §4 S14 says `check_required_capabilities` refuses on a desktop with no D455;
  measured, it cannot: every one of `admission.REGISTERED_CAPABILITIES` is
  about the semantic-source axis and all eight BIND on this host. So the
  refusal that names the missing camera comes from
  `runtime._venue1_attach_physical_ingress`, which runs one line AFTER the
  CAP-1 door — and the CAP-1 declaration is proved live a second way, by a
  counterfactual whose only delta is one line of the navigation file. Both are
  below, and `DESIGN.md` finding F1 carries the correction owed to the design.
* Nothing here starts a simulator, opens a socket, spends on a hosted model,
  or opens the owner's `parcel_memory.sqlite3`.
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
from parcel_robot.admission import CapabilityRefused
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.config import (
    OVERLAY_FREEFORM_PATHS,
    OVERLAY_INTRODUCIBLE_KEYS,
    ConfigStore,
    ProfileError,
    check_overlay_keys,
    deep_merge,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime
from scripts.parcel_capture.ingest import (
    LIVE_ADAPTERS,
    IngestUnavailableError,
    L2Ingest,
    active_venue,
    adapter_for,
)
from scripts.parcel_capture.ingest.l2 import GO2_EDU_PLUS_VENUE, LEGACY_ADDON_L2_VENUE

REPO = Path(__file__).resolve().parents[1]
BASE_CONFIG = REPO / "configs" / "robot.yaml"
PROFILE_NAME = "go2_edu_plus"
PROFILE = REPO / "configs" / f"robot.{PROFILE_NAME}.yaml"
VENUE_NAV = REPO / "configs" / "navigation" / "venues" / "go2_edu_plus.yaml"
NAV_DIR = REPO / "configs" / "navigation"

#: The base config's own digest, from the manifest that SHA-locks it. This card
#: adds an overlay precisely so that this number does not have to move.
BASE_CONFIG_SHA256 = "f7b57dcdf0b5981537ced874b63e010b4f0d6090de7a18118613e13f2990d6c1"

#: The two paths this card adds to `OVERLAY_INTRODUCIBLE_KEYS`, and the two
#: SHAPES an introducible key can honestly have.
#:
#: `venue` is a top-level SCALAR and `safety.require_physical_inputs` a scalar
#: nested under a parent the base already defines: for both, the loader itself
#: is the whole spelling guard, because it checks the exact path.
#: `backend` is ONE ENTRY EXEMPTING A SUBTREE, which `check_overlay_keys` will
#: merge a typo into (it stops descending at an exempt parent) — legitimate
#: only because card HW-2 put the guard at the READ site, twice:
#: `web_panel._BACKEND_KEYS` and `backends.go2.band_profile_from_config`. Both
#: halves are exercised below.
NEW_KEYS = ("venue", "backend", "safety.require_physical_inputs")

#: Empty, and that is the correction. The first pass admitted four
#: `perception.lidar_*` scalars plus a scalar `backend` and recorded them here
#: as "admitted ahead of the card that reads them". They were not ahead of
#: anything: HW-2 had already landed `web_panel._build_backend` reading
#: `backend:` as a SECTION, and the four lidar keys were a home this tree does
#: not read — the band's real read site is `backend.band`. The keys are gone,
#: the profile speaks HW-2's vocabulary, and nothing here is unread.
DECLARED_AHEAD: dict[str, str] = {}

#: Fields a physical profile may not carry, because each one hands the runtime a
#: fact it must otherwise SENSE, or claims a measurement nobody made. The list
#: is the design's HLD-Phase-1 rule made checkable; the profile's own header
#: carries the same list with the reason for each.
FORBIDDEN_PATHS = (
    "simulation",
    "poses",
    "battery.simulated_percent",
    "control.controller",
    "control.unitree_sport.axes_commissioned",
    "control.unitree_sport.state_frame_commissioned",
    "control.unitree_sport.lateral_sign",
    "control.unitree_sport.yaw_sign",
    "control.unitree_sport.allowed_modes",
    "perception.maps.enabled",
    "perception.semantic_source",
    "perception.tier",
    # DIRECTIONAL, not a blanket ban on `safety:`. Every threshold in the
    # section is a number that could be LOOSENED on a body nobody has braked,
    # so every one of them is named. `require_physical_inputs` is deliberately
    # NOT here: it is the one safety-adjacent key that can only move the join
    # in the strict direction, and the test below pins its VALUE as well.
    "safety.obstacle_stop_m",
    "safety.obstacle_slow_m",
    "safety.person_stop_m",
    "safety.person_slow_m",
    "safety.telemetry_stale_s",
    "safety.time_to_collision",
)

#: The only `safety.*` key a physical profile may write, and the only value it
#: may write there.
SAFETY_ALLOWED = {"require_physical_inputs": True}


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _paths(mapping: Any, prefix: str = "") -> set[str]:
    """Every dotted key path in a mapping, mappings recursed, lists as leaves."""

    found: set[str] = set()
    if not isinstance(mapping, dict):
        return found
    for key, value in mapping.items():
        path = f"{prefix}{key}"
        found.add(path)
        found |= _paths(value, prefix=f"{path}.")
    return found


# ======================================================================
# R1 / R2 — it loads, and the locked base did not move
# ======================================================================


def test_the_profile_loads_over_the_sha_locked_base_and_that_base_did_not_move() -> None:
    """R1 + R2. The whole reason a profile exists rather than an edit."""

    import hashlib

    digest = hashlib.sha256(BASE_CONFIG.read_bytes()).hexdigest()
    assert digest == BASE_CONFIG_SHA256, (
        "configs/robot.yaml is SHA-locked by evals/companion/embodied_plan_v1/"
        "manifest.json; this card must not move it"
    )

    store = ConfigStore(BASE_CONFIG, profile=PROFILE_NAME)
    assert store.overlay_path == PROFILE
    assert store.data["venue"] == GO2_EDU_PLUS_VENUE
    assert store.section("navigation")["config"] == ("configs/navigation/venues/go2_edu_plus.yaml")
    assert store.section("audio") == {"gateway": "array"}
    assert store.section("safety")["require_physical_inputs"] is True
    # The eye is declared, and it is the one that refuses on this desk.
    assert store.section("perception")["camera_backend"] == "realsense"
    assert store.section("perception")["camera_ingress"] is True
    assert store.section("perception")["detector"] == "daemon"

    # `backend:` is a SECTION in HW-2's vocabulary, and the band numbers live
    # under it because that is where `band_profile_from_config` reads them.
    backend = store.section("backend")
    assert backend["kind"] == "go2"
    assert backend["band"] == {"z_lo_m": 0.10, "z_hi_m": 0.60, "min_populated_bins": 1}
    # It really is HW-2's vocabulary, key by key — asked of HW-2's own
    # allow-lists rather than restated here, so a rename on their side reddens
    # this row instead of silently making the profile unreadable.
    from parcel_robot.backends.go2 import band_profile_from_config
    from parcel_robot.web_panel import _BACKEND_KEYS

    assert set(backend) <= set(_BACKEND_KEYS)
    profile_band = band_profile_from_config(backend["band"])
    assert (profile_band.z_lo_m, profile_band.z_hi_m, profile_band.min_populated_bins) == (
        0.10,
        0.60,
        1,
    )
    # The extrinsic is deliberately ABSENT: nobody has put a tape on this robot,
    # and an unmeasured mount written as a number would be the truth field this
    # whole card exists to keep out. `BandProfile`'s identity default stands.
    assert "extrinsic" not in backend["band"]
    # And the four `perception.lidar_*` keys of the first pass are gone from
    # every one of the three places they lived.
    assert not [key for key in store.section("perception") if key.startswith("lidar")]
    assert not [key for key in OVERLAY_INTRODUCIBLE_KEYS if "lidar" in key]


# ======================================================================
# R3 / R4 — the keys, and the spelling guard
# ======================================================================


def test_every_key_the_profile_writes_is_admitted_and_no_new_key_is_a_dotted_child() -> None:
    """R3. The overlay passes its own key walk, and neither entry is a child.

    HW-4's D6 as a standing guard: an entry naming a CHILD of an exempt parent
    looks like a spelling guard and is inert, because `check_overlay_keys` never
    descends past the parent. So `backend.kind` is NOT listed beside `backend`,
    and the guard that would have been is asserted where it really lives —
    HW-2's read site, in `test_a_backend_typo_is_refused_by_name_at_the_launcher`.
    """

    base = _load(BASE_CONFIG)
    overlay = _load(PROFILE)
    check_overlay_keys(base, overlay)

    assert set(NEW_KEYS) <= set(OVERLAY_INTRODUCIBLE_KEYS)
    for key in NEW_KEYS:
        assert not any(other.startswith(f"{key}.") for other in OVERLAY_INTRODUCIBLE_KEYS), (
            f"an entry under {key!r} would look like a spelling guard and be inert"
        )
    # `backend` is the one exempt SUBTREE this card adds, so the loader will
    # merge a typo inside it. That is only honest because HW-2's two read-site
    # validators exist; both are asserted to be reachable here, and exercised
    # through the launcher below.
    from parcel_robot.backends.go2 import band_profile_from_config
    from parcel_robot.web_panel import _BACKEND_KEYS

    check_overlay_keys(base, {"backend": {"kin": "go2"}})  # merges; not the guard
    with pytest.raises(ValueError, match="kin"):
        from parcel_robot.web_panel import _build_backend

        _build_backend({"kin": "go2"}, Path("/nonexistent.sock"))
    with pytest.raises(ValueError, match="z_lo"):
        band_profile_from_config({"z_lo": 0.10})
    assert {"kind", "band", "interface"} <= set(_BACKEND_KEYS)

    # Every path the profile writes resolves in the base, or is exempted AT or
    # ABOVE itself — which is the loader's own rule, restated so a key that
    # rides in under nobody's exemption cannot appear unnoticed.
    exempt = set(OVERLAY_INTRODUCIBLE_KEYS) | set(OVERLAY_FREEFORM_PATHS)
    for path in sorted(_paths(overlay)):
        parts = path.split(".")
        ancestors = {".".join(parts[:index]) for index in range(1, len(parts) + 1)}
        if ancestors & exempt:
            continue
        node: Any = base
        for part in parts:
            assert isinstance(node, dict) and part in node, path
            node = node[part]


def _profile_tree(tmp_path: Path, profile: str, overlay: dict[str, Any]) -> Path:
    """A byte copy of the shipped base plus a REAL sibling overlay, on disk.

    TRUTH-1's pattern: no product symbol is monkeypatched. `ConfigStore` goes
    looking for `<base>.<profile>.<ext>` beside the file it was handed, which is
    the path an operator actually takes.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    base = tmp_path / "robot.yaml"
    base.write_text(BASE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    sibling = tmp_path / f"robot.{profile}.yaml"
    sibling.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
    return base


@pytest.mark.parametrize(
    ("good", "typo", "overlay"),
    [
        ("venue", "venu", {"venu": GO2_EDU_PLUS_VENUE}),
        ("backend", "backned", {"backned": {"kind": "go2"}}),
        ("perception.detector", "perception.detecter", {"perception": {"detecter": "daemon"}}),
        (
            "safety.require_physical_inputs",
            "safety.require_physical_input",
            {"safety": {"require_physical_input": True}},
        ),
    ],
)
def test_a_misspelling_of_each_new_key_refuses_by_name_at_the_real_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, good: str, typo: str, overlay: dict
) -> None:
    """R4. `minimum_confidenc` is the defect; this is its guard at the loader.

    A misspelled key merges cleanly and changes nothing, so the operator gets
    the shipped robot while the file on disk says otherwise. These three paths
    are the ones the LOADER answers for — a misspelled TOP-LEVEL name is not
    under anybody's exemption, so no read site has to be remembered. The typo
    INSIDE `backend:` is a different guard in a different place, and it has its
    own test below.
    """

    profile = "hw5typo"
    base = _profile_tree(tmp_path, profile, overlay)
    monkeypatch.setenv("PARCEL_PROFILE", profile)

    with pytest.raises(ProfileError) as refusal:
        ConfigStore(base)
    assert typo in str(refusal.value)

    # ...and the correct spelling of the same key loads. A guard that refuses
    # the good case as well as the bad one has not fixed anything.
    leaf = good.rsplit(".", 1)[-1]
    value = next(iter(overlay.values()))
    if "." in good:
        correct: dict[str, Any] = {good.split(".", 1)[0]: {leaf: next(iter(value.values()))}}
    else:
        correct = {leaf: value}
    _profile_tree(tmp_path, profile, correct)
    assert ConfigStore(base) is not None


# ======================================================================
# R5 / R6 — the venue reaches the capture lane
# ======================================================================


def _channel(channel_id: str) -> Any:
    from parcel_robot.capture.channels import CHANNELS

    return next(entry for entry in CHANNELS if entry.channel_id == channel_id)


def test_the_profile_makes_hw3s_retirement_gate_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R5. HW-3 built the gate and said in its own region that it was INERT.

    "Nothing passes ``venue=``... the wiring belongs to HW-5, and the injection
    point is ``ingest/__init__.py``." This is that wiring, measured through
    `adapter_for` — the function preflight, record and the rehearsal all call.
    """

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    assert active_venue() == GO2_EDU_PLUS_VENUE

    with pytest.raises(IngestUnavailableError) as refusal:
        adapter_for(_channel("l2.cloud"))
    message = str(refusal.value)
    assert GO2_EDU_PLUS_VENUE in message
    # The refusal carries the remedy, not just the refusal: an operator who
    # reaches this on a session morning is sent to the Mid-360 decoder rather
    # than to a three-hour build of a vendor SDK for a device that is not on
    # their robot.
    assert "parcel_robot.lidar" in message

    # And it is the L2 rows ONLY. A venue that quietly changed what the DDS or
    # the RealSense adapter is would be a much bigger change than this card.
    for channel_id in ("go2.sportmodestate", "d455.color"):
        assert adapter_for(_channel(channel_id)) is not None


def test_with_no_profile_every_adapter_is_constructed_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R6. The flag-off path, which is every host in this tree today."""

    from parcel_robot.capture.channels import CHANNELS
    from scripts.parcel_capture.ingest import IngestRefusedError

    monkeypatch.delenv("PARCEL_PROFILE", raising=False)
    assert active_venue() is None

    for entry in CHANNELS:
        try:
            bound = adapter_for(entry)
        except (IngestRefusedError, IngestUnavailableError) as error:
            # Unserved transports are a stated gap and must stay the SAME gap.
            assert isinstance(error, IngestRefusedError), entry.channel_id
            continue
        # Byte-identical to the pre-card construction: the same class, built
        # with no arguments, carrying the same state.
        plain = next(f for f in LIVE_ADAPTERS if isinstance(bound, f))()
        assert type(bound) is type(plain)
        assert bound.__dict__ == plain.__dict__, entry.channel_id

    assert L2Ingest().venue == LEGACY_ADDON_L2_VENUE


# ======================================================================
# R7 / R8 — the refusal, and the declaration
# ======================================================================


class _Backend:
    """The smallest backend a runtime can turn against. No simulator, no socket."""

    name = "hw5-fake"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend="hw5-fake",
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
def _sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """The owner's stores are never opened, and process globals never leak.

    `PARCEL_MEMORY_PATH` keeps `parcel_memory.sqlite3` shut (card R27) —
    this card is the first to build a runtime from the SHIPPED
    `configs/robot.yaml`, whose `memory.path` names exactly that file — and
    `PARCEL_ONLINE_MAP_PATH=:memory:` keeps the learned map off disk.
    """

    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("PARCEL_ONLINE_MAP_PATH", ":memory:")
    monkeypatch.delenv("PARCEL_CAMERA_BACKEND", raising=False)
    monkeypatch.delenv("PARCEL_PROFILE", raising=False)
    try:
        yield
    finally:
        from parcel_robot.perception_source.selection import use_learned_map, use_semantic_source

        use_semantic_source(None)
        use_learned_map(None)


def test_the_desktop_refuses_this_profile_because_there_is_no_d455(
    monkeypatch: pytest.MonkeyPatch, audio_status: AudioDeviceStatus
) -> None:
    """R7. The card's headline: a profile that names a venue nobody has REFUSES.

    Zero monkeypatching of any product symbol — the real shipped base, the real
    sibling overlay, `$PARCEL_PROFILE`, and `RobotRuntime.start()`. The refusal
    is `_venue1_attach_physical_ingress`'s and it carries the device census.

    IT IS NOT CAP-1'S, and that correction is this card's (DESIGN §g F1): every
    name in `admission.REGISTERED_CAPABILITIES` is about the semantic-source
    axis and all eight BIND on this host, so `check_required_capabilities`
    cannot express "needs a D455". It passes here, one line before this raise —
    which is itself the assertion below.
    """

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    runtime = RobotRuntime(BASE_CONFIG, _Backend(), language_model=None, audio_status=audio_status)
    try:
        with pytest.raises(Exception) as refusal:
            runtime.start()
    finally:
        runtime.close()

    message = str(refusal.value)
    assert "camera venue 'realsense' was selected" in message
    assert "No device connected" in message
    assert "Attach the D455" in message
    # The CAP-1 door was passed, not skipped: it runs one line earlier, and a
    # declared capability this process had not bound would have raised THERE.
    assert not isinstance(refusal.value, CapabilityRefused)


def _declaring_tree(tmp_path: Path, *, semantic_source: str | None) -> Path:
    """The real profile with the eye off, over a copy of the real venue nav file.

    Two declared deltas from the shipped pair and no more:
      * `perception.camera_ingress: false` — otherwise the D455 refusal above
        fires first and the CAP-1 door is unreachable on this host;
      * `navigation.config` absolutised onto the copy, so the counterfactual can
        change ONE line of it.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    nav = yaml.safe_load(VENUE_NAV.read_text(encoding="utf-8")) or {}
    if semantic_source is not None:
        nav["perception"]["semantic_source"] = semantic_source
    nav_path = tmp_path / "nav.yaml"
    nav_path.write_text(yaml.safe_dump(nav, sort_keys=False), encoding="utf-8")

    overlay = _load(PROFILE)
    overlay["perception"]["camera_ingress"] = False
    overlay["navigation"]["config"] = str(nav_path)
    return _profile_tree(tmp_path, PROFILE_NAME, overlay)


def test_the_capability_declaration_is_live_and_not_a_decoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audio_status: AudioDeviceStatus
) -> None:
    """R8. CAP-1 was wired and inert — nothing in the tree declared. Now one does.

    Three arms. (a) the declaration is well formed and every name is registered;
    (b) the SAME profile over a navigation file whose only delta is
    `semantic_source: oracle` REFUSES at startup, naming the capability and
    printing the table; (c) unmodified, it starts with nothing unmet.

    Arm (b) is the proof that the declaration is load-bearing, and it is the
    drift it exists to catch: a dog whose navigation file quietly said `oracle`
    would be reading a MuJoCo scene sidecar that does not exist on it.
    """

    declared = admission.required_capabilities(_load(VENUE_NAV))
    assert declared, "the venue profile declares nothing — the card delivered nothing"
    assert set(declared) <= set(admission.REGISTERED_CAPABILITIES)

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)

    base = _declaring_tree(tmp_path / "counterfactual", semantic_source="oracle")
    runtime = RobotRuntime(base, _Backend(), language_model=None, audio_status=audio_status)
    try:
        with pytest.raises(CapabilityRefused) as refusal:
            runtime.start()
    finally:
        runtime.close()
    message = str(refusal.value)
    assert "learned_map_source" in message
    assert "admission table:" in message

    base = _declaring_tree(tmp_path / "shipped", semantic_source=None)
    runtime = RobotRuntime(base, _Backend(), language_model=None, audio_status=audio_status)
    try:
        runtime.start()
        table = runtime.snapshot()["admission"]
        assert table["required_capabilities"] == list(declared)
        assert table["unmet_capabilities"] == []
        assert table["declaration_error"] is None
    finally:
        runtime.close()


def test_only_the_venue_navigation_file_declares_anything(tmp_path: Path) -> None:
    """R12. CAP-1 pins the three top-level files; this pins the whole tree.

    `tests/test_cap1_admission.py` asserts that every `configs/navigation/*.yaml`
    declares nothing, and that glob is NOT recursive — `cities/`, `experiments/`
    and `models/` have always been outside it. The venue profile is under
    `venues/` for exactly that reason, and this walk covers strictly more files
    than CAP-1's does, so the fact that ONE file in this tree declares is
    checked, not assumed. See DESIGN.md finding F2: the handoff to CAP-1's owner
    is to widen that loop's sentence, not its glob.
    """

    del tmp_path
    declaring = {
        path.relative_to(NAV_DIR).as_posix()
        for path in sorted(NAV_DIR.rglob("*.yaml"))
        if admission.required_capabilities(_load(path))
    }
    assert declaring == {"venues/go2_edu_plus.yaml"}


# ======================================================================
# R9 — no truth, no oracle
# ======================================================================


def test_the_profile_contains_no_truth_or_oracle_field() -> None:
    """R9. HLD Phase 1, made checkable.

    Every name below hands the runtime a fact it must otherwise SENSE, or
    claims a measurement nobody made:
    `simulation.*` is a MuJoCo scene sidecar and there is none on a dog;
    `poses:` is a gazetteer of places nobody surveyed;
    `battery.simulated_percent` is a fabricated hardware reading;
    `control.controller` is the WRITER axis (`RobotRuntime` refuses anything but
    `simulator` without an injected manager — configuration alone cannot arm
    hardware) and the four `unitree_sport` commissioning fields are claims that
    Stage 0 was run; `safety.*` would relax a band on a body nobody has braked.
    """

    written = _paths(_load(PROFILE))
    offending = sorted(
        path
        for path in written
        if any(path == name or path.startswith(f"{name}.") for name in FORBIDDEN_PATHS)
    )
    assert not offending, (
        f"the physical profile carries fields the runtime would read as ground truth: {offending}"
    )
    # The `safety:` rule is DIRECTIONAL and the allow-list is exactly one key
    # at exactly one value. A profile that wrote `require_physical_inputs:
    # false` would be buying a LOOSER join for a robot, which is the same class
    # of move as relaxing a band, and it fails here.
    assert _load(PROFILE).get("safety", {}) == SAFETY_ALLOWED

    # The rule is about the FILE, not the merged result: the base still ships
    # `simulation:` and `battery.simulated_percent`, and this profile leaves
    # both exactly where they are rather than pretending they mean something
    # here.
    merged = ConfigStore(BASE_CONFIG, profile=PROFILE_NAME).data
    assert merged["battery"] == _load(BASE_CONFIG)["battery"]
    assert merged["simulation"] == _load(BASE_CONFIG)["simulation"]


# ======================================================================
# R10 / R11 — flag-off identity, and what is declared ahead of its reader
# ======================================================================


def test_no_profile_and_the_prototype_profile_are_untouched_by_this_card() -> None:
    """R10. The loader is transparent with no profile; the prototype is unmoved.

    Six new entries in `OVERLAY_INTRODUCIBLE_KEYS` can only ever ADMIT a key an
    overlay writes. No overlay in the tree but this card's writes one, so the
    two profiles that existed before this card merge to exactly what they merged
    to before it.
    """

    base = _load(BASE_CONFIG)
    assert ConfigStore(BASE_CONFIG, profile="").data == base

    prototype = _load(REPO / "configs" / "robot.prototype.yaml")
    merged = ConfigStore(BASE_CONFIG, profile="prototype").data
    assert merged == deep_merge(base, prototype)
    for key in NEW_KEYS:
        assert key.split(".")[0] not in prototype or key not in _paths(prototype)
    assert "venue" not in merged
    assert "backend" not in merged


def test_the_profile_reaches_the_product_launcher_and_refuses_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11, rewritten. The LAUNCHER, not a grep — verifier finding H1.

    The first pass asserted that `web_panel.build_runtime` "still constructs
    `MujocoSocketBackend(socket_path)` unconditionally", meaning to force an
    edit the day HW-2 landed. HW-2 had already landed; the literal survived
    inside `_build_backend`, so the guard passed while the profile could not be
    built through the launcher at all (`ConfigStore.section("backend")` raised a
    bare `TypeError` on the scalar the profile then carried). A grep for a
    literal is not a proof about a call.

    So this row is the call. Real shipped base, real sibling overlay,
    `$PARCEL_PROFILE`, `web_panel.build_runtime` — the function
    `web_panel.main` itself invokes. Nothing is monkeypatched but environment
    variables.

    WHAT THE REFUSAL IS, AND WHY IT IS NOT THE D455's. `_build_backend` runs
    BEFORE `RobotRuntime` is constructed, so on this desktop the launcher never
    reaches the camera: it refuses at `LiveGo2Sources`, naming the one thing
    box-day step B-con supplies. R7's D455 refusal is one layer down, at
    `RobotRuntime.start()`, and is reachable only once a backend can be built —
    on the Orin, or from a recorded fixture.
    """

    from parcel_robot import web_panel
    from parcel_robot.backends.go2 import Go2SdkUnavailable

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    with pytest.raises(Go2SdkUnavailable) as refusal:
        web_panel.build_runtime(BASE_CONFIG, tmp_path / "sim.sock", use_llm=False)
    message = str(refusal.value)
    assert "the live Go2 source needs the robot NIC name (backend.interface)" in message
    assert "/sys/class/net" in message

    # With the NIC filled in as B-con will fill it, the launcher gets one step
    # further and refuses on the venv — still HW-2's refusal, still before the
    # runtime exists. Recorded so the box-day expectation is the measured one.
    overlay = _load(PROFILE)
    overlay["backend"]["interface"] = "eth0"
    base = _profile_tree(tmp_path / "withnic", PROFILE_NAME, overlay)
    with pytest.raises(Go2SdkUnavailable) as refusal:
        web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    assert "unitree_sdk2py is not importable" in str(refusal.value)

    # And nothing about this card moved the no-profile launcher: with no
    # profile the section is absent and the simulator backend is built.
    monkeypatch.delenv("PARCEL_PROFILE", raising=False)
    runtime = web_panel.build_runtime(BASE_CONFIG, tmp_path / "sim.sock", use_llm=False)
    try:
        assert type(runtime.backend).__name__ == "MujocoSocketBackend"
    finally:
        runtime.close()


def test_a_backend_typo_is_refused_by_name_at_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the subtree bargain, through the product path.

    `backend` exempts a whole subtree, so `check_overlay_keys` MERGES
    `backend.kin: go2` without a word — asserted in R3. If the read site did
    not check, the operator would get `kind: mujoco`'s simulator while the file
    on disk said `go2`. HW-2 put the check in `_build_backend`; this pins that
    it is REACHED from a real profile, which is TRUTH-1's F2 lesson (the
    function was pinned, the CALL was not, and removing the call left six tests
    green).
    """

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    overlay = _load(PROFILE)
    overlay["backend"]["kin"] = "go2"
    base = _profile_tree(tmp_path, PROFILE_NAME, overlay)

    # The loader merges it — by design, the subtree is exempt.
    assert ConfigStore(base).section("backend")["kin"] == "go2"

    from parcel_robot import web_panel

    with pytest.raises(ValueError, match="kin"):
        web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)


def test_the_two_nic_keys_are_written_from_one_reading(tmp_path: Path) -> None:
    """One cable, two processes, two keys — and never one of them alone.

    `backend.interface` is the NIC the PRODUCT venv's observer binds
    (`LiveGo2Sources` -> `rt/sportmodestate`); `control.unitree_sport.interface`
    is the same wire as the MOTION venv's commissioning writer sees it. They are
    two keys because the two processes must never share one (design §3:
    CycloneDDS is process-global), and one value because it is one cable, read
    once at box-day step B9.

    Today the profile writes NEITHER — the Orin's name for that port is unknown
    until somebody reads `/sys/class/net` on it, and a guessed NIC would be a
    confident lie in the file a commissioning session reads. This guard is for
    the day it is filled in: writing one and forgetting the other is the
    failure, and it fails here by name.
    """

    del tmp_path
    written = _paths(_load(PROFILE))
    keys = ("backend.interface", "control.unitree_sport.interface")
    present = [key for key in keys if key in written]
    assert present in ([], list(keys)), (
        f"the profile sets {present} but not {sorted(set(keys) - set(present))}: one B9 "
        f"reading fills both, or neither"
    )
    if present:
        overlay = _load(PROFILE)
        assert (
            overlay["backend"]["interface"] == overlay["control"]["unitree_sport"]["interface"]
        ), "two spellings of one cable must not disagree"


# ======================================================================
# F2 — a profile that cannot be read is never a "stated gap"
# ======================================================================


def test_an_unreadable_profile_refuses_by_name_instead_of_emptying_the_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier finding F2, closed.

    `active_venue()` used to wrap `ProfileError` in `IngestRefusedError`, which
    is the class `coverage()` and `preflight.default_reader_factory` both read
    as "this transport has no reader, and here is the stated reason". So a
    one-character typo in `$PARCEL_PROFILE` printed `served: 0  unserved: 28`
    and a remedy for twenty-eight transports, with the real reason discarded —
    the exact silent-degradation the region's own header forbids.

    "I could not read the configuration" and "this channel has no adapter" are
    different answers, and only one of them is the capture package's to give.
    """

    from scripts.parcel_capture.ingest import coverage, dependency_report_text
    from scripts.parcel_capture.preflight import default_reader_factory

    monkeypatch.setenv("PARCEL_PROFILE", "go2_edu_plu")
    entry = _channel("l2.cloud")
    for call in (
        coverage,
        dependency_report_text,
        lambda: adapter_for(entry),
        lambda: default_reader_factory(entry),
    ):
        with pytest.raises(ProfileError) as refusal:
            call()
        assert "go2_edu_plu" in str(refusal.value)
        assert "does not exist" in str(refusal.value)

    # The correctly spelled profile still answers, so the guard is not a wall.
    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    assert active_venue() == GO2_EDU_PLUS_VENUE


# ======================================================================
# Addendum (HW-2 verdict F6) — what this rig accepts as evidence
# ======================================================================

#: HW-2's shipped replay fixture. Synthesised, and its own header says so; it
#: is used here only as the thing the join must REFUSE to believe.
HW2_FIXTURE = REPO / "tests" / "data" / "hw2_stage0_replay.jsonl"


def _replay_tree(tmp_path: Path, *, require_physical: bool | None) -> Path:
    """The real profile with a replay backend, and the switch as given.

    Two declared deltas from the shipped pair, and no more: `backend.fixture`
    (the shipped profile must never name a recording — its own comment says so,
    and a desktop has no other way to make `_build_backend` succeed), and
    whatever `require_physical` asks of `safety.require_physical_inputs`.
    `None` DELETES the key, which is the shipped-base default and the
    counterfactual this row exists for.
    """

    overlay = _load(PROFILE)
    overlay["backend"]["fixture"] = str(HW2_FIXTURE)
    if require_physical is None:
        overlay["safety"].pop("require_physical_inputs")
    else:
        overlay["safety"]["require_physical_inputs"] = require_physical
    return _profile_tree(tmp_path, PROFILE_NAME, overlay)


def _hw2_replay_backend_is_constructible() -> str:
    """`""` when HW-2's own fixture backend builds here, else the reason.

    NARROW ON PURPOSE. This asks whether card HW-2's `Go2Backend` can be
    constructed from HW-2's OWN shipped fixture with no HW-5 input at all, so it
    can only ever excuse a row for a defect outside this card — never for a
    wrong profile, a wrong key or a wrong value, each of which is asserted
    elsewhere with no escape hatch. It exists because HW-2's correction pass is
    in flight in this shared tree.
    """

    from parcel_robot.backends.go2 import Go2BackendError
    from parcel_robot.web_panel import _build_backend

    if not HW2_FIXTURE.is_file():
        return f"HW-2's replay fixture is not in the tree ({HW2_FIXTURE})"
    try:
        _build_backend({"kind": "go2", "fixture": str(HW2_FIXTURE)}, Path("/nonexistent.sock"))
    # Named, not blind: `Go2BackendError` is HW-2's own refusal base, and the
    # four builtins are what a half-landed constructor raises. Anything else
    # propagates and reddens the row, which is the right answer for a failure
    # nobody predicted.
    except (Go2BackendError, TypeError, ValueError, OSError, AttributeError) as error:
        return f"{type(error).__name__}: {error}"
    return ""


def test_under_this_profile_a_replayed_scan_does_not_pass_the_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HW-2's row B1a, through HW-5's profile — and the key that makes it true.

    `RobotRuntime` picks its requirements table from
    `safety.require_physical_inputs` (`runtime.py:1707-1731`). Absent, it takes
    `requirements_allowing_sim_fixtures()`, on which a REPLAY sample with a
    fixture label SATISFIES the requirement — so on the shipped base a recorded
    scan and a synthesised pose pass the dispatch health join on a rig that is
    supposed to be a robot. Board decision D-2 is explicit that
    `DEFAULT_REQUIRED_INPUTS` is the SIMULATOR default and still admits fixture
    SCAN geometry.

    Both arms differ in ONE key of one file. Nothing is monkeypatched but
    environment variables; the runtime comes from `web_panel.build_runtime`,
    the launcher's own call, with a fixture backend because that is the only
    `backend:` a desktop can construct (the live one needs the vendor SDK).
    """

    broken = _hw2_replay_backend_is_constructible()
    if broken:
        pytest.skip(f"card HW-2's replay backend does not construct in this tree: {broken}")

    from parcel_robot import web_panel
    from parcel_robot.core.input_health import HealthAction
    from parcel_robot.evidence_origin import EvidenceOrigin

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)

    # ARM A — the profile as shipped. The switch is on, the physical table is
    # active, and the recording is refused BY NAME.
    base = _replay_tree(tmp_path / "shipped", require_physical=True)
    runtime = web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    try:
        assert runtime._require_physical_inputs is True
        assert runtime.backend.scan_evidence_source.origin is EvidenceOrigin.REPLAY
        runtime.backend.start()
        observation = runtime.backend.observe()
        verdict = runtime._evaluate_dispatch_input_health(
            observation, now=observation.timestamp + 0.01
        )
        reasons = {fault.reason for fault in verdict.faults}
        assert "sim_fixture_forbidden" in reasons
        assert verdict.action is HealthAction.LATCHED_STOP
    finally:
        runtime.close()

    # ARM B — the same profile with that one key DELETED, i.e. the shipped
    # default. The identical recording now satisfies the join. This is the
    # defect the key closes, reproduced rather than described.
    base = _replay_tree(tmp_path / "default", require_physical=None)
    runtime = web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    try:
        assert runtime._require_physical_inputs is False
        runtime.backend.start()
        observation = runtime.backend.observe()
        verdict = runtime._evaluate_dispatch_input_health(
            observation, now=observation.timestamp + 0.01
        )
        assert "sim_fixture_forbidden" not in {fault.reason for fault in verdict.faults}
    finally:
        runtime.close()


def test_the_switch_reaches_the_runtime_from_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audio_status: AudioDeviceStatus
) -> None:
    """The pin, with no backend in the way — three arms, no HW-2 dependency.

    `safety.require_physical_inputs` is a scalar under a parent the base
    defines, so the LOADER refuses `require_physical_input` (asserted in R4).
    What is asserted here is the other half: that the value the profile writes
    actually ARRIVES at `RobotRuntime._require_physical_inputs`, and that with
    no profile the shipped default is untouched.

    Arm 1 is the real, unmodified profile through `RobotRuntime` — the same
    construction R7 and R8 use. Arm 2 is the LAUNCHER, with `backend.kind`
    switched to `mujoco` in a tmp copy for one stated reason: this row is about
    the switch, not about which backend gets built, and the go2 construction is
    R11's row. Arm 3 is the shipped default.
    """

    from parcel_robot import web_panel

    monkeypatch.setenv("PARCEL_PROFILE", PROFILE_NAME)
    runtime = RobotRuntime(BASE_CONFIG, _Backend(), language_model=None, audio_status=audio_status)
    try:
        assert runtime._require_physical_inputs is True
    finally:
        runtime.close()

    overlay = _load(PROFILE)
    overlay["backend"]["kind"] = "mujoco"
    base = _profile_tree(tmp_path, PROFILE_NAME, overlay)
    runtime = web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    try:
        assert runtime._require_physical_inputs is True
    finally:
        runtime.close()

    monkeypatch.delenv("PARCEL_PROFILE", raising=False)
    runtime = web_panel.build_runtime(BASE_CONFIG, tmp_path / "sim.sock", use_llm=False)
    try:
        assert runtime._require_physical_inputs is False
    finally:
        runtime.close()
