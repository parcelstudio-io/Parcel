"""Regression tests for the shared companion-to-embodiment prompt contract."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _prompt(name: str) -> str:
    return (REPO / "prompts" / "system" / name).read_text(encoding="utf-8")


def test_core_prompt_makes_continuity_support_and_owner_space_explicit() -> None:
    core = _prompt("core.md")
    for phrase in (
        "ongoing companion friend by default",
        "recent dialogue and consented memory only",
        "quiet, privacy, distance",
        "inferred emotion never authorizes base travel",
        "fresh owner and world evidence",
    ):
        assert phrase in core


def test_action_examples_never_expand_the_active_capability_registry() -> None:
    policy = " ".join(_prompt("action_policy.md").split())
    for phrase in (
        "`runtime_context.available_social_skills` is the sole action allowlist",
        "copy its name exactly from that JSON list",
        "return `next_action: null`",
        "Never substitute a different available skill",
        "if it supplies bare names only, return null",
        "Immediately before returning JSON, validate the proposal again",
        "never authorizes base travel",
        "separately supplied admitted action contract",
    ):
        assert phrase in policy


def test_core_prompt_names_the_only_action_allowlist_and_fail_closed_result() -> None:
    core = " ".join(_prompt("core.md").split())
    assert "`runtime_context.available_social_skills` is the sole allowlist" in core
    assert "Every non-null action name must be copied exactly from that list" in core
    assert "return `next_action: null` without substituting" in core
