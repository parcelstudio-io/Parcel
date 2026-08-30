# T1 · NAV-INT-1 tier on the MERGED tree — W1's bar 2, re-measured (Opus executor)

**Card:** T1 (wave B, merged-tree NAV-INT-1 tier) · **Worktree:** `/home/jaewoo-jang/.cache/parcel-0e/wb/gate`
(HEAD `c96ac34` + W1 + W2 + W3 + W4 incl. F4/F5 + W6, merged and proven by M1: 671 passed).
**Spend:** $0.00 hosted, no network, no LLM (`use_llm=False`). **No pytest. No `ci_gate.py`. Physical motion: NO-GO.**

**Mandate:** RUN and REPORT only. No source, test, eval or config file in the gate worktree was edited
by this card (W5 is generating frozen artifacts in the same tree concurrently). `git` was never written to.
The only main-repo path this card writes is **this file**.

---

## 0 · Pre-flight (recorded before the first sim)

| fact | value |
|---|---|
| `parcel_robot.__file__` | `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py` — the GATE worktree |
| interpreter | `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/.parcel/bin/python` (the symlinked project venv) |
| env, every shell | `PYTHONPATH=$PWD/src:$PWD`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset, `PARCEL_MEMORY_PURPOSE` unset |
| `uptime` at start (09:44 EDT) | load average **2.04, 2.00, 2.11** on 192 cores — clear; W5's panel/matrix runs share the host |
| sims running before launch | exactly one: pid 807004, the OWNER's `/tmp/parcel_sim.sock` — never touched |
| `NI1_WORKDIR` | `/home/jaewoo-jang/.cache/parcel-0e/wb/t1-sock/` (this card's own AF_UNIX root; longest socket path 54 B, cap 108) |
| `NI1_OUT_PREFIX` | `m1-merged-` → outputs land as `research/20260829/nav-interrupt-1/m1-merged-*` |
| `PARCEL_MEMORY_PATH` | `<NI1_WORKDIR>/memory{N}.sqlite3` (set by `harness.py` from `NI1_WORKDIR`); the owner's `parcel_memory.sqlite3` is never opened |
| recorded artifacts | `controls.jsonl` / `sequence_controls.jsonl` / `episodes.jsonl` / `results.json` / `sample_episode.txt` are **not written to** |

**Command (verbatim), started 2026-08-30 09:46:36 EDT:**

```bash
cd /home/jaewoo-jang/.cache/parcel-0e/wb/gate
export PYTHONPATH=$PWD/src:$PWD MUJOCO_GL=egl OPENBLAS_NUM_THREADS=32; unset TMPDIR
NI1_WORKDIR=/home/jaewoo-jang/.cache/parcel-0e/wb/t1-sock/ NI1_OUT_PREFIX=m1-merged- \
  .parcel/bin/python research/20260829/nav-interrupt-1/run.py --all --seed 20260829
```

### Frozen inputs, hashed before the run

| file | sha256 | vs W1's run |
|---|---|---|
| `gold_blind.json` | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` | **unchanged — the card's pinned value**, and equal to `gold_blind.sha256` |
| `interrupt_tier_v1.json` | `23466d5ff9e4452e38f0da7f82fcc53019f16efed55208faf191845c33dce541` | unchanged (the episode SET has not moved) |
| `queue_policy.py` | `d56c39e83cdb9b93d3ed51705abac4444d01a16ff53cb52272c5a64cd9c40724` | unchanged (issue door + steering classifier) |
| `harness.py` | `3b040e7e8e4082aea57d33b5764d6d7cb883ba041662e42f7a6ae4ad101a09ec` | **moved** — W4-F1's `GoalSpec._region_for` band ∩ support fix (W1 ran `cf3ccd2e…`) |
| `run.py` | `fab00962dd49357192b274f6a9f5325e08790824cb346cef1bcc745da96c5818` | **moved** — W1's `_false_arrival_in_window` revision-aware predicate + W4's `NI1_WORKDIR`/`NI1_OUT_PREFIX` overrides, merged |

### Build under test (git hash-object, gate worktree, at launch)

| file | blob |
|---|---|
| `src/parcel_robot/runtime.py` | `39ebf4a75bed3b7e8fb5ce297c31eeee3b966b5a` |
| `src/parcel_robot/brain/plan_queue.py` | `c1bcdb6e755bd16f03f5d4c24047eeba1d104967` |
| `src/parcel_robot/brain/executive.py` | `aaba3745779fe0ff88a3737f1ba33e0ebb9b1bb8` |
| `src/parcel_robot/instructnav/scoring.py` | `aa876aa043f2e2a044042559f42de28a03ab6a8e` |
| `src/parcel_robot/navigation/pipeline.py` | `2f24104734be1b7286b1751f3743cd7c34cc354d` |
| `src/parcel_robot/navigation/poi_admission.py` | `dd9242afddaf906b29dc9b8f67e9a10bc248be8e` |
| `src/parcel_robot/perception/city_semantics.py` | `473c42f84b7de39a7c5235c0363a88ad90cb3df8` |
| `src/parcel_robot/simulation/headless_city.py` | `94c8cf6294b96d5903320fc4ca15d3e5683bf3c7` |
| `src/parcel_robot/voice/agent.py` | `d34866684417e246c56258d2261a8fd8e520d3cd` |

---

## 1 · Metric definitions reproduced before the run (no criterion moved)

Every derived statistic in §3 was first **reproduced bit-for-bit against W1's own artifacts**
(`~/.cache/parcel-0e/wb/w1-out/`) so the merged-tree number is computed by the same rule W1 was judged by.

| statistic | rule | W1's published value | reproduced here |
|---|---|---|---|
| from-rest floor, per goal | control `leg.path_m ÷ leg.shortest_m`, mean over the goal's 2 reps | median over all 10 controls = **1.280** | **1.2797** ✓ |
| bar-3 population | `both_reachable`: rows with a re-issue whose goal 1 (and, unless `hold`, goal 2) verified BOTH authorities from rest | n = **12** with a ratio | **12** ✓ |
| resume/from-rest quotient, all rows | `path_ratio_oracle ÷ mean(floor(g1), floor(g2))`; hold rows use `floor(g1)` alone | mean **1.5809**, median 1.5251 | **1.5809 / 1.5251** ✓ |
| quotient vs the single median floor | `path_ratio_oracle ÷ 1.2797` | mean **1.3518** | **1.3518** ✓ |
| **hold-row quotient** | `path_ratio_oracle ÷ floor(g1)` on `hold` rows only | mean **0.9801** (0.999 / 0.938 / 1.003) | **0.98007** ✓ |

**The two-leg oracle (integrator's refinement), stated.** parcel-6c's lens asks for resume rows to be
priced against a *two-leg* reference (goal 1 → goal 2 → goal 1) rather than N8's straight line. The tier
already records that reference and it needs no new geometry: the **10 from-rest SEQUENCE CONTROLS** are
the stack executing `seq-<goal 2>-then-<goal 1>` uninterrupted from rest — exactly the two legs an
admitted amendment demands, in the order it demands them, with the interruption removed. So

> **two-leg-oracle ratio = `episode.total_path_m ÷ sequence_control["seq-<g2>-then-<g1>"].total_path_m`**

which is `run.py`'s own `path_ratio_vs_measured_sequence` (aggregate line ~1687), reported here on the
same `both_reachable` population and again restricted to the **resume rows only** (`amended_goal` label).
A straight-line variant (`total_path ÷ [d(start→goal 2) + d(goal 2 end→goal 1)]`, i.e. N8 with the
pre-interruption travel credit removed) is reported beside it as a cross-check. W1's published value of
the harness statistic on its own run: **1.088 (n = 13)**.

---

## 2 · RUN IN FLIGHT — this file is written incrementally

Started 09:46:36 EDT. Expected wall ≈ 1–2.5 h (10 controls + 10 sequence controls + 40 episodes,
one simulator at a time). Bars land in §3 as they are measured.

### Live observation already recorded (controls stage)

* `ctl-bench#0/1` → `sys=False scorer=False cat=agreement dtg=0.241 / 0.244`.
  **W4's arrival authority survives the merge on the bench**: at HEAD and under W1-alone these two legs
  read `sys=False scorer=True cat=authority_disagreement`. The scorer has stopped certifying the road.
* `ctl-lamppost#0` → `sys=False scorer=True cat=authority_disagreement dtg=0.0` — **a disagreement that
  exists in NEITHER parent** (HEAD: agreement; W1-alone: agreement; W4-alone: agreement). Flagged; the
  recorded refusal detail is read in §4 once the run finishes.

---

## FINDING F-T1-1 (live, 09:52 EDT) — F4's `LegIdentity` refuses the whole lamppost family, and W4's tier never saw F4

**What the merged tree measures on the from-rest controls:**

| control | HEAD-08-29 | W1-alone | W4-alone | **MERGED (T1)** | recorded refusal |
|---|---|---|---|---|---|
| `ctl-bench#0/1` | `sys=F scorer=T` **disagreement** | `sys=F scorer=T` **disagreement** | `sys=F scorer=F` agreement | **`sys=F scorer=F` agreement** dtg 0.241 / 0.244 | `semantic_arrival_verification_failed` |
| `ctl-come_here#0/1` | agreement ✓ | agreement ✓ | agreement ✓ | **agreement ✓** dtg 0.225 / 0.228 | `owner_follow_verified` |
| `ctl-sidewalk#0/1` | agreement ✓ | agreement ✓ | agreement ✓ | **agreement ✓** dtg 0.0 | `navigation_goal_verified` |
| **`ctl-lamppost#0/1`** | agreement ✓ | agreement ✓ | agreement ✓ | **`sys=F scorer=T` DISAGREE / tolerated** dtg 0.0 | **`arrival_receipt_for_another_place`** |
| **`ctl-towards_lamppost#0/1`** | agreement ✓ | agreement ✓ | agreement ✓ | **`sys=F scorer=T` tolerated_boundary** dtg 0.0 | **`arrival_receipt_for_another_place`** |

* **W4's band ∩ support authority survives the merge intact** — the bench legs read `agreement` at dtg 0.24, exactly W4-alone's 0.243/0.244. That half of W4 composes.
* **F4's `LegIdentity` does not.** Four legs that verified in *every* parent cell now fail on the product authority with F4's own refusal token, while the scorer puts the robot *inside* the committed region (`dtg = 0.0`) and `region_provenance` records `committed_entity_id_raw = lamp_post_1`, `scored_entity_id = lamp_post_1`, `region_source = committed_instance`. The scorer and the navigator agree about the place; only the receipt-vs-leg comparison disagrees.

**Why no earlier cell caught it — W4's tier is a MIXED BUILD, measured pre-F4.** The `--all` run that produced W4's `0/80` and `bench 0/29` started at ≈ **07:53:55** (wall 3478.7 s, finishing 08:51:54; its controls stage closed at **07:58:50**). F4 landed in that same worktree at **08:19:53** (`src/parcel_robot/runtime.py`) and **08:22:08** (`instructnav/arrival_receipt.py`, `tests/test_arrival_receipt_wiring.py`) — *after* the runner process had already imported both modules. The `RobotRuntime` (and therefore every F4 consumer) lives in that long-lived runner process, not in the per-episode sim subprocess, so **no episode of W4's tier ran F4's code**. Corroboration: the string `arrival_receipt_for_another_place` appears **0 times** in `w4-b32-episodes.jsonl` and `w4-b32-controls.jsonl`, and 4 times in the merged run's first 10 control legs.

**So T1 is the first tier measurement of F4 at all** — which is what a merged-tree headline instrument is for. W1's own build-freeze discipline ("one build produces every number on this card", W1_STATUS §"Build freeze") is exactly the rule that was not held on W4's F1 run.

**Mechanism (read-only, from the shipped code).** `runtime._cut_navigation_receipt` is called on **every** `_step_navigation` tick, not only at the terminal, and it does two things at once: it stamps the receipt from *this tick's* `mission.metadata`, and it calls `_navigation_leg_identity`, which **snaps `region_id` at the first tick that has any committed region and never moves it** (`if leg.region_id is None and region is not None: …`). `committed_region_id` reduces the committed `GoalRegion` to `anchor_entity or kind`. For a semantic object goal the pipeline rebuilds `arrival_goal_region` from the current `SemanticCandidate` each tick (`pipeline.py:3305`, `_build_arrival_goal_region(relation, result)`), so a lock-on that legitimately *refines* which instance it is tracking — and `lamppost` is the one goal in this scene with two instances, `lamp_post_1` / `lamp_post_2`, that the runtime path actually resolves through perception — changes the anchor after the snap. The terminal receipt then names the refined id, the frozen leg names the first one, and `receipt_refusal` returns `OTHER_PLACE`. The consequence is the inverse of the defect F4 was written for: F4 stops a receipt about `sidewalk_south` from verifying a leg issued to `sidewalk`, and in doing so also stops a receipt about `lamp_post_1` from verifying a leg that *is* about `lamp_post_1` but was first sighted as another instance. The exact pair of ids is measured in §4.

---

## 2b · How the run actually went (recorded, including the interruption)

| | |
|---|---|
| started | **09:46:36 EDT**, one process, `--all --seed 20260829` |
| 10 controls | 09:46:36 → 09:51:5x |
| 10 sequence controls | 09:51:5x → 10:01:5x |
| tier episodes `ni1-00 … ni1-38` | 10:01:5x → 10:46:5x, **0 errors** |
| **interruption** | at **10:53:41** the runner received **SIGTERM** from the session's background-task supervisor (a harness-side task timeout, not the experiment). `run.py`'s trap fired — `[teardown] signal 15; closing sims` — and an external `pgrep` immediately afterwards found **no sim of ours alive** (only the owner's pid 807004 on `/tmp/parcel_sim.sock`, untouched). `ni1-39` was in flight and was not written. |
| **resume, same build** | before resuming, all 11 product/harness blobs were re-hashed and are **byte-identical** to the launch table in §0 (`runtime.py 39ebf4a7…`, `harness.py 237a73bf…`, `run.py 4dbd4282…`, …). `--stage tier --offset 39 --limit 1` ran **10:54:59 → 10:55:42**, appending `ni1-39`; then `--stage sample --stage classifier --stage aggregate`. **One build produced every number on this card** (W1_STATUS's build-freeze rule, kept). |
| final counts | `controls 10 · sequence_controls 10 · tier_episodes 40 · tier_errors 0` |
| effective wall | ≈ **4085 s (68 min)**; `results.json`'s own `wall_s` is 0.0 because the aggregate ran in the short resume invocation — the true wall is the span above |
| orphan proof | both resume invocations printed `[N3 orphan check] clean=True ours=[] other_processes=[]`; external check after the SIGTERM: clean. **No orphan sims, at any point.** |
| the owner's stack | `/tmp/parcel_sim.sock` sim (pid 807004) alive and untouched throughout; `:8080` / `:8765` never contacted |
| recorded artifacts | `git status research/20260829/nav-interrupt-1/` shows **only** M1's own ` M harness.py` / ` M run.py` plus my five `?? m1-merged-*` files. `controls.jsonl` / `sequence_controls.jsonl` / `episodes.jsonl` / `results.json` / `sample_episode.txt` **untouched** |
| `gold_blind.json` at close | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` — **unchanged**, `blind_sha256_matches: true` |
| spend | **$0.00** — `local_plan_sketch`, `use_llm=False`, no hosted call |

---

## 3 · THE BARS ON THE MERGED TREE

Every cell is a real measured run of the same 40-episode tier. `HEAD-08-29` = the recorded baseline;
`W1-alone` = `~/.cache/parcel-0e/wb/w1-out/results.json`; `W4-alone` = `w4-b32-results.json`;
`MERGED(T1)` = `m1-merged-results.json`.

| # | row | bar | HEAD-08-29 | W1-alone | W4-alone | **MERGED (T1)** | verdict |
|---|---|---|---|---|---|---|---|
| 1 | instruction admission | ≥ 0.9 | 24/32 = 0.7500 | 31/32 = 0.9688 | 24/32 = 0.7500 | **31/32 = 0.9688** | **GREEN** — W1's plan queue survives the merge exactly |
| 1b | — by family | — | amend_cue 7/14 · explicit 14/14 · hold 3/4 | 14/14 · 14/14 · 3/4 | 7/14 · 14/14 · 3/4 | **14/14 · 14/14 · 3/4** | identical to W1 |
| 1c | admission latency | — | — | — | — | p50 **14.9 ms** · p95 22.9 · max 27.4; **31/31 within 1000 ms** | GREEN |
| **2** | **amended success, BOTH authorities** | **≥ 0.8** | 11/28 = 0.3929 | **21/28 = 0.7500** | 14/28 = 0.5000 | **16/28 = 0.5714** | **RED — and it moved the WRONG WAY vs W1** (see §4) |
| 2b | amended success, scorer (K0) only | — | 14/28 = 0.5000 | 24/28 = 0.8571 | 14/28 = 0.5000 | **21/28 = 0.7500** | |
| 2c | amended success, system only | — | 14/28 = 0.5000 | 21/28 = 0.7500 | 14/28 = 0.5000 | **16/28 = 0.5714** | |
| 2d | by goal 2 | — | bench 0/7 · come_here 3/9 · lamppost 3/3 · sidewalk 1/5 · tw_lamppost 4/4 | bench 0/7 · **9/9** · 3/3 · **5/5** · 4/4 | bench 0/7 · 3/9 · 3/3 · 4/5 · 4/4 | bench **0/7** · come_here **9/9** · lamppost **1/3** · sidewalk **4/5** · tw_lamppost **2/4** | the entire regression vs W1 is lamppost −2, tw_lamppost −2, sidewalk −1 |
| 3 | resume path ratio vs the straight-line oracle (N8) | ≤ 1.1× | 1.4905 (n=8) | 1.7299 (n=12) | 1.4875 (n=8) | **1.7225 (n=5)**, p50 1.838 p95 2.254 | **RED as written** — unchanged in character from W1; the population collapsed 12 → 5 (see §3a) |
| 3b | **hold-row resume/from-rest quotient** | ≤ 1.1 (next-tier) | 0.9771 (3 rows) | 0.9801 (3 rows) | 0.9778 (3 rows) | **0.9687** (2 rows: 0.9998, 0.9375) | **GREEN** — parking is still free; the third hold row (`ni1-39`) left the population because `towards_lamppost` no longer verifies from rest |
| 3c | **resume rows vs the TWO-LEG oracle** | ≤ 1.2 (parcel-6c) | not computable (baseline wrote only 5 sequence controls, all `-then-bench`) | 1.3728 (n=8) | 1.4675 (n=3) | **1.0790 (n=3)**: 1.0739 / 1.1323 / 1.0309 | **GREEN** |
| 3d | two-leg ratio, all `both_reachable` rows | — | — | 1.0880 (n=13) | 0.8980 (n=9) | **0.8411 (n=5)** | |
| 4a | owner-referring amendments admit | 6/6 | 0/6 | 6/6 | 0/6 | **6/6** | **GREEN** |
| 4b | held queue utterance admits after cue-stripping | 8/8 | 0 legs stripped | 8/8 | 8/8 | **8/8 legs cue-stripped, 8/8 admitted work** | **GREEN** |
| 5 | return rate | — | 8/9 = 0.8889 | 13/13 = 1.0000 | 9/9 = 1.0000 | **5/5 = 1.0000** (scorer-only, same 5 rows: 5/5) | GREEN on rate; the denominator collapsed with the reachable set |
| 6 | refused-and-continued (`goal_1_continued`) | 0 | 7 | 0 | 7 | **0** | **GREEN** |
| 7 | terminal false arrivals (amended leg) | 0 | 3 | 0 | 0 | **0** | **GREEN** |
| 8 | switch-window false arrivals (W1's revision-aware predicate) | 0 | 0 | 3 measured / **0** re-scored | 1 | **0** | **GREEN — measured LIVE.** The merged `run.py` carries W1's revision-aware `_false_arrival_in_window`, so `results.json` is already the corrected number; **no offline re-score was needed and none was done** |
| 9 | **authority disagreements** | **≤ 2/80** | 17/80 | 9/85 | **0/80** | **7/85** strict (`system_failed_but_arrived` 7 + `system_succeeded_but_not_arrived` 0); **20/85** if `tolerated_boundary` (13) is counted as W4 counted `n − agreement` | **RED** |
| 10 | **bench `system_failed_but_arrived`** | **0/29** | 11/29 | 9/28 | **0/29** | **0/28** | **GREEN — W4's B32 band ∩ support authority composes cleanly.** (Denominator 28 not 29 for the same reason as W1-alone: the plan queue changes the leg mix.) |
| 11 | collisions, switch window (sim flag / clearance ≤ 0) | 0 | 0 / 0 | 0 / 0 | 0 / 0 | **0 / 0** | **GREEN** |
| 11b | min clearance, switch window | — | 0.8294 m | 0.8258 m | 0.8316 m | **0.8233 m** | |
| 11c | collisions, whole episode (all 40) | 0 | 0 | 0 | 0 | **0** | **GREEN** |
| 11d | min clearance, whole episode | — | 0.6580 m | 0.6593 m | 0.6591 m | **0.6494 m** | |
| 12 | H-NI1c blind classifier, 110 cases | port exact | 0.8273 | 0.8273 | 0.8273 | **0.8273** (91/110; revise .900 / keep .933 / queue .667 / clarify .800) | **GREEN — bit-identical across all four cells** |
| 13 | `gold_blind.json` sha256 | `c253df2f…` unchanged | ✓ | ✓ | ✓ | **✓ `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`, `blind_sha256_matches: true`** | **GREEN** |

### 3a · Why bar 3's population collapsed 12 → 5 (stated, not moved)

`run.py`'s `both_reachable` filter keeps only rows whose goals verified **both authorities from rest**
("a goal that never verifies from rest cannot be a fair test of the queue policy"). On the merged tree
the from-rest controls read `both = {bench 0, come_here 2, lamppost 0, sidewalk 2, towards_lamppost 0}` —
**`lamppost` and `towards_lamppost` dropped out of the reachable set**, for the reason in §4, taking 7
rows of bar 3's population with them. So bar 3's mean (1.7225) is measured on 5 rows, not 12, and is
**not** a like-for-like comparison with W1's 1.7299. The three refined statistics (3b, 3c, 3d) are the
ones that carry information here, and all three are green.

### 3b · The two-leg oracle, as computed

`two-leg ratio = episode.total_path_m ÷ sequence_control["seq-<goal 2>-then-<goal 1>"].total_path_m` —
the stack executing the same two goals, in the same order, uninterrupted from rest. This is `run.py`'s
own `path_ratio_vs_measured_sequence`; nothing new was written. On the merged tree the three resume
rows read **1.0739 / 1.1323 / 1.0309, mean 1.0790** — i.e. an interrupted-and-resumed two-goal
mission costs **8 % more path than the same two goals done straight through**, against a proposed bar
of 1.2. Together with the hold-row quotient (0.969) this is the direct answer to the question bar 3
was written to ask: *resume is not a re-issue, and the queue adds no measurable path overhead.*

A straight-line variant was computed as a cross-check —
`total_path ÷ [d(start → goal 2) + d(goal 2 end → goal 1)]`, i.e. N8 with the pre-interruption travel
credit removed — and is reported as **uninformative rather than green**: it reads 2.54 on W1's data
because `come_here`'s anchor is the *moving owner*, who walks toward the dog, so its straight-line
denominator collapses toward zero. The measured-sequence denominator does not have that failure mode,
which is why it is the one quoted above.

---

## 4 · FINDING F-T1-1, closed: F4 discards receipts that say `arrived_verified`

**The measurement (live, on the merged tree, single sim, own socket root — the diagnostic drives
`RobotRuntime.handle_text` and samples `runtime._navigation_leg` / `runtime._navigation_receipt`; it
edits nothing):**

```
=== lamppost: 'go to the lamppost'
  t      leg (goal_id, seq, region_id)                receipt (goal_id, seq, region_id, claimed, inside, support_ok, settled, reason)
  0.2s   ('go to the lamppost', 1, None)              (..., '',            False, None,  True,  False, 'no_system_arrival_claim')
  4.2s   ('go to the lamppost', 1, 'lamp_post_2')     (..., 'lamp_post_2', False, False, False, False, 'no_system_arrival_claim')
 19.8s   ('go to the lamppost', 1, 'lamp_post_2')     (..., 'lamp_post_1', False, False, False, False, 'no_system_arrival_claim')
 38.0s   ('go to the lamppost', 1, 'lamp_post_2')     (..., 'lamp_post_1', True,  True,  True,  True,  'arrived_verified')
```

(`walk towards the lamppost` reproduces the same shape: snap `lamp_post_2` at 4.0 s, refine to
`lamp_post_1` at 13.2 s, `arrived_verified` at 20.2 s.)

**Read the last line.** The receipt's own verdict is **`arrived_verified`** — the system claimed,
the pose is inside the committed region, the support clearance passes, the loop settled. Every
component of B32's authority says the dog arrived. It is then thrown away by one comparison:
`receipt.region_id ('lamp_post_1') != leg.region_id ('lamp_post_2')` → **`arrival_receipt_for_another_place`**.

**Why the two ids differ.** `runtime._cut_navigation_receipt` runs on **every** `_step_navigation`
tick, and `_navigation_leg_identity` snaps `region_id` at the **first tick that has any committed
region** and never moves it. At 4.2 s perception's first answer for "the lamppost" is `lamp_post_2`;
by 19.8 s the lock-on has **refined** to the instance it is actually driving to, `lamp_post_1`
(`pipeline._lock_on_view_candidate`'s documented behaviour — "keeps a lock-on REFINING one instance").
F4 froze the first sighting and then reads the refinement as going to a different place.

**It never went anywhere else.** Across all 24 legs carrying the refusal, `region_provenance` records
`committed_entity_id_raw == scored_entity_id` in **every single case**
(`lamp_post_1 → lamp_post_1` ×21, `sidewalk_south → sidewalk_south` ×2, one owner-anchored row), with
`region_source: committed_instance` and `distance_to_goal_m = 0.0`, and the independent K0 scorer says
**arrived on 23 of the 24**. The refusal is a false negative of the leg-identity comparison alone.

**Blast radius, by goal:** lamppost 9 legs · towards_lamppost 12 · sidewalk 2 · hold 1 = **24**.
Both sidewalk cases (`ni1-09`, `ni1-20`) committed AND were scored on `sidewalk_south`; the directive
named the *label* "the sidewalk", which C7-F1's own provenance rule calls a legitimate referent
("an instance carrying the goal's label is a legitimate referent"). **F4 conflates "refined to another
instance of the same label" with "went to the wrong place"** — and B-09's real defect (a directive that
meant the north sidewalk) is a *label* question F4's first-sighting snapshot cannot answer either.

### The counterfactual, exactly

The gap between bar 2's two readings is **5 amended legs, and all 5 are this defect**:

| episode | goal 2 | detail | dtg | committed → scored | `region_source` |
|---|---|---|---|---|---|
| `ni1-06-bench-lamppost` | lamppost | `arrival_receipt_for_another_place` | 0.0 m | `lamp_post_1` → `lamp_post_1` | `committed_instance` |
| `ni1-07-bench-lamppost` | lamppost | `arrival_receipt_for_another_place` | 0.0 m | `lamp_post_1` → `lamp_post_1` | `committed_instance` |
| `ni1-09-bench-sidewalk` | sidewalk | `arrival_receipt_for_another_place` | 0.0 m | `sidewalk_south` → `sidewalk_south` | `committed_instance` |
| `ni1-14-bench-towards_lamppost` | towards_lamppost | `arrival_receipt_for_another_place` | 0.0 m | `lamp_post_1` → `lamp_post_1` | `committed_instance` |
| `ni1-15-bench-towards_lamppost` | towards_lamppost | `arrival_receipt_for_another_place` | 0.0 m | `lamp_post_1` → `lamp_post_1` | `committed_instance` |

**Remove this one false refusal and bar 2 reads 21/28 = 0.7500 — W1's exact number** (its scorer-only
row, 21/28, already is that number). The bar's remaining shortfall would again be **`bench 0/7`** and
nothing else. **No criterion was moved and no number here is a projection of a fix: 16/28 is what the
merged tree measures, and 21/28 is the independent K0 authority's reading of the same 28 legs.**

### Why nobody saw this before T1 — W4's tier is a mixed build

The `--all` run behind W4's published `0/80` and `bench 0/29` started at ≈ **07:53:55** and its
controls stage closed at **07:58:50**. F4 landed in that worktree at **08:19:53**
(`src/parcel_robot/runtime.py`) and **08:22:08** (`instructnav/arrival_receipt.py`,
`tests/test_arrival_receipt_wiring.py`) — after the runner process had already imported both modules.
The `RobotRuntime` and every F4 consumer live in that long-lived runner process (the per-episode
subprocess is only `parcel_robot.sim`), so **no leg of W4's tier executed F4's code**. Corroboration:
`arrival_receipt_for_another_place` appears **0 times** in `w4-b32-episodes.jsonl` and
`w4-b32-controls.jsonl`, and **24 times** in the merged run. F4's four wiring cells all hand the
consumer a leg whose `region_id` was set by the test, so none of them exercises the *snapshot timing*
that is the actual defect. **T1 is the first tier measurement of F4 at any scale.**

W1's build-freeze rule — "*one build produces every number on this card*", enforced there by
discarding two partly-run tiers — is exactly the rule that was not held on W4's F1 run. Recorded as a
process finding, not only a code one.

### What this does NOT say

* **W4's B32 band ∩ support authority is not implicated and composes cleanly**: bench
  `system_failed_but_arrived` **0/28**, bench controls `sys=False scorer=False cat=agreement` at
  dtg 0.241 / 0.244 (W4-alone: 0.243 / 0.244). The scorer has stopped certifying the road, and the
  honest failure is still scored as a failure.
* **W1's plan queue is not implicated**: admission 31/32, amend_cue 14/14, owner-referring 6/6,
  cue-stripped re-issues 8/8, refused-and-continued 0, terminal false arrivals 0, switch-window false
  arrivals 0 — every one of W1's own rows reproduces on the merged tree.
* The defect is **not** "F4 is wrong to check the place". It is that the expected `region_id` is
  captured at the *first sighting* rather than at the commitment the directive is about. A fix is the
  integrator's/W4's call, not this card's; the shape the evidence points at is to snap the leg's region
  when the mission's instance selection settles (or to compare on the goal's **label**, the rule
  `region_provenance` already uses), never inside T1's read-only mandate.

---

## 5 · Output file list

All five are **new, untracked** files inside the gate worktree at
`/home/jaewoo-jang/.cache/parcel-0e/wb/gate/research/20260829/nav-interrupt-1/`:

| file | bytes | what |
|---|---|---|
| `m1-merged-results.json` | 43,039 | every headline number (`h_ni1a`, `h_ni1b`, `h_ni1c`, `authority_disagreement`, `orphan_check`) |
| `m1-merged-episodes.jsonl` | 383,749 | 40 episodes, 0 errors — full receipt timelines, 1 Hz tracks, switch windows, queue logs, `region_provenance` |
| `m1-merged-controls.jsonl` | 29,890 | 10 from-rest controls |
| `m1-merged-sequence_controls.jsonl` | 57,497 | 10 from-rest two-leg sequence controls (the two-leg oracle) |
| `m1-merged-sample_episode.txt` | 2,946 | one episode printed end to end |

Scratch (not in any repo): `/tmp/claude-1000/…/scratchpad/t1/` — `tier.log`, `tier_resume.log`,
`tier_aggregate.log`, `bars_t1.py` (the four-cell comparison), `diag_leg.py` (the §4 diagnostic).
Socket root `/home/jaewoo-jang/.cache/parcel-0e/wb/t1-sock/`, diagnostic root `…/wb/t1-diag/`.

**Nothing in the main repo was written except this file. `git` was never written to. No pytest, no
`ci_gate.py`, no watcher left running, no orphan sim, $0.00.**

---

## 6 · Summary for the integrator

1. **Bar 2 (the reason this card exists) is 16/28 = 0.5714 — RED, and BELOW W1-alone's 21/28.** The
   expectation that W4's arrival authority would let the bench legs verify **did not hold and could not
   have**: B32 makes the scorer *stop certifying* unstandable ground, so bench moved from
   `system_failed_but_arrived` to honest `agreement` at dtg 0.24 — the dog still does not reach
   standable ground at the bench (bench controls `success_both` 0/2, as W4 itself reported). Bench is
   **0/7** in every cell.
2. **The regression from 21/28 to 16/28 is one defect, F4's, on 5 legs, fully diagnosed in §4** — a
   receipt reading `arrived_verified` is discarded because the leg froze the *first sighted* instance
   id. Fix it and bar 2 returns to exactly 21/28 = 0.7500, W1's number, still RED against 0.8 with
   `bench 0/7` as the only remaining shortfall — i.e. **the pre-registered ceiling W1 recorded is
   confirmed on the merged tree, not beaten**.
3. **W4's authority bar is RED on the merged tree: 7/85 strict (20/85 counting `tolerated_boundary`)
   against ≤ 2/80** — entirely the same F4 defect (lamppost 3 + sidewalk 2 + towards_lamppost 2). Its
   companion bar, **bench `system_failed_but_arrived` 0/28, is GREEN**.
4. **Everything else on the merged tree is green and matches or beats its parents**: admission 0.9688,
   the two live-defect rows 6/6 and 8/8, refused-and-continued 0, terminal false arrivals 0,
   switch-window false arrivals 0 (measured live under W1's revision-aware predicate — no re-score),
   collisions 0/0 everywhere, min clearance 0.6494 m whole-episode / 0.8233 m in-window, classifier
   0.8273 bit-identical, `gold_blind.json` unmoved.
5. **Bar 3 as written stays RED (1.7225) and MET on intent, now with three independent readings**:
   hold-row quotient **0.969**, resume rows vs the two-leg oracle **1.079** (bar 1.2), all
   `both_reachable` rows vs the two-leg oracle **0.841**. Its population fell 12 → 5 as a *consequence*
   of the F4 defect (lamppost and towards_lamppost stopped verifying from rest), so the mean is not
   comparable to W1's; the three refined statistics are.
6. **Process finding: W4's F1 tier was a mixed build and never ran F4.** Any wave-B artifact generated
   by a long-lived runner process must re-verify its blobs at the end of the run, not only at the start.

---

# Re-run after F7

**Why this section exists.** AUDIT_T1 accepted T1's measurement but recorded that it ran on a tree
**without W4-F7**, and that its headline (bar 2 = 16/28) was depressed by defect **F-T1-1**. F7 landed;
this section is the **same tier, same seed, same recipe**, re-run so the committed state's numbers are
the tested state's numbers — plus the by-name re-score AUDIT_T1 required.

**Mandate unchanged: RUN and REPORT only.** No source, test, eval or config file was edited by this
re-run (W5 is finishing F1 in `scripts/`, `evals/nav_instruct/`, `tests/` in the same tree). `git` was
never written to. The only main-repo path written is this file.

## R0 · Patch-stack stamp and pre-flight

| fact | value |
|---|---|
| **patch-stack stamp at START** | **`bfc72ae269a2cce52fa5b4a028750b6420afe4f1288e751e2379b522f8c8b539`** — matches the dispatch stamp `bfc72ae2…` exactly |
| stamp recipe | `(git diff; git ls-files --others --exclude-standard \| grep -v '^\.parcel' \| sort \| while read f; do sha256sum "$f"; done) \| sha256sum` in the gate worktree |
| `parcel_robot.__file__` | `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py` — the GATE worktree |
| interpreter | `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/.parcel/bin/python` (the symlinked project venv) |
| env, every shell | `PYTHONPATH=$PWD/src:$PWD`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset, `PARCEL_MEMORY_PURPOSE` unset |
| `uptime` at start (11:14 EDT) | load average **1.55, 1.90, 1.91** on 192 cores — clear |
| sims running before launch | exactly one: pid 807004, the OWNER's `/tmp/parcel_sim.sock` — never touched; `:8765` (owner panel) and `:8080` (llama-server) never contacted |
| `NI1_WORKDIR` | `/home/jaewoo-jang/.cache/parcel-0e/wb/t1f7-sock/` — this re-run's OWN socket root, distinct from T1's `t1-sock/` |
| `NI1_OUT_PREFIX` | `m1-merged-f7-` → outputs `research/20260829/nav-interrupt-1/m1-merged-f7-*`; **T1's `m1-merged-*` are not overwritten** |
| `PARCEL_MEMORY_PATH` | `<NI1_WORKDIR>/memory{N}.sqlite3` (set by `harness.py`); the owner's `parcel_memory.sqlite3` is never opened |
| per-sim containment | `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`, one sim at a time (harness.py:476-483) |

**Command (verbatim), started 2026-08-30 11:16:01 EDT:**

```bash
cd /home/jaewoo-jang/.cache/parcel-0e/wb/gate
export PYTHONPATH=$PWD/src:$PWD MUJOCO_GL=egl OPENBLAS_NUM_THREADS=32; unset TMPDIR
NI1_WORKDIR=/home/jaewoo-jang/.cache/parcel-0e/wb/t1f7-sock/ NI1_OUT_PREFIX=m1-merged-f7- \
  .parcel/bin/python research/20260829/nav-interrupt-1/run.py --all --seed 20260829
```

Launched under `setsid` so a session background-task timeout cannot SIGTERM the runner the way it
interrupted T1 at episode 39/40. (T1's resume was legitimate and proven; avoiding the interruption
outright is strictly better evidence.)

### R0a · Build under test — what MOVED since T1's run

`git hash-object`, gate worktree, at launch. **F7's footprint is exactly the two arrival-identity files.**

| file | T1's run | **this re-run** | |
|---|---|---|---|
| `src/parcel_robot/runtime.py` | `39ebf4a75bed3b7e8fb5ce297c31eeee3b966b5a` | **`319c93d7ffa8364fdc31703f6a07ff0e2daea40d`** | **MOVED — F7** |
| `src/parcel_robot/instructnav/arrival_receipt.py` | (not recorded by T1) | **`fe0cfc6cbe6ffa3a414a88b99bfc0d455b649b74`** | F7's `committed_region_ids` / `commitment_index` |
| `src/parcel_robot/simulation/headless_city.py` | `94c8cf6294b96d5903320fc4ca15d3e5683bf3c7` | **`17e6d5c23596c47dfe7158faa7d8973b6c124391`** | **MOVED** — W4's venue now carries the typed receipt + `LegIdentity` |
| `src/parcel_robot/brain/plan_queue.py` | `c1bcdb6e755bd16f03f5d4c24047eeba1d104967` | `c1bcdb6e755bd16f03f5d4c24047eeba1d104967` | unchanged |
| `src/parcel_robot/brain/executive.py` | `aaba3745779fe0ff88a3737f1ba33e0ebb9b1bb8` | `aaba3745779fe0ff88a3737f1ba33e0ebb9b1bb8` | unchanged |
| `src/parcel_robot/instructnav/scoring.py` | `aa876aa043f2e2a044042559f42de28a03ab6a8e` | `aa876aa043f2e2a044042559f42de28a03ab6a8e` | unchanged |
| `src/parcel_robot/navigation/pipeline.py` | `2f24104734be1b7286b1751f3743cd7c34cc354d` | `2f24104734be1b7286b1751f3743cd7c34cc354d` | unchanged |
| `src/parcel_robot/navigation/poi_admission.py` | `dd9242afddaf906b29dc9b8f67e9a10bc248be8e` | `dd9242afddaf906b29dc9b8f67e9a10bc248be8e` | unchanged |
| `src/parcel_robot/perception/city_semantics.py` | `473c42f84b7de39a7c5235c0363a88ad90cb3df8` | `473c42f84b7de39a7c5235c0363a88ad90cb3df8` | unchanged |
| `src/parcel_robot/voice/agent.py` | `d34866684417e246c56258d2261a8fd8e520d3cd` | `d34866684417e246c56258d2261a8fd8e520d3cd` | unchanged |
| `research/…/harness.py` | `237a73bf457af87286501758490e0112f0cde31d` | `237a73bf457af87286501758490e0112f0cde31d` | unchanged |
| `research/…/run.py` | `4dbd4282d8e5c9f24c7043ce96e547e0932e4348` | `4dbd4282d8e5c9f24c7043ce96e547e0932e4348` | unchanged |
| `research/…/queue_policy.py` | `b72a19e8e78e5dda3771ac4c953dd36b9be19f05` | `b72a19e8e78e5dda3771ac4c953dd36b9be19f05` | unchanged |

**The instrument did not move.** `harness.py`, `run.py` and `queue_policy.py` are byte-identical to
T1's run, so every difference below is the product's, not the measurement's.

### R0b · Frozen inputs, re-hashed (sha256) — all UNCHANGED vs T1

| file | sha256 | |
|---|---|---|
| `gold_blind.json` | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` | **the card's pinned value**, and equal to `gold_blind.sha256` |
| `interrupt_tier_v1.json` | `23466d5ff9e4452e38f0da7f82fcc53019f16efed55208faf191845c33dce541` | the episode SET has not moved |
| `queue_policy.py` | `d56c39e83cdb9b93d3ed51705abac4444d01a16ff53cb52272c5a64cd9c40724` | unchanged |
| `harness.py` | `3b040e7e8e4082aea57d33b5764d6d7cb883ba041662e42f7a6ae4ad101a09ec` | unchanged |
| `run.py` | `fab00962dd49357192b274f6a9f5325e08790824cb346cef1bcc745da96c5818` | unchanged |

### R0c · How the by-name re-score is computed (stated before the numbers)

A **leg** is one scored navigation-leg record; its terminal outcome is the leg's `details`, which is
exactly its terminal receipt `detail` (verified against the `receipts` timeline). The census enumerates
every leg in all three leg-bearing artifacts — `controls` (`ctl-<goal>#<rep>`), `sequence_controls`
(`<control_id>::first|second`) and `episodes` (`<episode_id>::amended_goal|reissue`), 109 legs.

**Validated against T1 before use:** run on T1's own artifacts it returns **24 legs** carrying
`arrival_receipt_for_another_place`, split **lamppost 9 · towards_lamppost 12 · sidewalk 2 · hold 1** —
reproducing T1 §4's published blast radius exactly. The same census is then run on the F7 artifacts.
The four-cell bar table is produced by **T1's own `bars_t1.py`, unmodified except for a fifth cell**
pointing at `m1-merged-f7-*`, so no statistic is recomputed by a new rule.

*(Run in flight — results land below.)*

## R1 · Live observation, controls stage — F7 fixes the lamppost family at the first opportunity

The from-rest controls are the cell where F-T1-1 was first seen. Recorded as measured, before the tier:

| control | T1 (pre-F7) | **this re-run (post-F7)** | |
|---|---|---|---|
| `ctl-bench#0/1` | `sys=F scorer=F` agreement, dtg 0.241 / 0.244, `semantic_arrival_verification_failed` | **`sys=F scorer=F` agreement, dtg 0.241 / 0.241, `semantic_arrival_verification_failed`** | unchanged — B32's honest bench strip survives F7 |
| `ctl-come_here#0` | `sys=T scorer=T` agreement, dtg 0.225, `owner_follow_verified` | **`sys=F scorer=F` agreement, dtg 3.218, `owner_follow_verified`** | **moved** — still `agreement`; the owner-anchored goal is the one moving target in the scene (see R3 note) |
| `ctl-come_here#1` | `sys=T scorer=T` agreement, dtg 0.228 | **`sys=T scorer=T` agreement, dtg 0.228** | unchanged |
| **`ctl-lamppost#0`** | `sys=F scorer=T` **authority_disagreement**, `arrival_receipt_for_another_place` | **`sys=T scorer=T` agreement, dtg 0.0, `navigation_goal_verified`** | **F-T1-1 FIXED** |
| **`ctl-lamppost#1`** | `sys=F scorer=T` **tolerated_boundary**, `arrival_receipt_for_another_place` | **`sys=T scorer=T` agreement, dtg 0.0, `navigation_goal_verified`** | **F-T1-1 FIXED** |
| `ctl-sidewalk#0/1` | `sys=T scorer=T` agreement, dtg 0.0 | **`sys=T scorer=T` agreement, dtg 0.0** | unchanged |
| **`ctl-towards_lamppost#0`** | `sys=F scorer=T` **tolerated_boundary**, `arrival_receipt_for_another_place` | **`sys=T scorer=T` agreement, dtg 0.0, `navigation_goal_verified`** | **F-T1-1 FIXED** |
| **`ctl-towards_lamppost#1`** | `sys=F scorer=T` **tolerated_boundary**, `arrival_receipt_for_another_place` | **`sys=T scorer=T` agreement, dtg 0.0, `navigation_goal_verified`** | **F-T1-1 FIXED** |

**All 10 from-rest controls, post-F7: `arrival_receipt_for_another_place` appears 0 times.** The
from-rest both-authority reachable set is now `{bench 0, come_here 1, lamppost 2, sidewalk 2,
towards_lamppost 2}` — **all four non-bench goals are back in it** (T1 had `lamppost 0` and
`towards_lamppost 0`), which is what restores bar 3's population.

The commitment chain does exactly what U32 specified: the terminal receipt, cut after perception's
lock-on refined `lamp_post_2 → lamp_post_1`, is now **in the leg's chain at the current commitment
index**, so it verifies — and `lamppost` re-enters the from-rest reachable set, which is what collapsed
bar 3's population to 5 in T1.

*(Tier in flight.)*

## R2 · Stamp discipline — the stamp MOVES during this run, and why that is not a build change

The dispatch stamp hashes **the tracked diff plus every untracked file's contents**. Two things
inside the gate worktree change that set while the tier runs, so a bit-identical end stamp was never
achievable — recorded here rather than glossed:

| # | what moves the stamp | mtime | enters stamp? | imported by the tier? |
|---|---|---|---|---|
| 1 | **this run's own outputs** `research/20260829/nav-interrupt-1/m1-merged-f7-*` | 11:17 → close | yes (new untracked files) | no — they are the output |
| 2 | **W5-F1, working concurrently**: `scripts/mutation_panel_mutations.py` (untracked) | **11:19:46** | yes | **no** — `grep -n mutation_panel research/20260829/nav-interrupt-1/*.py` → no match |
| 3 | **W5-F1**: `evals/nav_instruct/results/mutation_panel.json` (tracked, ` M`) | **11:17:09** | yes (via `git diff`) | **no** |
| — | `MUJOCO_LOG.TXT`, `logs/duplex/*.jsonl`, `.ruff_cache/`, `__pycache__/` | during run | **no — `git check-ignore` says IGNORED** | (the duplex logs are this runner's own) |

Both W5 files were written **after** this run's 11:16:01 launch, by the peer card the board says is
finishing F1 in `scripts/`, `evals/nav_instruct/` and `tests/`. Neither is on the tier's import path.

**So the stamp is not the invariant that matters here — the build is.** The invariant actually held,
and asserted at close in R6, is: **all 13 product + harness blobs are byte-identical from launch to
close**, which is W1's build-freeze rule ("one build produces every number") and the rule AUDIT_T1
demanded after W4's F1 tier turned out to be a mixed build. The stamp is reported at start and at
close with the drift attributed file-by-file, per the dispatch instruction.

*(Tier in flight.)*

## R3 · Note on `ctl-come_here#0` — a timing-staged row, not an F7 effect

`ctl-come_here#0` read `sys=T scorer=T dtg 0.225` in T1 and `sys=F scorer=F dtg 3.218` here. Recorded
as a difference and attributed, not smoothed over:

* The `come_here` goal anchors on the **owner**, and `run.py::stage_owner` walks him up the block with
  three `live.move_owner(1.0, 0.0)` calls separated by **wall-clock `time.sleep(1.0)`** (`run.py:375-387`).
  That staging is not seeded — it races the robot's approach — so this row's from-rest verdict is
  legitimately variable between runs under different host load. It is **not** on F7's code path.
* Both authorities **agree** (`sys=F scorer=F` → `agreement`), so the row creates **no** authority
  disagreement and cannot flatter or damage bar 9.
* `ctl-come_here#1` still verifies both authorities, so `come_here` **stays in the from-rest reachable
  set** and no `both_reachable` population depends on the difference.

## R4 · THE BARS AFTER F7 — every row, all five cells

**Every row in this table ran under patch stack `bfc72ae269a2cce5…`** (start stamp = dispatch stamp;
build freeze proven byte-identical at close, R6). One process, no interruption, no resume:
`controls 10 · sequence_controls 10 · tier_episodes 40 · tier_errors 0`, `wall_s 3735.8` (62.3 min).

`T1-postF7` is computed by **T1's own `bars_t1.py`**, unmodified except for a fifth cell.

| # | row | bar | HEAD-08-29 | W1-alone | W4-alone | T1 pre-F7 | **T1 post-F7** | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | instruction admission | ≥ 0.9 | 24/32 = 0.7500 | 31/32 = 0.9688 | 24/32 = 0.7500 | 31/32 = 0.9688 | **31/32 = 0.9688** | **GREEN** |
| 1b | — by family | — | 7/14 · 14/14 · 3/4 | 14/14 · 14/14 · 3/4 | 7/14 · 14/14 · 3/4 | 14/14 · 14/14 · 3/4 | **14/14 · 14/14 · 3/4** | identical to W1 |
| 1c | admission latency | — | — | — | — | p50 14.9 / p95 22.9 / max 27.4 | **p50 15.0 · p95 24.1 · max 25.5 ms; 31/31 within 1000 ms** | GREEN |
| **2** | **amended success, BOTH authorities** | **≥ 0.8** | 11/28 = 0.3929 | **21/28 = 0.7500** | 14/28 = 0.5000 | 16/28 = 0.5714 | **21/28 = 0.7500** (95 % CI 0.566–0.873) | **RED vs 0.8 — but exactly W1's number; F-T1-1 gone** |
| 2b | — scorer (K0) only | — | 14/28 | 24/28 | 14/28 | 21/28 | **21/28 = 0.7500** | the two authorities now **agree exactly** |
| 2c | — system only | — | 14/28 | 21/28 | 14/28 | 16/28 | **21/28 = 0.7500** | |
| 2d | — by goal 2 | — | bench 0/7 · 3/9 · 3/3 · 1/5 · 4/4 | bench 0/7 · 9/9 · 3/3 · 5/5 · 4/4 | bench 0/7 · 3/9 · 3/3 · 4/5 · 4/4 | bench 0/7 · 9/9 · 1/3 · 4/5 · 2/4 | **bench 0/7 · come_here 9/9 · lamppost 3/3 · sidewalk 5/5 · towards_lamppost 4/4** | **`bench 0/7` is the ONLY shortfall** |
| 3 | resume path ratio vs straight-line oracle | ≤ 1.1 | 1.4905 (n=8) | 1.7299 (n=12) | 1.4875 (n=8) | 1.7225 (n=5) | **1.7303 (n=12)**, p50 1.842 p95 2.300 | **RED as written** — population restored 5 → 12, and the value is W1's 1.7299 |
| 3b | hold-row quotient | ≤ 1.1 | 0.9771 (3) | 0.9801 (3) | 0.9778 (3) | 0.9687 (2) | **0.9808 (3 rows: 1.0002 / 0.9369 / 1.0053)** | **GREEN** — third hold row back |
| 3c | resume rows vs the TWO-LEG oracle | ≤ 1.2 | n/a | 1.3728 (n=8) | 1.4675 (n=3) | 1.0790 (n=3) | **mean 1.3743 (n=8)**; **median 1.0614**; rows 1.0309/1.0505/1.0507/1.0512/1.0715/1.1342/**2.3014**/**2.3043** | **mean RED, median GREEN — see R4a; T1's 1.079 was a 3-row artifact** |
| 3d | two-leg ratio, all `both_reachable` | — | — | 1.0880 (n=13) | 0.8980 (n=9) | 0.8411 (n=5) | **1.0890 (n=13)** | matches W1 |
| 4a | owner-referring amendments admit | 6/6 | 0/6 | 6/6 | 0/6 | 6/6 | **6/6** | **GREEN** |
| 4b | held queue utterance admits after cue-stripping | 8/8 | 0 | 8/8 | 8/8 | 8/8 | **8/8 stripped, 8/8 admitted work** | **GREEN** |
| 5 | return rate | — | 8/9 = 0.8889 | 13/13 | 9/9 | 5/5 | **13/13 = 1.0000** (scorer-only 13/13) | **GREEN** — denominator restored 5 → 13 |
| 6 | refused-and-continued (`goal_1_continued`) | 0 | 7 | 0 | 7 | 0 | **0** | **GREEN** |
| 7 | terminal false arrivals (amended leg) | 0 | 3 | 0 | 0 | 0 | **0** | **GREEN** |
| 8 | switch-window false arrivals (revision-aware) | 0 | 0 | 3 | 1 | 0 | **0** | **GREEN — measured live, no re-score** |
| **9** | **authority disagreements** | **≤ 2/80** | 17/80 | 9/85 | 0/80 | 7/85 strict (20/85 incl. tolerated) | **0/85 strict AND 0/85 including `tolerated_boundary`** | **GREEN — beats the bar and beats every parent cell** |
| 10 | bench `system_failed_but_arrived` | 0/29 | 11/29 | 9/28 | 0/29 | 0/28 | **0/28** | **GREEN** |
| 11 | collisions — switch window (sim flag / clearance ≤ 0) | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | **0 / 0** | **GREEN** |
| 11b | min clearance, switch window | — | 0.8294 m | 0.8258 m | 0.8316 m | 0.8233 m | **0.8241 m** | |
| 11c | collisions, whole episode (all 40) | 0 | 0 | 0 | 0 | 0 | **0** | **GREEN** |
| 11d | min clearance, whole episode | — | 0.6580 m | 0.6593 m | 0.6591 m | 0.6494 m | **0.6590 m** | |
| 12 | H-NI1c blind classifier, 110 cases | port exact | 0.8273 | 0.8273 | 0.8273 | 0.8273 | **0.8273** (91/110; revise .900 / keep .9333 / queue .6667 / clarify .800) | **GREEN — bit-identical across all five cells** |
| 13 | `gold_blind.json` sha256 | `c253df2f…` | ✓ | ✓ | ✓ | ✓ | **✓ `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`, `blind_sha256_matches: true`** | **GREEN** |

### R4a · Bar 3c honestly restated — T1's GREEN was a small-population artifact

T1 reported 3c as **1.0790 (n=3), GREEN**. That must not stand unqualified: T1's `both_reachable`
population had collapsed to 5 rows *because of F-T1-1*, and the 3 surviving resume rows were all
`sidewalk-come_here`. With the population restored to its full 8 resume rows, 3c reads **mean 1.3743**
— which is **W1-alone's 1.3728 (n=8) to three decimals**, i.e. the merged tree reproduces W1 exactly.

The mean is carried by exactly **two** rows, `ni1-36-towards_lamppost-sidewalk` (2.3014) and
`ni1-38-towards_lamppost-sidewalk` (2.3043); the other six lie in 1.031–1.134. The **median is 1.0614**,
comfortably inside the 1.2 bar, and 3d (all `both_reachable` rows) is **1.0890**. So the finding
"resume adds no measurable path overhead" survives on the median and on 3d, but **3c's mean is RED at
n=8** and T1's green cell should be read as n=3. The two outliers are a `towards_lamppost → sidewalk`
pair and are the same rows that were outliers in W1's own run — a pre-existing route-quality issue,
not an F7 effect.

### R4b · What moved vs T1, and why

* **Populations restored.** `both_reachable` 5 → 13, bar-3 ratio rows 5 → 12, return denominator 5 → 13,
  hold rows 2 → 3 — all because `lamppost` and `towards_lamppost` verify from rest again.
* **The from-rest reachable set** is `{bench 0, come_here 1, lamppost 2, sidewalk 2, towards_lamppost 2}`.
  `come_here` is 1 (not 2) because of the timing-staged `ctl-come_here#0` row explained in R3; it stays
  in the set. **Caveat on the derived quotient row:** the from-rest *floor* is a mean over both reps
  regardless of arrival, so `come_here`'s floor is 0.4659 here vs 0.9302 in W1 — which is why the
  resume/from-rest quotient reads 1.879 vs W1's 1.581. That row is distorted by the non-arriving rep and
  should not be compared across the two runs; 3b/3c/3d are the population-stable statistics.

## R5 · The post-F7 re-score, BY NAME (AUDIT_T1's requirement)

Census rule and its validation against T1 are stated in R0c. Both cells' named authority legs are
**asserted equal to their own `results.json` totals** before anything is reported.

### R5a · T1's 24 `arrival_receipt_for_another_place` legs — every one, and its outcome now

**All 24 → `navigation_goal_verified`. Outcome histogram: `{navigation_goal_verified: 24}`.**
The 23 scored legs all read `sys=True scorer=True dtg=0.0 success=True`, category `agreement`; the one
`hold` leg stays `unknown` because a hold row observes the running goal and is never scored.

| # | leg | goal | T1 terminal → post-F7 terminal | T1 category → post-F7 |
|---|---|---|---|---|
| 1 | `ctl-lamppost#0` | lamppost | `arrival_receipt_for_another_place` → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 2 | `ctl-lamppost#1` | lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 3 | `ctl-towards_lamppost#0` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 4 | `ctl-towards_lamppost#1` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 5 | `seq-lamppost-then-bench::first` | lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 6 | `seq-towards_lamppost-then-bench::first` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 7 | `seq-bench-then-lamppost::second` | lamppost | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 8 | `seq-bench-then-towards_lamppost::second` | towards_lamppost | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 9 | `seq-come_here-then-towards_lamppost::second` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 10 | `ni1-05-bench-lamppost::reissue` | lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 11 | `ni1-06-bench-lamppost::amended_goal` | lamppost | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 12 | `ni1-07-bench-lamppost::amended_goal` | lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 13 | `ni1-09-bench-sidewalk::amended_goal` | sidewalk | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 14 | `ni1-14-bench-towards_lamppost::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 15 | `ni1-15-bench-towards_lamppost::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 16 | `ni1-16-lamppost-bench::reissue` | lamppost | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 17 | `ni1-19-lamppost-bench::reissue` | lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 18 | `ni1-20-sidewalk-bench::reissue` | sidewalk | → **`navigation_goal_verified`** | system_failed_but_arrived → **agreement** |
| 19 | `ni1-28-towards_lamppost-bench::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 20 | `ni1-30-towards_lamppost-bench::amended_goal` | **hold** | → **`navigation_goal_verified`** | unknown → unknown *(hold rows are not scored)* |
| 21 | `ni1-31-towards_lamppost-bench::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 22 | `ni1-35-towards_lamppost-come_here::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 23 | `ni1-37-towards_lamppost-sidewalk::amended_goal` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |
| 24 | `ni1-39-towards_lamppost-sidewalk::reissue` | towards_lamppost | → **`navigation_goal_verified`** | tolerated_boundary → **agreement** |

**Token census over all 109 legs:** `arrival_receipt_for_another_place` **24 → 0**.
Terminal-detail histogram moves `navigation_goal_verified` **27 → 52** with `semantic_target_unreachable`
(24 → 24), `owner_follow_verified` (16 → 16) and `suspended:goal_amend` (3 → 3) unchanged, and
`semantic_arrival_verification_failed` 15 → 14. **Nothing was converted into a different refusal; the
24 became verified arrivals and no other class grew.**

### R5b · `arrival_receipt_superseded` — count and names

**0 occurrences**, across all 109 legs (and 0 in T1's run, where the token did not yet exist). No leg to
name. This is the **expected** result and it is the load-bearing check on U32's tightening: the token
fires only when a receipt is cut under one commitment index and read under a later one, and the tier
cuts its terminal receipt **after** the last refinement, at the current index. `stale_arrival_receipt`
and `outside_support_polygon` are likewise 0. F7's stricter rule therefore **added no new refusals** to
the tier while removing 24 false ones — the outcome the fix was designed for, confirmed by measurement
rather than by its unit tests.

### R5c · The authority-disagreement legs, by name, with attribution

| cell | strict | incl. `tolerated_boundary` | named legs |
|---|---|---|---|
| T1 pre-F7 | **7/85** | 20/85 | 6 of the 7 carry `arrival_receipt_for_another_place`: `ctl-lamppost#0`, `ni1-06-…::amended_goal`, `ni1-09-…::amended_goal`, `ni1-14-…::amended_goal`, `ni1-16-…::reissue`, `ni1-20-…::reissue`. **The 7th, `ni1-29-towards_lamppost-bench::reissue`, is NOT F-T1-1** — its terminal is `semantic_arrival_verification_failed` at dtg 0.0. All 13 tolerated legs but one (`ni1-14-…::reissue`, `semantic_target_unreachable`) carry the F4 token. |
| **T1 post-F7** | **0/85** | **0/85** | **none — the list is empty** |

**Correction to T1 §6.3, recorded:** T1 attributed all 7 strict disagreements to F-T1-1. Six were; the
seventh (`ni1-29-towards_lamppost-bench::reissue`) was a separate `semantic_arrival_verification_failed`.
It too is `agreement` post-F7, so the conclusion is unaffected — but the attribution is now exact.

**On the expected residual.** AUDIT_T1 anticipated a residual of **bench legs = B32's honest strip at
dtg ≈ 0.24**. Measured: the bench legs are **not a residual disagreement at all**. All **28** bench legs
read `system_arrival=False, scorer_arrival=False → agreement` (dtg min 0.080 / mean 1.729 / max 4.715;
the from-rest controls sit at 0.241). B32 makes the scorer stop certifying unstandable ground, so a
bench leg is an **agreed honest failure**, which is why bar 9 lands at 0/85 rather than at the
"bench-shaped residual" the audit allowed for. **Bar 9 is GREEN and beats every parent cell** —
including W4-alone's 0/80, on a larger population of 85 legs.

### R5d · Bar 2, confirmed against the pre-registered expectation

Expected by AUDIT_T1: **21/28 with `bench 0/7` the only shortfall.** Measured: **21/28 = 0.7500**, by
goal 2 `bench 0/7 · come_here 9/9 · lamppost 3/3 · sidewalk 5/5 · towards_lamppost 4/4` — **exactly
that, on the nose.** The scorer-only and system-only readings are now **both** 21/28: the two
authorities agree leg-for-leg, which is the deeper statement (T1 had 21 vs 16).

**The pre-registered ceiling is confirmed, not beaten.** Bar 2 is **RED against 0.8** and W1's 21/28 is
reproduced on the merged, F7-corrected tree. The whole remaining gap is `bench 0/7`: the dog does not
reach standable ground at the bench, and B32 now says so honestly instead of certifying it.

## R6 · Close — build freeze, stamps, hygiene, output files

### R6a · Build freeze (the rule AUDIT_T1 demanded after W4's mixed-build tier)

**All 13 product + harness blobs re-hashed at close are BYTE-IDENTICAL to the launch table in R0a.**
`runtime.py 319c93d7…`, `arrival_receipt.py fe0cfc6c…`, `headless_city.py 17e6d5c2…`,
`plan_queue.py c1bcdb6e…`, `executive.py aaba3745…`, `scoring.py aa876aa0…`, `pipeline.py 2f241047…`,
`poi_admission.py dd9242af…`, `city_semantics.py 473c42f8…`, `voice/agent.py d3486668…`,
`harness.py 237a73bf…`, `run.py 4dbd4282…`, `queue_policy.py b72a19e8…`. **BUILD FREEZE HELD: YES.**
`gold_blind.json` and `interrupt_tier_v1.json` also unchanged at close.

**One build produced every number**, and unlike T1 this run needed no resume: a single process ran
controls → sequence → tier → classifier → aggregate with **no SIGTERM and no `--offset` resume**
(the runner was launched under `setsid`, out of reach of the session task supervisor).

### R6b · Stamps, as instructed

| | value |
|---|---|
| **stamp at START** | **`bfc72ae269a2cce52fa5b4a028750b6420afe4f1288e751e2379b522f8c8b539`** — **identical to the dispatch stamp `bfc72ae2…`** |
| **stamp at CLOSE** | **`132e224ada31361d72f2b36a0c6783a5a80e83b14c94251b0862596be052d67d`** — differs |

**Which rows ran under which: ALL of them ran under `bfc72ae2…`.** The tier launched at 11:16:01 with
the start stamp equal to the dispatch stamp, and the build was frozen through close (R6a). The close
stamp differs only because the stamp recipe hashes *every untracked file's contents plus the tracked
diff*, and two sets of files inside the worktree changed during the 62-minute run — **neither on the
tier's import path**:

| what changed | mtime | whose |
|---|---|---|
| `research/20260829/nav-interrupt-1/m1-merged-f7-{controls,sequence_controls,episodes}.jsonl`, `…-results.json` | 11:22 → 12:18 | **this run's own outputs** |
| `evals/nav_instruct/results/mutation_panel.json` (tracked ` M`) | 11:47:16 | **W5-F1** |
| `scripts/mutation_panel.py` (tracked ` M`) | 11:26:41 | **W5-F1** |
| `scripts/mutation_panel_mutations.py` (untracked) | 11:19:46 | **W5-F1** |
| `.pytest-matrix-freshness/nav-instruct-v1-baseline-v5-20260830T161509Z.json` (untracked) | 12:15:09 | **W5-F1** |
| `MUJOCO_LOG.TXT`, `logs/duplex/*.jsonl`, `.ruff_cache/`, `__pycache__/`, `.hypothesis/` | during run | **ignored — `git check-ignore` confirms these never enter the stamp** |

`grep -n mutation_panel research/20260829/nav-interrupt-1/*.py` → **no match**: the tier does not import
any file W5 touched. **A bit-identical close stamp was unachievable by construction** (this card's own
outputs land inside the hashed set), which is why R6a's blob-level freeze — not the stamp — is the
invariant that certifies the measurement.

### R6c · Host and hygiene

| | |
|---|---|
| orphan sims | **`clean: true`, `survivors_ours: []`, `survivors_other_processes: []`** — 60 sims launched, 60 reaped; external `ps` after close finds **0** sims on `…/wb/t1f7-sock/` |
| the owner's stack | sim pid **807004** on `/tmp/parcel_sim.sock` alive and untouched throughout; `:8765` (owner panel) and `:8080` (llama-server) never contacted |
| containment | every sim under `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`, one at a time |
| memory store | `PARCEL_MEMORY_PATH` under `…/wb/t1f7-sock/memory{N}.sqlite3`; the owner's `parcel_memory.sqlite3` never opened; `PARCEL_MEMORY_PURPOSE` never set |
| load | 1.55 at launch, ≤ 2.2 throughout — no contention with W5 |
| recorded artifacts | the five baseline files (`controls.jsonl`, `episodes.jsonl`, `sequence_controls.jsonl`, `results.json`, `sample_episode.txt`) are **tracked with empty git status — untouched**; T1's `m1-merged-*` five files untouched |
| watchers | all progress watchers stopped; **none left running** |
| **spend** | **$0.00** — `use_llm=False`, no hosted call, no network |
| no pytest, no `ci_gate.py`, no `git` write, no source/test/eval/config edit | confirmed |

### R6d · Output file list

Four **new, untracked** files in `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/research/20260829/nav-interrupt-1/`:

| file | bytes | what |
|---|---|---|
| `m1-merged-f7-results.json` | 44,063 | every headline number (`h_ni1a`, `h_ni1b`, `h_ni1c`, `authority_disagreement`, `orphan_check`) |
| `m1-merged-f7-episodes.jsonl` | 387,278 | 40 episodes, 0 errors — receipt timelines, 1 Hz tracks, switch windows, queue logs, `region_provenance` |
| `m1-merged-f7-sequence_controls.jsonl` | 56,644 | 10 from-rest two-leg sequence controls (the two-leg oracle) |
| `m1-merged-f7-controls.jsonl` | 31,088 | 10 from-rest controls |

There is **no `m1-merged-f7-sample_episode.txt`**: `--all` expands to
`controls, sequence, tier, classifier, aggregate` (`run.py:1834`) and deliberately excludes `sample`.
T1's fifth file came from the explicit `--stage sample` in its resume invocation, which this
uninterrupted run did not need. Four files is the complete `--all` output.

Scratch (no repo): `/tmp/claude-1000/…/scratchpad/t1f7/` — `tier.log`, `bars_t1f7.py` (T1's script + a
fifth cell), `rescore.py` (the by-name census), `bars_out.txt`, `rescore_out.txt`.
Socket root `/home/jaewoo-jang/.cache/parcel-0e/wb/t1f7-sock/`.

## R7 · Summary for the integrator

1. **F-T1-1 is closed by measurement.** All **24** legs → `navigation_goal_verified`; the token is **0×**
   in 109 legs; no other refusal class grew.
2. **Bar 2 = 21/28 = 0.7500**, exactly the pre-registered expectation, with **`bench 0/7` the only
   shortfall**. Scorer-only and system-only both read 21/28 — the authorities agree leg-for-leg.
   **Still RED against 0.8: the ceiling W1 recorded is confirmed on the merged tree, not beaten.**
3. **Bar 9 = 0/85 strict and 0/85 including tolerated — GREEN**, beating the ≤ 2/80 bar and every parent
   cell. The anticipated bench residual does not exist as a disagreement: all 28 bench legs are
   `agreement` (`sys=F scorer=F`), B32's honest strip.
4. **`arrival_receipt_superseded` = 0** — U32's tightening added no new refusals to the tier.
5. **Everything else green:** admission 0.9688, 6/6 and 8/8, refused-and-continued 0, terminal and
   switch-window false arrivals 0, collisions 0 everywhere, classifier 0.8273 bit-identical,
   `gold_blind.json` unmoved. Populations restored (`both_reachable` 5 → 13, return 5/5 → 13/13).
6. **One correction to T1 and one to itself:** T1's 7 strict disagreements were 6 × F-T1-1 + 1 ×
   `semantic_arrival_verification_failed` (`ni1-29-…::reissue`), not 7 × F-T1-1; and **T1's bar-3c GREEN
   (1.079, n=3) was a small-population artifact** — restored to n=8 it reads mean **1.3743** (W1's
   1.3728), median **1.0614**. 3c's mean is RED; the "resume adds no path overhead" claim survives on
   the median, on 3b (0.9808) and on 3d (1.0890), and should be stated that way.
7. **Process rule honoured:** one build, no resume, blobs byte-identical at close; the stamp moved only
   through this run's own outputs and W5's concurrent mutation-panel work, neither on the import path.
