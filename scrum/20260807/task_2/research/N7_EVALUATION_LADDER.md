# N7 — Evaluation ladder honesty

**Workstream:** N7 (Opus research wave, 2026-08-07)  
**Question:** What evidence ladder can tell better navigation from a
benchmark-shaped adapter, a scorer bug, or an oracle shortcut—and why must
that ladder precede SOTA model work?  
**Status:** complete for research; defects named below remain open in code.

## Verdict

Parcel does not yet have an honest capability score for instruction-following
or social navigation. The headline NAV_INSTRUCT minival is **1/25 (SR 0.04)**
under the frozen scorer; derived rescoring raises that only to **3/25 / 4/25**.
The pedestrian product-path case remains an intentional **xfail**. External
suites are either non-official proxies (native BARN 44%), single-world
smoke (ROS2 BARN / upstream MPPI), or unimplemented (MetaUrban).

**Do not run SOTA VLN / local-policy / owner-follow models against promotion
gates until:** (1) product-path evaluation is scorer-honest, (2) authority and
safety defects that make A/B runs uninterpretable are closed, and (3) at least
one role-matched classical baseline sits on the same frozen episodes. Author
scores from papers are not Parcel scores.

## Evidence classes (non-negotiable)

Every ledger row and prose claim must name exactly one class from
[`EVALUATION_AND_ROADMAP.md`](../EVALUATION_AND_ROADMAP.md):

| Class | May claim | Must not claim |
| --- | --- | --- |
| `derived_rescore` | old traces under a new scorer | a new run, a promotion sample |
| `contract_smoke` | import/schema/device readiness | task success |
| `synthetic_unit` | component behavior under generated inputs | product navigation |
| `product_headless` | unchanged product path in deterministic sim | physical safety, official rank |
| `external_proxy` | nonofficial / reduced / deployment-disabled hill-climb | leaderboard / top-decile |
| `external_public` | official-shaped public episodes | hidden-organizer rank |
| `external_hidden` | organizer-held protocol | anything without that attestation |
| `HIL` / `physical_supervised` | staffed hardware evidence | unsupervised deployability |

Never promote a number upward in prose. In particular:

- NAV_INSTRUCT **0.12 / 0.16** are `derived_rescore`, not runs.
- Native BARN **44%** is `external_proxy`, deployment-disabled, not Go2, not
  official.
- Upstream MPPI on **one** BARN world is not a Parcel score.
- Habitat CUDA/EGL/render smoke is not navigation.
- Simulator semantics / owner identity do not prove camera perception.

## Measured Parcel state (what numbers actually mean)

### NAV_INSTRUCT frozen rows — 1/25

Artifacts (same `episode_digest`):

- baseline `evals/nav_instruct/results/nav-instruct-v1-baseline-20260805T070524Z.json`
- candidate `evals/nav_instruct/results/nav-instruct-v1-candidate-20260806T070335Z.json`

Both report **SR 0.04 (1/25)** under the frozen rule. The candidate did not
improve the frozen headline. These rows exercise a direct-navigator / headless
path more than the full voice→executive product path; they are still the best
frozen instruction suite Parcel has.

### U31 — scorer / runner hold mismatch (measurement closed, defect open)

`backlog/UNVERIFIED.md` **U31**: `score_episode` requires a 1.0 s
inside-and-stopped arrival hold, but the headless runner ends the episode one
0.1 s tick after `arrived_verified`. The hold window can never accumulate.

Honest bound after Wave-0 option-1 rescoring (`hold-or-trace-end-v1`,
`evals/nav_instruct/rescore.py`):

| Run | Frozen rule | Derived rule |
| --- | --- | --- |
| baseline | 0.04 (1/25) | **0.12 (3/25)** |
| candidate | 0.04 (1/25) | **0.16 (4/25)** |

Ceiling is **4/25**, not the retracted 8/25. Four `circle_owner` step-limit
rows are real termination failures (still moving). Derived rows append to
`ledger.jsonl` with `kind="derived_rescoring"` and `parent_run_id`; frozen rows
were not rewritten.

