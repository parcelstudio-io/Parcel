# Sprint 2026-08-04 · task_3 — voice-steered attention (foundations first)

**Author:** Fable 5 · **Design record:**
[../../../docs/ATTENTION_STEERING_DESIGN.md](../../../docs/ATTENTION_STEERING_DESIGN.md)
· **Owner decisions locked:** trainable core with decisions ≥1 Hz (delivered
at 10 Hz), temperament + every knob tunable, **refactor first**, navigation
eval quality as a hard gate.

**Executors:** Claude Opus (repo-integrated), ChatGPT Sol 5.6 Ultra (pure
modules, frozen contracts), Fable (review + integration + cross-cutting
calls). Working agreements 1–8 inherit from
[../task_1/README.md](../task_1/README.md) and
[../task_2/README.md](../task_2/README.md).

> **Execution:** the startable slice (V0–V3, with V1 decomposed for
> parallel work) runs as [../task_4/](../task_4/). This folder remains the
> plan of record for V4–V7.

## Board

| ID | Card | Owner | Depends on | Status |
|---|---|---|---|---|
| V0 | Spike + hygiene: Go2 posture-compose spike plan, pause-semantics convention doc, B4 dead-code sweep | Opus | — | todo |
| V1 | **Foundations refactor** (registry, preemption table, nav pause, executive SUSPENDED, ResumeIntent, per-channel generations, typed details) | Opus | V0 doc | todo |
| V2 | Stimulus bus (pure): typed ADD/REVOKE/COMMIT events + prosody summons features + name-spot fusion scoring | Sol | — | todo |
| V3 | ReactionArbiter (pure core): tiers, resource table, Improv scoring, seeded draw, commitment bonus, signed habituation | Sol | — | todo |
| V4 | Wire T2 behaviors: probabilistic glance + chuckle bounce through the arbiter; `/api/social`; episode logging | Opus | V1 V2 V3 | todo |
| V5 | T1 summons/recall: suspend → stop-turn-attend → resume-as-fresh-dispatch; get-in legibility; sensor-suppression guard | Opus | V1 V4 | todo |
| V6 | Temperament + engagement modes + per-step reaction-policy contract + LLM-authored variant pools (offline) | Opus | V4 | todo |
| V7 | Eval: `ATTENTION_V1` scenarios + statistical bands + nav-eval regression gate wiring | Opus | V4 V5 | todo |
| — | Integration review at V1, V4, V5 exits; Stage-B fusion-MLP decision when the log matures | Fable | — | standing |

Parallelism: V2 and V3 (Sol, new files only) run alongside V1 (Opus). V0 is
days and starts immediately.

## The hard gates (owner decision #4)

- **V1 exit:** full suite green **and** follow-bench + embodied-plan ledger
  rows **byte-identical** to pre-refactor. A pure refactor moves no eval
  number; if one moves, the refactor has a bug. Freeze the pre-V1 rows
  first.
- **V5/V7 exit:** existing nav suites still green; new interaction scenarios
  pass (glance-during-walk: no collision increase, follow band held;
  summons-resume: mission completes within bounded delay); Stage-A
  deterministic assertions + zero safety-gate violations across seeded runs.

## Open decisions to settle during V0 (owner input welcome)

Priority placement (~55 vs 60), mask-vs-suspend duration threshold,
resume-vs-await default, HAL Option A/B (spike-driven), live randomness
(recommend true-random live, seeded evals), summons-interrupts-SearchOwner
scope (if yes, the shared-map refactor joins V1).

## Handoffs

(append here)
