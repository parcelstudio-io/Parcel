#!/usr/bin/env python3
"""Emit a digest of Parcel's *resolved effective configuration*.

N27's exit criterion is that an installed wheel reports the same effective
navigation/prompt/capability configuration as the source checkout. Comparing
files present is not enough: a missing packaged file makes a loader fall back
to a code default silently (``navigation/pipeline.py`` substitutes a default
inside-probability threshold when ``configs/navigation/pose.yaml`` cannot be
read, and the substituted value happens to equal the file's own value today).
Hashing resolved VALUES is what makes that visible.

Absolute paths legitimately differ between install layouts, so nothing here
hashes a resolved path — only values. Per-component sub-hashes are emitted so a
mismatch names the component that moved instead of only "hashes differ".

Run with ``PARCEL_ROOT`` set to pick the tree under test::

    python tools/release_parity_probe.py
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=repr).encode("utf-8")
    ).hexdigest()


def _navigation() -> Any:
    from parcel_robot.navigation.pipeline import DirectiveNavigator

    navigator = DirectiveNavigator.from_config()
    return {
        "model_id": navigator.model_id,
        "progress_timeout_steps": navigator.progress_timeout_steps,
        "safety": navigator.safety,
    }


def _robot() -> Any:
    from parcel_robot.config import ConfigStore
    from parcel_robot.paths import resolve_config_yaml

    store = ConfigStore(resolve_config_yaml())
    return {
        "safety_limits": store.safety_limits(),
        "navigation": store.section("navigation"),
        "safety": store.section("safety"),
        "speech_mode": (store.section("speech") or {}).get("mode"),
    }


def _skills() -> Any:
    from parcel_robot.paths import resolve_skills_root
    from parcel_robot.skills.catalog import SkillCatalog

    catalog = SkillCatalog.load(resolve_skills_root())
    return sorted(catalog.ids())


def _prompts() -> Any:
    from parcel_robot.paths import resolve_prompts_root
    from parcel_robot.prompting.loader import PromptLibrary

    library = PromptLibrary(resolve_prompts_root())
    profiles = sorted(library.list_personalities(), key=lambda profile: profile.id)
    return {
        "personalities": [
            {
                "id": profile.id,
                "name": profile.name,
                "instruction": profile.instruction,
                "reply_style": profile.reply_style,
                "affect_actions": profile.affect_actions,
            }
            for profile in profiles
        ],
        "planner_system": library.planner_system(),
    }


def _personality() -> Any:
    import yaml

    from parcel_robot.paths import resolve_asset

    text = resolve_asset("configs", "personality.yaml", kind="file").read_text(encoding="utf-8")
    return yaml.safe_load(text)


COMPONENTS = {
    "navigation": _navigation,
    "robot": _robot,
    "skills": _skills,
    "prompts": _prompts,
    "personality": _personality,
}


def effective_config() -> dict[str, Any]:
    """Return {component: sub-digest} plus the combined digest."""

    components: dict[str, str] = {}
    for name, loader in COMPONENTS.items():
        try:
            components[name] = _digest(loader())
        except Exception as exc:  # noqa: BLE001 - a broken component IS the finding
            components[name] = f"ERROR:{type(exc).__name__}:{exc}"
    return {"components": components, "digest": _digest(components)}


def main() -> int:
    print(json.dumps(effective_config(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
