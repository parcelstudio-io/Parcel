# System-readiness remeasurement — results

Date: 2026-08-26
Evidence tier: desktop GPU inference, offline replay, deterministic headless
simulation, and repository audit. No robot, Orin, mounted microphone/speaker,
physical sensor, ROS 2 graph, or physical motion was used.

## Headline

The current prototype remains a **motion NO-GO** and a **conversation release
NO-GO**. The new Realtime companion relationship instruction has deterministic
render/freeze/parity evidence, while the separate local structured prompt can
be made fail-closed on the disclosed ten-case set. Broad conversation,
semantic navigation, completion authority, social yield, acoustics, and the
real Go2 path remain red.

The complete raw artifacts are in this directory. The frozen navigation
ledger and diagnostic input hash were checked before and after the runs and
were unchanged.

## Articulated Go2 asset smoke

An independent close review added `run_go2_mjcf_smoke.py`, captured one result,
and reproduced it in two verification runs against
the tracked, hash-pinned official Unitree scene. Under Python 3.14.4 and MuJoCo
3.11.0 it loaded a model with `nq=19`, `nv=18`, `nu=12`, and 41 sensors, then
completed 1,000 steps / 2.0 simulated seconds with finite state. All three runs
produced the same final-state digest
`ca2367ef44c02771d429c4ae8f425d624229452dea4a9025cd08905033715c96`;
load time varied from 165.620 to 189.281 ms and is diagnostic, not part of the
replay comparison.

Artifact: `go2_mjcf_smoke.json`. This only establishes that the vendored MJCF
is usable in the local physics library. It does not exercise native SDK2/DDS,
the motion gateway, a locomotion policy, contact safety, AGX Orin, or hardware.

## Conversation results

### Local structured prompt and model

This evaluator renders `PromptLibrary` from `prompts/system`, the runtime
context, function contract, and personality. It does **not** render or test
`si-companion-v4` from `src/parcel_robot/realtime/prompting.py`.

The first current local structured-prompt run exposed a capability
contradiction. The model copied six unavailable names from personality or
policy prose even though `runtime_context.available_social_skills` did not
contain them. Two preregistered corrective iterations instructed that local
lane to use the field as its sole allowlist and prohibited semantic
substitution; runtime admission remains responsible for rejecting invalid
names.

| run | provider parse | structured safety | machine cases | key observation |
|---|---:|---:|---:|---|
| initial current prompt | 10/10 | 4/10 | 3/10 | six unavailable action proposals |
| capability rule | 10/10 | 8/10 | 6/10 | unavailable names gone; two substitutions remained |
| final validation rule | **10/10** | **10/10** | **6/10** | all ten `next_action` values null |
| compatibility restoration | **10/10** | **10/10** | **7/10** | all ten actions still null; one stochastic same-corpus run |

The final desktop run had model HTTP p95 1,703.898 ms and TTFT p95
1,034.885 ms. The compatibility-restoration rerun measured 1,659.446 ms and
1,034.767 ms respectively. It used the admitted Gemma 4 26B-A4B Q4 model through the pinned
CUDA llama.cpp environment on an RTX 5000 Ada. These are neither spoken
end-to-end nor AGX Orin timings. The current 7/10 result exceeds the registered
6/10 floor but is one stochastic same-corpus run, not a demonstrated quality
gain. Because every current action is null, the result proves suppression/
fail-closed behavior only—not one successful available gesture or
conversation-to-motion behavior. No held-out or human quality claim follows.

Remaining machine misses were hypothetical-affect calibration, a perception
intent label, and diagnosis wording rather than unauthorized action proposals.
The frozen cases, rubric, generation settings, and model were unchanged across
the corrective runs. The iteration decisions were written before each rerun in
`ITERATION_1.md`, `ITERATION_2.md`, and `ITERATION_3.md`.

### Broader conversation and task evidence

| suite | result | interpretation |
|---|---:|---|
| Captured realtime SI-v1 corpus | 6 PASS / 8 MIXED / 11 FAIL threads; 43/76 semantic expectations | Provenance-complete offline replay, but unblinded AI review and red quality |
| Personal conversation fixture | 13/13 turns | Deterministic heuristic fixture only |
| Personal conversation, live local model | **3/13 turns; 2/8 families** | Six families fail; conversation is not release-ready |
| Brain v1 task boundary | 15/15, including 7/7 fail-closed | Strong typed software boundary; zero physical episodes |
| Embodied plan | 4/4 supported cases; one unsupported case | Simulator-only; six simulator skill episodes, no robot |
| Fresh planner-quality v2 | **3/5** | Failed the five-step and orbit/follow cases; p95 HTTP 8,015.824 ms |
| Fresh PlanSketch v1 | **3/5** | Same accuracy; p95 HTTP 2,902.479 ms, so faster but not better |

