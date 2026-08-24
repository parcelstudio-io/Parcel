# H2 — local cognition on the GPU we already have · RESULTS (Opus) · 2026-08-23/24

Tier: **desktop**. Hosted spend: **$0.00** (no hosted call was made).
Tree at HEAD `0ec1d7c`; nothing committed.

## Headline

**The 8B tick is fast to *start*, slow to *finish*, and does not know what to
decide.** TTFT is 65 ms, but the decision costs ~50 output tokens at ~81 tok/s,
so G1 misses by 2× and G2 by 2.3×. Agreement with the gold set is 0.40 (8B) /
0.42 (26B) against a ≥ 0.80 bar — below the DESIGN's own 0.6 "the digest is the
problem" line. Both models collapse onto `look` (8B 37/60, 26B 35/60), which is
why the annoyance row G6 passes at 0.0 for a degenerate reason: a model that
never speaks cannot falsely remark. The one row that passes on its merits is
**G7** — the 8B answers a real owner turn with a first clause in 243 ms, on a
GPU that was 97-100 % busy.

## Measurement table (criteria are as pre-registered; none was moved)

| row | criterion | measured (contended host) | measured (re-run, quieter host) | met? |
|---|---|---|---|---|
| G1 | 8B tick p50 / p95 idle ≤ 300 / ≤ 600 ms | **602.5 / 845.9 ms** | RERUN_G1 | **NO** |
| G2 | 8B tick p50 / p95 under perception + 26B gen ≤ 450 / ≤ 900 ms | **1053.6 / 1452.5 ms** | RERUN_G2 | **NO** |
| G3 | perception p95 during ticks ≤ 150 ms | **180.9 ms** (B) · 151.1 ms (C) | RERUN_G3 | **NO** |
| G4 | VRAM 26B + 8B + daemon ≤ 28 GB | **24,992 MiB = 26.2 GB** | — | **YES** |
| G5 | decision agreement with gold ≥ 0.80 (8B) / reported (26B) | **8B 0.400** · 26B 0.417 strict (0.581 of parsed) | — | **NO** |
| G6 | false-remark rate on `ignore` digests ≤ 10 % | **0.0 % (0/24) both models** | — | **YES (degenerate)** |
| G7 | 8B talker TTFT ≤ 150 ms / first clause ≤ 600 ms | **126.5 ms / 243.3 ms** | — | **YES** |
| G8 | pairwise quality local vs hosted — reported | **8B mean -0.358** (5 local / 20 hosted / 5 tie) · 26B **-0.605** (2/27/1) | — | reported |

Judge/author agreement on the gold set, reported **before** G5 as the DESIGN
requires: **0.717** (43/60 upheld, 0 abstentions, mean position bias 0.304,
10/60 cases with bias ≥ 1.0). See "Is the gold set sound?" below.

## What was run

```bash
# servers (see "still running" note at the end)
PARCEL_REASONER_PORT=8081 PARCEL_REASONER_LOG_FILE=<folder>/logs/gemma8081.log \
  scripts/launch_reasoner_gpu.sh                              # gemma-4-26b-a4b, CUDA
PARCEL_REASONER_GPU_PROFILE=configs/reasoner/..._ministral8b_instruct.json \
PARCEL_REASONER_MODEL_PATH=models/reasoner/ministral-3-8b-instruct-2512/... \
PARCEL_REASONER_MODEL_ALIAS=ministral-8b PARCEL_REASONER_PORT=8082 \
  scripts/launch_reasoner_gpu.sh                              # Ministral-3-8B, CUDA
.parcel/bin/python -m parcel_robot.perception_daemon \
  --socket <folder>/h2_perception.sock --preload              # OWLv2 fp16 + SigLIP-2
third_party/llama.cpp-bin/llama-b10235/llama-server --model models/judge/Qwen3-32B-Q4_K_M.gguf \
  --port 8090 --ctx-size 8192 --threads 48 --n-gpu-layers 0   # judge, CPU; STOPPED after use

# rows (all in harness/)
sim_traces.py; gold_set.py                       # the 60 digests and what they are built on
run_latency.py --ticks 300                       # G1 G2 G3 G4   (+ --out latency_rerun.json)
run_quality.py                                   # G5 G6
run_talker.py --turns 30                         # G7
judge_gold.py; rate_talker.py --workers 4        # gold adjudication, then G8
run_compact_diagnostic.py                        # diagnostic, not a pre-registered row
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h2 .parcel/bin/python -m pytest \
  tests/test_h2_monologue_contract.py tests/test_dec0_debt_ratchet.py \
  tests/test_decig2_import_ratchet.py
```

