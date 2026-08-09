# N3 — Social / dynamic navigation & proxemics

**Workstream:** Opus research matrix N3 (`OPUS_RESEARCH_WAVE.md`)  
**Checked:** 2026-08-07  
**Scope:** Pedestrian-contested goals, yield-advance pacing, mid-mission
re-rank, dwell arrival, owner-follow social metrics (Follow-Bench), and
external social/dynamic simulators.  
**Primary Parcel anchor:** N11 residual — sidewalk-with-traffic e2e dies
~**0.33 m** short of the region after one-shot traffic-aware placement +
yield-advance wiring (`test_go_to_the_sidewalk_with_pedestrian_traffic`
still xfail). The distance comes from the stored xfail reason; this workstream
did not rerun that episode, so treat it as historical evidence until a frozen
`--runxfail` reproduction.

This note challenges the prior N6 appendix summary where evidence warrants
it; it does not reopen Sol↔Opus N11 wiring approvals.

---

## 1. Verdict

Parcel already has the *right safety posture* for contested final approach:
`person_stop` / TTC / collision brake remain hard, and `RampMemory` + final-
metre creep are memory/recovery seeds only. The remaining N11 failure is
**not** a missing brake — it is a **goal-commitment + arrival-definition**
problem under a contested, occupied destination strip.

Literature converges on the same split Parcel needs:

1. **Hard geometry / collision** stays authoritative.
2. **Soft social/proxemic cost** ranks candidates and paces motion.
3. **Commitment is temporary** — goals and formations re-rank online when
   predicted occupancy invalidates the committed pose.
4. **Comfort metrics** (min distance, private-zone time, jerk, preferred
   follow annulus) are evaluation and soft cost, never permission to cross a
   stop gate.

**Recommendation:** Ship a one-week residual card that (a) mid-mission
re-ranks approach poses while dwelling in `person_stop` near the goal, (b)
adds a dwell-based `inside` arrival using polygon+clearance, and (c) keeps
yield-advance as seed-only. Follow-Bench is the first external owner-follow
comparator; HuNavSim 2 / MetaUrban are later social/city stress services —
not N11 flip criteria.

**Confidence:** high on N11 residual diagnosis and the hard/soft split;
medium on which predictor beats constant-velocity for week-1 (CV + age
filter is enough to flip the known e2e); medium on Follow-Bench adapter
effort until licenses and Parcel track→oracle seams are spiked.

---

## 2. Parcel ground truth (N11 near-miss)

### What landed

| Layer | Artifact | Role |
| --- | --- | --- |
| Pure | `navigation/traffic_aware.py` | `tracks_from_payload`, `traffic_occupancy_cost`, `rank_approach_candidates`, `RampMemory` |
| Wire | `approach.safe_approach_pose`, `pipeline.DirectiveNavigator`, `grid_navigator.seed_ramp` | Traffic weight when tracks present; ramp seed on clear after `person_stop` |
| Parked | `proxemic_approach.reject_cost` | Fail-closed veto; correctly **not** wired (would break empty-tracks identity) |

Empty tracks keep byte-identical static ordering (ladder). Mission metadata
records `approach_static_cost` / `approach_traffic_cost` /
`approach_total_cost`. Safety gates were not weakened.

### Measured residual (~0.33 m)

From `OPUS_N11_STATUS.md` and Lane D logs:

- Scripted pedestrians occupy the sidewalk strip (y≈2.85–3.55).
- Commit-time CV ranking prefers a quieter south-edge pose (~y=2.64).
- Person-stop correctly refuses the final ~0.3 m as agents sweep that edge.
- End pose ≈ (−0.27, +2.07) — short of polygon (y≥2.2) and K0 eval region
  (y≥2.4); `step_timeout` after ~240 s.
- Yield-advance + final-metre creep (`FINAL_APPROACH_BAND_M=1.0`,
  `FINAL_APPROACH_CREEP_MPS=0.12`, horizon 1.5 s) are necessary but
  insufficient: clear windows stay too short to accumulate the last metre
  **to the same committed point**.

### Three deferred follow-ons (still open)

1. **Mid-mission re-rank / re-commit** when dwelling in `person_stop` near
   the goal with fresh tracks.
2. **Dwell-based `inside` arrival** via `point_in_polygon_with_clearance`
   (today `_inside_arrival_goal_region` intentionally returns False for
   `inside`).
3. Optional later: `proxemic_approach.reject_cost` as an *additional* veto
   only when tracks are non-empty (preserve empty-tracks identity).

