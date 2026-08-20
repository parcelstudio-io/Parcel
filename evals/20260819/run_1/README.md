# evals/20260819/run_1 — the common-sense eval pack

**Run:** `20260820T073858Z` · 2026-08-20 07:39:00Z → 07:47:27Z UTC
**Card:** `scrum/20260819/task_5/README.md` (E1) · **Status doc:**
`scrum/20260819/task_5/E1_STATUS.md`
**Proves the day's work:** R8 (narration wire), R9 (e-stop), R10 (arrival
semantics, `circle_owner` / `follow_owner`, orbit feasibility), R11 (the
situational whisperer).

This folder is written for a future auditor who has nothing but this folder.

---

## What was tested, and how

Six scenarios, each stating its claim before it ran, on **one sim process and
one real hosted session**. The owner's sentences went into the live session, the
hosted model chose the tools, the shipping broker routed them, the real body
moved on the real sim, and the whisperer decided what the robot was told about
its own state — all in the same process at the same clock.

That matters because it is the thing the day's cards had *not* done. R10 proved
the body with a recording broker and no model; R11 proved the model with a
recording lane and no body, and R11 open risk 9 says plainly that "the two
halves have never been run as ONE process". A pack whose transcripts and paths
came from different runs would be that seam again, one folder later.

* **Model:** `gpt-realtime-2.1-mini`, text modality, real provider.
* **System instruction:** `si-companion-v2`, profile `gentle_companion`
  (digest pinned in `manifest.json`). SI v2 does **not** mention `circle_owner`
  or `follow_owner` — the model found them from the tool schemas alone.
* **Whisperer knob:** the shipped defaults, `max_updates_per_minute: 2`,
  `min_gap_s: 15.0`.
* **Scene:** `city_block`, static.
* **Trajectory medium:** timestamped path JSONL at 10 Hz plus a hand-rendered
  top-down SVG per scenario. Video stays owner-gated — offscreen MuJoCo
  rendering is heavy and adds no auditability over paths plus transcripts.
* **Total measured cost:** **$0.129514** ($0.120762 for the run, $0.008752 for
  the pre-flight smoke test) against a $2 cap.

## Verdicts

| # | Scenario | Verdict | One line |
| --- | --- | --- | --- |
| 1 | `sidewalk-on-top` | **PASS** | Base ended at (1.388, 2.523) — centre *and* footprint inside the `sidewalk` polygon by scene truth |
| 2 | `door-etiquette` | **FAIL** | No shipped scene contains a door; the mission failed `semantic_target_not_found`. The ask-what's-next half passed |
| 3 | `orbit-feasible` | **PASS** | `circle_owner` → 354.7° swept around the owner, `orbit_complete` at progress 1.0 |
| 4 | `orbit-refused` | **PASS** | Boxed in, the validator refused; 0.0 m/s and 0.0° of sweep, and the model said why |
| 5 | `run-with-me-flex` | **FAIL** | Follow, pace intent and the speed caps all held; the pace-mismatch ask never fired |
| 6 | `whisperer-discipline` | **PASS** | 195 s, 92 telemetry offers, **0** telemetry forwards, 109 = 8 forwarded + 101 suppressed |

Two of six failed. They are recorded as failed, with their evidence and a defect
note in their `verdict.md`, because this is an audit record and not a brochure.
Failures become tomorrow's cards — see "Defects filed" below.

## Timing and cost, per scenario

| Scenario | Window UTC | Duration | Path samples | Decision rows | Cost |
| --- | --- | --- | --- | --- | --- |
| `sidewalk-on-top` | 07:39:00 → 07:39:25 | 25.33 s | 252 | 14 | $0.017230 |
| `door-etiquette` | 07:39:43 → 07:40:38 | 55.01 s | 550 | 15 | $0.016089 |
| `orbit-feasible` | 07:40:56 → 07:41:52 | 56.12 s | 560 | 47 | $0.012766 |
| `orbit-refused` | 07:42:10 → 07:42:37 | 26.81 s | 268 | 1 | $0.014776 |
| `run-with-me-flex` | 07:42:55 → 07:43:54 | 58.81 s | 587 | 24 | $0.015419 |
| `whisperer-discipline` | 07:44:12 → 07:47:27 | 195.04 s | 1948 | 109 | $0.038913 |

