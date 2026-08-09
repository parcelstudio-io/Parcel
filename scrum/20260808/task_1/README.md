# Task 1 — three full navigation/behavior designs for team review

**Date:** 2026-08-08  
**Status:** complete — ready for team review  
**Safety status:** architecture proposals only; not clearance for unsupervised
physical motion.

## Objective

Turn the 2026-08-07 navigation and instruction-following research into three
complete system designs that can be reviewed as alternatives. Each design must
cover the whole path from owner utterance to verified task completion:

```text
speech/text → intent/task → grounding → navigation/behavior → safety
            → Unitree Sport → feedback → terminal witness/conversation
```

The alternatives share the same safety and embodiment boundary but make
different choices about where deterministic algorithms end and learned
reasoning begins.

## Review packet

- [Shared foundation and contracts](SHARED_FOUNDATION.md)
- [Design A — deterministic companion](designs/DESIGN_A_DETERMINISTIC_COMPANION.md)
- [Design B — dual-system semantic companion](designs/DESIGN_B_DUAL_SYSTEM_COMPANION.md)
- [Design C — predictive candidate companion](designs/DESIGN_C_PREDICTIVE_COMPANION.md)
- [Comparison and recommendation](COMPARISON_AND_RECOMMENDATION.md)
- [Team review worksheet](TEAM_REVIEW.md)

Prior evidence and detailed audits remain in
[`../../20260807/task_2`](../../20260807/task_2/README.md), especially the
[crown research thesis](../../20260807/task_2/RESEARCH_THESIS.md),
[target architecture](../../20260807/task_2/TARGET_ARCHITECTURE.md), and
[model/RL decision](../../20260807/task_2/MODEL_AND_RL_DECISION.md).

## The three choices

| Design | Primary decision mechanism | Best property | Principal cost |
| --- | --- | --- | --- |
| A — deterministic | Typed grammar + semantic registry + classical planning/control | Most auditable and easiest to commission | Narrower long-tail instruction and semantic flexibility |
| B — dual-system | A deterministic real-time spine plus asynchronous LLM/VLM proposals | Best product balance of competence, latency, and containment | More contracts, services, and cross-rate orchestration |
| C — predictive candidate | Multiple classical/open-weight candidate generators plus an optional learned ranker over hard-admissible trajectories | Highest potential in difficult dynamic/social scenes | Largest evaluation, compute, data, and assurance burden |

These are full-stack alternatives for review, not permission to choose a
different safety policy per design. All three retain Unitree Sport for
gait/balance and the shared foundation below.

## Non-negotiable shared decisions

1. Unitree Sport remains the low-level closed-loop locomotion controller.
2. Exactly one admitted component writes the body-velocity target at a time.
3. Camera/LiDAR-derived metric geometry, state feedback, and an independent
   post-shaper monitor own the final stop decision.
4. Missing/stale required sensing, pose, transform, or feedback produces
   exact-zero HOLD. It never selects an open-loop navigation fallback.
5. Learned systems may propose tasks, goals, waypoints, trajectories, dialogue,
   or reactions. They never emit Unitree commands or declare free space,
   identity, authorization, or task success.
6. Every physical task has a task ID, monotonically increasing revision,
   evidence IDs, deadlines, resource leases, recovery limits, and independent
   terminal witnesses.
7. `ApproachOwner` terminates; `FollowFormation` is persistent until cancelled
   or held.
8. External maps remain advisory. Road entry requires a task-bound,
   authenticated and authorized owner/control-channel decision; transcript
   text alone is not authority.
9. Lateral velocity is allowed when coverage and kinematics permit it, but
   ordinary destination travel penalizes lateral motion and prefers heading
   alignment plus forward motion.
10. Simulator success is evidence, not a physical safety certificate.

## Decision requested from the team

The review packet recommends **Design B as the product architecture, Design A
as the mandatory deterministic baseline/degraded mode, and Design C as a
shadow research lane until candidate-selection residual gates pass**. This is a
staged composition over one safety and navigation substrate, not three active
motion stacks.

The team should select:

1. the **product architecture** to implement (recommended in the comparison);
2. the **Phase-0 shared ABI** that freezes before parallel work;
3. which parts of the other designs remain baselines or shadow experiments;
4. measurable promotion gates, rather than a model or framework preference.

No runtime code, model activation, or physical-motion configuration is changed
by this task.