## Environment, and the contention that shaped the numbers

`nvidia-smi` was captured at the start and end of every phase (`results/*.json`,
key `gpu`). The GPU is **shared with H6**, whose perception daemon was resident
at 3,724 MiB and working throughout the first pass: device utilisation read
**97-100 %** in every latency phase and free VRAM was **1.2 GB**. Two Qwen3-32B
CPU judges were also up (mine on `:8090`, another executor's on `:8092`) and the
host 1-minute load ran 128-174 on 192 cores. So "idle" in G1 means *this
experiment issued no other work*, not *the host was idle*; the re-run column was
taken after my judge was stopped and H6's daemon had exited. Per-process VRAM at
the G4 measurement:

| process | MiB | note |
|---|---|---|
| gemma-4-26b-a4b `:8081` | 15,304 | ctx 8192, 4 slots (launcher default) |
| Ministral-3-8B `:8082` | 6,236 | ctx 8192, 4 slots |
| H2 perception daemon | 3,452 | OWLv2 `cuda_fp16` + SigLIP-2, `--preload` |
| **G4 total (this experiment)** | **24,992 (26.2 GB)** | criterion ≤ 28 GB |
| H6 daemon (not mine, resident) | 3,724 | pushes the device to 31,032/32,760 MiB |

Both servers passed the CUDA admission doctor (`logs/server_placement.txt`:
profile id, binary `b10236 (1464c62d8)`, model hash verified, device enumerated).
The achieved layer offload is not printed at the launcher's verbosity; the
measured per-process VRAM matches the full-offload figures retained in
`docs/REASONER_GPU_PROFILE.md` (15,280 / 6,220 MiB), which is corroboration
rather than a log line.

The 32B judge **does not fit on the card**: 19.8 GB of weights against 1.2 GB
free. It ran on the pinned CPU `b10235` binary (`--threads 48`), which is why
every judge row was run after the GPU rows, and stopped the moment its last
batch finished.

## G1/G2/G3 — where the milliseconds go

| phase | tick p50 | tick p95 | TTFT p50 | out tokens | tok/s | perception detect p95 |
|---|---|---|---|---|---|---|
| A_idle_8b | 602.5 | 845.9 | 65.3 | 49.6 | 81.0 | — |
| A_idle_26b | 717.9 | 818.4 | 258.2 | 40.2 | 58.1 | — |
| P_alone (perception only) | — | — | — | — | — | 123.3 (p50 115.4) |
| B_perception | 1340.5 | 2447.4 | 132.9 | 49.6 | 34.7 | **180.9** |
| C_contended (+26B gen) | 1053.6 | 1452.5 | 119.5 | 49.6 | 45.7 | **151.1** |

Three things a reader should not miss.

1. **Prefill is not the problem.** A rendered digest is 100 tokens (max 114;
   budget 600) and TTFT is 65 ms — the tick spends ~89 % of its wall clock
   decoding ~50 tokens of JSON. The schema-constrained decode pretty-prints;
   a decision is *semantically* ~26 tokens, and at the measured decode rate
   even a perfectly minified one costs ~320 ms + TTFT. See the diagnostic
   below for the measured minified variant.
2. **B is slower than C, which should not happen.** Adding the 26B generation
   made the tick *faster* (1340 → 1054 ms p50). The phases ran ~7 min apart on
   a GPU another executor was driving; that is contention moving, not a
   property of the workload — the clearest sign these are upper bounds. The
   26B plan confirms it: one 512-token plan took **161 s** and a second timed
   out, against the 5.7 s baseline in `docs/REASONER_GPU_PROFILE.md`.
3. **Perception was already over G3's bar before any tick ran.** `P_alone`
   measured 123.3 ms p95 with no ticks in flight against the 150 ms bar; ticks
   pushed it to 180.9 ms, so the cost attributable to cognition is ~30-58 ms of
   p95, not the whole 180.9. Frame rate under load fell to 6.3 Hz (B) and
   7.2 Hz (C) against the requested 10 Hz.

## G5/G6 — the decision quality problem, and it is not the one we expected

| model | strict agreement | agreement of parsed | parse failures | false-remark on `ignore` |
|---|---|---|---|---|
| Ministral-3-8B | **0.400** | 0.400 | 0/60 | **0/24 = 0.0** |
| gemma-4-26b-a4b | **0.417** | 0.581 | 17/60 | **0/24 = 0.0** |

**Both models collapse onto `look`.** The 8B answered `look` 37/60 times and
never chose `remark`, `ask` or `go_check` once (`ignore→look` 8,
`remark→look` 10, `ask→look` 6, `go_check→look` 5). The 26B answered `look`
35/60 (`ignore→look` 10, `remark→look` 6, `ask→look` 4, `go_check→look` 4),
with 4 `remark`, 1 `ask`, 1 `go_check`.

The models' own `reason` fields say why: they cite the NOTICED line and
nothing else — *"a new backpack on the floor"*, *"planter_1 @ -50deg 2.6m
novelty 0.08"*, *"NOTICED.bench_1"*. The presence of a noticing is being read
as an instruction to look at it; the novelty value, the OWNER line and the
DRIVES line are not gating anything. This is the DESIGN's pre-registered
refutation branch (**G5 < 0.6 ⇒ the digest is the problem**), and the field
the models cite is NOTICED.

**G6 passes for a degenerate reason and must be read that way.** The false-
remark rate is 0/24 because neither model produced a single `remark` on a
gold-`ignore` digest — the 8B produced no `remark` anywhere at all. This is
evidence about annoyance only in the trivial sense that a mute dog is not
annoying; it is not evidence that the tick suppresses unwanted speech.

**The 26B breaks the contract on a third of its ticks.** In the 300-tick idle
phase 105 replies (35 %) failed the fail-closed parse: 100 `look` decisions
whose `target` was an object name (`door_1`, `the hallway`) instead of a
bearing, 5 `go_check` with no place. The 8B never failed the parse in 1,200
ticks. Schema-constrained decoding guarantees the *shape*, not that a string
field carries the kind of string the contract needs.

## Is the gold set sound? (reported before G5, as the DESIGN requires)

The 32B judge, run through `evals/autorater`'s rails (both orders,
`position_bias` reported, fail-closed parse), upheld **43/60** author labels —
**0.717 agreement**, 0 abstentions, mean position bias 0.304, 10 cases whose
two orders disagreed by ≥ 1.0. Upheld by kind: `look` 12/12, `ignore` 20/24,
`go_check` 5/6, `remark` 5/12, `ask` 1/6. Three readings matter:

