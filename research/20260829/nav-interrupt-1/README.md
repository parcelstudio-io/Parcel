# NAV-INT-1 — instruction following with mid-task interruptions

Pre-registration: `DESIGN.md` (Fable, frozen before any run).
Binding amendments: `AMENDMENTS.md` (N1–N11; all applied except the
optional dynamic-city rows in N10 — see RESULTS.md).
Findings: `RESULTS.md`. Verdict: `VERDICT.md` (Fable, independent).

Evidence tier: **`desktop-sim`** — the MuJoCo static city driven through the
live `RobotRuntime.handle_text` product path, i.e. exactly the
`tests/test_voice_nav_e2e.py::_LiveRuntime` chain (transcript → intent route
→ local PlanSketch → PlanIR admission → TaskExecutive → NavigateTo →
grid navigation → terminal semantic verification). The local reasoner is the
deterministic `local_plan_sketch` lane: `build_runtime(..., use_llm=False)`,
so no LLM planner and no hosted call — **$0.00 spend, no hosted-live rows**.
Physical motion: **NO-GO**, unchanged. Nothing here gains authority.

## Reproduce

```bash
cd <repo>
unset TMPDIR                     # a long TMPDIR breaks the AF_UNIX sockets
.parcel/bin/python research/20260829/nav-interrupt-1/gen_tier.py           # deterministic; --check verifies freshness
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --all --seed 20260829
```

`--all` runs, in order: `controls` → `sequence` → `tier` → `classifier` →
`aggregate`, and writes `results.json`. Stages can be run one at a time (this
is how the recorded run was done, so a stage can be re-measured without
re-running the rest):

```bash
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage controls   --seed 20260829
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage sequence   --seed 20260829
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage tier       --seed 20260829 [--limit N --offset K]
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage sample     --seed 20260829   # renders sample_episode.txt
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage classifier --stage aggregate --seed 20260829
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage controls --only come_here --seed 20260829   # one goal's controls
```

The classifier stage needs no simulator and takes under a second:

```bash
.parcel/bin/python research/20260829/nav-interrupt-1/run.py --stage classifier --stage aggregate
```

Wall clock for the full sweep on this host: roughly 2–2.5 hours (one simulator
at a time, a fresh world per run). `run.py` never runs two sims at once and
traps teardown on every exit path.

## Files

| file | what it is |
|---|---|
| `harness.py` | `LiveSession` — sim subprocess + runtime + a 50 Hz sampler; the interruption scheduler (`wait_for_trigger`), the receipt timeline (`Receipt`), and the differential arrival authority (`score_arrival`, `owner_arrival`), all copied from the e2e pattern rather than imported from it |
| `gen_tier.py` | deterministic generator for the scenario tier (seed 20260829); `--check` fails if the JSON is stale |
| `interrupt_tier_v1.json` | the ADDITIVE 40-episode tier (`frozen_baseline: false`) + 5 from-rest controls + 10 from-rest sequence controls. Families: amend-cue 14 / explicit-directive 14 / queue 8 / hold 4 (amendment N5) |
| `queue_policy.py` | the harness-side plan-queue policy (H-NI1b) and the `{revise, keep, queue, clarify}` steering classifier (H-NI1c) |
| `gold_blind.json` + `gold_blind.sha256` | the VERIFIER's blind 110-case set (amendment N7). **The H-NI1c bar reads on this file only**; the sha256 is checked at scoring time |
| `gold.json` | the executor's own DEV set (60 pre-registered-shape cases + 30 supplementary). Reported for transparency; no bar reads on it |
| `run.py` | the runner and the aggregation; writes `results.json` |
| `results.json` | every headline number |
| `controls.jsonl`, `sequence_controls.jsonl`, `episodes.jsonl` | one line per run: the leg records, the 1 Hz track, the queue log and the FULL receipt timeline |
| `sample_episode.txt` | one episode printed end to end, with its receipt timeline |
| `RESULTS.md` | the findings against the pre-registered bars |

## Reading `episodes.jsonl` (one JSON object per episode)

| key | meaning |
|---|---|
| `family_class` | `amend_cue` \| `explicit_directive` \| `queue` \| `hold` (amendment N5) |
| `trigger` | where the interruption actually fired: `fired`, `progress`, `travelled_m`, `pose` |
| `steering_decision` | the H-NI1c classifier's call on the second utterance, with every feature |
| `admission` | H-NI1a. `held_pre_runtime: true` means the utterance never reached `handle_text` (amendment N9), so `admitted`/`latency_ms` are `null` BY POLICY, not by failure. `latency_ms` is the sampler-observed receipt; `inband_handle_text_ms` is the synchronous `handle_text` call |
| `amended_goal` | the leg that ran after the interruption, with `label`: `amended_goal` (the interruption was admitted), `goal_1_continued` (it was refused, the original goal kept running), `goal_1_uninterrupted` (queue family, held), `hold` (bare-cue HOLD row) |
| `switch_window` | amendment N6: cue − 2 s … cue + 10 s, sampled at 50 Hz. `min_clearance_m`, the sim's own collision flag, and the false-arrival test on goal 1 |
| `reissue` | the plan-queue policy's re-issue leg (amendment N1) — a fresh task, never a resume |
| `queue` | every policy decision, in order, with the classifier label beside the observed effect |
| `oracle_path_m`, `path_ratio_oracle` | amendment N8's reference: start → interruption pose → goal 2 → goal 1, straight line |
| `receipts` | the FULL executive receipt timeline, timestamped by the 50 Hz sampler |
| `track` | the 1 Hz pose polyline |

Every leg carries BOTH arrival authorities (`system_arrival`, `scorer_arrival`)
and their `authority_category`; `results.json → authority_disagreement` tallies
the disagreement class per goal separately, because it reproduces from rest and
is not an interruption effect.

## Host rules this experiment follows

* one simulator at a time, each on a unique short socket under
  `~/.cache/parcel-0e/ni1/` (AF_UNIX paths are capped at 108 bytes), launched
  under `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0` and
  `start_new_session=True`;
* teardown is trapped on every exit path and the run ends with a `pgrep`
  proof that no sim of ours survived (amendment N3; recorded in
  `results.json` under `orphan_check`);
* `TMPDIR` unset; `PARCEL_MEMORY_PATH` → scratch and `PARCEL_MEMORY_PURPOSE`
  never set to `owner`, so `parcel_memory.sqlite3` is never opened;
* the owner's `:8080` / `:8765` / `/tmp/parcel_sim.sock` are never touched;
* no pytest is run by this experiment, so the guard wrapper is not needed;
  nothing here is a test;
* the frozen `evals/nav_instruct` sets (v1–v4, v4s) are read only — this tier
  is additive and no digest moves;
* the NAV evals' held-out scene is never named anywhere in this folder, and
  `gen_tier.py` refuses to emit an utterance naming a place outside the
  static city's own landmark vocabulary (amendment N4).

## What this does NOT prove

Nothing about spoken audio (commands are text through `handle_text`, as in
the e2e), nothing about the hosted voice, nothing about a real robot. The
scene is the demo city. The plan-queue policy and the steering classifier
live in the harness: neither is a product seam, and neither is reachable
from the shipped runtime today.
