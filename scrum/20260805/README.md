# Sprint 2026-08-05 — the walking companion

**Author:** Fable 5 (plan + integration + adversarial review).
**Executors:** Claude Opus (repo-integrated) and ChatGPT Sol 5.6 Ultra
(self-contained modules with frozen contracts), same split rationale as
[../20260804/README.md](../20260804/README.md).

**Theme.** Last sprint gave the dog a body that feels alive while mostly
standing still. This sprint makes it a companion that *walks with you*:
anticipates where you are going instead of trailing where you were, refuses to
path through where a pedestrian is about to be, moves with animal smoothness
rather than industrial steps, and — for the first time — knows what to do when
it loses you. Every card is sim-testable now; nothing waits on hardware.

Sources: [../../backlog/NEXT.md](../../backlog/NEXT.md) (N1–N4, N6, N8),
[../../docs/RESEARCH_2026_ROADMAPS.md](../../docs/RESEARCH_2026_ROADMAPS.md)
§3 steps 1–3, 5–6. Findings from the in-flight sprint review of 2026-08-04
work are fixed by Fable before integration begins.

## Board

| ID | Card | Owner | Depends on | Backlog |
|---|---|---|---|---|
| W1 | `OwnerMotionPredictor` — Kalman CV/CA module (pure numpy) | Sol | — | N2 |
| W2 | Follow the *predicted* owner path + NIS uncertainty brake | Opus | W1 | N2 |
| W3 | `DynamicAgentCostField` + rollout TTC check (pure numpy) | Sol | — | N3 |
| W4 | Merge dynamic costs into `grid_v1`; compile the TTC gate | Opus | W3 | N3 |
| W5 | `SCurveVelocityShaper` — jerk-limited filter (pure numpy) | Sol | — | N4 |
| W6 | Shaper between controllers and the SE2 HAL, affect-modulated | Opus | W5 | N4 |
| W7 | `SearchOwner` — reacquisition skill (LOP → sweep → frontier) | Opus | — | N6 |
| W8 | Emote triggers onto the playback clock (epoch-tagged) | Opus | — | N1 / U6 |
| W9 | Eval: new walk-with-owner scenarios + expression metrics + ledger | Opus | W2 W4 W6 W7 | N8 |
| — | Fix 2026-08-04 review findings; integration review; final suite | Fable | — | — |

Parallelism: W1, W3, W5 (Sol) and W7, W8 (Opus) have no mutual dependencies —
five cards can start at once. Sol again touches only new files.

## Working agreements

All seven agreements from [../20260804/README.md](../20260804/README.md)
carry over verbatim — safety authority untouchable, suite+ruff green per
handoff, loud degradation, manifest re-freeze on `robot.yaml` edits (compute
the hash **per named entry from disk**, never by line position — see the
2026-08-04 housekeeping incident), tests in the same card, honest handoffs,
and every "not verified" line lands in
[../../backlog/UNVERIFIED.md](../../backlog/UNVERIFIED.md).

One addition:

8. **New config keys get fail-closed validation in the same card.** The
   mis-indented-YAML incident survived a full sprint because a section
   accepted keys it never read. `build_prompting_stack` and
   `_build_expression_engine` show the pattern.

## Definition of done for the sprint

- **Anticipation:** in a scenario where the owner turns 90° mid-walk, the
  follower's mean distance-band error during the turn drops measurably vs the
  frozen baseline (record both numbers in the ledger).
- **Dynamic safety:** the pedestrian cut-in scenario completes with zero hard
  collisions *without* relying on the reactive gate alone — the planner's
  chosen path visibly yields (the gate remains the unconditional backstop).
- **Smoothness:** RMS jerk in the follow scenarios drops against the frozen
  baseline with the shaper on; no follow-success regression.
- **Reacquisition:** owner walks behind the occluder and keeps moving; the
  dog reaches last-observed-position, sweeps, searches, and reacquires within
  the scenario budget. Today's behavior (stand and wait forever) is the
  baseline to beat.
- **Emotes on the playback clock:** a queued-but-superseded sentence fires no
  gesture (U6 closed in the register with evidence).
- Full suite green, ruff clean, one ledger row per eval-visible change.

## Handoffs

(append here)
