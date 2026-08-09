# Opus cross-review of Sol · N11 support

**Reviewer:** Claude Opus (integrator; standing in) · **Date:** 2026-08-06  
**Under review:** Sol pure support for N11 — `traffic_aware.py`
(`tracks_from_payload`, ranking, `RampMemory`), `tests/test_traffic_aware.py`,
[SOL_N11_SUPPORT.md](SOL_N11_SUPPORT.md).  
**Baseline:** Opus wiring already landed ([OPUS_N11_STATUS.md](OPUS_N11_STATUS.md)).  
**Nothing edited this round.** Claims executed against the tree with
`.parcel/bin/python`.

## Verdict

**APPROVE**

The pure support layer matches what Opus wired. Loud reject at the helper
boundary, ladder identity on empty tracks, and RampMemory’s never-emit-during-
stop architecture all hold. `proxemic_approach` stays complementary and
unwired — correct for this card.

## Criteria

| Criterion | Result |
|---|---|
| Pure / fail-closed / loud reject on bad payload | **Pass** |
| Ladder identity when empty tracks | **Pass** |
| RampMemory cannot emit during stop | **Pass** |
| Helper contract matches Opus wiring | **Pass** |

## Findings

### Pure / fail-closed / loud reject

- `traffic_aware.py` is stdlib-only (`math`, `collections.abc`, `dataclasses`,
  `typing`). No pipeline / runtime / numpy imports.
- `tracks_from_payload` is the right sibling of
  `dynamic_layer.tracks_from_payload`: same field contract (`x`/`y`/`vx`/`vy`
  required, `radius_m` default 0.35), cap `DEFAULT_MAX_TRACKS = 16`,
  `None`/empty → `()`, malformed → `ValueError` (SB-3, including wrong-type
  payload / non-mapping entries / non-finite / negative radius). Never
  silently drops a bad entry.
- Layering is correct: pure module raises; Opus wiring
  (`pipeline._dynamic_tracks_from_observation`) catches
  `(TypeError, ValueError)` and degrades to `()` — same loud-then-degrade
  pattern Sol cites from `grid_navigator._refresh_dynamic_costs`. Sol’s
  suggested call shape in `SOL_N11_SUPPORT.md` matches what is already live.

### Ladder identity (empty tracks)

- `rank_approach_candidates` with empty tracks forces `traffic_cost = 0.0`
  and sorts by `(total_cost, static_cost, index)` → equivalent to
  `(static, index)` for any `static_weight > 0`.
- Pinned by `test_empty_tracks_ordering_identical_to_static_ordering` (byte-
  identical points + indices, including duplicate-static index tie-break).
- Also holds for `traffic_weight=0`, all-stale under `max_age_s`, and
  `top_k` subsets. Matches Opus’s approach seam:
  `_rank_approach_point` → empty tracks keep static nearest order.

### RampMemory cannot emit during stop

- `note_stopped` returns `None` always; no command API while gated.
- `held_velocity_mps` is telemetry only.
- `release` is defined as the caller’s assertion the gate already opened;
  seed is still subject to every downstream authority.
- Pinned by `test_never_emits_during_stop`. Opus wiring returns `0.0`
  immediately on `collision_note == "person_stop"` without calling
  `release` — defense in depth on the same property.
- Align/zero ticks do not wipe held state (`min_record_vx`, SB-4) — matches
  Opus’s `RAMP_RUNNING_FLOOR_MPS` guard.

### Helper contract ↔ Opus wiring

| Sol surface | Opus call site | Match |
|---|---|---|
| `tracks_from_payload(extras["dynamic_agents"])` | `pipeline._dynamic_tracks_from_observation` | Yes |
| `rank_approach_candidates(..., static_cost_fn=distance)` | `approach._rank_approach_point` | Yes |
| `RankedCandidate.{static,traffic,total}_cost` | `approach._record_approach_costs` → mission metadata | Yes |
| `RampMemory.note_stopped` / `release` / `note_running` | `DirectiveNavigator._update_ramp_memory` → `seed_ramp` + `pending_ramp_seed_mps` | Yes |
| `proxemic_approach` optional / unwired | Explicitly not wired (`OPUS_N11_STATUS`) | Yes |

No API rename, signature drift, or missing field blocked integration.

## Tests

```text
.parcel/bin/pytest tests/test_traffic_aware.py tests/test_proxemic_approach.py -q
→ 64 passed (56 traffic_aware + 8 proxemic)
```

Coverage hits the load-bearing pins: payload adapter + loud reject, empty-
tracks ladder, stream-vs-quiet ranking, RampMemory hold/decay/reset /
never-emit-during-stop, SB-1..SB-5 pins, SB-3 ValueError-never-TypeError
table.

## Nits (non-blocking)

1. `SOL_N11_SUPPORT.md` claims 45+8=53 green; current suite is 56+8=64. Doc
   drift only — suites are green.
2. Support note still says “NavPipeline owns one RampMemory”; the owning
   class is `DirectiveNavigator` in `pipeline.py`. Symbol-level citation is
   fine; the name is cosmetic.

## Explicit non-claims (agree with Sol)

- Pedestrian e2e xfail remains xfail (Opus wiring did not flip it; remaining
  gap is closed-loop / one-shot placement, not pure-layer defects).
- `proxemic_approach.reject_cost` stays PARKED — would break empty-tracks
  identity if wired as a hard veto without an empty-tracks bypass.
