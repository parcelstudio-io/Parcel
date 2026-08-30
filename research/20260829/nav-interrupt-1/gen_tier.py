"""NAV-INT-1 — deterministic generator for ``interrupt_tier_v1.json``.

ADDITIVE tier. It touches no frozen episode set: ``evals/nav_instruct``
v1–v4 (and v4s) are read-only to this experiment and no digest moves.

40 episodes = 10 ordered goal pairs x 4 interruption triggers
(fraction 0.25 / 0.5 / 0.75, and one wall-clock trigger), with the five
phrasing families spread 8-8-8-8-8 across the 40 slots by a seeded shuffle.
Every distinct goal gets a paired FROM-REST control (DESIGN.md: "paired
from-rest controls for every goal"), and every distinct ordered pair gets a
FROM-REST SEQUENCE control (goal 2 then goal 1, both from rest) — that is the
reference the H-NI1b path-length ratio is measured against.

AMENDMENT N4 (binding): every place name in every generated utterance is
checked against an allowlist built from the scene's own derived landmark
labels. The NAV evals' held-out scene is never named anywhere in this folder.

Run: ``.parcel/bin/python research/20260829/nav-interrupt-1/gen_tier.py``
(deterministic: re-running overwrites the file byte-for-byte).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.nav_instruct.scene_truth import derived_landmark_table

SEED = 20260829
TIER_ID = "interrupt_tier_v1"

#: Goals, keyed as in ``harness.GOALS``. ``place`` is the noun the utterance
#: uses; ``goal_1_ok`` marks the goals that can legitimately be interrupted
#: mid-flight. The owner-approach lane (``come here`` / ``go to the owner``)
#: is a PERSISTENT FollowFormation whose task record reports ``succeeded``
#: about a second after dispatch (measured in ``tests/test_voice_nav_e2e.py``),
#: so it can never be the goal that is halfway done — it appears only as the
#: interrupting goal 2.
GOAL_CATALOGUE: dict[str, dict] = {
    "sidewalk": {"place": "sidewalk", "plain": "go to the sidewalk", "goal_1_ok": True},
    "lamppost": {"place": "lamppost", "plain": "go to the lamppost", "goal_1_ok": True},
    "bench": {"place": "bench", "plain": "go to the bench", "goal_1_ok": True},
    "towards_lamppost": {
        "place": "lamppost",
        "plain": "walk towards the lamppost",
        "goal_1_ok": True,
    },
    "come_here": {"place": "owner", "plain": "come here", "goal_1_ok": False},
}

#: Pairs that name the same physical anchor twice are excluded: an amendment
#: from "go to the lamppost" to "walk towards the lamppost" is not a goal
#: change, and scoring it as one would inflate every rate in the tier.
_SAME_ANCHOR = {("lamppost", "towards_lamppost"), ("towards_lamppost", "lamppost")}

#: AMENDMENT N5 — the shipped stack has TWO admission paths and the tier must
#: exercise both with >= 12 episodes each, plus a bare-cue HOLD row.
#:
#: * ``amend_cue``   — the C8 transactional amendment: the utterance carries a
#:   cue from ``voice/closed_intents._GOAL_AMEND`` (actually / instead / no, /
#:   change that / correction / rather), so ``runtime._apply_goal_amend`` runs
#:   its suspend-quiesce-replace transaction.
#: * ``explicit_directive`` — a bare second directive: ``submit()`` plus
#:   ``request_interrupt(source="correction", requested="at_checkpoint")``,
#:   which cancels the first task at its next checkpoint. No HOLD, no suspend.
#: * ``queue`` — the "after that / when you're done" family. AMENDMENT N9: the
#:   harness HOLDS these; they never reach ``handle_text`` mid-task.
#: * ``hold`` — an amend cue with NO replacement goal ("actually"), the
#:   bounded self-explaining hold (``goal_amend_replan == "waiting_for_goal"``).
PHRASING_FAMILIES: dict[str, str] = {
    "amend_actually": "actually, {plain}",
    "amend_no": "no, {plain}",
    "amend_instead": "instead {plain}",
    "explicit_directive": "{plain}",
    "queue_after_that": "after that, {plain}",
    "hold_actually": "actually",
}
FAMILY_CLASS: dict[str, str] = {
    "amend_actually": "amend_cue",
    "amend_no": "amend_cue",
    "amend_instead": "amend_cue",
    "explicit_directive": "explicit_directive",
    "queue_after_that": "queue",
    "hold_actually": "hold",
}
#: Exact counts over the 40 slots: amend_cue 14, explicit_directive 14,
#: queue 8, hold 4 — both admission paths clear amendment N5's >= 12 bar.
#: ``come here`` does not survive a prefix: the closed COME grammar is an
#: EXACT phrase set (``voice/closed_intents._PHRASES``), so "actually, come
#: here" is a goal amendment whose residual is not a COME. Owner goal 2s
#: therefore take the amendment cue with the explicit owner phrasing.
OWNER_PLAIN_FOR_CUED_FAMILIES = "go to the owner"

FAMILY_COUNTS: dict[str, int] = {
    "amend_actually": 5,
    "amend_no": 5,
    "amend_instead": 4,
    "explicit_directive": 14,
    "queue_after_that": 8,
    "hold_actually": 4,
}

TRIGGERS: list[dict] = [
    {"kind": "fraction", "fraction": 0.25, "time_s": 45.0},
    {"kind": "fraction", "fraction": 0.5, "time_s": 45.0},
    {"kind": "fraction", "fraction": 0.75, "time_s": 45.0},
    {"kind": "time", "fraction": None, "time_s": 6.0},
]

N_PAIRS = 10


def allowed_place_names() -> set[str]:
    """AMENDMENT N4 — the only place nouns generated text may contain."""

    names = {
        str(row.get("label")).lower()
        for row in derived_landmark_table().values()
        if row.get("label")
    }
    names.add("owner")
    return names


def scan_names(text: str, allowed: set[str]) -> None:
    """Refuse any generated utterance that names a place outside the scene."""

    for word in re.findall(r"[a-z]+", text.lower()):
        if word in allowed:
            continue
        if word in _FUNCTION_WORDS:
            continue
        raise ValueError(f"generated text names a non-scene word {word!r}: {text!r}")


_FUNCTION_WORDS = {
    "a", "actually", "after", "and", "are", "come", "done", "go", "head", "here",
    "instead", "me", "no", "on", "onto", "once", "over", "please", "that", "the",
    "then", "to", "towards", "walk", "when", "you", "your", "re", "finish", "s",
}


def build(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    allowed = allowed_place_names()

    keys = sorted(GOAL_CATALOGUE)
    first_keys = [key for key in keys if GOAL_CATALOGUE[key]["goal_1_ok"]]
    pairs = [
        (a, b)
        for a in first_keys
        for b in keys
        if a != b and (a, b) not in _SAME_ANCHOR
    ]
    pairs.sort()
    rng.shuffle(pairs)
    chosen_pairs = sorted(pairs[:N_PAIRS])

    slots = len(chosen_pairs) * len(TRIGGERS)
    if slots != 40:
        raise ValueError(f"tier must be exactly 40 episodes, got {slots}")
    families = [name for name in sorted(FAMILY_COUNTS) for _ in range(FAMILY_COUNTS[name])]
    if len(families) != slots:
        raise ValueError(f"family counts sum to {len(families)}, need {slots}")
    rng.shuffle(families)

    episodes: list[dict] = []
    for index, (pair, trigger) in enumerate(
        [(pair, trigger) for pair in chosen_pairs for trigger in TRIGGERS]
    ):
        goal_1, goal_2 = pair
        family = families[index]
        template = PHRASING_FAMILIES[family]
        plain_2 = GOAL_CATALOGUE[goal_2]["plain"]
        if goal_2 == "come_here" and family not in {"explicit_directive", "hold_actually"}:
            plain_2 = OWNER_PLAIN_FOR_CUED_FAMILIES
        text_1 = GOAL_CATALOGUE[goal_1]["plain"]
        text_2 = template.format(plain=plain_2)
        scan_names(text_1, allowed)
        scan_names(text_2, allowed)
        episodes.append(
            {
                "episode_id": f"ni1-{index:02d}-{goal_1}-{goal_2}",
                "goal_1": {
                    "key": goal_1,
                    "place": GOAL_CATALOGUE[goal_1]["place"],
                    "text": text_1,
                },
                "goal_2": {
                    "key": goal_2,
                    "place": GOAL_CATALOGUE[goal_2]["place"],
                    "text": text_2,
                    "family": family,
                    "family_class": FAMILY_CLASS[family],
                    # The HOLD family names no replacement goal at all, so
                    # there is no goal-2 arrival to score for those rows.
                    "has_goal": family != "hold_actually",
                },
                "trigger": dict(trigger),
                "control_goal_1": f"ctl-{goal_1}",
                "control_goal_2": f"ctl-{goal_2}",
                "sequence_control": f"seq-{goal_2}-then-{goal_1}",
            }
        )

    used_goals = sorted({ep["goal_1"]["key"] for ep in episodes} | {ep["goal_2"]["key"] for ep in episodes})
    controls = [
        {
            "control_id": f"ctl-{key}",
            "goal_key": key,
            "text": GOAL_CATALOGUE[key]["plain"],
            "reps": 2,
        }
        for key in used_goals
    ]
    sequence_controls = [
        {
            "control_id": f"seq-{b}-then-{a}",
            "first": {"key": b, "text": GOAL_CATALOGUE[b]["plain"]},
            "second": {"key": a, "text": GOAL_CATALOGUE[a]["plain"]},
        }
        for (a, b) in chosen_pairs
    ]

    return {
        "tier_id": TIER_ID,
        "record_schema": "nav_instruct-style additive tier record (amendment N10)",
        "frozen_baseline": False,
        "seed": seed,
        "generated_by": "research/20260829/nav-interrupt-1/gen_tier.py",
        "evidence_tier": "desktop-sim",
        "scene": "mujoco static city (parcel_robot.sim --static-city)",
        "additive": (
            "additive tier; evals/nav_instruct v1-v4 and every frozen digest "
            "are read-only to this experiment"
        ),
        "note_owner_goal": (
            "the owner-approach lane is a persistent FollowFormation whose task "
            "record succeeds ~1 s after dispatch, so it is never goal 1"
        ),
        "pairs": [list(pair) for pair in chosen_pairs],
        "phrasing_families": dict(PHRASING_FAMILIES),
        "family_class": dict(FAMILY_CLASS),
        "family_counts": dict(FAMILY_COUNTS),
        "triggers": TRIGGERS,
        "episodes": episodes,
        "controls": controls,
        "sequence_controls": sequence_controls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=HERE / "interrupt_tier_v1.json")
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()

    payload = build(args.seed)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print("interrupt_tier_v1.json is STALE", file=sys.stderr)
            return 1
        print("interrupt_tier_v1.json is current")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(
        f"wrote {args.out} — {len(payload['episodes'])} episodes, "
        f"{len(payload['controls'])} from-rest controls, "
        f"{len(payload['sequence_controls'])} sequence controls, seed {args.seed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
