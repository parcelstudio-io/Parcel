# MA-1 — RESULTS

Executor: Opus (parcel session), 2026-08-29.  Design: `DESIGN.md` (FROZEN).
Evidence tier: **`desktop-sim`** (headless city, kinematic, no audio, no real LiDAR noise beyond the venue's own profile).  Physical motion: **NO-GO**, unchanged.  No verdict is drawn here — Fable writes `VERDICT.md`.

## 0. Pre-flight

* **AMENDMENTS.md at start of run: PRESENT** (5960 bytes)
* seed `20260829`; venv `~/.cache/parcel-0e/venv` (python 3.14.4); scratch `/home/jaewoo-jang/.cache/parcel-0e/ma1`
* `PARCEL_MEMORY_PATH` -> `/home/jaewoo-jang/.cache/parcel-0e/ma1/scratch_memory.sqlite3` (the owner's store is never opened); `PARCEL_MEMORY_PURPOSE` unset
* **No sim subprocess is launched** — the headless city runs in-process. The only children are this file's multiprocessing Pool workers; they are joined and the process group is proved empty at exit (see §7).
* No sockets are opened, nothing touches `/dev/bus/usb`, no hosted API call and no VLM call is made, and no git write command is run. The owner's `:8080` / `:8765` / `/tmp/parcel_sim.sock` are untouched.
* The NAV evals' held-out scene is never loaded and never named; the venue is the headless city's own default block, perturbed procedurally.  No frozen digest is read or moved.

* GPU at start: free [29667] MB (cap for this job: 12 GB; a foreign executor shares the card, so every training job is gated at >= 14 GB free — see §4).

## 1. Sample episodes (timing sanity check)

`sample_episodes.txt` is written FIRST (23931 bytes, 28 s): 30-frame excerpts of one **plain**, one **revise** and one **queue** episode on a generated scene, each anchored on its interruption, with the scripted owner's utterances, the `stop` cue and any sound events timestamped above the table.

What the excerpt is there to let a reader check, and what it shows:

* the `cmd:` cue and the matching narration (`nav.start` / `plan.revised` / `plan.queued`) land on the SAME frame as the owner's utterance;
* **the goal channels do NOT flip on that frame** — A3's 5-frame mask keeps them on the old goal, so an arm that switches must be reading `cmd_target`, not `goal_bear`;
* the act stream turns toward the new bearing over the following frames;
* after a `cmd:stop` the `stop_state` channel latches `stopped` and the act stream holds until the owner re-issues (`cmd:go_to` again) — stop is a held state, not a one-frame event;
* `steer:resume` and `plan.resumed` appear only after the amendment goal's terminal;
* frame 0 emits `<idle>`, not a zero twist: the two are one token (see §2.1).

## 2. Teacher corpus and the held-out geometry (A2)

The teacher is the shipped stack: `DirectiveNavigator` + grid planner + semantic resolution ladder + `apply_reactive_safety`, driven in `HeadlessCityWorld`.

**A2 — held-out GEOMETRY, not held-out labels.** The first draft perturbed the frozen block with `MjSpec` jitter; the amendment is applied instead: every episode runs on a real MJCF variant built by `evals.nav_instruct.scene_gen.build_scene(seed, scratch_dir)` — the same rejection-sampled generator the NAV `val_unseen` split uses, with its round-trip / overlap / support / **navigability** filters — on MA-1's own seed ranges `train (770000, 770600)`, `dev (780000, 780060)`, `held (790000, 790120)`. These are disjoint from each other and from the `val_unseen` manifests' seeds (91011-91015); nothing writes into `configs/scenes/generated/` (scenes land in MA-1's scratch tree) and the NAV evals' held-out scene is never loaded and never named. Splits are **grouped by geometry seed**.

| split | scenes | manifest sha256 |
|---|---|---|
| train | 600 | `ddbbc79e0e4534cd3674165dc01914e3...` |
| dev | 60 | `af22bce8a580b91efa8fefe27936e6ab...` |
| held | 120 | `78c53b9701937bdc2a25e7fbb39545ec...` |

| split | episodes | frames | scene seeds | plain/revise/queue | teacher SR | any-arrival | collision rate | mean frames | stop cues | speaking cues | sound events |
|---|---|---|---|---|---|---|---|---|---|---|---|
| train | 3000 | 856152 | 600 | 1785/605/610 | **0.0423** | 0.056 | 0.0 | 285.4 | 280 | 318 | 1294 |
| dev | 240 | 69405 | 60 | 150/41/49 | **0.0667** | 0.0792 | 0.0 | 289.2 | 17 | 26 | 86 |
| held | 600 | 206058 | 120 | 200/200/200 | **0.045** | 0.0617 | 0.0 | 343.4 | 60 | 89 | 299 |

Per-target teacher success (train): `bench` 0.046, `crosswalk` 0.066, `lamppost` 0.037, `planter` 0.033, `sidewalk` 0.029

**The target vocabulary is bounded to what the teacher can demonstrate.** A pre-generation probe of 16 plain episodes per target on the frozen block measured the shipped stack at `sidewalk` 0.75, `lamppost` 0.44, `bench` 0.19, `crosswalk` 0.12, `planter` 0.06, **`tree` 0.00, `door` 0.00** (112 episodes, band-entry predicate). `tree` and `door` are therefore out of the vocabulary: a goal the teacher never reaches teaches the student to wander, and `door` does not exist in generated variants at all. This is a bound on the CLAIM, and it is the first thing §6 says the result does not prove.

### 2.1 Teacher receipts vs the truth oracle (review row)

A1 makes the truth oracle the gold. The teacher's OWN opinion — the navigator's `mission.status` and its `MidLevelCommand.note` block / recovery words — is recorded on the same frames and compared. It is never used as a label; it is here so the gap is a number.

On the 600 held-out teacher episodes, within a 1.0 s window: **637 oracle block edges** vs **892 navigator block edges**; the navigator covers 0.0141 of the oracle's, the oracle covers 0.0101 of the navigator's. Arrival: both agree on 12 episodes, oracle-only on 26, navigator-only on 402; median lag -11.3 s (oracle minus navigator).

**They are not the same signal**, which is exactly why the amendment moved gold to the oracle: the navigator calls itself blocked whenever its recovery ladder is running (a semantic-search rotate counts), while the oracle only says blocked when the body is actually inside the reactive-safety stop band. A harness-side "stalled for 3 s" class that the first draft also emitted was CUT for the same reason — it fired at 2.9 s on an episode where the robot was accelerating away with a clear forward sector. `nav.blocked:stalled` and `nav.blocked:unroutable` remain in the vocabulary with ZERO support and are reported as such.

**The hold token.** DESIGN.md writes `<hold>`; the shipped `ActTokenCodec` vocabulary has no such token, so **`<idle>` is the hold token throughout**, and the zero twist `<twist:1:2>` (vx = 0, vyaw = 0) is folded into it — one token for one body state, no label noise. The act vocabulary is 46 tokens.

Generation wall: 0.1 s on 24 CPU workers (`OPENBLAS_NUM_THREADS=1` per worker; no sim subprocess).

## 3. Arm C — training

* AMENDMENTS.md check before this row: PRESENT
* **GPU gate** (a foreign executor shares this card): needed >= 14000 MB free, saw 29665 MB after waiting 0.0 s -> START. Our own cap is 12 GB.
* host at launch: `{"loadavg": [2.87, 3.14, 4.77], "cpus": 192, "compute_apps": ["197110, /opt/google/chrome/chrome --type=gpu-process --ozone-platform=wayland --render-node-override=/dev/dri/renderD128 --crashpad-handler-pid=197071 --enable-crash-reporter=4a3d2ce7-5a61-4486-9320-ac186b6b89b3? --change-stack-guard-on-fork=enable --gpu-preferences=YAAAAAAAAAAgAQAEAAAAAAAAAAAAAGAASAAAAAAAAAABAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAMAAAAAAAAAAwAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAMAAAAAQAAAAAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --metrics-shmem-handle=4?i?12079234730313437124?6417331928648802753?262144 --field-trial-handle=3?i?14573182382656154685?3075928576371648801?262144 --disable-features=EyeDropper --variations-seed-version --pseudonymization-salt-handle=7?i?3895470481966016212?11730574767758071709?4 --trace-process-track-uuid=3190708988185955192, 231 MiB", "2743734, ptyxis, 26 MiB", "2862102, /usr/bin/nautilus, 28 MiB"], "gpu": "2564 MiB, 29665 MiB, 33 %"}`

Arm C: BehaviorFormer, 6 layers x d=256 x 4 heads, ctx 128, two heads (act 46 / narration 43), **4.99 M params**. Class-weighted CE on both heads (BM-1's A4 rule, counts^-0.5 mean-normalised), AdamW + OneCycle, lr 0.0003, batch 32, window 128 (warm-up 16 frames excluded from the loss).

**Early stopping (pre-registered).** Dev-selection metric is A4's: the harmonic mean of dev **closed-loop** success and dev narration macro-F1 on a fixed 20-episode dev-geometry slice, evaluated every 400 steps, patience 3. Stopped by `early_stop` at step 2000; **best step 800** (score 0.0914).

| step | dev closed-loop SR | dev narration F1 | selection score | open-loop act top-1 | open-loop act bal-acc | open-loop narr F1 |
|---|---|---|---|---|---|---|
| 400 | 0.05 | 0.3148 | 0.0863 | 0.7194 | 0.3036 | 0.3344 |
| 800 | 0.05 | 0.5317 | 0.0914 | 0.7571 | 0.3804 | 0.5674 |
| 1200 | 0.0 | 0.6121 | 0.0 | 0.809 | 0.4171 | 0.5913 |
| 1600 | 0.0 | 0.6469 | 0.0 | 0.8262 | 0.4632 | 0.596 |
| 2000 | 0.0 | 0.6718 | 0.0 | 0.8314 | 0.5188 | 0.5987 |

* wall 370.6 s; GPU peak **644.9 MB** (cap 12000); 8.37 epoch-equivalents
* **checkpoint frozen before any held-out run**: `arm_C.pt` sha256 `2482d0f83af1397ae2171e1a824be749...`

## 4. Held-out closed loop

* AMENDMENTS.md check before this row: PRESENT — A1/A2/A3/A4/A7/A8/A10 applied; see §6 for the per-amendment ledger.
* 600 held-out episodes on **disjoint generated geometry** (A2). Every arm replays the SAME scripts through the same `run_core`, so the world, the cues and the gold timeline are identical across arms; only the policy differs.
* Each arm's act token is decoded by the product codec and passes through `apply_reactive_safety` before it reaches the world — the safety core is never bypassed by any arm.

* GPU gate before arm C closed loop: 28551 MB free after 0.0 s -> RUN
* GPU gate before arm C-h0 closed loop: 28551 MB free after 0.0 s -> RUN
### 4.1 H-MA1a — closed-loop navigation on held-out geometry

> **Bar (DESIGN):** >= 0.85 x teacher success, <= 1.25 x teacher path length, collision rate <= teacher + 0.02. Refuted below 0.6 x teacher success.  **A2 adds:** on held-out layouts C must beat STRAIGHT-TO-GOAL by >= 0.10 success, and the split is uninformative if STRAIGHT-TO-GOAL succeeds on > 0.7 of them.

| arm | success (A1-strict) | band entry | SPL | x teacher SR | path (m, successes) | x teacher path | collision rate | vs teacher | mean frames |
|---|---|---|---|---|---|---|---|---|---|
| T (teacher — the shipped stack) | **0.045** | 0.6517 | 0.0364 | 1.0 | 4.967 | 1.0 | 0.0 | 0.0 | 342.8 |
| C (Model A v0) | **0.0367** | 0.0867 | 0.0358 | 0.8156 | 1.147 | 0.2309 | 0.0 | 0.0 | 593.5 |
| C-h0 (history ablated) | **0.048** | 0.22 | 0.0452 | 1.0667 | 3.397 | 0.6839 | 0.0 | 0.0 | 592.0 |
| A'n (frozen reflex table) | **0.1983** | 0.5167 | 0.1688 | 4.4067 | 4.865 | 0.9795 | 0.0 | 0.0 | 517.9 |
| STRAIGHT-TO-GOAL (reference) | **0.2167** | 0.53 | 0.1836 | 4.8156 | 5.055 | 1.0177 | 0.0 | 0.0 | 507.1 |
| ALWAYS-IDLE (reference) | **0.03** | 0.03 | 0.03 | 0.6667 | 0.0 | n/a | 0.0 | 0.0 | 593.4 |

On the looser band-entry predicate the same comparison reads C 0.0867 vs teacher 0.6517 = **0.133 x teacher** (the DESIGN's bar is 0.85 x on success and 0.6 x is the refutation line; it is pre-registered against the strict predicate, so this row is a companion, not a substitute).

**A2 informativeness:** STRAIGHT-TO-GOAL succeeds on 0.2167 of held-out episodes (uninformative above 0.7) -> split is **INFORMATIVE**.
**C - STRAIGHT-TO-GOAL = -0.18** (A2 bar: >= 0.10) -> NOT MET.

### 4.2 H-MA1b — interruptions absorbed in stream

> **Bar (DESIGN):** switch toward the new goal within 1.0 s in >= 0.9 of cases; for queue cues `plan.queued` then `plan.resumed` in the right order in >= 0.8.  **A3:** the switch is anchored to the DETECTED CUE frame, the heading is measured from the truth pose, and the goal channels are masked for 5 frames after the cue so a bearing-follower cannot score from the input alone. The queue check is task-stack exact (oracle arrival at goal 2, then at goal 1).

| arm | switch rate (all cues) | median latency | revise | queue | queue narration order | queue task-stack exact |
|---|---|---|---|---|---|---|
| T (teacher — the shipped stack) | **0.5325** | 0.1 | 0.535 | 0.53 | 1.0 | 0.005 |
| C (Model A v0) | **0.1775** | 0.1 | 0.135 | 0.22 | 0.965 | 0.0 |
| C-h0 (history ablated) | **0.5301** | 0.2 | 0.4819 | 0.5783 | 0.1807 | 0.0 |
| A'n (frozen reflex table) | **0.9175** | 0.5 | 0.88 | 0.955 | 1.0 | 0.05 |
| STRAIGHT-TO-GOAL (reference) | **0.9025** | 0.5 | 0.86 | 0.945 | 0.0 | 0.04 |
| ALWAYS-IDLE (reference) | **0.0** | n/a | 0.0 | 0.0 | 0.0 | 0.0 |

### 4.3 H-MA1c — narration events, right and on time

> **Bar (DESIGN):** event-conditional F1 >= 0.85 for `nav.start`, `nav.arrived`, `nav.blocked`, `plan.revised/queued/resumed`, each within a 1.0 s window; false-event rate <= 0.05.  **A4:** an emission is a rising edge; at most one TP per gold event in the CAUSAL window `[t_gold, t_gold + 1.0 s]`; every other emission is an FP.  **A10:** the false-event rate is *predicted terminal with no backing receipt*; these tokens are PREDICTIONS and carry no authority.  **A7:** reported per vocabulary partition; `nav.progress` is INTERNAL-ONLY and is not scored as narration at all.

| arm | macro F1 | product-backed | research-only | false-event rate | predicted terminal w/o receipt | emitted events |
|---|---|---|---|---|---|---|
| T (teacher — the shipped stack) | **1.0** | 1.0 | 1.0 | 0.0 | 0.0 | 1928 |
| C (Model A v0) | **0.5023** | 0.0063 | 0.7504 | 0.2804 | 1.0 | 895 |
| C-h0 (history ablated) | **0.3661** | 0.0477 | 0.5253 | 0.7282 | 1.0 | 861 |
| A'n (frozen reflex table) | **0.696** | 0.1024 | 0.9928 | 0.8955 | 0.8253 | 12422 |
| STRAIGHT-TO-GOAL (reference) | **0.0** | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| ALWAYS-IDLE (reference) | **0.0** | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| ALWAYS-NONE (A4 reference) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| EVENT-EVERY-FRAME (A4 reference) | 0.0049 | 0.0015 | 0.0066 | 0.9974 | 0.9998 | 356070 |

Held-out gold events per scored class (A4 floor is 200): `nav.start` 654, `nav.arrived` 39, `nav.blocked` 635, `plan.revised` 200, `plan.queued` 200, `plan.resumed` 200

Per-class F1:

| class | T (teacher — the shipped stack) | C (Model A v0) | C-h0 (history ablated) | A'n (frozen reflex table) | STRAIGHT-TO-GOAL (reference) | ALWAYS-IDLE (reference) |
|---|---|---|---|---|---|---|
| `nav.start` | 1.0 | 0.1707 | 0.1513 | 0.9962 | 0.0 | 0.0 |
| `nav.arrived` | 1.0 | 0.0 | 0.0 | 0.2048 | 0.0 | 0.0 |
| `nav.blocked` | 1.0 | 0.0125 | 0.0954 | 0.0 | 0.0 | 0.0 |
| `plan.revised` | 1.0 | 0.94 | 0.798 | 0.985 | 0.0 | 0.0 |
| `plan.queued` | 1.0 | 0.9438 | 0.8187 | 0.99 | 0.0 | 0.0 |
| `plan.resumed` | 1.0 | 0.9471 | 0.3333 | 1.0 | 0.0 | 0.0 |

### 4.4 H-MA1d — liveness does not cost navigation

> **Bar (DESIGN):** `attend.sound` + a gaze toward the bearing within 0.5 s in >= 0.8 of sound events; success within 0.03 and path within 5 % of episodes with no sound event.

| arm | sound events | attend rate (narration AND gaze) | narration only | gaze only | SR with sound | SR without | delta SR | path delta % |
|---|---|---|---|---|---|---|---|---|
| T (teacher — the shipped stack) | 299 | **0.9933** | 1.0 | 0.9933 | 0.0233 | 0.0571 | -0.0338 | -33.94 |
| C (Model A v0) | 349 | **0.9341** | 0.937 | 0.9398 | 0.0169 | 0.0496 | -0.0327 | 17.0 |
| C-h0 (history ablated) | 150 | **0.76** | 0.78 | 0.76 | 0.0291 | 0.0612 | -0.0321 | -13.92 |
| A'n (frozen reflex table) | 334 | **0.9671** | 0.982 | 0.979 | 0.1048 | 0.2561 | -0.1513 | 9.58 |
| STRAIGHT-TO-GOAL (reference) | 334 | **0.0** | 0.0 | 0.0 | 0.1316 | 0.2688 | -0.1372 | 10.83 |
| ALWAYS-IDLE (reference) | 349 | **0.0** | 0.0 | 0.0 | 0.0127 | 0.0413 | -0.0286 | n/a |

### 4.45 A5 — does the last minute earn its place?

> **A5:** C-h60 (the full model) must beat C-h0 by >= 0.10 on time-to-switch success or on blocked-recovery success on the held-out slice, else the finding is "window suffices".  **Caveat, stated plainly:** C-h0 here is an INPUT ABLATION of the SAME trained checkpoint (the six history tokens, the five age channels and the two 60 s counters pinned to their null values at inference), not a separately trained model. A retrained C-h0 is the stronger experiment and was not run inside the wall budget.

Both rows are scored on the SAME 250 held-out episodes.

| arm | success | switch rate | narration macro F1 | nav.blocked F1 |
|---|---|---|---|---|
| C-h60 (full) | 0.036 | 0.1506 | 0.509 | 0.0385 |
| C-h0 (history pinned null) | 0.048 | 0.5301 | 0.3661 | 0.0954 |

delta switch rate = **-0.3795**, delta `nav.blocked` F1 = **-0.0569** (A5 bar: >= 0.10 on either) -> WINDOW SUFFICES.

### 4.6 "Does the sequence model earn its place?"

> **DESIGN:** beating A'n by >= 0.10 on (b)'s time-to-switch success or on (a)'s success is the clause.  **A3:** it is read on (a) and (c), and on (b) only under the goal mask (which is what 4.2 measures).  **A1:** on narration the clause is `C - A'n >= 0.10 on F1`, else the finding is "rules suffice for narration".

| axis | C | A'n | C - A'n | bar | met? |
|---|---|---|---|---|---|
| (a) held-out success | 0.0367 | 0.1983 | **-0.1616** | >= 0.10 | no |
| (b) time-to-switch success (masked goal) | 0.1775 | 0.9175 | **-0.74** | >= 0.10 | no |
| (c) narration macro F1 | 0.5023 | 0.696 | **-0.1937** | >= 0.10 | no |

On narration the clause is NOT met, so the finding this row carries is **"rules suffice for narration"** — the frozen reflex table, reading the cue channel and the free-space ring off a single frame, is not beaten by the sequence model by the pre-registered margin. Read it beside A'n's false-event rate in 4.3: a table that emits on every qualifying frame buys recall with precision, and the DESIGN's bar is on F1.

### 4.5 A8 — the safety row

> **Bar (A8):** every RAW violation rate <= 0.01, or the finding is "A runs only behind the deterministic filter". Post-filter rates must be 0. RAW = the arm's own emission; POST = after the filter (`stop` latched -> hold; owner speaking -> hold; forward twist into an occupied sector -> zero forward). Every arm additionally passes through `apply_reactive_safety` before the world sees it.

| arm | stop frames | speaking frames | occupied-ahead frames | RAW non-idle after stop | RAW twist into occupied | RAW twist while owner speaking | POST (all three) |
|---|---|---|---|---|---|---|---|
| T (teacher — the shipped stack) | 1787 | 1371 | 4037 | **0.0** | **0.0** | **0.0** | 0.0 |
| C (Model A v0) | 2189 | 1679 | 7870 | **0.0** | **0.0027** | **0.0107** | 0.0 |
| C-h0 (history ablated) | 792 | 521 | 7053 | **0.0** | **0.0035** | **0.0326** | 0.0 |
| A'n (frozen reflex table) | 1832 | 1523 | 16466 | **0.0** | **0.0** | **0.0** | 0.0 |
| STRAIGHT-TO-GOAL (reference) | 1896 | 1464 | 7550 | **0.0** | **0.9996** | **0.9679** | 0.0 |
| ALWAYS-IDLE (reference) | 2189 | 1669 | 7325 | **0.0** | **0.0** | **0.0** | 0.0 |

## 5. Per-frame latency

Streaming cost of one decision: a full forward over the ctx = 128 frame window, no KV cache — the deployable cost of the shape as written. 2 000 frames each. The 10 Hz duplex clock gives a 100 ms budget per frame.

| arm | device | ms / frame | within the 100 ms frame budget |
|---|---|---|---|
| C (RTX 5000 Ada) | cuda | 2.18 | yes |
| C (1 CPU thread) | cpu | 15.138 | yes |
| A'n (1 CPU thread) | cpu | 0.0021 | yes |

Host at measurement (A4's co-tenant clause): loadavg [5.59, 6.49, 7.65], 192 CPUs; GPU `3678 MiB, 28551 MiB, 31 %`; compute apps on the card: `['197110, /opt/google/chrome/chrome --type=gpu-process --ozone-platform=wayland --render-node-override=/dev/dri/renderD128 --crashpad-handler-pid=197071 --enable-crash-reporter=4a3d2ce7-5a61-4486-9320-ac186b6b89b3? --change-stack-guard-on-fork=enable --gpu-preferences=YAAAAAAAAAAgAQAEAAAAAAAAAAAAAGAASAAAAAAAAAABAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAMAAAAAAAAAAwAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAMAAAAAQAAAAAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --metrics-shmem-handle=4?i?12079234730313437124?6417331928648802753?262144 --field-trial-handle=3?i?14573182382656154685?3075928576371648801?262144 --disable-features=EyeDropper --variations-seed-version --pseudonymization-salt-handle=7?i?3895470481966016212?11730574767758071709?4 --trace-process-track-uuid=3190708988185955192, 233 MiB', '2743734, ptyxis, 26 MiB', '2862102, /usr/bin/nautilus, 28 MiB', '499316, /home/jaewoo-jang/.cache/parcel-0e/venv/bin/python, 1104 MiB']`. A foreign executor shares this host, so these are wall-clock figures under real contention, not an idle-machine best case.

## 6. Amendments, the published channel list, and what this does not prove

`AMENDMENTS.md` appeared POST-START (15:53) and is binding. Every row above is the AMENDED row; where an amendment could not be applied inside the wall budget it is named here rather than quietly skipped.

| id | status | how |
|---|---|---|
| **A1** gold from the truth oracle; label-copy channels masked | **APPLIED** | Gold is `nav.arrived` = truth pose inside the harness's own goal region AND stopped >= 5 frames; `nav.blocked` = truth minimum clearance below the reactive-safety stop band (0.65 m) for >= 5 frames; `plan.*` anchored to the cue frame; `nav.failed` on the step limit. `plan_step` and `blocked` were DROPPED from the frame and the teacher-side `replan` count was replaced by `replan_own` (A's own emitted-block count). Channel list below. |
| **A2** held-out GEOMETRY | **APPLIED** | Real MJCF variants from `evals.nav_instruct.scene_gen.build_scene` on MA-1's own seed ranges, split by geometry seed, manifests hashed into `results.json`; STRAIGHT-TO-GOAL criterion and informativeness test reported in 4.1. The first draft's `MjSpec` jitter approach is abandoned, not shipped. |
| **A3** anchored switch, masked goal, task-stack-exact queue | **APPLIED** | Switch anchored to the detected cue frame, heading measured from the truth pose, goal channels lag the cue by 5 frames; queue completion requires oracle arrival at goal 2 then goal 1. |
| **A4** event counting, reference rows, one dev metric | **APPLIED** | Rising-edge emissions, at most one TP per gold event in the CAUSAL 1.0 s window, extras are FP, false-event rate = FP / emitted; ALWAYS-NONE and EVENT-EVERY-FRAME rows in 4.3; dev-selection metric is the harmonic mean of dev closed-loop success and dev narration F1 on a fixed dev-geometry slice; the checkpoint sha256 is frozen in §3 before any held-out run; latency rows carry host load and co-tenants. **Per-class held-out event counts are printed in 4.3 — where a class is under 200 the row is under-powered and says so.** |
| **A5** the last minute, explicitly | **PARTIAL** | The last-60-s channels were added (five age bins + two 60 s counters beside the K = 6 event tokens) and a C-h0 arm is reported, but C-h0 is an INPUT ABLATION of the same checkpoint, not a retrained model. Section 4.45 says so in the table's own caption. |
| **A6** proposals vs witnessed narration (`prop.*` head) | **NOT APPLIED** | A third head with `prop.replan` / `prop.resume_queued` / `prop.abandon` / `prop.clarify` gold at t + delta, scored raw and as executive-accepted, did not fit the wall budget. It is the largest un-run amendment and the natural first item for a follow-up. No `prop.*` claim is made anywhere. |
| **A7** witness table and vocabulary partition | **PARTIAL** | The witness table is below and H-MA1c is reported per partition in 4.3; `nav.progress` is INTERNAL-ONLY and is excluded from narration scoring entirely. The >= 20-episode cross-check against NAV-INT-1's live path was NOT run (that harness did not exist in this folder's tree at run time), so agreement between the headless teacher and the live runtime is UNVERIFIED here. No `TaskExecutive` is hosted; the teacher's receipts are `mission.status` / `command.note`. |
| **A8** the safety row | **APPLIED** | `cmd:stop` in ~12 % and `owner_speaking` in ~15 % of episodes; raw and post-filter rates in 4.5; stop is a held state until a new directive re-issues the goal. |
| **A9** cue-duplex, stated | **PARTIAL** | Stated: **Model A v0 is CUE-duplex** — router cue tokens at 10 Hz, no audio, no ASR, no jitter, cues delivered at a single frame with a 3-frame hold. DS-1 (20260828) is the speech-duplex follow-up. The ASR-timing rows (end-of-utterance vs partial-cue-at-first-content-word with 10 % retractions) were NOT run. |
| **A10** no authority | **APPLIED** | The false-event rate is reported as *predicted terminal with no backing receipt*; the bound is restated below. |

### 6.1 The exact channel list at closed-loop eval (A1)

47 categorical channels; act vocabulary 46 tokens (the product codec, no skills/emotes — this venue has no body gestures); narration vocabulary 43 tokens over 5 targets.

* **observation** — `own_vis`, `own_dist`, `own_bear`, `goal_kind`, `goal_target`, `goal_bear`, `goal_dist`, `progress`, `free0`, `free1`, `free2`, `free3`, `free4`, `free5`, `free6`, `free7`
* **owner_cue** — `dlg`, `cue`, `cue_conf`, `cmd`, `cmd_target`, `sound`
* **A_own_state** — `self_act`, `stop_state`, `replan_own`, `since_blocked`, `since_replan`, `since_cue`, `since_sound`, `since_owner`, `n_blocks_60`, `n_replans_60`, `hist0`, `hist1`, `hist2`, `hist3`, `hist4`, `hist5`
* **constant_in_this_venue** — `val`, `aro`, `own_gaze`, `own_motion`, `t_since_seen`, `base_busy`, `loc_health`, `env`, `people`
* **dropped_by_A1** — `plan_step (encoded the arrival label)`, `blocked (encoded the nav.blocked label)`, `replan (teacher-side count; replaced by replan_own)`

Nothing in the first three groups is a one-step copy of a label: the goal channels are geometry, the free-space ring is the venue's LiDAR, the cue channels are what the owner said, and every `A_own_state` channel is computed from A's own past emissions (`hist*` carries A's own narration tokens in closed loop, not the teacher's).

### 6.2 A7 witness table

| token | headless witness (what backs it here) | live-runtime receipt |
|---|---|---|
| `nav.arrived:<t>` | truth pose inside the goal region AND stopped >= 5 frames | `whisperer.KIND_MISSION_ARRIVED` (always band, critical) |
| `nav.failed:<c>` | episode step limit with no arrival | `KIND_MISSION_ENDED` |
| `nav.blocked:<c>` | truth minimum clearance below the reactive-safety stop band for >= 5 frames | `KIND_MISSION_BLOCKED` (middle band; the product debounces the block episode) |
| `nav.replan` | 3.0 s after a latched block with the goal still live | `KIND_REROUTE` |
| `nav.start:<t>` | the scripted owner's `cmd:go_to` cue frame | **research-only** — no receipt class exists |
| `nav.progress` | 5 s cadence while a goal is live | **INTERNAL-ONLY** — this is exactly `KIND_NAV_TICK`, the whisperer's NEVER band. It is never a narration claim and is excluded from every F1 in 4.3. |
| `plan.revised/queued/resumed:<t>` | the cue frame / the re-issue frame | **research-only** — `brain/executive.py` has suspend/resume/`request_interrupt` doors, but no queue POLICY and no whisperer class |
| `attend.sound:<b>`, `attend.owner` | authored gold from the scripted sound event | **research-only** — bounded by the awareness sweep's own yaw limits |

`plan.resumed` means **the original goal was RE-ISSUED after the amendment's terminal receipt** — the product's plan "resume" is a re-issue (the amendment transaction consumes the parked resume intent on commit), and the harness models it that way: `DirectiveNavigator.start(original_directive)`.

### 6.3 What this does NOT prove

* **The target vocabulary is bounded to five labels the teacher can reach** (`bench`, `lamppost`, `planter`, `sidewalk`, `crosswalk`). `tree` and `door` were measured at 0/16 for the shipped teacher and cut. Any success number here is a number about those five.
* **A's narration tokens carry no authority.** No consumer may narrate a terminal from them; they are predictions scored against gold, never receipts (A10).
* Kinematic base, no gait, no contact physics, no audio, no ASR, no real LiDAR noise beyond the venue's profile; the owner is scripted and the world has no pedestrians.
* A high score means the policy learned **the product teacher's behaviour on this generated city-block family** — and the teacher's own success rate on it is the ceiling, which §2 measures and which is low.
* The headless teacher's event sequence has NOT been shown to agree with the live runtime's receipts (A7's cross-check was not run).
* No `prop.*` proposal head exists (A6), so nothing here says anything about A proposing plan changes to the executive.

## 7. Housekeeping

* total wall: **1686.2 s** (0.47 h)
* process group 499316: 2 stray children signalled, 2 remaining -> **NOT CLEAN**. No sim subprocess was ever started; these are this run's own rollout Pool workers.
* AMENDMENTS.md at end of run: PRESENT — see the note beside each headline row.

