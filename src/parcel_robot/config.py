from __future__ import annotations

import difflib
import importlib
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType  # ---- CARD SENSE-1: the premise table ----
from typing import Any

import yaml

from .models import ModuleSpec, Pose, WifiCard
from .safety import SafetyLimitError, SafetyLimits

#: Environment variable that selects a config PROFILE OVERLAY (card P0-A).
#: ``PARCEL_PROFILE=prototype`` makes every entrypoint that builds a
#: :class:`ConfigStore` deep-merge ``configs/robot.prototype.yaml`` on top of
#: ``configs/robot.yaml``. ``scripts/launch_stack.sh --prototype`` exports it,
#: which is how one flag reaches the panel and the simulator at once.
PROFILE_ENV = "PARCEL_PROFILE"

#: A profile names a sibling file, so it may not name a PATH. Anchored, and
#: deliberately narrower than "no slashes": ``..`` and ``~`` are out too.
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProfileError(ValueError):
    """A profile was named and could not be honoured (typo, not a policy)."""


def _clean_profile(name: str | None) -> str | None:
    """Normalise a profile name. Empty/blank means "no profile"."""

    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    if not _PROFILE_NAME.match(text) or text in {".", ".."}:
        raise ProfileError(
            f"invalid config profile name {name!r}: a profile names a sibling "
            f"file (configs/robot.<profile>.yaml), never a path"
        )
    return text


