# AUDIT — R10 "arrive like you mean it" · Fable

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_3` (revised on bench
evidence) · **Verdict:** **ACCEPT_CLOSE.**

## Independently verified

1. **Gate, auditor's own run: PASS** (final tree 6601 after R11; R10's own
   close at 6486, +91), ruff `new 0` — the executor's 5 self-inflicted ruff
   violations were FIXED, not re-baselined. **The frozen nav baseline did
   not move** — the card's hard constraint held.
2. **All 21 seeds re-run solo: 21/21 RED, restored.** Two initial GREENs
   were weak tests, strengthened per the rule (S20 bypassed the ring
   clearance entirely; S21's owner disc could never reach the ring).
3. **Root cause confirmed and better than the card's guess:** the live
   `semantic_target_unreachable` was a relation gate, not tolerance — both
   `inside` tiers required a straight clear segment (one static occlusion
   disqualified every interior sample) and region goals had NO fallback
   solver (`_fallback_near_arrival_pose` returns None for non-near
   relations). The resampler relaxes ONLY the straight-line heuristic;
   containment, clearance, and person keepouts are never relaxed.
4. **Live:** sidewalk arrival with `footprint_inside: true` scored against
   `scene_truth.json` — after the executor REJECTED its own first
   measurement (live-frustum scoring that proved nothing) and replaced it;
   `circle_owner` full orbit; boxed-in refusal at admission with the model
   narrating it, blocked arcs quantified (0.196 m vs 0.42 m criterion).
5. **Verifier CLEAN.** One deviation accepted: `voice/local_plans.py`
   (5 default-relation lines) outside OWNS, disclosed as Deviation 1.

## Carried forward

The door-etiquette path has never run end-to-end — E1 discovered NO SHIPPED
SCENE CONTAINS A PORTAL (see AUDIT_E1). The arrival table, hint validation,
and tool declarations are pinned and live-proven on every class that exists
in the world; the portal class awaits a world that has one.