Between scenarios the body was stopped (`stay`) and the session left quiet for
18 s, so one scenario's min-gap and per-minute budget do not distort the next.
Those gaps belong to no scenario and are not in any slice.

## Session-level results

Facts that belong to the whole session rather than to one scenario:

* **`system_initiated_responses: 12`, `system_initiated_tool_calls: 0`.** Twelve
  times the robot started a reply off its own state and the model never once
  tried to call a tool inside it. R11's forced test had to narrow the declared
  surface and set `tool_choice: "required"` to reach the gate at all; under
  production conditions — full surface, `tool_choice: "auto"` — the model simply
  does not try. Both results are true and the gate is what makes the difference
  not matter.
* Broker: 5 calls, 4 executed, 1 rejected (the orbit refusal), 0 dropped,
  0 `system_initiated_motion_refusals` (nothing needed refusing).
* Lane: 0 reconnects, 0 stalls, 0 rollovers, 0 protocol errors, 21 usage rows.

## How to read a scenario folder

```
scenario_<name>/
  verdict.md            pass/fail against the claim, with the evidence and,
                        for a failure, a defect note for tomorrow
  transcript.json       every ledger row of the hosted session inside this
                        window (owner + robot), the broker calls, the usage
                        rows and the cost
  path.jsonl            one JSON object per line at 10 Hz: t_s, t_utc, base
                        x/y/heading_rad, owner_x/owner_y/owner_visible, plus
                        the nav / spatial / follow / block state at that instant
  path.svg              top-down render: region polygons and objects from
                        scene truth, the base track (blue) with heading spurs,
                        the owner track (orange, dashed), start and end
                        markers, refusal and block callouts, 1 m scale bar
  events.json           the runtime event ring and the mission log for the
                        window, plus `measurements` — the scenario's derived
                        numbers (containment, feasibility verdict, phases)
  whisperer_log.jsonl   R11's decision log, sliced to the window: every
                        forward AND every suppression with the deterministic
                        rule that fired
```

`path.jsonl`'s `t_s` is seconds since one monotonic origin shared by the whole
run, so tracks from different scenarios are directly comparable; `t_utc` is the
wall clock. `whisperer_log.jsonl`'s `at_s` is the runtime's own
`time.monotonic()` — the clock its debounce and min-gap actually run on — so
compare those rows against each other and use `t_utc` to align with the path.

**There is no `judge_decisions.jsonl`.** The card's scenario 6 named one, and
the card's own layout block carries the correction: R11's bench rejected the
judge band (deterministic debounce caught 11/12 gold facts with 0 spam;
judge-everything delayed an e-stop by 9.8 s), so v1 ships with no LLM anywhere
in the forwarding path. `whisperer_log.jsonl` records deterministic rule
firings, which is strictly more auditable — "why did the dog say that" has an
exact, reproducible answer, and so does "why did it stay quiet".

### The rule vocabulary in `whisperer_log.jsonl`

Forwarding: `always_band`, `critical_bypass`, `block_debounce_elapsed`,
`clear_after_forwarded_block`, `pace_mismatch_sustained`.
Suppressing: `never_band`, `whisperer_disabled`, `unknown_kind_fails_closed`,
`duplicate_within_dedup_window`, `min_gap`, `budget_exhausted`,
`block_debounce_holding`, `clear_without_forwarded_block`,
`middle_band_requires_a_mechanism`, `narration_floor_refused`.
All are module constants in `src/parcel_robot/realtime/whisperer.py`.

## How to re-run

The harness lives in the executor's scratchpad and is **not** committed; its
files are hashed in `manifest.json` so a future re-run can be compared against
this one byte for byte.