**Honesty rule:** quote **1/25** as the frozen capability number; quote
**≤4/25** only as the U31-corrected diagnostic bound. Never call 0.12/0.16 a
new experiment. Option 2 (keep stepping for `arrival_hold_s`, then re-freeze
**both** baseline and candidate together) remains open.

### U32 / episode-spec defects (related, not U31)

False-arrival visibility is half-closed (`FailureClass.FALSE_ARRIVAL`). Lane D
replay showed at least two rows are **eval specification** defects (definite
article / wrong anchor), not navigator capability. Re-freeze those with U31
option 2 and scene-truth adoption—do not “fix arrival honesty” by chasing
mis-specified goals.

### Pedestrian xfail — product-path social residual

`tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_with_pedestrian_traffic`
remains `@pytest.mark.xfail` (strict=False). Post-N11 measurement: clean
admission, ~2.09 m travel to (−0.28, 2.07), ends **~0.33 m** outside the
sidewalk `GoalRegion`, fails `step_timeout` on the 240 s NavigateTo budget.
Owner: final-approach / proxemic cost on the approach pose (dynamic-social
card), not goal placement. Flipping this xfail without a hard pass is an
honesty violation.

Related pinned near-misses (sit-next-to placement, marginal towards band) are
the same final-approach family; keep them attributed, not aggregated into a
fake SR.

### Other measured external evidence (for context only)

| Artifact | Number | Class / does-not-prove |
| --- | --- | --- |
| Native BARN fixed-50 proxy | 44% success, metric ~0.10, 0 collisions | non-official, circular footprint, public worlds, deployment-disabled |
| Upstream Nav2 MPPI world 0 | success ~37.7 s, metric 0.1802 | reason to spike MPPI; not Parcel |
| Parcel ROS2 BARN world 0 | timeout 100 s, score 0 | adapter liveness / current controller miss |
| MetaUrban wrapper | `NotImplementedError` | no result exists |

Top-decile BARN claim requires official hidden protocol and score ≥ **0.4880**
(rank-2 / ceil(10% × 17) in the frozen 2026 cohort;
`evals/external/targets/barn_2026_top_decile.json`). Native 44% cannot satisfy
it even if the numeric proxy “looks close.”

## External ladder — what each tier measures and lies about

Primary sources checked 2026-08-07 (WebSearch + official pages/papers). Full
citations in [`SOURCE_LEDGER.md`](../SOURCE_LEDGER.md).

### Tier 1 — Parcel product headless (required every relevant PR)

**Measures:** voice/text → router → compiler → executive → navigator →
agent-issued stop → independent K0/truth-side predicate.  
**Does not measure:** physical stopping, camera ReID, official ranks.  
**Honesty obligations:**

- Route NAV_INSTRUCT (and walk-with-me) through `RobotRuntime.handle_text` /
  voice-final, not only direct controller hooks.
- Keep oracle replays for **attribution only** (oracle grounding / identity /
  route / scripted controller). First repair identifies the causal boundary;
  none is a product score.
- Reject oracle fields in the agent observation.
- Crash, OOM, timeout, stale sensor, model deadline → failed episode, not
  excluded data.
- Close U31 option 2 before treating the next frozen SR as capability.

### Tier 2 — BARN ROS2 (first external controller gate)

**Official protocol** ([BARN Challenge 2026](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html),
[2026 retrospective PDF](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf)):

- Standardized Clearpath Jackal, 270° Hokuyo 2D LiDAR, max 2 m/s.
- Development: 300 public cellular-automata worlds.
- Official simulation score: **50 organizer-hidden worlds × 10 trials**.
- Score \(s_i = 1_{\mathrm{success}} \times OT / \mathrm{clip}(AT, 2OT, 8OT)\);
  mean over 500 trials; upper bound 0.5.