The fresh planner runs are important because an older frozen artifact had
reported 5/5. The current admitted local-model path does not reproduce that
quality and must not inherit the earlier claim.

The four virtual-acoustic gates reported in QEV-1 remain red and no mounted
through-air measurement was available. Prompt and text-model success cannot
substitute for VAD, AEC, endpointing, barge-in, playback-rejection, or room
acoustics evidence.

## Navigation results

### Instruction navigation

The exact NAV_INSTRUCT v4 recipe was rerun with seed `20260804`,
`scaled-path-v1`, `max_steps=200`, and no ledger writes.

| matrix | n | success | frozen-rule success | SPL | collision | false arrival |
|---|---:|---:|---:|---:|---:|---:|
| minival | 25 | 0.200 | 0.120 | 0.153259 | 0 | 0 |
| full | 125 | **0.200** | 0.136 | **0.134772** | 0 | **1** |

The full failure attribution was 31 grounding, 12 planning, 21 termination,
33 refusal, two search, one false-arrival, and 25 successes. `object_relative`
and `circle_owner` were 0/25 each. The full readiness criterion was success at
least 0.80, SPL at least 0.60, no false arrivals/collisions, and nonzero
success in every family/tier; it failed decisively.

### Scene split

The scene-split CLI ignored `--out` and wrote into the tracked default report
location. That evaluator defect was repaired and covered by
`tests/test_nav_scene_split_output.py` before the real split was run.

| split | episodes | success | SPL | false arrivals | collisions |
|---|---:|---:|---:|---:|---:|
| seen city scene | 15 | 0.1333 | 0.1333 | 0 | 0 |
| five unseen scenes | 75 | 0.2533 mean | 0.2401 mean | **16** | 0 |

The negative seen-minus-unseen gap does not show useful generalization: both
sides are poor, unseen mean distance-to-goal is 13.31 m, and unseen completion
authority produces 16 false arrivals. This diagnostic should be treated as a
failure-family generator, not a leaderboard claim.

### Companion navigation

| suite | result | readiness implication |
|---|---:|---|
| Walk-with-me stub | 10/10 | Mechanically vacuous for navigation |
| Walk-with-me headless | **5/10** | Below the 8/10 floor; grounding, planning, and termination failures |
| Follow bench | 7/9 Follow, 2/2 Navigate, zero hard collisions | Scripted/oracle-owner evidence only; two Follow failures and higher jerk |
| Yield extension | **STOP-AND-REPORT** | One simulated hard collision/contact, -0.468 m pedestrian surface clearance, and 3.1 s intimate-space dwell |
| Generic external proxy | 100 episodes: SR 0.52, SPL 0.52, collision 0.44, human collision 0.08 | Synthetic proxy, not an official benchmark; clearly red |

### Liveness and completion hypotheses

The separate navigation-generalization experiment repeated 516 episode
executions with deterministic digests.

- A supervisor watching only `no_path` was **refuted**: it typed 17/24 held-out
  blockers, while seven stayed `goal_blocked` until tick 900.
- The exploratory post-hoc state set `{no_path, goal_blocked}` typed 24/24
  blockers and preserved all 60/60 paired nominal outcomes. It needs a new
  untouched dynamic holdout before product promotion.
- Requiring five consecutive arrival claims was **refuted as a remedy**. All
  three aliased-kidnap cases still falsely completed 5.21–5.30 m from truth at
  confidence 1.0. Completion needs evidence independent of the aliased map
  hypothesis, not a longer streak or higher scalar threshold.

## Evaluator integrity and test findings

- The navigation mutation panel killed all seven registered mutants.
- The brain contract suite retained its frozen behavior. The embodied-plan
  semantic outcomes remained 4/4 supported cases plus one explicit unsupported
  case, with zero collisions and zero timeouts. Its regenerated 2026-08-28
  execution row moved from 997 to 1,051 simulator steps and from 0.883147 m to
  0.865683 m minimum clearance after the headless navigator began carrying the
  already-observed owner track and executing the verified owner-facing terminal
  phase; the minimum remains above the configured 0.65 m clearance.
