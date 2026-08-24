# RTP-1 · CLAUDE_REVIEW — research-to-functional-prototype · Fable (parcel-fb) · 2026-08-24

Reviewed: `main`/`origin/main` = `0c5ea97`; dirty overlay = `pyproject.toml`
(H7 `localization` extra), live-churning tracked logs under
`research/20260823/local-cognition-gpu/logs/` (their server processes were
stopped by the integrator during this review; final quiet-host results file
`results/latency_rerun.json` written 04:44Z), and two untracked H2 results
files. Owner context that postdates the card and this review incorporates:
the offline fallback is now **a canned line + follow-with-obstacle-avoidance
only** ("Sorry, I'm offline; all I can do is follow you until we're
connected"), and the goal is the fastest path to an advanced conversational
companion with autonomous navigation, early-exiting research on convergence.

## Disposition: **ACCEPT_WITH_REQUIRED_CHANGES**

The phase structure (close only decision-blocking research → one functional
vertical slice → make it feel alive), the thin-slice order, the admission/
stop policy, and fifteen of seventeen concerns stand. Required changes:
(1) the owner's new offline floor supersedes C6's ladder — H9's grammar/8B
arms are DROPPED, not staged; H9 narrows to the connected-planner adapter
probe; (2) C8 is refuted at the runtime layer (evidence below) and shrinks
to one focused test; (3) Follow stays in M1 because the owner's offline
floor *is* follow — C16's identity branch is thereby chosen, hardware-gated,
with HOLD-on-ambiguity; (4) H2 is closed in this review from evidence
already on disk (no further model campaign).

## Product-path / evidence-ceiling matrix (C1)

| # | seam(s) | first production constructor/caller | ceiling |
|---|---|---|---|
| H1 | `realtime/cost.py RateCard`, `spend_ledger` v2 | ledger v2 is opt-in (`rate_card=` / env); `runtime.py` builds `SpendLedger` WITHOUT it → **NONE** (one line in M1-1); `voice/engagement.py` → **NONE** | hosted-live (34+66 ledgered responses, $0.0378) for pricing; replay for the ladder |
| H2 | `brain/monologue.py` | **NONE** | desktop (quiet-host re-run on disk) |
| H3 | `attention/drives.py`, `patrol/coverage.py` flag | **NONE** (flag default-off) | desktop-sim |
| H4 | `contracts/body_intent.py`, `motion/body_composer.py`, adapters | **NONE**; `control/go2_sport_body_adapter.py` is a refusing stub | desktop-sim |
| H5 | `memory/{scheduler,episodes}.py`, `online_map/answers.py`, tiered persistence | **NONE** (flag `memory.continual` off) | replay/synthetic |
| H6 | `perception/noticing.py` | **NONE** | desktop (renders + rebuilt COCO photos) |
| H7 | `localization/` | **NONE** | desktop-sim (numpy ICP proxy) |
| H8 | none (DESIGN only) | — | — |
| H9 | corpus only | — | — |
| H10 | memo | — | — |
Nothing in `RobotRuntime` constructs any wave-1 seam. Every "works" claim in
the wave is harness-only; the verdicts already say so per row.

## C1–C17 dispositions

| C | disposition | evidence / correction |
|---|---|---|
| C1 | CONFIRM | matrix above |
| C2 | CONFIRM | M1-0 native governor/gateway remains the single next build card; no smaller prerequisite unblocks a physical outcome (`Go2Backend` refuses all motion until it exists) |
| C3 | CONFIRM_WITH_CORRECTION | thin slice accepted; correction: Follow moves EARLIER (the owner's offline floor is "canned line + follow + avoid"), gated by C16's identity study; "final transcript → validated semantic task" is already partially product-real (tool broker → PlanIR path) and rides the same stage as NavigateTo. Gates per stage in §Gates |
| C4 | CONFIRM | H2 closed herewith from `results/latency_rerun.json` (quiet host, load ≈2): 8B tick total p50/p95 **604/756 ms idle** (bar 300/600 — REFUTED even uncontended), 978/1240 under perception, 1564/1977 contended; 26B 453/496 idle; one contended plan call p50 15.8 s; agreement stays 0.40/0.42. **Topology decided: deterministic drives own the tick; an LLM only phrases; the 8B talker (TTFT 66–71 ms quiet) is the phrasing seat.** Servers stopped; run state recorded in H2's VERDICT.md. No further model campaign |
| C5 | CONFIRM | NAV-CORE is the top pre-freeze experiment (design summary in §NAV-CORE); H8 demoted to an optional post-NAV-CORE seam probe exactly as the card describes |
| C6 | CONFIRM_WITH_CORRECTION | superseded in part by the owner (2026-08-24): the offline floor is a canned refusal line + follow-with-avoid (+ spoken stop, which must stay local — safety). H9's grammar and 8B-normalizer arms are DROPPED, not staged; what remains is the **connected planner**: a hosted structured-output PlanSketch through an explicit provider adapter (correct: it is an adapter/factory, not YAML — `providers.py` is llama.cpp-shaped), compiled and validated locally, with "tell me which step first" as the link-loss behavior. The 60-item corpus is reused to measure hosted PlanSketch validity + the intent gate |
| C7 | CONFIRM | corpus stays frozen; an independently authored adversarial intent-gate set (narratives/questions/corrections containing physical words) will be authored by parcel-6c (not by this reviewer, who wrote the gold); false-physical-plan rate reported separately from PlanIR validity |
| C8 | **REFUTE (with one residual test)** | `voice/amendment.py:16` defines `AMEND_SUSPEND_REASON = "goal_amend"`; `runtime.py:4017-4085 _apply_goal_amend` counts executive tasks in the gate and sends `InterruptRequest(source="voice", reason=AMEND_SUSPEND_REASON, requested="interrupt_now")` to EVERY running/waiting/queued executive task. The claim "not an explicit policy reason / falls through to overlap" is contradicted at file:line. Residual: whether the executive honors `interrupt_now` between checkpoints — one focused test (executive-only task + goal_amend ⇒ assert suspended before the next step dispatch), a precondition for replanning as the card says |
| C9 | CONFIRM | VOICE-GATE experiment (§plan) on the real XVF3800 — the one hardware we have; owner-voice gating vs wake phrase vs push-to-talk is its pre-registered decision; C5's 960 opens/h is the number it must beat |
| C10 | CONFIRM | the four H5 defects are M1-4 acceptance work; continual memory stays off until revocation/provenance survive end-to-end with a distractor-rich independent probe set |
| C11 | CONFIRM | depth + stamped extrinsics + real-bag LIO prerequisite to spatial claims; covariance untrusted (ANEES 100–230×); providers are candidates to measure |
| C12 | CONFIRM | contract retained; commission one primitive at a time starting with stationary HOLD + one bounded expression |
| C13 | CONFIRM | Go2 retained provisionally; vendor-written confirmations needed: X30 compute/cellular, Go2 payload-rail power budget, AGX carrier weight/thermals; no AGX purchase until H9-successor/NX soak shows need |
| C14 | CONFIRM | canonical = DESIGN/RESULTS/VERDICT + one compact results JSON per hypothesis; raw/append-only logs move out of git (this session untracks `research/**/logs/` in a program commit, retention = session scratch + the compact JSON); active lanes limited to one physical-integration lane + one blocking experiment; corrections batch at milestone boundaries |
| C15 | CONFIRM | the target-compute/mount freeze packet (60-min Orin co-residency soak + payload/rail/CoG/cooling facts, pre-registered keep-NX / offboard / reconsider branches) is hardware acceptance at box-day, not desk research |
| C16 | CONFIRM_WITH_CORRECTION | binary choice made the other way for the stated reason: Follow STAYS (the owner's offline floor is follow); therefore the small physical identity study is REQUIRED at box-day (two-person crossing, occlusion/reacquisition, clothing/lighting, appearance vs appearance+UWB); ambiguity/loss ⇒ HOLD + the canned line; until it passes, Follow is supervised-only |
| C17 | CONFIRM | closure table below; rows marked P block first pulse, T first translation, A first autonomous mission |

## NAV-CORE (the one experiment that must close before design freeze)
Decision: retain Parcel's navigator for M1, simplify to metric point-goals,
or delegate to an external navigation subsystem. Pre-registered: one-room
corpus (20 episodes × 3 seeds), `final transcript → validated NavigateTo →
known metric goal → planner/controller → physical-shaped scan+pose
(DriftingOdomProvider `calibrated_go2`, no truth pose, no oracle IDs, no
exact polygons, detector-shaped re-detection with dropouts) → verified
arrival | typed honest failure`. Bars: arrival ≥ 0.8 at ≤ 0.5 m, 0 false
arrivals, 0 contacts, honest-failure classification 100 %; refuters: scan
dropout mid-leg ⇒ HOLD, pose DEGRADED ⇒ refusal, moved obstacle ⇒ replan or
honest failure. Stop when the topology choice is unambiguous; do not tune
past the decision.

## Revised first-prototype ODD (supersedes the milestone draft's §1 in part)
As drafted (one room ≤ 8×8 m, operator + independent stop, ≤ 0.3 m/s, Sport
mode) with the **offline floor replaced**: on link loss the dog says the
canned line, keeps spoken/panel STOP and follow-with-obstacle-avoidance
(identity-gated, HOLD on ambiguity), and nothing else; all cognition beyond
that is connected-tier.

## Dependency order and next build card
Accepted thin slice (with Follow's position conditional on C16's study):
NAV-CORE decision → **M1-0 native governor/gateway + independent stop**
(BUILD_NEXT — the single next build card) → stamped body/LiDAR/RGB-D
observation → real LIO health/jump → supervised stop + known-place
NavigateTo → Follow (after identity study) → transcript→validated task →
continuous HOLD/gaze/breathing → governed memory → bounded initiative and
search.

## Assignments
- **CLOSE_BEFORE_BUILD:** NAV-CORE; VOICE-GATE (through-air activation on
  the XVF3800); CONNECTED-PLANNER (hosted PlanSketch adapter probe + intent
  gate on the frozen corpus + parcel-6c's adversarial set); H2 (closed in
  this review); the ODD/hazard table (below); H10 vendor confirmations
  (letters, not experiments).
- **BUILD_NEXT:** M1-0 gateway/governor (+ the C8 residual test riding the
  first replanning card).
- **DEFER:** H8 beyond the tiny seam probe (post-NAV-CORE); H3 wiring
  (Phase C); H5 fixes as M1-4 acceptance; H6 quiet-host throughput rework
  (the CPU-preprocessing fix lands with M1-5); H7 provider bake-off (real
  bags at box-day); mount freeze packet (box-day); identity study (box-day).
- **DROP:** H9 grammar + 8B-normalizer offline arms (owner's floor);
  on-body 26B / AGX / X30 work; further H2 model comparisons; full H8
  OCR/open-world exploration; outdoor/stairs/crowds; trainable initiative;
  continual weight learning; broad voice-model campaigns.

## Gates for the vertical slice (positive / refuter / stop-continue)
- Gateway bench: exact-zero on kill, client death, stale lease, epoch
  mismatch / seeded fault suite green ↔ any non-zero on loss ⇒ stop.
- First pulse (P rows): preflight READY×3 + clockmap + attest + single-axis
  commissioning record ↔ any refusal ⇒ stop.
- First translation (T): measured stop latency/distance + independent
  E-stop + six envelope terms measured ↔ UNMEASURED row ⇒ stop.
- NavigateTo sessions (A): ≥ 10 leashed runs, 0 contacts, 0 false arrivals,
  honest-failure rate reported ↔ any contact ⇒ stop and diagnose.
- Voice: VOICE-GATE bars (false opens/h with gating ON, spoken-stop recall
  ≥ 0.99, self-speech immunity) ↔ a single self-transcribed motion command
  ⇒ stop.

## Hazard / authority closure (C17, one table)
| hazard | prevented by | detected by | fail state | witness | blocks |
|---|---|---|---|---|---|
| collision/contact | reactive gate 0.65 m + proximity ladder + speed cap | scan + person tracks | exact-zero + HOLD | gateway stop report | T |
| runaway / stale command | TTL ≤ 350 ms + watchdog + epoch/lease | governor freshness check | exact-zero | audit ring | P |
| fall / drop-off / glass | ODD exclusion (flat, taped glass) + leash | operator | E-stop | session record | A |
| localization jump/loss | health refusals (H7-proven) | `LocalizationUpdate.health/jump` | HOLD, no false arrival | drift-ladder rows | A |
| sensor/network/cloud loss | link-loss floor (canned line + follow/HOLD) | R28 input-health table | HOLD / follow-only | preflight + logs | T |
| wrong-person follow | identity study + HOLD-on-ambiguity | tracker continuity score | HOLD + canned line | study rows | A |
| battery/thermal | profile refusals (SENSE-1) + soak packet | preflight + telemetry | sit + announce | soak record | T |
| false/self-transcribed voice cmd | VOICE-GATE (identity + AEC + triage) | gate metrics | ignore + log | VOICE-GATE rows | T |
| independent stop fails | handheld remote (out-of-band) + measured latency | commissioning test | operator physical | commissioning record | P |
| payload/mount failure | mount freeze packet | pre-session check | stop session | packet | T |
| private audio/video/memory | consent gates + owner store isolation + no cloud audio in silence | ledger + OT-2 tests | refuse | existing oracle suites | A |

## Spend / WIP / artifact policy
Pre-freeze research ≈ 3–5 focused days excluding hardware-gated work; one
physical-integration lane + one blocking experiment concurrently; a study is
admitted only if a failed result changes body/BOM/compute/safety/ODD/
acceptance; every study has one decision, pre-registered branches, and an
early-stop rule; hosted spend per study ≤ $2 unless the study is itself a
cost measurement; raw logs untracked (canonical files only); corrections
batch at milestone boundaries; no card-per-observation.

## Does not prove
This review proves no physical capability whatsoever: no gateway exists, no
motion authority, no measured stop, no real localization or perception on a
robot, no through-air acoustics, no owner identity in the flesh, and no
mounted compute. It converts research verdicts and code reads into an
order of work; every physical claim above is a gate to be earned, and the
harness-only matrix in §C1 is the honest ceiling of everything the wave
built.
