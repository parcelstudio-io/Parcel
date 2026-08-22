from __future__ import annotations

import difflib
import importlib
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
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
        with self.path.open(encoding="utf-8") as stream:
            data: dict[str, Any] = yaml.safe_load(stream) or {}
        if self.profile:
            overlay = self._load_overlay(self.profile)
            # Spelling first, then merge. A key the base does not define cannot
            # change anything, so merging it and letting the value validators
            # pass is how `minimum_confidenc: 0.5` booted at 0.75.
            check_overlay_keys(data, overlay, source=str(self.overlay_path))
            data = deep_merge(data, overlay)
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