```
scratchpad/e1/e1_smoke.py       one cheap hosted turn — run this first
scratchpad/e1/e1_pack.py        boots the stack, runs all six scenarios
scratchpad/e1/e1_render.py      writes this folder from the recorded run
scratchpad/e1/e1_manifest.py    writes manifest.json last
```

1. `set -a; . ~/.config/parcel/realtime.env; set +a` for the credential.
2. `configs/robot.yaml` is **copied** to the scratchpad with only `memory.path`
   changed to a scratch sqlite file, and `PARCEL_REALTIME_CONFIG` is pointed at
   a scratch realtime yaml carrying the knob values above. The owner's
   `parcel_memory.sqlite3` and `~/.config/parcel/realtime.yaml` are never
   touched.
3. Sim spawn: `python -m parcel_robot.sim --socket <path>.sock --static-city`.
   The socket must live outside the scratchpad — `AF_UNIX` caps the path at
   ~107 bytes and the scratchpad root alone is 92.
4. `python e1_pack.py`, then `python e1_render.py <report>.json`, write the
   verdicts, then `python e1_manifest.py <report>.json`.

**Determinism, honestly.** The scene is static and the router and planner are
deterministic, so the *setup* reproduces from the spawn line. No RNG seed is
set. Live hosted replies vary by construction, so every verdict is scored on
tool routing, geometry and the decision log — never on exact wording. Scenario 5
is the live proof of why that distinction matters: it failed on a mechanism that
fired in two later re-runs of the same setup.

## Defects filed by this run

1. **No shipped scene contains a portal**, so R10's door etiquette has never
   executed end to end (`scenario_door-etiquette/verdict.md`). Blocks a claim
   the day's work was meant to make; the fix is a scene, and it touches the
   digest-pinned `scene_truth.json` and the packaged MJCF.
2. **The pace watcher is silently gated on the follow controller's best-effort
   owner-speed estimate**, which can be `None` for tens of seconds and produces
   no decision row when it declines (`scenario_run-with-me-flex/verdict.md`).
3. **`runtime._whisperer_digest` reads `follow_snapshot["distance_m"]`, a key
   that does not exist** (`FollowOwnerController.snapshot()` publishes only
   `desired_distance_m`), so `follow_distance_dm` is permanently 0 and
   `KIND_FOLLOW_TICK` is dead code (same verdict file).
4. **A block that was announced can have its clear swallowed by the budget**, so
   the owner is told the robot is waiting and never told it stopped
   (`scenario_whisperer-discipline/verdict.md`). Shipped design; needs the owner
   because it changes what the cost knob means.

## What this pack does not prove

* No live mission ever ended at a **door**, a **portal**, or a **person**
  terminal — `city_block` has none of them.
* The **in-region resampler** (R10's fix for the live `semantic_target_unreachable`)
  is very likely never reached in scenario 1: it runs only when the proxemic
  veto rejects tier 2, which needs dynamic tracks in the way.
* The **mid-orbit abort** never fired; scenario 4's refusal is admission-time.
* The boxed-in geometry in scenario 4 and the pedestrians in scenario 6 are
  **injected at `backend.observe`**. Everything below that seam is shipping
  code, and the card asks for scripted obstacles — but this scene cannot produce
  them from its own furniture.
* Audio was never in the loop: `mode: text` throughout.
* One hosted turn in scenario 2 answers an **injected** arrival fact and
  therefore says something untrue about the body. It is labelled in the log key
  and explained in that scenario's verdict; nothing in the shipping path can
  emit that fact without a real portal arrival.

## Frozen surfaces

`evals/20260819/` is new and owned by this card. Nothing under
`evals/companion/` was touched, `evals/nav_instruct/scene_truth.json` was read
and never written, and no source, test or config file was edited by this card at
all. The full `ci_gate --tier commit` — including `frozen-digest-sentinels` and
`release-parity` — was run after this folder was written; the verbatim output is
in `scrum/20260819/task_5/E1_STATUS.md` §6.
