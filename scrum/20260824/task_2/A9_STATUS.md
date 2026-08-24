# A9 — MEMORY-FIXES + NON-TRAVEL LIFE · executor report (Opus) · 2026-08-24

Card: `IMPLEMENTATION_PLAN.md` row A9 (HLD Gate 8 + §16's ratified wave-2
amendments). Tree: branch `main`, HEAD `f5106e8`, **not committed**. Guard label
`a9-life`; every pytest through `~/.cache/parcel-guard/pytest_guard.sh`, never
`-n auto`, never `ci_gate --tier`. Git read-only. **$0** — no hosted call, no
device, no owner store opened (read-only or read-write),
`PARCEL_MEMORY_PURPOSE` never set, `:8765` / `/tmp/parcel_sim.sock` / `:8080`
untouched.

## 0. Files

| file | change |
|---|---|
| `src/parcel_robot/memory/conversation.py` | +76/−15 — defects 1 and 3 (reader emits `session_id`, `add()` can stamp it, tombstone-aware upsert, `revoked_fact_keys` method) |
| `src/parcel_robot/owner_model/distiller.py` | +135/−5 — defects 1, 2 and 3 (`respect_revocations`, `report.revoked`, honest `written`, the constrained-JSON proposer path, `FACT_RESPONSE_SCHEMA`) |
| `src/parcel_robot/providers.py` | +90/−0 — defect 2: `StructuredJsonModel` protocol + `LlamaCppProvider.complete_json` |
| `src/parcel_robot/memory/scheduler.py` | +14/−0 — `revoked_fact_keys` delegates to the store; the flag now reaches the write |
| `src/parcel_robot/online_map/online_map.py` | +36/−1 — defect 4: `_background_policy()` |
| `src/parcel_robot/runtime.py` | **+22 lines, 3 hunks** (import; lane construction; the `_step_expression` tick). DEC-0 pin named in the construction hunk: no new marked region, invariants live in the two new leaves |
| `src/parcel_robot/motion/body_lane.py` | NEW — the 50 Hz body-intent lane (H4 productized) |
| `src/parcel_robot/attention/initiative.py` | NEW — the zero-translation lease, rate envelope, terminals, opener/governor path (H3 + the ratified terminal amendment) |
| `tests/test_a9_memory_fixes.py` | NEW — 22 rows |
| `tests/test_a9_life.py` | NEW — 33 rows |

`src/parcel_robot/config.py` **byte-unchanged** (DEC-0 ceiling, 1000 lines).
No `configs/**` change. Safety floors untouched: `obstacle_stop_m`,
`apply_reactive_safety`, `finalize_command`, `core/hard_stop.py`, the A3 latch,
the A6 stop path, A8's `follow_compose.py` — zero diff, composed with, never
modified. No new lock (nothing r24-shaped added; `test_r24_lock_discipline`
green). **noqa added: 0** (`git diff -U0 | grep -c '^+.*noqa'` → 0; the two new
modules and the two new test files contain 0; none removed either).

## 1. The four H5 defects — old → new, at the sites the VERDICT names

| # | site (VERDICT §4) | measured before | after | seed-RED row |
|---|---|---|---|---|
| 1 | `distiller.py:486-492` filter vs `conversation.py:630-669` reader | `distil_session(session_id="s1")` → **`turns_read 0`** on 3 turns; `session_id=None` → 3 | 3 turns → **3**; a second session → 1; `None` → 4; an unknown id → 0 (the filter working) | `_PreA9Reader` — the exact old reader wrapped round a real store — still reads **0** |
| 2 | `distiller.py:360` → `providers.py:168-214` (`_decision_response_schema`) | live reply is prose; `_parse_candidates` → `[]`; proposer **== `DeterministicFactProposer`** on 13/13 calls | `complete_json` + `FACT_RESPONSE_SCHEMA` → **2/2 candidates parsed**, `structured_calls 1`, `fallbacks 0` | a model with only `decide` still parses **0** and now COUNTS the fallback |
| 3 | `conversation.py:843-847` upsert | add→forget→add left **2 rows / 1 live**, and a non-scheduler `distil_session` resurrected the fact | one key = **1 row** for the life of the store, tombstone revived in place; a model pass reports `report.revoked` and writes nothing | the pre-A9 SQL, run against the same store, still leaves **2 rows**; `respect_revocations=False` still resurrects (one flag, still measurable) |
| 4 | `abstention.py:566/1181-1200` + "the runtime passes no policy" (`runtime.py:13036-13040`) | enabled gate on the map's own background: **0/2 admitted**, `ranking_margin 0.0`, `background_mad 0.0` | unconfigured map now pairs its label-strength background with the fitted estimator: **2/2 admitted**, margin > 1.0 (`label_strength_margin([5.2]+[0.0]*7) = 43.333`) | the explicit-`robust_z` arm still refuses `indecisive_ranking` at 0.0 — P0-D's own seeded-red arm stays red, and its suite is green |