- 2026 cohort: 17 sim teams; top decile ≈ ranks 1–2 (0.4975 / **0.4880**).
- Physical finals: classical stacks only for the second consecutive year;
  physical stage uses i3/16 GB, **no GPU**.

**DynaBARN:** optional parenthesized sim numbers; **excluded from ranking**;
physical dynamic arena not run in 2026; organizers plan static focus. Keep as
a separate nonofficial dynamic regression only.

**Parcel use:** public-development / repository-local regression is
`external_proxy` or `external_public` at best—never a leaderboard claim.
Adapters change observations/actions only. BARN proves LiDAR constrained
navigation under Jackal rules—not voice, semantics, owner follow, city
behavior, Go2 gait, or physical safety.

### Tier 3 — Follow-Bench (first external owner-follow comparator)

**Source:** [arXiv:2509.10796](https://arxiv.org/abs/2509.10796),
[project](https://follow-bench.github.io/),
[code](https://github.com/MedlarTea/follow-bench).

**Measures:** socially aware robot person following (RPF) motion planning—
target trajectory patterns, crowd dynamics, layouts; safety (collision /
tracking continuity) and comfort (proxemics, visibility, jerk). Lightweight 2D
sim; planners re-implemented for fair comparison; some real differential-drive
transfer in the paper.

**Does not measure:** enrolled owner ReID from camera, Parcel formation
semantics, Go2 dynamics, voice instruction, or hard metric-geometry safety
authority.

**Parcel lanes (required):**

1. Oracle target state → isolate formation / local planning.
2. Camera-derived enrolled-owner tracks → product composition.

Review licenses before vendoring. Do not start this adapter before owner
identity + formation goals exist (otherwise the “product” lane is fiction).

### Tier 4 — MetaUrban (dynamic-city stress service)

**Source:** [arXiv:2407.08725](https://arxiv.org/abs/2407.08725),
[MetaUrban / MetaUrban](https://metadriverse.github.io/metaurban/),
[github.com/metadriverse/metaurban](https://github.com/metadriverse/metaurban).

**Measures:** compositional urban micromobility; PointNav and SocialNav;
pedestrians / cyclists / vehicles; multimodal sensing; SR / SPL / SNS /
cumulative cost. Author baselines show the tasks are unsolved (paper reports
mid-density PointNav / SocialNav far from saturated).

**Parcel reality:** configured path raises `NotImplementedError`; no Parcel
episode metric exists. Full assets need registration/terms. Run as pinned
Python service; agent sees only permitted sensors/localization; semantic /
collision truth stays evaluator-side. Kinematics success ≠ Sport/quadruped
authority.

### Tier 5+ — HuNavSim / Arena, Habitat–VLN, ABotN, OmniGibson, Go2 physics

Use only after Tiers 1–4 contracts exist for the **role** under test. Habitat
maintenance is stale post v0.3.4; VLN-CE is legacy. ABotN is role-specific
3DGS RGB—not LiDAR fusion or owner follow. OmniGibson/BEHAVIOR is interactive
indoor physics later, not the next city/follow gate. Every surviving stack
needs a **Go2 embodiment physics gate** before HIL; BARN / MetaUrban / circular
proxy success cannot validate fall risk or Sport lag.

## Why the ladder before SOTA models

Models cannot repair:

- residual nonzero velocity after proximity/TTC stop (safety ordering);
- missing/stale LiDAR open-loop translate;
- truth pose standing in for localization;
- pause/resume channel vs task desync;
- `come here` as persistent follow vs terminating approach;
- U31 hold bookkeeping and false-arrival / mis-specified episodes;
- follow twists that bypass the obstacle-aware planner;
- oracle semantics on the product observation path.

If a VLA or local policy is inserted now, every gain is confounded with
termination bookkeeping, authority bugs, and oracle leakage. Phase order from
the task board remains:

```text
P0 evidence + safety + lifecycle freeze
  → P1 honest state / TaskRequest / product-path NAV_INSTRUCT
  → P2 classical Nav2 + formation goals + BARN adapter
  → P3 product eval overhaul + Follow-Bench / MetaUrban adapters
  → P4 learned proposers in offline replay → shadow (never motor authority)
  → P4-D Go2 physics → P5 safety case → supervised HIL
```

Promotion still requires: zero critical false-success / collision / false-owner
in the promotion set; paired statistically credible gain; no family or p99
latency regression; deterministic HOLD on model failure, except that the same
existing classical goal may continue after task/revision authorization and all
freshness, pose/transform, controller, and metric-geometry gates re-admit it;
gain on product suite **and** one role-relevant external suite; license and
device gates; separate HIL authorization.

## Recommended claim language (copy/paste)

**Allowed**

- “Frozen NAV_INSTRUCT minival SR is 1/25 (0.04) under
  `nav-instruct-v1.1-k0-arrival`.”
- “Derived rescoring under `hold-or-trace-end-v1` yields 3/25 baseline and
  4/25 candidate; defect U31 remains open in the runner.”
- “Native BARN fixed-50 proxy reached 44% success; not official, not Go2.”
- “`test_go_to_the_sidewalk_with_pedestrian_traffic` remains xfail; measured
  near-miss ~0.33 m / step_timeout after N11.”

**Forbidden**

- “NAV_INSTRUCT is at 16% after the candidate.”
- “We are top-decile on BARN” from public or native proxy worlds.
- “MetaUrban SocialNav works” without a Parcel ledger row.
- “Pedestrian traffic is solved” while the e2e case is xfail.
- Comparing author InternVLA / CityWalker / MiniCPM numbers to Parcel SR as if
  they shared a denominator.

## Immediate evaluation work (ordered)

1. **Freeze dirty-tree baseline hashes** before further nav edits (P0-0).
2. **U31 option 2 + U32 episode-spec re-freeze** with scene-truth—one paired
   baseline/candidate freeze, not silent scorer edits.
3. **Product-path NAV_INSTRUCT** through `handle_text` with agent-issued stop
   and independent predicates; keep direct-controller suite named lower-level.
4. **Close safety/lifecycle defects** that invalidate A/B (exact-zero stop,
   fail-closed sensors, atomic resume)—strict resume xfail → pass.
5. **Nav2 RPP/MPPI sidecar** on identical local + BARN public-dev episodes
   (matched-information and full-product lanes reported separately).
6. **Follow-Bench adapter** after owner identity + formation goals; then
   MetaUrban service with terms pin.
7. **Only then** shadow MiniCPM / CE-Nav / CityWalker / InternVLA-class
   proposers under `NavProposalV1`, latest-frame-wins, TTL, safety veto.

## Confidence

| Claim | Confidence |
| --- | --- |
| Evidence-class policy and anti-promotion rules | high |
| U31 size and derived 0.12/0.16 diagnostics | high (measured Wave 0) |
| BARN official vs proxy distinction; DynaBARN non-ranking | high (official report) |
| Follow-Bench as best first owner-follow external lane | high for role fit; medium until licenses/adapter exist |
| MetaUrban as best dynamic-city stress service | high for role; low for near-term ops (unimplemented) |
| Ladder-before-models ordering | high given open P0 authority defects |

## Sources (primary)

- Parcel: `EVALUATION_AND_ROADMAP.md`, `CURRENT_STACK_AUDIT.md`,
  `SOURCE_LEDGER.md`, `backlog/UNVERIFIED.md` (U31/U32),
  `evals/nav_instruct/results/*`, `evals/external/targets/*`,
  `tests/test_voice_nav_e2e.py` (pedestrian xfail).
- BARN 2026 page; BARN 2026 retrospective PDF; ROS2 challenge repo
  `Saadmaghani/The-Barn-Challenge-Ros2`.
- Follow-Bench arXiv:2509.10796 / follow-bench.github.io.
- MetaUrban arXiv:2407.08725 / metadriverse/metaurban.

External scores above are author- or organizer-reported unless a Parcel
`evals/**/results/` artifact is cited. Scores from different tasks are not
cross-comparable.