def resolve_profile(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """The active profile: ``--profile NAME`` in *argv*, else ``$PARCEL_PROFILE``.

    Both spellings are accepted because both exist in the wild: the launcher
    exports the environment variable (so it reaches the panel AND the sim
    without either argument parser learning a new flag), while a caller that
    already owns an argv list can hand it over directly.
    """

    if argv:
        items = list(argv)
        for index, item in enumerate(items):
            if item == "--profile":
                if index + 1 >= len(items):
                    raise ProfileError("--profile requires a value")
                return _clean_profile(items[index + 1])
            if item.startswith("--profile="):
                return _clean_profile(item.split("=", 1)[1])
    source = os.environ if env is None else env
    return _clean_profile(source.get(PROFILE_ENV))


def profile_overlay_path(base: str | Path, profile: str) -> Path:
    """``configs/robot.yaml`` + ``prototype`` -> ``configs/robot.prototype.yaml``.

    Resolved as a SIBLING of the base config, never from the CWD, so a packaged
    install, a bind-mounted ``PARCEL_ROOT`` and a test's ``tmp_path`` all find
    the overlay next to the file they were actually handed.
    """

    path = Path(base)
    return path.with_name(f"{path.stem}.{profile}{path.suffix}")


#: Dotted paths whose CHILDREN are data, not schema. Everything under one of
#: these is accepted without further checking, because the key names are the
#: content: pose names, wifi-card names, and the owner facts the prompt builder
#: interpolates. A spell-checker over those would be a spell-checker over the
#: owner's own vocabulary.
OVERLAY_FREEFORM_PATHS = frozenset(
    {
        "poses",
        "wifi_cards",
        "prompting.user_profile",
    }
)

#: Keys an overlay may INTRODUCE even though ``configs/robot.yaml`` does not
#: carry them. Each is a real, validated key with a code default that the
#: shipped file simply leaves out, and each has its own downstream loader that
#: refuses a typo *within* it (``CameraStreamConfig.from_section`` for the
#: ``perception.camera_ingress*`` family). The base file cannot simply grow
#: them: it is SHA-locked, which is the whole reason profiles exist.
#:
#: This list is the escape hatch named in the refusal message below. Adding to
#: it is a deliberate act with a reviewer; the alternative — accepting any
#: unknown key — is what let ``minimum_confidenc`` boot at the shipped 0.75.
OVERLAY_INTRODUCIBLE_KEYS = frozenset(
    {
        # C-1 observation stream (validated by CameraStreamConfig.from_section)
        "perception.camera_ingress",
        "perception.camera_ingress_rate_hz",
        "perception.camera_ingress_queue_capacity",
        "perception.camera_ingress_max_detections_per_frame",
        "perception.camera_ingress_queries",
        # legacy B4 grounding switch (RobotRuntime reads camera_ingress.enabled)
        "camera_ingress",
        "camera_ingress.enabled",
        # ---- CARD ROAM-1: the roam behavior's knobs ------------------------
        # The base configuration is SHA-locked and cannot grow a `roam:`
        # section, so without this entry the prototype overlay REFUSES to load
        # one — which is what the verifier measured: `_roam_limits` read
        # `store.section("roam")` and no operator could ever put anything in
        # it.
        #
        # ONE ENTRY, NOT SIX, and the difference matters. Listing `roam` here
        # exempts the WHOLE SUBTREE: the loop below `continue`s on the exempt
        # parent and never descends, so `roam.budget_st` would merge silently.
        # Listing the five children alongside it would LOOK like a spelling
        # guard and be inert — the same shape of lie as the
        # `minimum_confidenc` key this whole mechanism exists to catch. So the
        # typo check lives where the section is READ, in
        # `RobotRuntime.roam_config`, which refuses an unknown key by name and
        # is the roam family's equivalent of `CameraStreamConfig.from_section`.
        "roam",
        # ---- CARD VENUE-1: which VENUE the eye is on -----------------------
        # Two scalars, not a subtree, so the exemption cannot hide a typo in a
        # child the way a bare `perception.camera` would. Both are read by the
        # VENUE-1 region in `RobotRuntime` (`_venue1_resolve_venue` and
        # `_venue1_detector`), and both refuse an unknown VALUE by name there —
        # `camera_backend` through P1-A's `resolve_backend_kind`, which lists
        # the accepted kinds, and `detector` against {daemon, in_process}.
        #
        # They are separate keys rather than a `perception.camera:` block for
        # the same reason P1-A kept the camera's HARDWARE description out of
        # `configs/robot.yaml` entirely (`PARCEL_CAMERA_CONFIG`): a camera is
        # host hardware, not robot policy, and the SHA-locked base cannot grow
        # a section for it. What belongs in the profile is the one decision the
        # ROBOT makes — which venue this run's eye is on.
        "perception.camera_backend",
        "perception.detector",
        # ---- CARD TRUTH-1: the planner LLM's own section -------------------
        # CAP-1 surveyed every config section the PRODUCT reads and found this
        # one unreachable: `web_panel.build_runtime` reads
        # `store.section("planner_model")` to decide whether to construct a
        # SECOND llama.cpp provider for the planner, and `configs/robot.yaml`
        # is SHA-locked and omits the block. So with no profile the section
        # read `{}` and the planner could never be enabled, and a profile that
        # tried to set it made the whole config load REFUSE. The knob existed
        # and no operator could ever turn it — ROAM-1 finding 6, a second time,
        # in the product launcher.
        # ONE ENTRY, NOT FOUR, for the reason written beside `roam` above: the
        # loop stops descending at an exempt parent, so listing
        # `planner_model.enabled` alongside it would LOOK like a spelling guard
        # and be inert. The real typo check lives where the section is READ, in
        # `web_panel._check_planner_model_section`, which refuses an unknown
        # key by name — this family's `CameraStreamConfig.from_section`.
        #
        # DEFAULTS ARE UNCHANGED. The base still omits the block, so
        # `planner_config.get("enabled", False)` is still False on every run
        # that does not write one; this entry only makes writing one possible.
        "planner_model",
        "social_progress",
        # ---- CARD HW-4 (task_37): WHICH EAR THIS VENUE HAS ------------------
        # `audio.gateway: browser|array` chooses between
        # `realtime.audio_gateway.BrowserAudioGateway` (the shipped default: the
        # ear is a Chrome tab) and `ArrayAudioGateway` (the ear is the reSpeaker
        # XVF3800 on the robot's own body). `runtime._build_realtime_sink` reads
        # `store.section("audio")` and the SHA-locked base omits the section, so
        # without this entry a profile that wrote `audio:` would make the whole
        # config load REFUSE and the array could never be selected by anyone —
        # ROAM-1 finding 6 and TRUTH-1's `planner_model`, a third time.
        #
        # ONE ENTRY, NOT TWO, for the reason written beside `roam` and
        # `planner_model` above: `check_overlay_keys` stops descending at an
        # exempt parent, so listing `audio.gateway` here would LOOK like a
        # spelling guard and be inert. The real typo check lives where the
        # section is READ — `audio_gateway.resolve_audio_gateway_selection`,
        # which refuses an unknown KEY by name and an unknown gateway VALUE by
        # name. It sits in that module rather than in the runtime because that
        # module owns both gateways, so the thing that chooses sits beside the
        # things being chosen.
        #
        # DEFAULTS ARE UNCHANGED. The base still omits the block, so an absent
        # section resolves to `browser` and `_build_realtime_sink` constructs
        # byte-for-byte what it constructed before this card.
        "audio",
        # ---- END CARD HW-4 --------------------------------------------------
        # ---- CARD HW-5 (task_41): WHICH RIG THIS RUN IS ON -------------------
        # TWO entries for `configs/robot.go2_edu_plus.yaml`, the one overlay
        # that describes the Go2 EDU+ with the factory-fitted Livox Mid-360
        # (design `scrum/20260822/WAVE3_HW_DESIGN_FABLE.md` §5.8). Both are
        # READ TODAY, by two different lanes, and each is a different SHAPE for
        # a stated reason.
        #
        # `venue` — the rig identity, a SCALAR. Same string as
        # `parcel_robot.capture.channels.GO2_EDU_PLUS_VENUE` and
        # `scripts/parcel_capture/ingest/l2.py:GO2_EDU_PLUS_VENUE`. Read by
        # this card's region in `scripts/parcel_capture/ingest/__init__.py:
        # adapter_for`, which passes it to the adapter that accepts a `venue=`
        # and so makes HW-3's `refuse_retired_venue` reachable at last (it had
        # no caller: HW-3's own region says so, verifier finding F4).
        #
        # A scalar has no inside, so the loader below is its whole spelling
        # guard: `venu:` is refused here, by name, with no read site required.
        "venue",
        # `backend` — which source of FACTS the runtime observes through
        # (design seam S1): `MujocoSocketBackend` on a desktop, HW-2's
        # `Go2Backend` on the dog. Read by card HW-2 at
        # `web_panel._build_backend`, called from `build_runtime`.
        #
        # ONE ENTRY, NOT SEVEN, and this is the `roam` / `planner_model` /
        # `audio` shape rather than `venue`'s: `check_overlay_keys` stops
        # descending at an exempt parent, so listing `backend.kind` beside it
        # would LOOK like a spelling guard and be inert. The real typo check
        # lives where the section is READ, and HW-2 put it there — TWICE:
        # `web_panel._BACKEND_KEYS` refuses an unknown `backend.*` key by name,
        # and `backends.go2.band_profile_from_config` refuses an unknown
        # `backend.band.*` key by name. HW-2's DESIGN names this entry as
        # HW-5's to write; `tests/test_hw2_go2_backend.py` has the branch that
        # takes effect the moment it exists.
        #
        # NOT `control.controller`, and the difference is a safety boundary,
        # not a naming preference: `control.controller` is the WRITER axis and
        # `RobotRuntime.__init__` refuses any value but `simulator` unless a
        # `control_manager` was injected — "configuration alone cannot arm
        # hardware". A profile may say what the robot LOOKS through; it may not
        # say what moves it. NOT `motion.backend` either: that is the
        # locomotion policy (`rl`), a third axis again.
        #
        # DEFAULTS ARE UNCHANGED. The base omits the section, so
        # `_build_backend({})` returns `MujocoSocketBackend(socket_path)`
        # byte-for-byte as before; this entry only makes writing one possible.
        "backend",
        # `safety.require_physical_inputs` — the hardware-readiness switch, a
        # SCALAR nested under a parent the base already defines, so the loader
        # descends into `safety:` and checks this exact path itself. Read at
        # `runtime.py:1707-1711`; default False.
        #
        # WHAT IT DOES, and why a physical profile is the thing that must carry
        # it. With it False the runtime chooses
        # `requirements_allowing_sim_fixtures()`, on which a REPLAY or
        # SIMULATION sample with a fixture label SATISFIES a requirement. So on
        # the shipped base a recorded scan and a synthesised pose pass the
        # dispatch health join on a rig that is supposed to be a robot — stub
        # geometry admitted on a physically commissioned deployment, which is
        # board decision D-2's whole subject. True selects
        # `requirements_requiring_physical_inputs()`, on which no synthetic
        # origin satisfies anything and a replayed scan latches
        # `sim_fixture_forbidden`.
        #
        # IT IS A CONFIG KEY, NOT SAFETY-CORE LOGIC, and it only moves in one
        # direction: True is strictly STRICTER than the shipped default, the
        # requirements tables and the join are untouched, and no card may write
        # `false` here to buy a looser join — HW-5's profile test pins the value
        # as well as the key. Before this entry the only way to set it was to
        # edit the SHA-locked base, which is why HW-2's own tests write it into
        # a modified copy and say so (`tests/test_hw2_go2_backend.py:179-183`).
        "safety.require_physical_inputs",
        # ---- CARD SENSE-1 (scrum/20260823/task_3) --------------------------
        # `physical_resolution` — what a physical profile does about the
        # SIMULATOR PREMISES it inherits from the base. See the region below
        # `deep_merge` for the whole mechanism and the defect it closes.
        #
        # ONE ENTRY EXEMPTING A SUBTREE, the `roam` / `backend` shape, and
        # legitimate for the same stated reason: the read-site validator
        # exists and is `validate_physical_resolution`, which refuses an
        # unknown key inside the section BY NAME, refuses a declared path that
        # is not one of the premises, and refuses the same path declared two
        # ways. It runs at load, one line after this exemption admits the
        # section, so a typo cannot ride in unnoticed.
        "physical_resolution",
        # ---- END CARD SENSE-1 ----------------------------------------------
        # ---- CARD AWARE-1 (scrum/20260823/task_4) --------------------------
        # `awareness` — the idle head-turn sweep's knobs (enabled, cadence,
        # rate, arc). The SHA-locked base cannot grow the section, and CAP-1's
        # G2 survey found the read (`RobotRuntime.__init__` reads
        # `store.section("awareness")`) with no way for any operator to turn
        # the knob — the ROAM-1 / TRUTH-1 finding, a third time. ONE ENTRY
        # EXEMPTING A SUBTREE, the roster's own shape, and legitimate for the
        # stated reason: the read-site validator is
        # `awareness_limits_from_config`, which refuses an unknown key inside
        # the section BY NAME and type-checks every value. The feature ships
        # disabled; an overlay that sets `awareness.enabled: true` is how it
        # turns on without re-pinning the base.
        "awareness",
        # ---- END CARD AWARE-1 ----------------------------------------------
        # NOT HERE, deliberately, and each for a measured reason.
        #
        # `required_capabilities`: CAP-1 reads that key from the NAVIGATION
        # config (`admission.navigation_config_mapping` ->
        # `required_capabilities`), which the robot profile selects with the
        # base key `navigation.config` — so a top-level entry here would be
        # admitted, merged, read by nothing, and would look exactly like a
        # declaration. `admission.REQUIRED_CAPABILITIES_KEY`'s own docstring
        # says which file it lives in; this card obeys it instead of adding a
        # second spelling. The declaration is in
        # `configs/navigation/venues/go2_edu_plus.yaml`.
        #
        # `perception.lidar_*`: HW-5's first pass put the Mid-360's band and
        # extrinsic in four flat scalars here, on the reasoning that a family
        # with NO read-site validator is only honest as scalars. The premise
        # was wrong in this tree: the validator exists — HW-2's
        # `band_profile_from_config` — and it lives under `backend.band`. Four
        # keys nothing reads is exactly the defect this list's own docstring
        # warns about, so they are gone and the numbers are in `backend.band`.
        # ---- END CARD HW-5 ---------------------------------------------------
        # A6 STOP-LOCAL: the spoken stop's grammar policy (mode + name), which
        # the SHA-locked base omits. Typo guard at the READ site as with `roam`:
        # `audio.stop_hotword.StopHotwordConfig.from_mapping` refuses by name.
        "stop_hotword",
    }
)


def check_overlay_keys(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    source: str = "overlay",
    prefix: str = "",
) -> None:
    """Refuse an overlay key path the base configuration does not define.

    THE DEFECT THIS EXISTS FOR. A profile overlay is deep-merged, and a merge
    has no opinion about spelling: ``agent.affect.minimum_confidenc: 0.5``
    merged cleanly, added a key nothing reads, left the threshold at the
    shipped 0.75, and booted. The operator got the production robot while the
    file on disk said otherwise — the exact silent-default failure the rest of
    this loader refuses to have.

    So every key path in the overlay must already exist in the base mapping,
    recursively (mappings recurse; lists and scalars are leaves and their
    CONTENTS are values, not schema). Two exemptions, both explicit and both
    named above: :data:`OVERLAY_FREEFORM_PATHS` (children are data) and
    :data:`OVERLAY_INTRODUCIBLE_KEYS` (optional keys the SHA-locked base omits).

    This is a spelling check, not a type check. The downstream fail-closed
    validators still see the merged mapping and still refuse a well-spelled key
    with a wrong value; both layers are wanted, because they catch different
    mistakes.
    """

    for key, value in overlay.items():
        path = f"{prefix}{key}"
        if path in OVERLAY_FREEFORM_PATHS:
            continue
        if key not in base:
            if path in OVERLAY_INTRODUCIBLE_KEYS:
                continue
            near = difflib.get_close_matches(str(key), [str(k) for k in base], n=3, cutoff=0.6)
            hint = f" Did you mean: {', '.join(near)}?" if near else ""
            raise ProfileError(
                f"{source}: unknown key {path!r} — the base configuration does "
                f"not define it, so merging it would change nothing and the "
                f"setting would silently stay at its shipped value.{hint} If "
                f"the key is real and the base legitimately omits it, add its "
                f"path to config.OVERLAY_INTRODUCIBLE_KEYS with a reason."
            )
        current = base[key]
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            check_overlay_keys(current, value, source=source, prefix=f"{path}.")


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursive mapping merge; the overlay wins, and a list is a VALUE.

    Merging lists element-wise would make ``brain.skills`` impossible to
    shorten from an overlay, and an overlay that can only ever add is not an
    overlay. So mappings merge and everything else replaces.
    """

    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


# ---- CARD SENSE-1 resolved-profile validation (scrum/20260823/task_3) ------
#
# THE DEFECT, reproduced by the ARCH-1 verifier and again by this card before
# a line was written (X06 / A08 / R14). `deep_merge(configs/robot.yaml,
# configs/robot.go2_edu_plus.yaml)` resolves, on the profile whose entire
# purpose is `safety.require_physical_inputs: true`:
#
#     battery.simulated_percent        90.0        <- a fabricated reading
#     control.controller               simulator   <- the writer axis
#     control.unitree_sport.interface  enp3s0      <- a DESKTOP's NIC
#     wifi_cards.robot.interface       enp3s0      <- the same desktop NIC
#
# Not one of them is written by the profile. The profile's own header FORBIDS
# writing the first two, and `tests/test_hw5_physical_profile.py` greps the
# file to enforce that — correctly, because a profile that WROTE
# `battery.simulated_percent` would be handing the runtime a fabricated
# hardware reading. But a commented-out key does not delete a base value, so
# the rule produced a file that looks clean and a RESOLVED CONFIG that is not:
# on the dog, `runtime.py:2174` reads that 90.0 and reports it as the battery.
#
# THE FIX IS NOT "let the profile set them". It is that a profile claiming a
# physical rig must SAY, for every simulator premise it inherits, which of
# three things is true — and that a profile which says nothing is refused at
# load, by name, with the fix in the message:
#
#   * the profile sets the key itself (a real value, measured on the rig);
#   * `physical_resolution.no_value_on_this_rig` — the base's value is not
#     this rig's truth and reading it is refused (:func:`require_physical_value`);
#   * `physical_resolution.inherited_deliberately` — the base's value IS this
#     rig's truth and stands, which for `control.controller: simulator` is the
#     accurate answer: Parcel commands no motion on this robot, so the only
#     writer is the one that writes nothing (docs/MOTION.md, design §5.5).
#
# WHAT THE MERGE STILL DOES, unchanged and on purpose: nothing is deleted from
# the resolved mapping. `ConfigStore.data` is still `deep_merge`'s output
# byte for byte — HW-5's row asserting `merged["battery"] ==
# base["battery"]` is a statement about the loader's transparency and it is
# still true. What changes is that a rig may no longer be SILENT about a
# premise, and that a declared-absent key has a typed refusal at USE instead
# of a plausible simulator value.
#
# WHY THE TRIGGER IS THE OVERLAY'S OWN DECLARATION, not the merged value.
# `safety.require_physical_inputs: true` in the merged config can also come
# from a base that a test or an operator edited by hand
# (`tests/test_hw2_go2_backend.py:_config_tree` does exactly that, and there
# is no overlay in sight). Inheritance is a question only a PROFILE can be
# asked: it is the file that chose to leave a key behind. So the check runs
# when the OVERLAY declares the rig physical, and a base config with the
# switch flipped is left exactly as it was.


class PhysicalProfileError(ProfileError):
    """A profile claimed a physical rig and left a simulator premise unresolved.

    A ``ProfileError`` subclass so every existing ``except ProfileError`` — the
    launcher's, ``ingest.active_venue``'s — keeps catching it.
    """


#: The section a physical profile resolves its inheritance in.
PHYSICAL_RESOLUTION_KEY = "physical_resolution"

#: Its two WRITABLE dispositions. ``no_value_on_this_rig`` means a read is
#: REFUSED; ``inherited_deliberately`` means the base's value stands.
PHYSICAL_RESOLUTION_ABSENT = "no_value_on_this_rig"
PHYSICAL_RESOLUTION_KEPT = "inherited_deliberately"
PHYSICAL_RESOLUTION_DISPOSITIONS = (PHYSICAL_RESOLUTION_ABSENT, PHYSICAL_RESOLUTION_KEPT)

#: The third disposition, which is never written because it is DEMONSTRATED:
#: the profile set the key itself. A measured value is the strongest answer to
#: "what does this rig do about the base's?", so it supersedes a declaration —
#: including a stale ``no_value_on_this_rig`` entry left behind when box-day
#: step B9 finally fills a NIC in. That order is not a convenience: HW-5's
#: pinned launcher row fills `backend.interface` into the shipped profile and
#: nothing else, which is exactly the operator gesture the card describes, and
#: a loader that then refused would be refusing the fix.
PHYSICAL_RESOLUTION_SET = "set_by_profile"

#: Every simulator premise a physical profile must resolve: ``path -> (why,
#: fix)``. The list is short and closed on purpose — it is the four keys the
#: ARCH-1 verifier reproduced plus the one box-day key HW-5 deliberately left
#: unset — because a validator that guesses which keys are premises would
#: either miss the ones that matter or refuse a profile for a key nobody meant.
PHYSICAL_PREMISE_KEYS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "battery.simulated_percent": (
            (
                "a fabricated battery reading the base ships because the simulator "
                "has no battery; a robot has one and it is SENSED"
            ),
            (
                f"declare it under {PHYSICAL_RESOLUTION_KEY}."
                f"{PHYSICAL_RESOLUTION_ABSENT} (the profile may not write this key: "
                "it would be the fabricated reading itself)"
            ),
        ),
        "control.controller": (
            (
                "the WRITER axis: it says what moves the robot, and a physical "
                "profile may not arm hardware by configuration"
            ),
            (
                f"declare it under {PHYSICAL_RESOLUTION_KEY}."
                f"{PHYSICAL_RESOLUTION_KEPT} if the base's `simulator` is the truth "
                "on this rig (it is, while Parcel commands no motion — "
                "docs/MOTION.md)"
            ),
        ),
        "control.unitree_sport.interface": (
            (
                "the NIC the MOTION venv's commissioning writer binds; the base "
                "ships a desktop's name for a port that does not exist on the robot"
            ),
            (
                "set it to the NIC read from `ls /sys/class/net` on the Orin "
                f"(box-day step B9), or declare it under {PHYSICAL_RESOLUTION_KEY}."
                f"{PHYSICAL_RESOLUTION_ABSENT} until that reading exists"
            ),
        ),
        "wifi_cards.robot.interface": (
            (
                "the same cable under its second spelling; a desktop NIC name here "
                "sends the panel's network card at a port the robot does not have"
            ),
            (
                "set it to the same NIC as control.unitree_sport.interface, or "
                f"declare it under {PHYSICAL_RESOLUTION_KEY}."
                f"{PHYSICAL_RESOLUTION_ABSENT}"
            ),
        ),
        "backend.interface": (
            (
                "the NIC the PRODUCT venv's observer binds for `rt/sportmodestate`; "
                "the base does not define it at all, so there is nothing to inherit "
                "and nothing to fabricate"
            ),
            (
                "set it from the same box-day reading, or declare it under "
                f"{PHYSICAL_RESOLUTION_KEY}.{PHYSICAL_RESOLUTION_ABSENT} while it "
                "is unmeasured (`LiveGo2Sources` then refuses at USE, by name)"
            ),
        ),
    }
)


def _dotted(mapping: Mapping[str, Any] | object, path: str) -> tuple[bool, Any]:
    """``(found, value)`` for a dotted path in a nested mapping."""

    node: Any = mapping
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False, None
        node = node[part]
    return True, node


def physical_resolution_dispositions(
    resolved: Mapping[str, Any],
) -> Mapping[str, str]:
    """``path -> disposition`` as the resolved config DECLARES it.

    The written half only: it cannot see :data:`PHYSICAL_RESOLUTION_SET`, which
    is a fact about the overlay rather than about the merge.
    :func:`validate_physical_resolution` returns the effective map, and
    :attr:`ConfigStore.physical_resolution` is where a read site finds it.

    Empty when the config declares nothing, which is every configuration in the
    tree but a physical profile's.
    """

    section = resolved.get(PHYSICAL_RESOLUTION_KEY)
    if not isinstance(section, Mapping):
        return MappingProxyType({})
    declared: dict[str, str] = {}
    for disposition in PHYSICAL_RESOLUTION_DISPOSITIONS:
        paths = section.get(disposition)
        if not isinstance(paths, (list, tuple)):
            continue
        for path in paths:
            declared[str(path)] = disposition
    return MappingProxyType(declared)


def declares_physical_rig(overlay: Mapping[str, Any]) -> bool:
    """True when ``overlay`` is a profile for a NAMED PHYSICAL RIG.

    Both halves are load-bearing and each one is protected by a shipped row
    this card is not allowed to move:

    * ``safety.require_physical_inputs`` is read from the OVERLAY, not from the
      merge, because a BASE configuration can carry it too — ``tests/
      test_hw2_go2_backend.py:_config_tree`` writes it into a copy of the base
      and merges an unrelated one-key overlay on top. There is no inheritance
      question to ask there: with no profile, the file on disk is the whole
      truth.
    * ``venue`` is the rig identity, and requiring it is what separates a
      profile from a FRAGMENT. ``tests/test_hw5_physical_profile.py::
      test_a_misspelling_of_each_new_key_refuses_by_name_at_the_real_loader``
      loads ``{safety: {require_physical_inputs: true}}`` and nothing else, to
      prove the spelling guard admits the good spelling; a file that does not
      say which rig it is on is not making a claim about hardware.
    """

    return (
        _dotted(overlay, "safety.require_physical_inputs")[1] is True
        and bool(str(overlay.get("venue", "") or "").strip())
    )


def validate_physical_resolution(
    overlay: Mapping[str, Any],
    resolved: Mapping[str, Any],
    *,
    source: str = "profile",
) -> Mapping[str, str]:
    """Refuse a physical profile that inherited a simulator premise silently.

    ``overlay`` is the profile as written (what it EXPLICITLY set); ``resolved``
    is the merge (what the runtime will actually read). Both are needed: the
    defect is precisely the difference between them.

    Returns the EFFECTIVE disposition of every premise — the declared one, or
    :data:`PHYSICAL_RESOLUTION_SET` where the profile answered with a value.
    """

    section = resolved.get(PHYSICAL_RESOLUTION_KEY, {})
    if not isinstance(section, Mapping):
        raise PhysicalProfileError(
            f"{source}: {PHYSICAL_RESOLUTION_KEY} must be a mapping of "
            f"{' / '.join(PHYSICAL_RESOLUTION_DISPOSITIONS)} to lists of key paths"
        )
    unknown_sections = sorted(
        str(key) for key in section if str(key) not in PHYSICAL_RESOLUTION_DISPOSITIONS
    )
    if unknown_sections:
        raise PhysicalProfileError(
            f"{source}: unknown {PHYSICAL_RESOLUTION_KEY} key(s) "
            f"{', '.join(unknown_sections)}; the dispositions are "
            f"{' and '.join(PHYSICAL_RESOLUTION_DISPOSITIONS)}"
        )
    for disposition in PHYSICAL_RESOLUTION_DISPOSITIONS:
        if disposition in section and not isinstance(section[disposition], (list, tuple)):
            raise PhysicalProfileError(
                f"{source}: {PHYSICAL_RESOLUTION_KEY}.{disposition} must be a list of "
                f"key paths, got {type(section[disposition]).__name__}"
            )
    seen: set[str] = set()
    for disposition in PHYSICAL_RESOLUTION_DISPOSITIONS:
        for path in section.get(disposition, ()) or ():
            path = str(path)
            if path not in PHYSICAL_PREMISE_KEYS:
                raise PhysicalProfileError(
                    f"{source}: {PHYSICAL_RESOLUTION_KEY}.{disposition} names "
                    f"{path!r}, which is not one of the simulator premises this "
                    f"loader knows: {', '.join(sorted(PHYSICAL_PREMISE_KEYS))}. A "
                    f"declaration about a key nothing checks is a decoration."
                )
            if path in seen:
                raise PhysicalProfileError(
                    f"{source}: {path!r} is declared twice under "
                    f"{PHYSICAL_RESOLUTION_KEY}; a premise has one disposition"
                )
            seen.add(path)

    declared = physical_resolution_dispositions(resolved)
    effective: dict[str, str] = {}
    for path, (why, fix) in PHYSICAL_PREMISE_KEYS.items():
        set_by_profile, _own_value = _dotted(overlay, path)
        disposition = declared.get(path)
        if set_by_profile:
            # A MEASURED VALUE WINS over any declaration, including a stale
            # `no_value_on_this_rig` — see PHYSICAL_RESOLUTION_SET.
            effective[path] = PHYSICAL_RESOLUTION_SET
            continue
        if disposition is not None:
            effective[path] = disposition
            continue
        found, inherited = _dotted(resolved, path)
        carries = (
            f"resolves to {inherited!r}, inherited from the base configuration"
            if found
            else "is not defined anywhere in the resolved configuration"
        )
        raise PhysicalProfileError(
            f"{source}: this profile declares safety.require_physical_inputs: true, "
            f"so it is a ROBOT — but {path} {carries} and the profile says nothing "
            f"about it. {why.capitalize()}. Fix: {fix}."
        )
    return MappingProxyType(effective)


def require_physical_value(
    resolved: Mapping[str, Any],
    path: str,
    *,
    dispositions: Mapping[str, str] | None = None,
) -> Any:
    """The value at ``path``, or a typed refusal naming the key and the fix.

    The USE half of the mechanism above, and the answer to "what does a
    deliberately unset box-day key do when something finally reads it?" — it
    refuses by name, which is the same thing ``LiveGo2Sources`` already does
    for ``backend.interface`` and for the same reason: a fabricated default is
    a confident lie, and a NIC name nobody read is not a NIC name.

    ``dispositions`` is the EFFECTIVE map (:attr:`ConfigStore.
    physical_resolution`). Left out, the declaration is read from ``resolved``
    itself, which cannot see a value the profile supplied over a stale
    declaration — so a read site with a store should pass the store's map.
    """

    if dispositions is None:
        dispositions = physical_resolution_dispositions(resolved)
    disposition = dispositions.get(path)
    why, fix = PHYSICAL_PREMISE_KEYS.get(path, ("", ""))
    if disposition == PHYSICAL_RESOLUTION_ABSENT:
        raise PhysicalProfileError(
            f"{path} has no value on this rig: the profile declared it "
            f"{PHYSICAL_RESOLUTION_ABSENT}"
            + (f" ({why})" if why else "")
            + (f". Fix: {fix}." if fix else ".")
        )
    found, value = _dotted(resolved, path)
    if not found:
        raise PhysicalProfileError(
            f"{path} is not defined in this configuration and has no default worth "
            f"inventing" + (f". Fix: {fix}." if fix else ".")
        )
    return value


# ---- END CARD SENSE-1 resolved-profile validation ---------------------------


class ConfigStore:
    """Loads user-editable poses, network cards, and extension modules.

    FAIL-CLOSED NUMERICS (card R23)
    -------------------------------
    Every numeric key this loader coerces is validated here, at the boundary,
    with an error that names the file, the dotted key, and the offending
    value. The doctrine is ``realtime/config.py``'s and the reason is the same:
    a typo that silently reads as "no limit" is worse than a typo that refuses
    to start. It matters most for the velocity clamps, because a NaN there is
    not a wrong clamp — it is no clamp, at both enforcement sites at once.

    ``configs/robot.yaml`` is digest-pinned and passes this validation
    unchanged; nothing here alters an effective limit on the shipped config.

    PROFILE OVERLAYS (card P0-A)
    ----------------------------
    ``configs/robot.yaml`` is SHA-locked (``evals/companion/embodied_plan_v1/
    manifest.json``), so every relaxation the prototype wants used to be an
    edit that moved that digest. A profile is the alternative: with
    ``PARCEL_PROFILE=prototype`` (or ``profile="prototype"``) this loader
    deep-merges the sibling ``configs/robot.prototype.yaml`` over the shipped
    file and hands the MERGED mapping to every consumer.

    The merge happens here, at the very bottom, on purpose: nothing downstream
    learns that profiles exist, and every validator — this class's fail-closed
    numerics, ``ReactiveSafetyPolicy``, ``FollowConfig.from_mapping``,
    ``CameraStreamConfig.from_section`` and the rest — sees the merged result
    and refuses a WRONG VALUE in the overlay exactly as it refuses one in the
    base.

    Those validators cannot catch a MISSPELLED KEY, though, because most of
    them read with a default and a key nothing reads is indistinguishable from
    a key nobody wrote. :func:`check_overlay_keys` runs before the merge and
    closes that: an overlay key path the base does not define is a refusal.

    With no profile the loader is transparent: ``self.data`` is
    ``yaml.safe_load`` of the file and nothing else.
    """

    def __init__(self, path: str | Path, *, profile: str | None = None):
        self.path = Path(path)
        #: ``None`` = consult ``$PARCEL_PROFILE``; ``""`` = explicitly no
        #: profile, ignore the environment (what tests of the default path
        #: want, and what the byte-identity proof runs under).
        self.profile = resolve_profile() if profile is None else _clean_profile(profile)
        self.overlay_path: Path | None = None
        #: ---- CARD SENSE-1 ---- The effective disposition of every simulator
        #: premise (``path -> set_by_profile / no_value_on_this_rig /
        #: inherited_deliberately``). EMPTY for every configuration that is not
        #: a named physical rig's, which is all of them but ``go2_edu_plus``.
        self.physical_resolution: Mapping[str, str] = MappingProxyType({})
        with self.path.open(encoding="utf-8") as stream:
            data: dict[str, Any] = yaml.safe_load(stream) or {}
        if self.profile:
            overlay = self._load_overlay(self.profile)
            # Spelling first, then merge. A key the base does not define cannot
            # change anything, so merging it and letting the value validators
            # pass is how `minimum_confidenc: 0.5` booted at 0.75.
            check_overlay_keys(data, overlay, source=str(self.overlay_path))
            data = deep_merge(data, overlay)
            # ---- CARD SENSE-1 (scrum/20260823/task_3) --------------------
            # Third and last: a profile that claims a physical rig must have
            # resolved what it inherits. The gate is the OVERLAY's own
            # declaration, so a base configuration with the switch flipped by
            # hand is untouched — see the region above `ConfigStore` for why
            # the merged value would be the wrong question to ask.
            if declares_physical_rig(overlay):
                self.physical_resolution = validate_physical_resolution(
                    overlay, data, source=str(self.overlay_path or self.path)
                )
            # ---- END CARD SENSE-1 ----------------------------------------
        self.data: dict[str, Any] = data

    def _load_overlay(self, profile: str) -> dict[str, Any]:
        """Read ``<base>.<profile>.<ext>``, or say which file is missing.

        A named profile whose file is absent is a typo at the command line, and
        starting the shipped configuration instead would answer it silently —
        the operator asked for a different robot and would get the default one
        with no way to tell from the panel. So this refuses by NAME and prints
        the path it looked for; it is a spelling error, not a policy.
        """

        overlay = profile_overlay_path(self.path, profile)
        if not overlay.is_file():
            raise ProfileError(
                f"config profile {profile!r} selected but {overlay} does not exist"
            )
        with overlay.open(encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, Mapping):
            raise ProfileError(
                f"{overlay}: a profile overlay must be a mapping, got "
                f"{type(loaded).__name__}"
            )
        self.overlay_path = overlay
        return dict(loaded)

    # ------------------------------------------------------------------
    # Fail-closed numeric coercion (card R23)
    # ------------------------------------------------------------------

    def _number(self, value: object, key: str) -> float:
        """Coerce one config value to a real number or refuse by name."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SafetyLimitError(f"{self.path}: {key} must be a number, got {value!r}")
        number = float(value)
        if not math.isfinite(number):
            raise SafetyLimitError(
                f"{self.path}: {key} must be finite, got {number}. A non-finite "
                f"value here is not a loose setting, it is an absent one."
            )
        return number

    def _positive_number(self, mapping: Mapping[str, Any], key: str, default: float, path: str) -> float:
        """A finite, strictly positive config number, named by its dotted key."""

        number = self._number(mapping.get(key, default), path)
        if number <= 0.0:
            raise SafetyLimitError(
                f"{self.path}: {path} must be greater than zero, got {number}. "
                f"A zero or negative clamp reads as a typo, not as intent."
            )
        return number

    def _whole_number(self, mapping: Mapping[str, Any], key: str, default: int, path: str) -> int:
        """A non-negative whole number. ``True`` is not 1 and 2.5 is not 2."""

        value = mapping.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SafetyLimitError(f"{self.path}: {path} must be a whole number, got {value!r}")
        if isinstance(value, float) and (not math.isfinite(value) or value != int(value)):
            raise SafetyLimitError(f"{self.path}: {path} must be a whole number, got {value!r}")
        number = int(value)
        if number < 0:
            raise SafetyLimitError(f"{self.path}: {path} must not be negative, got {number}")
        return number

    def poses(self) -> dict[str, Pose]:
        legacy = {
            name: Pose(
                name=name,
                joints={
                    joint: self._number(value, f"poses.{name}.joints.{joint}")
                    for joint, value in item["joints"].items()
                },
                duration=self._positive_number(item, "duration", 1.0, f"poses.{name}.duration"),
            )
            for name, item in self.data.get("poses", {}).items()
        }
        try:
            from parcel_robot.skills.catalog import SkillCatalog

            catalog = SkillCatalog.load(self.skills_root())
            poses = catalog.as_pose_map()
            poses.update(legacy)
            return poses
        except (FileNotFoundError, OSError, KeyError, ValueError, TypeError):
            return legacy

    def skills_root(self) -> Path:
        configured = None
        if "skills" in self.data and isinstance(self.data["skills"], dict):
            configured = self.data["skills"].get("root")
        from parcel_robot.paths import resolve_skills_root

        try:
            return resolve_skills_root(str(configured) if configured else None)
        except FileNotFoundError:
            # Preserve historical cwd fallback for ad-hoc local layouts.
            path = Path(str(configured or "configs/skills")).expanduser()
            if path.is_absolute():
                return path
            return (Path.cwd() / path).resolve()

    def motion_config(self) -> dict[str, Any]:
        return self.section("motion") if "motion" in self.data else {"backend": "rl"}

    def agent_config(self) -> dict[str, Any]:
        return self.section("agent") if "agent" in self.data else {}

    def prompts_root(self) -> Path:
        configured = self.agent_config().get("prompts_root", "prompts")
        from parcel_robot.paths import resolve_prompts_root

        try:
            return resolve_prompts_root(str(configured) if configured else None)
        except FileNotFoundError:
            path = Path(str(configured or "prompts")).expanduser()
            if path.is_absolute():
                return path.resolve()
            return (Path.cwd() / path).resolve()

    def safety_limits(self) -> SafetyLimits:
        """The velocity clamp both enforcement sites compare against.

        Card R23: previously a bare ``float()``, which turned ``max_vx: .nan``
        into a silently disabled clamp in the arbiter AND the
        SafetySupervisor. The defaults below are deliberately left at the
        historical (0.6, 0.4, 1.0) — they are the loader's fallback, not the
        dataclass's, and changing them is a threshold change this card does
        not make.
        """

        motion = self.motion_config()
        return SafetyLimits(
            max_vx=self._positive_number(motion, "max_vx", 0.6, "motion.max_vx"),
            max_vy=self._positive_number(motion, "max_vy", 0.4, "motion.max_vy"),
            max_vyaw=self._positive_number(motion, "max_vyaw", 1.0, "motion.max_vyaw"),
        )

    def wifi_cards(self) -> dict[str, WifiCard]:
        return {
            name: WifiCard(
                name=name,
                interface=str(item["interface"]),
                ros_domain_id=self._whole_number(
                    item, "ros_domain_id", 0, f"wifi_cards.{name}.ros_domain_id"
                ),
                purpose=str(item.get("purpose", "robot")),
            )
            for name, item in self.data.get("wifi_cards", {}).items()
        }

    def module_specs(self) -> list[ModuleSpec]:
        return [
            ModuleSpec(
                name=str(item["name"]),
                class_path=str(item["class"]),
                enabled=bool(item.get("enabled", True)),
                config=dict(item.get("config", {})),
            )
            for item in self.data.get("modules", [])
        ]

    def load_modules(self) -> list[Any]:
        modules = []
        for spec in self.module_specs():
            if not spec.enabled:
                continue
            module_name, class_name = spec.class_path.rsplit(".", 1)
            module_class = getattr(importlib.import_module(module_name), class_name)
            modules.append(module_class(spec.config))
        return modules

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        if not isinstance(value, dict):
            raise TypeError(f"configuration section {name!r} must be a mapping")
        return dict(value)

    # ---- CARD SENSE-1 (scrum/20260823/task_3) ---------------------------

    def physical_value(self, path: str) -> Any:
        """One value, honouring what a physical profile declared about it.

        The read a mount-day caller should use for anything in
        :data:`PHYSICAL_PREMISE_KEYS`: on a rig that disowned the key it
        REFUSES by name with the fix, instead of handing back the simulator's
        number the merge still carries. On every other configuration — no
        profile, the prototype, a simulator run — nothing is declared and this
        is a plain lookup that refuses only a genuinely absent key.
        """

        return require_physical_value(
            self.data, path, dispositions=self.physical_resolution
        )