`ranking_margin` and `label_strength_margin` are **byte-unchanged**: A9 changes
which estimator an unconfigured map selects, never what either computes, and an
explicitly-configured policy (either mode) still wins. `AbstentionPolicy()`
defaults are untouched (`enabled False`, `robust_z`) — pinned by a row here as
well as by P0-D's.

Product path, not just seeds: `RobotRuntime._realtime_remember_fact` /
`_realtime_forget_fact` / `_realtime_known_facts` driven over a stub (A7's
idiom) prove consent → revoke → a model pass that cannot undo it → the owner
re-stating it (same row id, no duplicate) → **restart** (new connection, same
answer, still one row).

**Gap found and recorded, not hidden:** revocation is per KEY. The
deterministic proposer derives `sister` *and* `sister_name` from one sentence,
so forgetting one leaves the sibling free to carry the same content. H5's M4
was a per-key row too; A9 does not widen it (value/embedding-level matching has
false-suppression risk and needs its own measurement). Row:
`test_revocation_is_per_key_and_this_card_does_not_change_that`.

## 2. Composer bars (H4 productized)

| bar | row | result |
|---|---|---|
| cadence, HOLD every tick | 3,000 ticks at 50 Hz | one intent per tick, `seq` 1:1, **3,000/3,000 HOLD**, 0 gaps over bound |
| cadence under load (replay) | 6,000 ticks, jitter 0–15 ms | `max_gap 0.100 s` bound held, **0** over-bound gaps, measured ≥ 20 Hz (H4 B1 floor) |
| anti-vacuity | a 0.38 s stall | counted (`gaps_over_bound 1`) — the bar can fail |
| HOLD is a command | `finalized_velocity=None` | `locomotion is HOLD`, `is_hold`, `velocity is None`, `ttl_ms > 0` — not a zero velocity, not silence |
| velocity is COPIED | 3 commands | `locomotion.as_tuple()` equals the finalized `(vx, vy, vyaw)` exactly |
| e-stop mechanism + bound | flag between ticks | **same tick**: HOLD, `priority 100`, gaze/posture snapped to 0, epoch **+1 exactly** (latched, not walking), elapsed **≤ 1 tick**. Reference asserted: H4 B6 = 17.66 ms = **0.88 tick** |
| beneath the chain | source order in `_dispatch_active` | `_finalize_for_actuator` … **then** `self._last_sent = command`; the lane's only velocity source is `_last_sent`, and `lane.tick(` appears **once** in `runtime.py` |
| never bypasses | code-only token scan (docstrings stripped) | `body_lane.py` contains no `submit_motion`, `set_target`, `control_manager`, `move`, `VelocityCommand`, `emergency_stop` |
| floors clean | import scan | `hard_stop`, `reactive_safety`, `arbiter`, `stop_hotword`, `safety` import neither new module |

Runtime rows: after one real `_step_expression()` the runtime publishes an
intent (HOLD, `source body_composer`); after `runtime.emergency_stop()` the next
tick is HOLD at priority 100; an exploding lane cannot take the expression
overlay down.

## 3. Zero-translation lease (H3), structurally

* **By type** — `BodyOffer` fields are exactly `{behavior, gaze, posture, style, line}`; the code (docstrings stripped) contains no `VelocityCommand`, `vx`, `vyaw`, `waypoint`, `submit_motion`. A drive cannot ask for translation because the vocabulary it is answered in has no word for it.
* **By construction** — `ZeroTranslationLease(policy=InitiativePolicy(travel_radius_m=6.0))` raises `TranslationRefused`; a travelling proposal raises at admission; a `budget_m` of any size raises.
* **Non-vacuous** — H3's own `propose()` at radius 6 still forms `GO_CHECK`/`APPROACH`; those exact proposals are then refused (3/3, `admitted 0`, `refused 3`).
* **Third guard, elsewhere** — `MotionIntent(source="drive"/"initiative"/"curiosity")` raises by name; no drive source exists in `SOURCE_PRIORITIES`.

Repertoire: look (bearing), **orient** (no measured bearing ⇒ the head lifts
rather than snapping to an invented number), stretch, remark — all
non-translating; offers are bounded by the lease itself (gaze ≤ 1.2 rad, dz ≤
0.04 m) so an out-of-band ask is a bug here, not a clamp in the composer.

