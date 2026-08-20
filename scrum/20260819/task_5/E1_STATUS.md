# E1 task_5 — the auditable common-sense eval pack — EXECUTOR STATUS

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_5/README.md` ·
**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Depends on:** R8 (`20260819/task_1`), R9 (`20260819/task_2`), R10
(`20260819/task_3`), R11 (`20260819/task_4`) — all four closed before this card
ran. This card **edits no source**: it produces `evals/20260819/run_1/`.

> **Document discipline.** Written INCREMENTALLY, section by section, as each
> piece completes — the R8 lesson (an executor finished its code and died before
> writing anything down; reconstruction cost a day). Sections appear in the
> order they were finished, not in card order.

---

## §0 — What was read first, and what it changed about the plan

The card names four status docs to read BEFORE running, so the pack tests what
actually shipped rather than what was drafted. All four were read in full
(`R8_STATUS.md`, `R9_STATUS.md` + `R9_STATUS_SESSION_B.md`, `R10_STATUS.md`,
`R11_STATUS.md`), plus both cards' REVISED READMEs. Five facts changed the plan
before a line of harness existed:

1. **There is no judge.** The card's scenario 6 says
   "`judge_decisions.jsonl` accounts for every suppression", and the Rules say
   "real hosted model + real local judge". R11's bench **rejected** the judge
   band (`bench_whisperer.md`: deterministic B2 caught 11/12 gold with 0 spam;
   judge-everything delayed an e-stop by 9.8 s) and v1 ships with **no LLM in
   the forwarding path**. The card's own layout block already carries the
   revision ("the log is now rule firings, which is strictly more auditable"),
   so the file is `whisperer_log.jsonl` and it is `Whisperer.decision_rows()`.
   Recorded as deviation 1.
2. **The tool surface is `circle_owner` / `follow_owner(pace)`**, declared by
   R10 on the broker and routed through the existing validate→router→
   `_admit_local_sketch` chain. `navigate_to` gained an optional `relation`
   hint. Scenario 3/4/5 drive those names, not a fabricated `navigate_to`.
3. **The rule names in the log are R11's module constants** — `always_band`,
   `critical_bypass`, `block_debounce_elapsed`, `clear_after_forwarded_block`,
   `pace_mismatch_sustained`, `never_band`, `min_gap`, `budget_exhausted`,
   `duplicate_within_dedup_window`, `block_debounce_holding`,
   `clear_without_forwarded_block`, `unknown_kind_fails_closed`,
   `middle_band_requires_a_mechanism`, `narration_floor_refused`. Every
   `verdict.md` scores against those, not against a drafted vocabulary.
4. **Arrival semantics are the local table's, hybrid on relation only.**
   Region→`inside`, portal→`near` + `do_not_cross` + face-owner + ask-hint,
   object→`near`, person→social. FACE and terminal etiquette are never
   model-settable (R10 seed S13). Scenario 1 scores containment against
   `evals/nav_instruct/scene_truth.json`, the generated geometry table — NOT
   `observation.semantic_regions`, which R10 §5.1 records as a measurement that
   proves nothing (a robot standing on a sidewalk cannot see the whole polygon).
5. **`city_block` contains no door** (R10 open risk 1, owner-gated item 3;
   confirmed independently here — `scene_truth.json` derives 3 regions and 13
   objects, none a portal, and `configs/scenes/city_block.semantics.yaml` has no
   `door` prefix). Scenario 2's geometry half is therefore **not provable in any
   shipped scene**, and the scenario is planned as a FAIL with its evidence
   rather than quietly re-scoped. See §3.

### The one design decision this card made

**The scenarios run against a REAL hosted session on the REAL sim stack, in one
process.** R10 §5 and R11 §3/§5 each proved one half — R10's hosted proof used a
recording broker with no body, R11's live proof used a recording lane with no
provider — and R11 open risk 9 states plainly that "the two halves have never
been run as ONE process". An audit pack whose transcripts come from a recorder
and whose paths come from a different run would be exactly that seam again, one
folder later. So this pack boots the sim, builds the runtime with the realtime
lane ENABLED against the real provider, binds a panel token, and lets the hosted
model drive the body through the shipping broker. Every `path.jsonl` row and
every `transcript.json` row in this pack come from the same process at the same
clock.

### Files this card writes

`evals/20260819/run_1/**` (new, owned here) and this status doc. **Nothing under
`src/`, `tests/`, `configs/` or `evals/companion/` is touched**; the frozen
manifests, sentinels and the SI-v1 corpus are verified by the gate in §6.
Nothing committed, staged or stashed.

---

## §1 — The harness, and the one thing that had to be proved before it ran

Four scratchpad scripts, none of them in the repo (they are hashed into
`manifest.json` so a future re-run can be compared against this one):

| Script | What it does |
| --- | --- |
| `<scratchpad>/e1/e1_smoke.py` | One short hosted turn on the combined stack, before anything expensive |
| `<scratchpad>/e1/e1_pack.py` | Boots the sim + runtime, opens ONE hosted session, runs the six scenarios, records everything |
| `<scratchpad>/e1/e1_render.py` | Writes the pack folders, including the hand-rendered SVGs and the derived metrics |
| `<scratchpad>/e1/e1_manifest.py` | Writes `manifest.json` last, hashing every other file in the pack |

`configs/robot.yaml` was **copied** to `<scratchpad>/livework/robot_e1_<STAMP>.yaml`
with **only** `memory.path` changed to a scratch sqlite file (R5 deviation 6).
The owner's `parcel_memory.sqlite3` was never opened, and the owner's
`~/.config/parcel/realtime.yaml` was never read — `PARCEL_REALTIME_CONFIG` was
pointed at a scratch yaml carrying the shipped knob values verbatim
(`enabled: true`, `mode: text`, `model: gpt-realtime-2.1-mini`,
`whisperer: {enabled: true, max_updates_per_minute: 2, min_gap_s: 15.0}`).

### The smoke test, and why it came first

The combined stack is the thing R11 explicitly had not built, so it was proved
for **$0.008752** before the 15-minute run was allowed to spend anything. It
established every seam the pack depends on: the fail-closed arming gate accepts
`bind_panel_token`; `submit_realtime_text` opens a real session and starts the
driver crank; both sides land in the ledger; `broker.calls`, `lane.usage_rows`
and `Whisperer.decision_rows()` are all readable live; `backend.move_owner`
moves the owner mocap; and `spatial.assess_orbit` answers `feasible=True` in
open space (the no-false-refusal baseline §3's scenario 4 is measured against).

### Two harness bugs found and fixed before the real run

1. **The orbit terminal predicate was wrong.** The first draft waited for
   `spatial.state in {"running", "active"}`; the real vocabulary is the ORBIT
   PHASE (`idle` / `approach_ring` / `orbit`) while running, and the runtime
   overwrites `state` with `completed` / `failed` / `cancelled` only at the
   terminal. Waiting on a state that never occurs would have recorded a 25 s
   stub of a 60 s orbit and called it a scenario. The predicate is now
   `spatial_detail["enabled"]`, which is written by the same code path in both
   directions.
2. **A straight 12 s run at 2.2 m/s does not fit in this scene.** The first
   `run-with-me-flex` draft walked the owner 26 m in one leg; the sim clamps
   mocap position at ±10 m, so the owner would have parked against the clamp
   and the recorded "run phase" would have been a stationary owner with a
   commanded speed in the notes. The owner now bounces between x = −5.5 and
   x = 5.5 in the empty road corridor, so the 2.2 m/s is real in the path
   deltas rather than asserted in a comment.

---

## §2 — The run, and the verdict table

One sim process, one hosted session (`rt_03cbba51af73`), 2026-08-20
**07:39:00Z → 07:47:27Z**. Model `gpt-realtime-2.1-mini`, text modality, SI
`si-companion-v2` / `gentle_companion`. Report:
`<scratchpad>/e1/e1_run_20260820T073858Z.json`.

| # | Scenario | Verdict | Evidence in one line |
| --- | --- | --- | --- |
| 1 | `sidewalk-on-top` | **PASS** | ended `(1.3881, 2.5235)`, centre **and** footprint inside `sidewalk` by scene truth; `arrived_verified` |
| 2 | `door-etiquette` | **FAIL** | `semantic_target_not_found` — no shipped scene has a door. The ask half passed |
| 3 | `orbit-feasible` | **PASS** | `circle_owner` → **354.7°** swept, `orbit_complete`, progress 1.0 |
| 4 | `orbit-refused` | **PASS** | refused at admission; **0.0000 m/s**, **0.0°** swept; 6 blocked arcs at 0.196 m |
| 5 | `run-with-me-flex` | **FAIL** | caps held (0.3534 m/s at 1 s vs 0.35); `pace_mismatch` **never fired** |
| 6 | `whisperer-discipline` | **PASS** | 195 s, 92 telemetry offers, **0** telemetry forwards, 109 = 8 + 101 |

**4 PASS / 2 FAIL.** Both failures are recorded as failures with their evidence
and a defect note; neither was re-rolled until it passed. Scenario 5 in
particular fired correctly in two later control re-runs of the same setup, and
the recorded FAIL stands — the card's rule is that this is an audit record, and
a green row obtained by throwing the dice again is worth nothing.

### Session-level results, which belong to no single scenario

* **`system_initiated_responses: 12`, `system_initiated_tool_calls: 0`.** Twelve
  times the robot started a reply off its own state and the model never once
  attempted a tool call inside one. R11 §3.2 had to narrow the declared surface
  AND set `tool_choice: "required"` to reach the C1 gate at all; under
  production conditions the model simply does not try. Both results are true and
  the gate is what makes the difference not matter.
* Broker: 5 calls, 4 executed, 1 rejected (the orbit refusal), 0 dropped,
  0 `system_initiated_motion_refusals` (nothing needed refusing).
* Lane: 0 reconnects, 0 stalls, 0 rollovers, 0 protocol errors, 21 usage rows.
* **Every hosted tool call was the right tool.** `navigate_to` ×2,
  `circle_owner` ×2, `follow_owner` ×1 — **0 fabricated `navigate_to` places**,
  against the bench's 5/6 fabrication rate with the tool-surface hole open. SI
  v2 still does not name `circle_owner` or `follow_owner`; the model found both
  from the schemas.

### Costs

| | USD |
| --- | --- |
| Pre-flight smoke (1 hosted turn) | 0.008752 |
| The six-scenario run (21 usage rows) | 0.120762 |
| **Receipted total** | **0.129514** |
| Cap | 2.00 |

One diagnostic re-run against the real provider (`e1_pace_rerun.py --hosted`,
two turns) did **not** record its usage rows — at the rates measured across the
21 receipted rows it is worth roughly $0.02–0.03. It is excluded from the total
above rather than estimated into it, and `manifest.json` says so.

---

## §3 — What the run found

### Finding 1 — the door claim is blocked by the absence of a scene, not by code

`city_block` has no portal: `scene_truth.json` derives 3 regions and 13 objects,
none of them a door, and the semantics sidecar declares no `door_` prefix. The
live mission ended `semantic_target_not_found`, which is the honest answer.
R10's door etiquette — `near` + `do_not_cross` + face-the-owner + ask-hint — is
pinned at the table, at the planner, and by seeds S6/S7/S9, and the SENTENCE it
generates is proved to work on the live model here (the model asked what to do
next, against a bench baseline of 0/12 chat and 0/6 injected). The GEOMETRY
between them has never run. This is R10 open risk 1 and owner-gated item 3;
this pack is the evidence that it blocks a claim the day was meant to make.

### Finding 2 — R11's pace watcher is inert when the owner-speed estimate is absent, and says nothing about it

`scenario_run-with-me-flex` recorded 24 decision rows, all `never_band`, and
**zero `owner_pace_change` rows**. That last number is the diagnostic: the differ
emits `owner_pace_change` on any change of the owner's speed BAND, `None → value`
included, so zero of them means `digest.owner_speed_mps` was `None` for the
whole 58.8 s window — while `path.jsonl` shows the owner verifiably at 2.2 m/s
for 12 s and then 1.0 m/s for 22 s, and `follow_pace_intent` was `"run"`.
`_pace_watch` gates on `digest.owner_speed_mps is not None`, treats `None`
exactly like "still running", and writes **no row at all** when it declines.

Two control re-runs (`<scratchpad>/e1/e1_pace_probe.json`,
`e1_pace_rerun_hosted.json`) both fired `pace_mismatch_sustained` with the full
composed item, one with no lane and no sampler, one under the recorded
conditions. So the mechanism is reachable and the failure is **intermittent**.
The offline probe shows the shape directly: `heading_available` went `False` for
a continuous **10 seconds** across the run→walk transition before recovering.

The defect is not "the estimator is imperfect" — it is that a feature the owner
experiences as *the dog notices when I slow down* is silently gated on a
best-effort estimator with no floor, no timeout, and **no row in the decision
log**, which is the one artifact whose entire purpose is answering "why did the
dog stay quiet". Minimum fix: carry availability into `StateDigest` and record a
`pace_unknown` suppression. Filed for tomorrow.

### Finding 3 — a digest field that reads a key that does not exist

`runtime._whisperer_digest` does `distance = follow_snapshot.get("distance_m")`,
but `FollowOwnerController.snapshot()` publishes no `distance_m` — its only
distance key is `desired_distance_m`. So `follow_distance_dm` is permanently 0
and `KIND_FOLLOW_TICK` can never fire. Confirmed by probe: **40 s of continuous
following produced 0 `follow_tick` rows** and `digest_follow_distance_dm` was 0
on all 40 samples. Blast radius today is nil — `follow_tick` is never-band, so
"never fires" and "always suppressed" are indistinguishable to the owner, which
is exactly why it survived 36 seeds and a live proof. One-line fix plus a seed
that mutates the key name.

### Finding 4 — an announced wait can lose its closure to the cost knob

Scenario 6, block episode 4: the block held 8.32 s, forwarded
(`block_debounce_elapsed`) as *"…it has stopped and is waiting… tell the owner
what is in the way and that you are waiting for it to clear"*, and 1.1 s later
its `mission_block_clear` was suppressed with rule `budget_exhausted`. This is
the shipped design and R11's comment states the choice deliberately — a closure
is min-gap exempt but not budget exempt — but the owner experiences it as the
robot opening a conversational pair and never closing it. Policy decision, not a
bug fix; owner-gated.

### Finding 5 — an injected fact makes the model say something untrue, faithfully

Scenario 2's portal arrival is injected (there being no door), and the model
answered it with *"I stopped just short of the door, turned to face you…"* — a
false statement about the body, faithful to the fact it was handed. Nothing in
the shipping path can emit that fact without a real portal arrival, so this is
not a live defect; it is recorded because an auditor reading the transcript
alone would read it as the robot lying. The whisperer log key names the
injection (`mission_arrived:the door (E1 injected arrival)`) precisely so that
cannot happen silently.

### Smaller thing, filed as a risk rather than a defect

The model added an unsupported clause to one arrival in scenario 6 — *"I'm now
standing in the crosswalk. I can't move past it unless something changes."* The
fact said only that it was standing inside the crosswalk. R11's honesty guard
covers the pace item; arrivals have no equivalent.

---

## §4 — Deviations, each with its reason

1. **`whisperer_log.jsonl`, not `judge_decisions.jsonl`.** The card's scenario-6
   text and its Rules line ("real hosted model + real local judge") predate the
   bench that rejected the judge band; the card's own layout block carries the
   revision. There is no judge and no LLM anywhere in the forwarding path, so
   the log is R11's deterministic rule firings. Recorded in `manifest.json`
   under `models.judge_note` so the discrepancy is answered inside the pack.
2. **Scenario 6's missions were issued through the LOCAL text door**
   (`runtime.handle_text`), not the hosted session. The claim is about a QUIET
   session: the owner must say nothing to the model for the window while the
   body keeps producing telemetry. Driving the body locally is the only way to
   have both. Stated in that scenario's `verdict.md`.
3. **Scenario 2's portal arrival fact is injected** through the real whisperer
   and the real lane, because no shipped scene has a door. The decision-log key
   names the injection.
4. **Scenario 4's boxed-in geometry is injected at `backend.observe`** — six
   person tracks on a 1.45 m ring. The card asks for scripted obstacles; this
   scene cannot produce them from its own furniture (R10 §5.4: 24/24 live
   admissions). Everything below the seam is shipping code.
5. **The verdicts were written by hand, not by the harness.** `e1_render.py`
   emits the derived metrics into the scratchpad and the six `verdict.md` files
   were written against those numbers afterwards. A pass/fail rule inside the
   recorder would have been a rule I wrote before seeing the evidence.
6. **`manifest.json` is excluded from its own inventory** (it cannot hash
   itself). The exclusion and a one-line verification command are both in the
   file.
7. **The sim socket lives at `/tmp/claude-1000/` rather than the scratchpad.**
   `AF_UNIX` caps the path at ~107 bytes and the scratchpad root alone is 92
   (R10 deviation 6). Only the socket moved; every artifact is in the scratchpad
   or the pack.
8. **One diagnostic hosted re-run was not cost-instrumented** (§2). Reported as
   uninstrumented rather than folded into the total as an estimate.

Nothing was committed, staged or stashed. No file under `src/`, `tests/` or
`configs/` was opened for writing at any point — `git status --short` is
byte-identical to the state R11 left, plus one new untracked directory,
`evals/20260819/`.

---

## §5 — The pack as written

```
evals/20260819/run_1/
  README.md                            what was tested, how to re-run, verdicts
  manifest.json                        scenarios, model ids, SI version+digest,
                                       input digests, costs, clock provenance,
                                       determinism/spawn/harness, 37-file sha256
                                       inventory
  scenario_sidewalk-on-top/            transcript.json path.jsonl path.svg
  scenario_door-etiquette/             events.json whisperer_log.jsonl verdict.md
  scenario_orbit-feasible/             (six files each, exactly the card's
  scenario_orbit-refused/               binding layout)
  scenario_run-with-me-flex/
  scenario_whisperer-discipline/
```

38 files, 37 in the inventory (`manifest.json` cannot hash itself). The
inventory verifies:

```
cd evals/20260819/run_1 && python -c "import hashlib,json;m=json.load(open('manifest.json'));\
print(all(hashlib.sha256(open(r['path'],'rb').read()).hexdigest()==r['sha256'] for r in m['inventory']))"
True
```

**The SVGs are hand-built strings**, no new library, as the card requires: scene
truth region polygons and object discs, the base track with heading spurs every
2 s, the owner track dashed, start/end markers, refusal and block callouts, a
1 m scale bar, a legend, and the verdict headline burned into the footer so a
reader who opens only the SVG is never left guessing. Three rendering defects
were found and fixed by measuring rather than eyeballing (there is no
rasteriser on this machine): a footer subtitle that ran ~240 px past the
viewBox, nine object labels whose centres were off-canvas, and a refusal callout
that overhung the left edge. A checker asserts every `<text>` element's
estimated box lies inside the viewBox; it now reports **0 overflows across all
six renders**.

---

## §6 — `ci_gate --tier commit`, verbatim, after the final edit

Read before pasting. The last pack write (`manifest.json`, 08:04Z) preceded the
run; nothing was edited while it ran. **`frozen-digest-sentinels` and
`release-parity` are the two the card names as proof that the frozen evals
surfaces survived, and both are green.**

```
CI GATE — tier=commit  (2026-08-20T08:07:46Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.76s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.35s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.32s
[  PASS] HARD  default-suite              6601 passed, 9 skipped, 42 deselected, 5 warnings in 246.29s (0:04:06)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 259.2s
```

**6601 passed — identical to R11's closing number.** This card added no tests
and removed none, which is what "edits no source" should look like in the gate.

### Confirming re-run, after this status doc was written

The run above quotes itself, which is circular, so the gate was run once more
with every artifact of this card on disk — the pack AND this document — in case
anything walks `scrum/**`. Same result, `default-suite` 6601 again:

```
CI GATE — tier=commit  (2026-08-20T08:13:28Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.76s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.38s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6601 passed, 9 skipped, 42 deselected, 6 warnings in 243.94s (0:04:03)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 256.9s
```

### No seeds, and why that is right here

The card says so explicitly ("for this card: no seeds — it edits no source").
FIX-A seeds prove a TEST would catch a regression in code the card wrote; this
card wrote no code. The equivalent discipline here is that every verdict cites a
measurement in a file in the pack, and that two scenarios were allowed to fail.

---

## §7 — Open risks and honest limits

1. **Two of six claims are unproven, not merely unproved today.** The door
   etiquette needs a scene that does not exist (Finding 1), and the pace ask is
   intermittent for a reason that lives in the follow controller (Finding 2).
2. **No live mission ever ended at a portal, or at a person terminal.**
   `city_block` has neither class. The arrival table's `near`/social rows are
   unit-tested and unexercised.
3. **The in-region resampler is very likely never reached** in scenario 1: it
   runs only when the proxemic veto rejects tier 2, which needs dynamic tracks
   between the robot and the region. Nothing stood in the way in this run, so
   the fix for the live `semantic_target_unreachable` is still proved only by
   R10's seeds S2–S5.
4. **The mid-orbit abort never fired.** Scenario 4's refusal is admission-time;
   `_lookahead_feasibility` is covered by seeds only.
5. **Two scenarios inject at `backend.observe`** (the crowd, and scenario 6's
   pedestrians arriving through real navigation). Everything below the seam is
   real; nothing proves this scene's own furniture can produce that geometry.
6. **Audio was never in the loop.** `mode: text` throughout, so the acoustic
   path, barge-in and the sink-ownership law are untested here.
7. **The pack is one run.** Scenario 5 is the proof that a single run is a
   sample, not a law: the same setup produced a different result twice
   afterwards. Anything read from this folder as a rate rather than as an
   existence proof is being over-read.
8. **The costs are the estimator's**, `realtime_spend_usd` at assumed rates, not
   a provider invoice.
9. **`whisperer_log.jsonl`'s `at_s` is raw `time.monotonic()`** and shares an
   origin with the process, not with the path's `t_s`. Rows are comparable to
   each other; cross-artifact alignment goes through `t_utc`. Recorded in
   `manifest.json` under `clock_provenance` rather than silently left for an
   auditor to trip over.

---

## §8 — Final state

* `evals/20260819/run_1/` exists in exactly the card's binding layout: README,
  manifest with a 37-file sha256 inventory, six scenario folders of six files
  each. The README's verdict table is filled.
* `ci_gate --tier commit`: **PASS**, every hard gate green, run after the last
  pack write (§6). 6601 passed / 9 skipped — unchanged from R11's close.
* **Frozen surfaces intact:** `frozen-digest-sentinels` (4 immutable manifests
  byte-identical to pin) and `release-parity` (91 packaged assets byte-identical)
  both green. `evals/companion/` was never opened;
  `evals/nav_instruct/scene_truth.json` was read and never written.
* **Verdicts: 4 PASS / 2 FAIL**, both failures recorded with evidence and a
  defect note rather than re-rolled.
* **Receipted live spend: `$0.129514`** of the $2.00 cap (plus one
  uninstrumented two-turn diagnostic, ≈$0.02–0.03, excluded rather than
  estimated in).
* No source, test or config file was edited. Nothing committed, staged or
  stashed. The owner's `parcel_memory.sqlite3` and
  `~/.config/parcel/realtime.yaml` were never touched; the owner's stack was
  never probed.

### Defects filed for tomorrow

1. **A scene with a portal.** R10's door etiquette cannot be proved end to end
   without one; the fix touches the digest-pinned `scene_truth.json` and the
   packaged MJCF, so it is a card of its own.
2. **Carry owner-speed availability into `StateDigest` and log a `pace_unknown`
   suppression.** Today the pace watcher declines silently and the decision log
   — the artifact that exists to answer "why did the dog stay quiet" — has no
   row. Separately, why the follow controller's heading estimate drops out for
   ten seconds at a pace transition is its own investigation. Neither may move a
   follow safety cap.
3. **Fix `_whisperer_digest`'s `follow_snapshot["distance_m"]`** (the key is
   `desired_distance_m`), with a seed that mutates the key name and reddens a
   `follow_tick` test.

### Owner-gated list (nothing here was done)

1. **A block that was announced can lose its closure to the per-minute budget**
   (Finding 4). Making a clear inherit its block's entitlement changes what the
   cost knob means, so it is the owner's call.
2. **Video as a trajectory medium.** Paths + transcripts were chosen and the
   card gates video on the owner; offscreen MuJoCo rendering is heavy and adds
   nothing this pack lacks.
3. **An arrival honesty guard.** The model added an unsupported clause to one
   arrival (§3, smaller thing). R11's guard covers the pace item only; whether
   arrivals need the same treatment is a design decision.
4. **SI v3.** Still stale — it does not name `circle_owner` or `follow_owner`.
   The model routed both correctly from the schemas alone in this run, which
   narrows the risk without closing it (R10 owner-gated item 1).
