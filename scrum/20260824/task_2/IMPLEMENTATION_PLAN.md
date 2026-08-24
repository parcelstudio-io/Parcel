# M1 implementation plan · v2 (findings-bound) · Fable · 2026-08-24 · owner-approved

Owner decisions: Follow IN M1 (option (a)); research + implementation
running; **every card below is bound to the measured findings it implements**
(owner's directive). Sequence adopted from Codex's dependency correction and
`research/20260824/PORTABLE_LIVING_DOG_HLD.md` §12 (Gates 0–8) — Follow moved
AFTER the observation spine (it imports `SimObservation` and its tracker has
no product installer; EMBODIMENT-KERNEL K3/K4). Governing record:
`CLAUDE_RESPONSE.md` + addenda; HLD cross-review by Fable DONE — ADOPT-WITH-AMENDMENTS (its Gate
order and M1 acceptance contract are adopted here ahead of that review; the
review may amend details, not the order). WIP: one integration lane + one
decision study. Roles: Opus implements, Fable designs/verifies, humans own
residual risk (owner: Jae).

## Lane A — integration (one card active; queue in order)
| # | card | implements which findings | done when |
|---|---|---|---|
| A1 | **M1-0 GATEWAY** (running) | HLD Gate 1; ARCH-1 X12 (co-located); bridge fixtures. **Added from Codex's live-code note: hung-vendor-call isolation** — `stop_move`/`state`/ledger I/O must be bounded or contained so a hung call cannot freeze the watchdog; fault set gains hung-I/O, lease theft, second writer, slow client, audit-full (HLD Gate 1 list) | seeded-fault suite green ×3; exact-zero on every loss class; watchdog provably non-blocking |
| A2 | **NAV-GLUE** (next; from NAV-CORE's fix list — the decision card) | Fix 3: ONE clearance authority (0.42 m planner vs 0.752/0.80 m brakes; 8/8 stalls "inside a brake ring, route still planned"). **Measured refinement: this is a DESIGN change, not a parameter wire** — `planner_inflation_m` has no call site and `_planner_coupling_ring_m` caps tighter-only by design (pending DOOR-1 H-2); `map_safety_margin_m`=0.45 recovered only 1/8 sampled stalls. A2 owns the DOOR-1 H-2 decision + a brake→replan signal. Fix 1: region/object kind-tolerant learned-map query (12/12 `bed` episodes `not_found`). Fix 2: off-oracle arrival verification (metric band + detector confirmation; `target_surface_unobserved` on 15/60). Then **re-run the frozen NAV-CORE corpus unchanged**: arm A ≥ 0.80 ⇒ retain; only arm B ⇒ simplify (fixes 1–2 stay post-M1) | corpus re-run decides retain/simplify; N4 typed-failure = 1.00 |
| A3 | **DISCONTINUITY-LATCH** (BUILD_BLOCKER regardless of A2's outcome) | NAV-CORE refuter 4b: shipped arms kept translating on HEALTHY after a kidnap (824–840/840 HEALTHY ticks, 0.84 m moved); the modelled A4/A10 latch caught 3/3 and the operator pose-reset re-armed cleanly; the whole-map second-best margin **does not exist in the product** (`ScanMatchLocalizer._relocalize` keeps no runner-up — fix 4) and correctly refused in the aliased world (margins 0.002–0.03 vs 0.25). Build: the latch + trigger journal + runner-up margin + the operator reset transaction. Also fix 5: no arrival claim from uncalibrated covariance (R3's false arrival at p=0.9922, 0.534 m out) — arrival confidence needs a calibration floor or detector confirmation | latch regression (kidnap ⇒ 0.00 m); margin published; R3 case refuses; **kidnap-ONSET detection in a NORMAL layout fires the jump/mismatch (JUMP_BOUND) path — not only ambient ambiguity — with `localization_jump_m` journalled** (4b lens); the operator re-arm is a ONE-SHOT journalled transaction, never a standing authorization |
| A4 | **SPINE** (HLD Gate 2; was M1-7 — moved up, Follow depends on it) | `NavigationSnapshotV2` assembler replacing `SimObservation` in the 9 audited modules (EMBODIMENT-KERNEL list: brain/observations, control/base, control/state, navigation/{follow, reactive_safety, search_owner, semantic_map, spatial}, runtime.py); stamped evidence header (HLD principle 5); simulator/replay/physical adapters; Orin service packaging skeleton | K3 = 0 modules; K4 = exists; adapters pass the existing suites |
| A5 | **C8-FIX** (parallel-safe per HLD §12; before any replanning ships) | Addendum A8: transactional suspend-only, atomic/rollback, `_amendment_pending` gated on arbiter quiescence, HOLD on partial failure; regression observes the command stream | multi-task forced-failure regression green; r24/nominal-stop unchanged |
| A6 | **STOP-LOCAL** (HLD Gate 3) | Addendum A9 tail bars: p95 ≤ 800 ms AND n ≥ 60 all ≤ 1.0 s; false triggers ≤ 1/24 h; today's only cloud-independent stops are panel/remote/watchdogs (lane.py:47) | bars met on the desk array (VOICE-GATE measures) |
| A7 | **EAR + GOVERNOR** (HLD Gate 7) | H1: rate card into the runtime `SpendLedger` (old ledger overcharged +336 %); pre-roll ≥ 500 ms (0 % truncation); server VAD stays ON (silence not billed — proven for server-VAD sessions only); **identity/engagement gate BEFORE upload** (Codex freeze finding 3: post-upload identity is too late for cost and privacy; H1 C5 960 opens/h on TV); `triage_in_exchange` (66/174 owner turns misread context-free); **product hard-cap call governor** (EVENT-BUDGET: nominal p95 $30.72/mo, ungated TV $571/mo, 1 Hz tick $777/mo — the governor is what is missing, not the price) | C-row regressions; governor seeded-red (cap reached ⇒ refuse non-critical) |
| A8 | **FOLLOW-COMPOSE** (HLD Gate 6; AFTER A4) | tracker product installation (`install_owner_tracker` has zero callers), synchronized pixel/range via the A4 snapshot, UWB decision from measured two-person ambiguity (not preference), follow-speed avoidance; ambiguity/loss ⇒ HOLD + canned line | capability suite + the box-day identity gate decides ENABLE |
| A9 | **MEMORY-FIXES + NON-TRAVEL LIFE** (HLD Gate 8) | H5's four verified defects (session-id filter, chat-completions proposer, tombstone-aware upsert, ranking margin); body composer (H4: 50 Hz, HOLD-as-command, e-stop 0.88 tick) + drives (H3: 5.3/h, 90 % admitted, 0-tick yield; **travel radius 0** — 1,222 contacts refuted travel; and per the ratified wave-2 terminal-aware refutation, the initiated-leg terminal is a **safe-hold invariant + receding-horizon against live people-flow**, NOT a scripted stop-and-return, which measured worse: contacts 319→323, contact time 89→245 s) under the zero-translation lease | governance suite + soak + the human nuisance bar |

## Lane B — decision studies (sequential; one at a time)
1. **NAV-CORE v2** — DECIDED at the pre-registered rule: both arms failed
   (A 0/60 — honest but unable; B 29/60 with 0 typed failures); **delegation
   refuted** (all defects are Parcel glue; 8/8 stalls inside Parcel's own
   brake rings with the route planned). The topology decision is DEFERRED to
   A2's corpus re-run by the executor's own rule. First measured
   `localization_jump_m` = 0.029 m max. Verification: mine, when the register
   lands; second lens: parcel-6c on refuter 4b honesty.
2. **VOICE-GATE v2 — DECIDED: push-to-talk for M1** (VERDICT in its
   folder). The pass rule was unsatisfiable on this host (no loudspeaker
   but the array's own DAC ⇒ AEC/barge-in unmeasurable; every arm row is
   honest `replay` tier) and PTT also measured best: owner recall 1.000,
   0 non-owner hosted bytes, 0 false openings/day, $0.15/day, 0 % replay.
   Consequences folded into the lane: **A6 STOP-LOCAL** ships
   name-prefixed unless the owner rules otherwise (bare "stop" spotter =
   ≈864 false/24 h on TV; name-prefixed = 0 on the same tape; a
   context-scoped hybrid — bare "stop" live while the dog speaks/moves on
   an owner mission — is proposed, unmeasured); **A7** gains: identity
   threshold recalibrated on the deployment channel (0.55 ships 0.167
   owner recall; ~0.352 gives 0.95 recall at 0.000 impostor FA, EER
   0.000), channel-matched enrollment, constrained/boosted ASR decoding
   over the known vocabulary (base.en misses names: slots 0.850), replay
   documented as accepted indoor risk (52.8 % at the usable threshold).
   Ambient upgrade = box-day mounted-acoustics decision.
3. **CONNECTED-PLANNER probe** (conditional per Codex/HLD §15: only if
   compound physical commands are binding for M1 — OWNER INPUT WANTED;
   otherwise deferred and one-step clarification ships).
4. **GATEWAY-FAULT study** is folded into A1's bench (Codex item 2).

## Findings the plan must never contradict (freeze list, from the verdicts)
No LLM owns a periodic tick (H2) · admission dominates cost; gate before
upload (H1/EVENT-BUDGET) · HOLD is a first-class command; body-neutral intent
(H4) · keep the localization contract, distrust its covariance and HEALTHY
after discontinuities (H7 + NAV-CORE 4b) · gallery novelty does not ship (H6)
· no online weight learning; no self-initiated translation (H3/Codex) · desk
GPU and cloud are optional accelerators — STOP, state estimation, safety,
gateway, event capture survive their loss (Codex/HLD principle 1).

## Freeze
Software architecture freezes after: A2's corpus re-run decision +
VOICE-GATE v2 + the applied HLD reconciliation (done: FABLE_HLD_CROSS_REVIEW.md adopts
`PORTABLE_LIVING_DOG_HLD.md` with `MILESTONE1_DESIGN_FABLE.md` into ONE
frozen reference. Electrical/mechanical/physical freeze: vendor written
answers + box-day packets (HLD Gates 3–6).