**Rate envelope**: `InitiativeLimits(enabled=False, max_per_hour=6.0,
window_s=3600, refractory_s=120, max_behavior_s=8)`. 6.0 = max(5, 5, 6), H3's
three measured seeds (~5.3/h), inside D1's pre-registered 3–8 band. Rows: 10
asks 5 minutes apart ⇒ **6 admitted**, the rest `rate_envelope_reached`; the
window slides and admits again; the 120 s refractory floor refuses a second ask
at 30 s; an injected quiet predicate refuses (`quiet_window`) and the module
re-implements no quiet/night logic (`quiet_hours`, `TIME_BAND`,
`ChatterScheduler` absent from its code — the product's own door stays the
door). **Initiative ships OFF**: a fresh lane refuses `initiative_disabled`.

## 4. Yield and terminal

* **0-tick yield** — an owner-owned motion lease during a running behavior ends it in the **same** tick: that call's offer is already `NEUTRAL_OFFER`, the terminal is `release_authority`/`owner_command`, `yields 1`, and the intent that tick carries the owner's own velocity. There is no tick in which the owner has spoken and the dog is still doing its own thing.
* **Terminal = safe hold, never a return** — every terminal over a 5-leg soak is in `M1_REACHABLE_TERMINALS` (`hold`, `release_authority`), `returned=False` on all, and `Terminal(returned=True)` **raises** with the refuted numbers in the message (contacts 319→323, contact time 89.1→244.6 s). A completed leg ends `hold`/`completed` with every one of its ticks a HOLD; the module's code contains no `goal`, `waypoint`, `navigate`, `return_to`, `plan`. At radius 0 the receding-horizon admission is answered without a plan: **the safe-hold region is where the body already is**, so there is nothing to return from. The other three ratified terminal names (`return`, `yield_aside`, `follow_owner`) are carried, unused, so the card that earns a positive radius extends a vocabulary instead of inventing one.

## 5. Composition with what shipped