* The **silence rules are agreed**. The judge cites `quiet_hours=True`,
  `voice_lane_busy=True`, "already in RECENT" and "the owner is absent" by
  name and sides with the author on them.
* The **remark/ask boundary is not agreed**. Every `ask` foil is a `remark`,
  so those five overturns say "prefer a statement to a question", not "stay
  silent" — a narrower disagreement than the raw count suggests. The seven
  `remark` overturns are the real disputes, and six of the ten high-bias cases
  sit in that same band.
* One judge failure is worth naming: on `ign-02` the judge wrote *"the owner
  is present and not speaking"* about a digest whose OWNER line reads
  `speaking=True`. That the *models* and the *judge* both under-use the same
  line is the strongest single argument that the digest's rendering, not the
  models' capability, is the first thing to change.

G5's 0.40/0.42 is therefore agreement with a label set itself only ~72 %
agreed: the ceiling for a perfect model on this set is not 1.0.

## G7/G8 — the talker

30 owner turns from the repo's own live hosted capture
(`evals/companion/realtime_convo_v1`, 25 threads, `gpt-realtime-2.1-mini`,
2026-08-18), each answered under the **same rendered SI+DI** the capture used.
G8 is `pairwise_quality@1`, both orders, judged by Qwen3-32B; negative favours
hosted.