N13 sit-next-to placement near-misses (bench ~0.21 m, lamppost ~0.072 m)
are the same **final-approach family** without traffic — treat as sibling
gates once N11 residual lands.

---

## 3. Literature map (primary sources, 2026-08-07)

Web-checked; author-reported numbers are not Parcel proof. Artifact terms
remain acquisition gates (`SOURCE_LEDGER.md`).

### 3.1 Follow-Bench — first external RPF comparator

- **Paper:** Ye et al., *Follow-Bench: A Unified Motion Planning Benchmark
  for Socially-Aware Robot Person Following*,
  [arXiv:2509.10796](https://arxiv.org/abs/2509.10796) (v4 May 2026 HTML).
- **Site:** [follow-bench.github.io](https://follow-bench.github.io/);
  code noted in ledger as [MedlarTea/follow-bench](https://github.com/MedlarTea/follow-bench).
- **Claim:** Unified 2-D simulator + diverse target trajectories, crowd
  dynamics, layouts; re-implements ~6–8 RPF planners; metrics explicitly
  split **safety** vs **comfort**; real-robot validation of top planners.
- **Metrics (paper Table II / Sec. II-B):**
  - Safety: ASR (collision-free), SSR (re-find after occlusion), SPL, SR.
  - Comfort: velocity/accel/jerk; time in personal zone (~0.45–1.2 m);
    angular deviation from preferred follow angle; target visibility ratio
    (TVR); time in private zone (<0.45 m) of bystanders; path length.
- **Parcel take:** Best **Tier-3** owner-follow planner gate
  (`EVALUATION_AND_ROADMAP.md`). Run two lanes — oracle target state vs
  enrolled-owner camera tracks. Do **not** make Follow-Bench an N11 flip
  criterion; N11 is NavigateTo-to-region under traffic, not RPF.

### 3.2 HuNavSim 2.0 — social behavior + metric suite

- **Paper:** [arXiv:2507.17317](https://arxiv.org/abs/2507.17317).
- **Code:** [robotics-upo/hunav_sim](https://github.com/robotics-upo/hunav_sim).
- **Claim:** ROS 2 human agents via Behavior Trees; noise-augmented Social
  Force Model; wrappers for Gazebo / Isaac / Webots; large compiled social
  metric set (~32 in v2 narrative).
- **Parcel take:** Tier-5 regression for proxemics/jerk/group/queue after
  Follow-Bench adapter exists. Useful for stress-testing yield policies
  against *reactive* humans (unlike SocNavBench replay).

### 3.3 MetaUrban — dynamic city stress

- **Paper / project:** [arXiv:2407.08725](https://arxiv.org/abs/2407.08725),
  [metadriverse.github.io/metaurban](https://metadriverse.github.io/metaurban/),
  ICLR 2025 spotlight.
- **Claim:** Compositional urban scenes; PointNav + SocialNav; pedestrians /
  VRUs / micromobility agents; RL/IL baselines; embodiment matters.
- **Parcel take:** Best dynamic-city stress **service** (Tier-4). Current
  Parcel MetaUrban path is unimplemented. Registration/asset terms block
  casual use. Not a substitute for the headless pedestrian e2e gate.

### 3.4 SocNavBench — grounded replay social nav

- **Paper:** Biswas et al., ACM THRI 2022; code
  [CMU-TBD/SocNavBench](https://github.com/CMU-TBD/SocNavBench).
- **Claim:** Real pedestrian datasets; metrics for TTC / closest-pedestrian
  distance / jerk / efficiency; pedestrians **do not react** to the robot.
- **Parcel take:** Archival / secondary. Good for comparing aggressiveness
  (SFM conservative vs ORCA/CADRL aggressive) without interactive humans.
  N11's scripted strip is closer to SocNavBench's non-reactive style —
  remember that when claiming "social" competence.

### 3.5 DynaBARN / BARN 2026 dynamics

- **Paper:** [SSRR 2022](https://doi.org/10.1109/ssrr56537.2022.10018758);
  [project](https://people.cs.gmu.edu/~xiao/Research/DynaBARN/DynaBARN.html).
- **BARN Challenge 2026:** Dynamic obstacles appear as **bonus** only;
  retrospective: DynaBARN parenthetical scores excluded from ranking;
  organizers plan to focus on static obstacles going forward.
- **Parcel take:** Keep DynaBARN as **nonofficial** dynamic-obstacle
  controller regression. Do not combine into static BARN scores or imply
  owner-follow / sidewalk-stream competence.

### 3.6 Prediction & social cost layers

| Source | Lesson for Parcel |
| --- | --- |
| [Trajectron++](https://arxiv.org/abs/2001.03093) | Dynamically feasible multi-agent forecasts; optional ego-conditioning. Strong architecture reference; **week-1** stick to calibrated CV/CA + `age_s` staleness (already in `TrackState`). |
| [GSCL social cost layer](https://link.springer.com/article/10.1007/s12369-026-01384-0) | Soft social costmap + BT replanning (~1 Hz) + stop-and-go in queues. Matches Parcel's "social soft / geometry hard" and suggests **1 Hz** re-rank cadence, not control-loop re-plan thrash. |
| [Group proxemics vector field](https://arxiv.org/abs/2502.04837) | Superpose individual → group fields; useful later for clusters on sidewalk strips. |
| [Proxemics taxonomy 2026](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2026.1800762/full) | Comfort is context-dependent (task, form factor, culture); egg-shaped / asymmetric / dynamic zones beat fixed circles. Parcel should keep zones **config + eval**, not universal constants. |
| [nav2_social_costmap_plugin](https://github.com/robotics-upo/nav2_social_costmap_plugin) | Reference proxemic costmap once Nav2 sidecar lands (N1/N3 classical). Soft only. |
| [SocialNav](https://github.com/AMAP-EAI/SocialNav) (CVPR 2026) | Watch; incomplete public checkpoint — do not integrate. |

### 3.7 Owner-follow proposers (adjacent, not N11)

- **MiniCPM-RobotTrack** ([HF](https://huggingface.co/openbmb/MiniCPM-RobotTrack),
  Apache-2.0): 0.9B, eight `(x,y,yaw)` waypoints, ~180 ms / 5+ FPS author
  claim on Go2 EDU Orin NX. Emits formation proposals — never identity or
  safety. Shadow against formation-goal → common planner (appendix N6).
- Direct proportional follow velocity in Parcel remains a defect; social
  RPF literature consistently routes through a local planner with proxemic
  goals, not open-loop chase.

---

## 4. Design implications for Parcel

### 4.1 Mid-mission re-rank (primary N11 fix)

**Problem:** `safe_approach_pose` runs once at commit. Over a ~240 s
NavigateTo, the quieter edge becomes a person-stop corridor.

**Sketch (pure + wire):**

```text
when mission.state in {navigating, person_stop}
 and dist(robot, committed_goal) < RE_RANK_BAND_M   # e.g. 1.5–2.0
 and person_stop_dwell_s >= RE_RANK_MIN_DWELL_S     # e.g. 0.8–1.5
 and tracks fresh (max age_s < max_age_s):
    candidates = sample_inside_goal_region(...)     # same free set as approach
    ranked = rank_approach_candidates(..., tracks=now)
    if ranked[0].total_cost + ε < committed.total_cost
       and ranked[0] reachable under static free space:
        re-commit; record approach_*_cost + re_rank_count
```

**Constraints:**

- Ladder: no tracks ⇒ never re-rank (identity with static).
- Cap frequency (~1 Hz / GSCL-like) to avoid goal flicker; require
  cost improvement + hysteresis.
- Re-commit must not clear `RampMemory` to zero if the gate is still
  held — only update the goal pose.
- Do **not** use `proxemic_approach.reject_cost` as the only selector
  (fail-closed `None` under empty/all-hot candidates). Ranking with
  finite costs + optional veto-when-tracks is the safe order.

**Why literature agrees:** Follow-Bench and RPF surveys treat preferred
relative pose as **adaptive** under crowd/layout change; GSCL re-plans
social costs at ~1 Hz; SNAPE/CORTEX-style followers replan with predicted
human pose, not a frozen offset.

### 4.2 Dwell arrival (`inside` / region goals)

**Problem:** Contested regions may never yield a long clear window to a
point on the busy edge, yet the robot can be **inside** the semantic
polygon (or within clearance) while yielding.

**Sketch:**

```text
if goal.mode == inside:
  if point_in_polygon_with_clearance(robot, region, clearance_m)
     and dwell_inside_s >= INSIDE_ARRIVAL_DWELL_S:   # e.g. 0.5–1.0
    succeed with detail=inside_dwell_verified
```

Pin against:

- False success while still in the street / outside polygon.
- Success during active collision-brake (require clear or person_stop
  *while already inside*, not while still approaching).
- K0 eval region vs semantic polygon disagreement — adopt one
  scene-truth rule with W0-D / stratum-3 region selection (NEXT.md).

Static N13 near-misses (7–21 cm outside `next_to` bands) may need a
sibling **band dwell** or slight band calibration — do not launder them
as traffic wins.

### 4.3 Yield-advance (keep; do not over-grow)

Already correct safety argument: seed only after gate clear; bounded by
slew / S-curve / TTC / arbiter.

**Week-scale tweaks only:**

- Keep `FINAL_APPROACH_*` creep; log predicted clear-window length vs
  creep distance (diagnostics for whether re-rank or creep is the lever).
- Optional: when re-rank moves the goal laterally along the strip,
  prefer a candidate whose CV occupancy predicts a clear window ≥
  `distance / creep_mps` (feasibility filter), not only lower integral
  occupancy.
- Never raise creep above person-stop envelope needs; never seed on
  `person_stop` ticks.

### 4.4 Soft social cost vs hard stop

| Signal | Authority |
| --- | --- |
| Occupied LiDAR / footprint collision | Hard stop |
| `person_stop_m` / TTC | Hard stop |
| `traffic_occupancy_cost` / proxemic Gaussians | Soft rank / pace |
| Follow preferred annulus / angle | Soft formation goal |
| Learned social critic / MiniCPM waypoints | Proposal only |

Crowd-cost defect called in appendix N6 (normalization / retain riskiest
tracks, not source order) remains in force for the grid `dynamic_layer`
path; approach ranking already uses stdlib `traffic_aware` with
`DEFAULT_MAX_TRACKS=16` — keep both seams aligned on max tracks and age
filters.

### 4.5 Owner-follow (N6 adjacency)

Replace proportional chase with 10–20 Hz formation-goal samples → common
planner. Identity is enrolled multi-frame posterior, not nearest person.
Follow-Bench oracle lane isolates the planner; camera lane measures the
product. MiniCPM-RobotTrack shadows as waypoint proposer only.

---

## 5. Evaluation honesty

| Gate | What it proves | What it does not |
| --- | --- | --- |
| `test_go_to_the_sidewalk_with_pedestrian_traffic` | Product NavigateTo under scripted non-reactive stream; N11 flip | Interactive human response, RPF comfort |
| Static sidewalk / lamppost e2e | Region grounding + arrival | Traffic competence |
| Follow-Bench (oracle / camera) | Formation + local planner safety/comfort | Voice, city semantics, Sport safety |
| HuNavSim 2 | Interactive social metrics under BT humans | Parcel product path |
| MetaUrban SocialNav | Procedural city density / embodiment | Commissioned Go2 safety |
| DynaBARN | Dynamic obstacle motion profiles for controllers | Social norms / following |
| SocNavBench | Replay disruption metrics | Interactive yield |

**Promotion vetoes:** any N11 "green" that weakens person-stop; Follow-Bench
wins with oracle IDs presented as product follow; DynaBARN blended into
BARN ranking claims.

---

## 6. Week-scale sketches

Assumes one focused engineer-week on the N11 residual family, then a
second week for Follow-Bench spike. Cards stay small; safety seams frozen.

### Week A — N11 residual flip (days 1–5)

| Day | Deliverable | Exit |
| --- | --- | --- |
| **A0** | Freeze failing e2e artifact: end pose, `approach_*_cost`, person-stop dwell histogram, clear-window lengths, creep seed events | Repro note in scrum; xfail reason cites digest |
| **A1** | Pure: `should_rerank_approach(...)` + hysteresis helpers in/near `traffic_aware` (stdlib); unit tests for empty-tracks no-op, cost Δ, age filter, band/dwell gates | `tests/test_traffic_aware.py` green |
| **A2** | Wire mid-mission re-commit in `DirectiveNavigator` / approach seam; metadata `re_rank_count`, new `approach_*_cost`; progress watchdog ignores re-rank ticks | Wiring tests + no regression on empty-tracks e2e |
| **A3** | Dwell `inside` arrival: `point_in_polygon_with_clearance` + dwell timer; pins for false-outside / true-inside | Unit + one headless region case |
| **A4** | Run pedestrian sidewalk e2e with `--runxfail`; if hard pass, flip xfail → gate. Else publish failure mode (still occupied, band mismatch, timeout) | Flip **only** on hard pass |
| **A5** | Sibling static near-miss triage (N13 lamppost/bench): either shared dwell-band helper or explicit "not this card" | Written disposition |

**Out of week A:** MetaUrban, HuNavSim, MiniCPM physical, `reject_cost`
wiring, learned predictors.

### Week B — Follow-Bench + social metric spine (days 6–10)

| Day | Deliverable | Exit |
| --- | --- | --- |
| **B0** | License/terms spike on Follow-Bench top-level + CVXPY/OSQP/deps; pin commit | Go/no-go in ledger note |
| **B1** | Adapter sketch: Parcel formation goal → Follow-Bench robot API; **oracle** target state lane only | Smoke 1 scenario |
| **B2** | Metric export aligned to paper: ASR, min distance, private-zone time, jerk, path length | JSON artifact schema |
| **B3** | 100-trial subset on 2–3 scenarios (corridor + crowd + doorway); compare current follow vs formation-goal prototype if ready | Report; no promotion claim |
| **B4** | Spec HuNavSim 2 headless CPU job (no Isaac yet) as Week C optional; list 5 Parcel-mapped metrics | Spec only |
| **B5** | Write promotion rules into eval README: oracle ≠ product; soft cost ≠ stop gate | Doc PR |

### Week C — optional stretch (only if A flipped and B adapter green)

- Camera-track Follow-Bench lane (enrolled owner).
- MetaUrban SocialNav service spike (terms permitting).
- CV→CA / simple turn model behind `traffic_occupancy_cost` with
  matched-information A/B on the sidewalk e2e.
- Soft `proxemic_approach` veto **when tracks non-empty**, behind a flag.
- Crowd-cost normalization fix on grid `dynamic_layer` (appendix N6).

### Staffing sketch

```text
Week A: 1 nav owner (pure+wire+e2e) + 0.25 review (Sol-style pure contract)
Week B: 1 eval/adapter owner + nav owner half-time on formation goal
Week C: optional; blocked on A flip + B license go
```

---

## 7. Risks & non-goals

**Risks**

- Re-rank flicker near ties → commitment bonus / min dwell (same pattern as
  `ReactionArbiter` soft commitment).
- Dwell arrival laundering near-misses outside true semantics → require
  polygon+clearance, not eval-disc alone.
- Creep + re-rank interacting badly → log both; change one knob per
  experiment.
- Treating Follow-Bench CPU planners as Go2 Sport authority.
- Interactive HuNavSim humans making N11 scripted gate look worse/better
  without matched protocols.

**Non-goals (this workstream)**

- End-to-end social RL / SocialNav weights.
- Weakening person-stop to "make progress."
- Replacing Unitree Sport with a social policy.
- Claiming BARN-2026 dynamic ranking from DynaBARN local runs.

---

## 8. Source checklist

| Source | URL / path | Used for |
| --- | --- | --- |
| Follow-Bench | https://arxiv.org/abs/2509.10796 | RPF metrics, scenarios, planner trade-offs |
| HuNavSim 2.0 | https://arxiv.org/abs/2507.17317 | Interactive humans, metric suite |
| MetaUrban | https://arxiv.org/abs/2407.08725 | City SocialNav stress |
| SocNavBench | https://dl.acm.org/doi/10.1145/3476413 | Replay disruption metrics |
| DynaBARN | https://people.cs.gmu.edu/~xiao/Research/DynaBARN/DynaBARN.html | Dynamic obstacle profiles |
| BARN 2026 | https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html | Dynamics = bonus only |
| Trajectron++ | https://arxiv.org/abs/2001.03093 | Prediction reference |
| GSCL | https://link.springer.com/article/10.1007/s12369-026-01384-0 | Soft cost + ~1 Hz replan |
| Proxemics taxonomy | https://www.frontiersin.org/articles/10.3389/frobt.2026.1800762 | Context-dependent zones |
| MiniCPM-RobotTrack | https://huggingface.co/openbmb/MiniCPM-RobotTrack | Follow proposer shadow |
| Parcel N11 | `traffic_aware.py`, `OPUS_N11_STATUS.md`, `pipeline.py` final-metre creep | Residual diagnosis |
| Prior appendix | `RESEARCH_WORKSTREAM_APPENDIX.md` §N6/N8 | Challenge/confirm |

---

## 9. One-paragraph thesis for the crown doc

Social/dynamic competence for Parcel is a **commitment and pacing** problem
on top of working hard stops: N11's ~0.33 m near-miss shows traffic-aware
one-shot placement and yield-advance seeds improve quieter entry but cannot
finish when the destination strip stays occupied. Mid-mission re-rank with
hysteresis, dwell-based region arrival, and seed-only yield-advance are the
week-scale product fixes; Follow-Bench then HuNavSim/MetaUrban supply
external RPF and interactive-city evidence without owning identity or
collision authority. Soft proxemic costs and learned follow proposers
rank and suggest; they never clear a person-stop.