* **A6** — the latch is the arbiter's and only the arbiter's: e-stop terminates any running behavior in-tick (`emergency_stop`/`release_authority`) and the intent is HOLD at priority 100; the runtime hunk reads `self.arbiter.emergency_stopped` (asserted in the function's source), no second flag.
* **A8** — a real `CommandArbiter` holding a `follow` lease: the drive is the one that yields, `follow` still owns motion afterwards at priority 40. A drive cannot contest it at all (§3, third guard).
* **A7** — `open_line()` asks the governor **before** any hosted phrasing and is spied: exactly one call, `("drive_opener", "routine")`, never `critical`. Over the envelope (seeded ledger `$160.01` vs `$160+$40`) it degrades to a local opener from `LOCAL_OPENERS` carrying the governor's own reason; under it, hosted is admitted and the same local line stays ready; **no governor wired ⇒ local**, because a build without a budget is not a build with an unlimited one. Neither new module contains `urllib`, `requests`, `http`, `socket` or `openai`. A7's AST firewall is untouched: no new governor call site in `runtime.py` (the consult lives in the leaf), and its suite is green.

## 6. Suites run (all through the guard, label `a9-life`)

* **This card**: `tests/test_a9_memory_fixes.py` (22) · `tests/test_a9_life.py` (33) — 55 passed.
* **A-cards**: `test_a5_goal_amend` · `test_a6_stop_local` · `test_a7_ear_governor` · `test_a8_follow_compose` — 163 passed.
* **Ratchets**: `test_dec0_debt_ratchet` · `test_decig2_import_ratchet` · `test_r24_lock_discipline` — green (see §7 for the DEC-0 near-miss).
* **Memory**: `test_p2a_owner_model` · `test_p2a_memory_probes` · `test_h5_continual_memory` · `test_tiered_memory` · `test_ot2_memory_principal` · `test_scene_and_memory_answers` · `test_conversation_store` · `test_owner_store_isolation`.
* **Perception/map**: `test_p0d_navigation_unblocks` · `test_perception_abstention` · `test_nm1_promotion_and_asks` · `test_p1d_vlm_veto` · `test_c2_online_map` · `test_c3_cutover` · `test_p1b_map_learns`.
* **Body/drives/runtime**: `test_h3_drives` · `test_h4_body_intent` · `test_expression` · `test_runtime` · `test_prototype_profile` · `test_brain_executive`.
* **Realtime/voice/other consumers of the touched modules**: `test_realtime_lane` · `test_realtime_driver` · `test_realtime_corpus_replay` · `test_realtime_reconnect` · `test_realtime_idle_hangup` · `test_realtime_pump_survival` · `test_duplex_integration` · `test_voice_streaming` · `test_first_clause_flush` · `test_prompting_activities` · `test_emote_skill` · `test_navcore_probe` · `test_a2_navglue` · `test_future_clock_guard` · `test_intelligence` · `test_plan_sketch_provider` · `test_curio1_chatter` · `test_move1_patrol` · `test_roam2_coverage` · `test_web_panel` · `test_truth1_texts` · `test_venue1_physical_venue` · `test_p0b_companion_unlocks`.

Largest single sweeps: 914 passed / 1 skipped, 517 passed, 405 passed, 271
passed. **No failure attributable to this card.** One flake seen once under
`-x` on a loaded host (`test_runtime.py::test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts`,
a LiDAR-staleness reply); it passes at HEAD, passes 3/3 in isolation with this
change, and passes in the full file (56/56).

## 7. Ports and near-misses named

* **DEC-0 long-function ratchet went red mid-card** on `add_owner_fact` (115 lines) and was fixed by MOVING the rationale to the module-level note beside `OWNER_FACTS_DDL` (THE TOMBSTONE AND THE UPSERT), not by deleting it: the function is now **100** lines, at the ceiling, not over it. `_assess` in `online_map.py` is 106 lines at HEAD and unchanged in length by this card (one argument replaced).
* **DEC-IG-2 import ratchet** green (its wall-clock budget row passed here at this host load).
* The structural source assertions read **code only** (comments and string literals stripped via `tokenize`), with an anti-vacuity row proving identifiers survive and that the docstrings which legitimately NAME forbidden things do not trip them.

## 8. Undone, and why

1. **The runtime never BEGINS a behavior.** No initiative digest source is wired (idle time, owner presence, a look bearing, place novelty), so the lease is exercised through the lane and never from live perception. This is deliberate for M1 — initiative ships OFF — but it means the drives are product code with no product trigger yet.
2. **No config key turns initiative on.** `config.py` is at its DEC-0 ceiling and every existing section validator refuses unknown keys by name, so introducing `expression.initiative` (or a sibling) costs a whitelist edit that belongs to the card that turns the feature on and measures it. Today the switch is the leaf's own default.
3. **The remark line is carried but not spoken.** `BodyOffer.line` reaches `LaneTick`; nothing calls `_brain_vocalize`. Wiring it is a runtime hunk on the speech path plus a decision about the second governor call site (A7's AST firewall) — named, not taken.
4. **No body adapter is installed**, so the published intent drives no actuator: `SimulationBodyAdapter` and the refusing `Go2SportBodyAdapter` both remain uninstalled. Box-day / the physical gates.
5. **H4's B3 (jerk) and B9 (loop P99) are not re-measured here** — the composer's limiter is byte-unchanged and H4 measured them; A9 measures cadence, HOLD, copy-fidelity and e-stop.
6. **The receding-horizon half of the ratified amendment is not built** (planning over predicted dynamic occupancy). It is unreachable at radius 0 and belongs to the card that earns a positive radius; the terminal vocabulary is carried whole so that card extends rather than invents.
7. **The plan row's soak and human nuisance bar are not run.** The governance suite is here; a long soak and blinded "alive / purposeful / not annoying" rating are evaluation work, not a unit suite, and need a running robot or a long simulated session. Box-day / eval.
8. **Defect 2's 0.96 precision is not re-measured live** ($0 rule): the structured seam is proven with doubles and a captured transport. A live re-run of H5's M2 through `complete_json` against the local GPU is the next measurement, and it is now a one-line change of proposer.
9. **`distil_session` and `ContinualMemoryScheduler` still have no product caller** (H5 §2, unchanged by this card). A9 fixed the four defects at their sites and proved the consent/revoke/restart path through the broker's own methods; installing the scheduler in the runtime is Gate 8's other half.
10. **Revocation is per key** (§1, recorded as a row).
11. **`CODEBASE_INDEX.md` is stale** — two new modules and two new test files. Regeneration belongs to the commit, which this card does not make.

## 9. Handoff

Nothing is committed. The verifier's fastest path: run
`tests/test_a9_memory_fixes.py` and `tests/test_a9_life.py` through the guard,
then re-run the four seeded-RED arms by reverting each fix in turn — the
pre-A9 reader (`_PreA9Reader`), the pre-A9 SQL (`_pre_a9_upsert`), a model with
only `decide`, and an explicit `robust_z` policy are all already in the suite,
so each measured defect reproduces without editing product source.
