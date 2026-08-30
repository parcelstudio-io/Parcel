# W6 · VALUE-CHANGES-MEASURED-1 — the release door and the full planner demand, measured on the frozen corpora and presented (research only)

**Executor:** Opus · **Verifier:** Fable · Research only (`research/20260830/value-changes-1/`); no product edit.

Two value changes were written up in wave A and deliberately not taken: (1) `progress_watchdog.held_stall_release = True` on the shipped profile (C3: non-POI stalls 47 → 10, strict flat, `semantic_target_unreachable` 63 → 96 on generated scenes; frozen-row effect unmeasured); (2) the planner demanding the full 1.12 m instead of the directional-cone discount (`1.12·sin θ = 1.0223` — C3 §2's 0.0977 m residual; "kills class A at the source" but raises an inflation and moves frozen routes).

Build: a pre-registered DESIGN, then for each of {OFF/ON} × {1.0223 / 1.12 m} (4 arms, harness-only overrides, no config edits): NAV-GEN-1 A0 (530 rows: strict, settled, arrived_verified, stalls by class, unreachable, collisions, < 0.65 m exposure, steps), the v4 minival (25 rows: digest, moved rows with reasons), the mutation panel (clean authority, survivors, kill channels per mutant) — all in isolated worktrees, PYTHONPATH pinned. Deliver a decision table with the frozen-row moves named per arm and a one-paragraph recommendation per value; no criterion, no flip.