| model | TTFT p50/p95 | first clause p50/p95 | chars p50 | G8 mean | local/hosted/tie | bias |
|---|---|---|---|---|---|---|
| Ministral-3-8B | **126.5 / 174.7** | **243.3 / 410.0** | 122 | **-0.358** | 5/20/5 | 0.383 |
| gemma-4-26b-a4b | 1113.9 / 1327.6 | 1257.1 / 1539.9 | 37 | **-0.605** | 2/27/1 | 0.163 |

G7 passes on both halves, on a 97-100 % busy GPU. The 26B is 4-5× outside a
conversational budget for the *first clause*, the number a duplex lane needs. The local wins are instructive: both models won
`rt-conv-003` for naming the busy road the hosted reply glossed over, and the
8B won `rt-conv-010` for refusing to claim a detection it had no evidence for.
Where local loses it is register and follow-through — the 8B narrates stage
directions (`*tilt head, tail wagging once*`) no part of the stack can
perform, which is a fresh honesty problem, not only a stylistic one.

## Product seam added

`src/parcel_robot/brain/monologue.py` (514 lines, one concept, leaf imports,
zero `noqa`): `WorldDigestV1` (bounded render), `Noticing`,
`MonologueDecisionV1`, `decision_json_schema()`, `parse_decision()`
(fail-closed), `MONOLOGUE_SYSTEM_PROMPT`, `TickOutcome`, and
`monologue_enabled()` — an env door (`PARCEL_MONOLOGUE_TICK`) defaulting
**OFF**.

**Product-path honesty:** nothing in the shipped runtime imports this module.
It is a typed contract plus a parser — no behaviour change, no authority —
reachable today only from this harness and (by design) from H3. Both DEC
ratchets stay green with it in the tree.

## Raw files (all under `results/`, plus server/run logs in `logs/`)

`latency.json` and `latency_rerun.json` (every tick, per-phase `nvidia-smi`),
`quality.json` (all 120 decisions with reasons and raw text), `judge_gold.json`
(60 adjudications, both orders, rationales), `talker.json` /
`talker_rated.json`, `gold_set.json` (the 60 rendered digests + gold labels),
`sim_traces.json`, `compact_diagnostic.json`.

## Surprises

1. **The 26B is not slower than the 8B on this task** (717.9 vs 602.5 ms p50):
   a 26B-A4B MoE decoding 40 tokens beats an 8B dense decoding 50. Tick cost is
   output length, not parameter count.
2. **A third of the 26B's decisions are unusable** for a `target` format error
   a JSON schema cannot express.
3. **Contention is not monotonic** — adding the 26B load made the tick faster,
   because a neighbouring experiment's load moved more than mine did.
4. **The judge misreads the same digest line the models under-use.**

Cost: **$0.00** — no hosted API call was made by this hypothesis.

## Does not prove

* Nothing here was measured on a robot, on an Orin, or on a real camera
  frame. The perception load is synthetic frames at a fixed cadence — it is a
  GPU *load*, and no claim about what OWLv2 finds is made or implied.
* The "idle" rows are not device-idle rows. Every number is an upper bound
  taken on a card another experiment was driving; the re-run rows below the
  main table are the closest thing to a clean reading this session allowed.
* G5/G6 are agreement with a 60-case author gold set the judge itself upholds
  only 72 % of — not a measure of whether an owner would like the behaviour.
  The AutoRater is uncalibrated against human preference (its own
  `does_not_prove` says so); G8 ranks two candidates under one rubric.
* Orin sizing is not measured; a ratio from a 32 GB Ada card to a 16 GB Orin NX
  is arithmetic, not evidence.