- The long navigation/nightly group produced 62 passed, seven expected
  failures, and two reproducible failures after 774 seconds:
  `sit next to the lamppost` remained `semantic_target_unreachable`, and
  `go to the lamppost` remained
  `semantic_arrival_verification_failed`. Both failed again in isolation.
- No frozen case, score threshold, or failure label was changed to make these
  results green.

### Repository close verification

The repository's one-time commit-tier close gate ran once, as required. Its
dedicated rows passed, including lint, hard-safety checks, assertion-bearing
evals, release parity, model-off tests, parity integrity, and owner-store
isolation. The default test row nevertheless recorded **FAIL**: 10,510 passed,
22 skipped, five expected failures, and two deterministic failures. Those two
failures were (1) a stale test expectation of 100 packaged assets after the
intentional increase to 102 and (2) `prompting.py` at 1,037 lines against the
existing 1,000-line debt ratchet.

Both exact defects were then repaired: the packaged-asset expectation was 102
at that closure point (`test_ci_gate` separately counted one external side
mirror, for 103 total comparisons) and the
unchanged SI v4 relationship text was extracted into the leaf
`relationship_prompt.py`, leaving `prompting.py` at 998 lines. Post-fix guarded
verification passed the two failed nodes **2/2**, and a broader affected suite
passed **111 tests with four skips**. Ruff, all new JSON documents, frozen SI
reproduction (12 pins across four versions), packaged-asset parity (102 files
plus one external side-mirror comparison),
and `git diff --check` also passed. The full commit gate was deliberately not
run a second time under its once-per-close policy, so its recorded status
remains the pre-fix red result; this report does not claim a post-fix full-gate
green run.

The later adversarial close did not rewrite that historical gate result. It
added `si-companion-v5`/`di-companion-v2`, froze three more current-version
persona snapshots, and moved the live parity truth to 105 packaged files plus
one external side mirror. A guarded prompt/action/freeze/parity suite passed
265 tests, and a real-HeadlessCity clock-domain regression passed 1/1. The full
commit gate remained intentionally unrerun.

## What changed in product/evaluator code

1. Added `si-companion-v4`, retaining exact v1-v3 rendering and digests, with
   an explicit continuing-friend contract: warmth and continuity from recent
   dialogue/consented memory, immediate respect for quiet/privacy/distance,
   no surveillance/dependence, and no emotion-triggered base travel.
   The later v5/DI-v2 close preserves that relationship while treating labeled
   runtime fields as data and making free-form history, owner-note, and sensor
   blocks explicitly quoted/delimited and untrusted.
2. In the separate local structured prompt, instructed the model to use
   `runtime_context.available_social_skills` as the only source for
   `next_action` and to fail to null rather than substitute. Runtime admission
   now independently enforces the tagged social allowlist and derives explicit
   action authority from deterministic owner-transcript parsing rather than the
   model's trigger label. Hosted Realtime uses a separately generated tool enum
   and broker.
3. Added frozen v4/v5 persona assets and prompt/release parity tests.
4. Fixed NAV_INSTRUCT scene-split report routing so `--out` is honored.
5. Declared the in-process simulator clock mapping at observation ingress; a
   direct HeadlessCity regression proves time-zero evidence starts fresh but
   still expires at the configured age limit.

These are fail-closed improvements. They do not add missing gestures, typed
runtime semantics, owner identity, action receipts, a gateway-compatible
`SportPort` and composed normal-runtime-to-robot path, or physical perception.
The repository's legacy `UnitreeSportController`/`SportClient` transport does
not by itself close or validate that gateway composition.

## Evidence limitations

- No human raters, real owner sessions, natural audio, physical sensors, Orin,
  Go2, SDK2 transport, physical stop, or articulated contact dynamics were
  exercised.
- Model tests reuse disclosed cases after prompt diagnosis; they estimate a
  rule repair, not population generalization.
- Headless simulations use synthetic truth and simplified dynamics.
- Zero collisions in a low-success suite can be vacuous. False completion is
  independently disqualifying.
- The linked Claude artifact returned a Claude `Page not found` page on this
  date. Only the committed repository work was reviewable.
