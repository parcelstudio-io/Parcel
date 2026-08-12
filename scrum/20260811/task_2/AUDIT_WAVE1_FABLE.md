# Fable audit — SLAM_M_PLAN Wave 1 (RM-1, DR-1), 2026-08-12

## Verdict: both cards CONFIRMED.

1. Fresh ci_gate (Fable's run): **PASS — 3778/0, 10/10 hard gates** (3668
   baseline + 41 RM-1 + 69 DR-1).
2. Ownership: clean. RM-1's one declared out-of-OWNS edit
   (`route_memory/__init__.py`, re-export needed by RM-2's import) verified
   **21 insertions / 0 deletions — strictly additive: ACCEPTED.**
3. Spot re-runs (independent): RM-1 no-invented-edges family 7/7; DR-1's
   pre-existing calibration pins 25/25 untouched-green.
4. Quality notes: RM-1 killed 8/8 self-seeded mutants incl. the literal
   invent-a-shortcut bug; DR-1 changed exactly ONE line of existing code
   (provably no-op when slip off, endpoint-fingerprint pinned) and closed a
   pre-existing fail-open config hole.

## Cross-lane intel binding on Wave 2 (folded into the dispatch briefs)

- **DR-2 MUST vary the drift seed per episode** (DR-1's warning: the shipped
  fixed seed sits at 25.8% vs the 14.2% 60-seed mean for go2_degraded — a
  mean-based per-episode band gate would red spuriously, and n episodes on
  one seed measure a sample of size one).
- **RM-2 MUST call `reset_track()` at every episode/mission boundary** (else
  the inter-episode teleport records as a traversal) and SHOULD pass
  `reanchored=True` from the pose provider's own correction event rather
  than leaning on the distance heuristic (RM-1's stated limitation).
- RM-2 consumes RM-1's frozen contract verbatim (RM1_STATUS.md): `()` =
  fail-closed no-route = today's behavior; attach radius 8.05 m keeps
  un-recorded end legs inside one planner window.
