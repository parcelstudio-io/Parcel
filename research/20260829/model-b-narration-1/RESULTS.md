# MB-1 — RESULTS

Executor: Opus (parcel session for MB-1), 2026-08-29. `DESIGN.md` is frozen;
`AMENDMENTS.md` is PRE-RUN and BINDING and wins wherever the two differ. No
verdict is written here — `VERDICT.md` is Fable's.

Written **incrementally**, in the order the rows were produced: scripted
(`$0.00`) → local (`$0.00`) → hosted (metered). Nothing below was back-filled
after a later row was known.

Evidence tiers, labelled and never blended:

| stage | tier | what the model was |
|---|---|---|
| scripted | `replay` | a **real** `RealtimeLane` over the product's `fake_server` frames, answered by a deterministic responder — a harness proof, not a model result |
| local | `replay` | `Qwen2.5-7B-Instruct-Q4_K_M` on a `llama-server` this card started on `:8093` |
| hosted | `hosted-live` | `gpt-realtime-2.1-mini`, `mode: text`, through the product runtime, every response priced in the wave ledger |

Physical motion: **NO-GO**, unchanged. Nothing here gains authority.

---

## 0. What was built, and what it is measuring

Model B is two functions over typed inputs.

**Steer** — `steer(utterance, queue) → {revise, keep, queue, clarify}` plus the
executive call it would realize. It reuses `voice/closed_intents.py` and
`voice/amendment.py` read-only and adds the two things the product does not
have: a **queue** decision ("after that, check the bench" → push behind the
running head, no executive call until it completes) and
**clarify-with-plan-context** (an ungrounded referent produces a question that
names what is already in the queue).

**Narrate** — the plan-queue whisper: an ordered `{goal, status, since_s,
task_id}` list plus the last receipt, rendered inside the shipped
`UNTRUSTED_DATA_BEGIN/END` delimiters, sent as a conversation item with its own
purpose string (`"plan queue"`), **replacing** the previous one, with **no**
`response.create`. Robot-initiated speech follows the pre-registered trigger
table, gated by the whisperer's own band discipline.

Arm D is amendment M6's redefinition: **the product whisperer's forwarded events
as shipped**, composed by `realtime/whisperer.py` at the runtime's own call
sites. The `≤ 0.6` figure from QEV-1 is dropped, as M6 requires; arm D is
measured fresh on every stage.

### Corpus (`events.py`)

40 scenarios = 8 families × 5 demo-city place-sets, all receipts in the wave's
shared fact vocabulary.

| | |
|---|---|
| scenarios | 40 (`clean, blocked, failed, queued, resumed, clarification, cancelled, keys`) |
| receipts | 235 — accepted 65, running 85, completed 55, blocked 10, resumed 10, failed 5, cancelled 5 |
| gold **narratable** receipts | 155 |
| owner turns | 110 — gold steer: revise 75, keep 25, clarify 5, queue 5 |
| keys turns | 15 |
| places | the bench, the crosswalk, the door, the lamppost, the sidewalk, the sofa, the tree |

`events.assert_places_admissible()` refuses the NAV held-out scene by
**importing** `evals.nav_instruct.scene_truth.HELD_OUT_SCENE_ID`; the name is
never written in this folder.

### Steer, against the corpus's gold labels

**110 / 110 = 1.000.** Deterministic, no model, no seed dependence
(`.parcel/bin/python research/20260829/model-b-narration-1/steer.py`).

This is a self-consistency check and is reported as one: the gold labels are
this card's, on this card's corpus. NAV-INT-1 measures the decision against the
shipped stack; MB-1 only needs `steer` to be a stable input to the wording.

### The narration decision ledger (amendment M6's reporting requirement)

`results/narration_decisions.json`, model-free and regenerable
(`run.py --decisions`). Bands read from the wave `realtime.yaml`:
`max_updates_per_minute: 2`, `min_gap_s: 15.0` — the conservative shipped
defaults, not the prototype 6 / 4.

| arm | forwarded | suppressed | by which rule |
|---|---|---|---|
| **Q** (trigger table) | 70 | 165 | `context_only` 165 |
| **D** (product whisperer) | 85 | 65 | `never_band` 55, `block_debounce_holding` 10 |

Arm D's 85 forwards are `critical_bypass` 65 (55 arrivals + 5 failed +
5 cancelled), `block_debounce_elapsed` 10, `clear_after_forwarded_block` 10.

**Injected tokens per refresh (amendment M1's row): 156.3 approximate tokens,
235 refreshes, ~36 700 tokens over the corpus.** The measured figure from the
hosted ledger is in §3.

Two facts about the shipped whisperer that shape arm D and were verified at HEAD
on 2026-08-29:

1. **The product has no whisperer class for a plan acceptance.** `_diff` turns a
   `nav_state` change into `nav_tick`, which is in the NEVER band, and a
   `nav_goal` change produces nothing at all. So arm D structurally cannot
   acknowledge a new goal from a receipt — its 55 `never_band` suppressions are
   exactly those events. This is the finding, not a harness limitation.
2. **`KIND_REROUTE` is dead code.** It is declared, banded ALWAYS, listed in
   `CRITICAL_KINDS`, given a HINT and exported — and no product code anywhere in
   `src/` ever constructs one. Arm D therefore gets no sentence when the owner
   revises a goal mid-trip, and MB-1 does not invent one on its behalf.

---

## 1. Scripted rows — the harness, proven before any money (`replay`, $0.00)

A **real** `RealtimeLane` over an in-process transport pair, answered by a
dynamic server built on the product's own `fake_server` frame builders. The
responder is not a language model and does not pretend to be one; its job is to
prove that the plan-queue item reaches the wire, that the trigger table fires
exactly one `response.create`, that the reply comes back through the lane, and
that the scorer's bars can be **both met and missed**.

`results/fake.json`, `transcripts/fake.jsonl`.

| | arm Q | arm D |
|---|---|---|
| robot turns | 180 | 185 |
| grounding (turn-level) | **1.000** [1.000, 1.000] | 0.885 [0.808, 0.948] |
| coverage of narratable events | **0.969** | 0.769 |
| claims / turn | 1.361 | 0.892 |
| zero-claim turns | 20 | 20 |
| b1 new goal acknowledged | 75/75 = **1.00** | 50/75 = 0.67 |
| b2 completion announced | 55/55 = **1.00** | 55/55 = **1.00** |
| b3 resume offer | 10/10 = **1.00** | 0/10 = 0.00 |
| b4 premature claims | 0/180 = **0.000** | 0/185 = **0.000** |
| b5 keys turn | 15/15 = 1.00 | 15/15 = 1.00 |
| invented actions | 0 | 0 |

Wire counts: arm Q sent 240 conversation items and 180 `response.create`s; arm D
sent 85 items and 190 `response.create`s.

**The harness is proven in both directions.** Arm D's 0.885 grounding is not
noise: the scripted responder composes a *cancelled* terminal as a failure
("I couldn't get to — the trip ended"), the scorer catches it as an unsupported
`failed` claim on the 5 cancelled scenarios, and that is a real overclaim on a
real sentence. A scorer that only ever passes is worth nothing; this one fails a
sentence a human can read and disagree with.

Latency is not reported for this stage — the responder answers in ~0.1 ms and
the number would be about Python, not about narration.

---

## 2. Local rows — H-MB1d (`replay`, $0.00)

`Qwen2.5-7B-Instruct-Q4_K_M` (4.4 GB, well inside amendment M9's ≤ 10 GB), on a
`llama-server` this card started on `:8093` and killed by process group on every
exit path. `results/local.json`, `transcripts/local.jsonl`.

**Deviation from M9, recorded rather than hidden:** the vendored llama.cpp build
(`third_party/llama.cpp-bin/llama-b10235`) ships CPU backends only — the
directory contains `libggml-cpu-*.so` and no `libggml-cuda`. `--n-gpu-layers 99`
was passed and had no effect; `nvidia-smi` showed the GPU untouched throughout.
The local row is therefore **CPU**, on a host running at load 18-42. Its TTFT
numbers should be read as an upper bound for this quant, not as the GPU figure
M9 anticipated.

| | Q-local | D-local |
|---|---:|---:|
| robot turns | 180 | 185 |
| grounding | 0.9637 [0.9350, 0.9887] | 0.9000 [0.8662, 0.9338] |
| coverage | 0.5225 | 0.2263 |
| new-goal acknowledgement | 18/75 | 8/75 |
| completion announcement | 51/55 | 20/55 |
| resume offer | 2/10 | 0/10 |
| keys inability bar | 0/15 | 4/15 |
| invented actions | 6 | 12 |
| TTFT p50 / p95 | 633 / 1,658 ms | 155 / 411 ms |

Q-local grounds most claims but does not cover enough required events and
misses the 400 ms TTFT gate. H-MB1d is refuted.

---

## 3. Hosted rows — complete Q, quota-truncated D (`hosted-live`)

Primary artifacts: `results/hosted-QD-full.checkpoint.json` and
`results/hosted-QD-full.json`. Recovery details and hashes are in
`RECOVERY.md`; the independent deterministic verifier is
`results/hosted-QD-full.verification.json` (`PASS`).

The scheduled 240 scenarios are **122/240 complete**: Q is 120/120; D is
2/120. The provider's daily request quota stopped the run before D scenario 3
and the incomplete row has byte-identical ledger-before/after snapshots. D is
not compared with Q.

The first process lost its in-memory Q results after 119 scenarios. Those
transcripts were recovered from the isolated research database. Response-slot
timing was unique for 50 sessions and ambiguous for 69; all possibilities were
enumerated. The published Q point uses the pessimistic assignment. The range
below spans pessimistic through optimistic assignments, so the verdict does
not depend on choosing one.

| hosted Q, 120 scenarios / 164 robot turns | result or admissible point range |
|---|---:|
| grounding | **0.6120–0.7274** |
| coverage | **0.2283–0.2883** |
| new-goal acknowledgement | 99/225 = **0.440** |
| completion announcement | 11–27/165 = **0.067–0.164** |
| resume offer | 10–11/30 = **0.333–0.367** |
| premature arrivals | 5–13/164 = **0.030–0.079** |
| keys inability bar | 1/25 = **0.040** |
| invented actions | 45 in 39 turns |
| measured latency subset | n=5, TTFT p50/p95 1,271/1,990 ms; total 3,337/3,967 ms |

Recovered rows have latency `UNMEASURED_NOT_RECOVERED`; only the 5 exact robot
turns contribute latency. The latency row must not be generalized to all Q.

The full hosted run added 550 response-ledger rows and $1.32843624, from
$0.87959880 to $2.20803504. The whole shared research-wave ledger remains
below both the $4.50 experiment stop and $5 product envelope. Provider RPD
units are not equated with response-ledger rows.

### Blind flag audit (report-only)

All 102 individual machine findings across the 66 queued turns were judged
blind to arm by the frozen prompt and local Qwen model. It returned 38
`CONFIRMED` and 64 `FALSE_POSITIVE` (62.75% false-positive rate). For the 45
invented-action findings specifically it confirmed 4 and called 41 false
positives; for 57 unsupported-claim findings it confirmed 34 and called 23
false positives. Artifact:
`results/adjudication-hosted-QD-full.json`, SHA-256
`783a0bafab6a4fac30a99970f9a7e382252b6917b910748a5b4ff757ab96aba5`.

This audit is report-only by preregistration and the local judge is not a gold
human label. It does show the deterministic action matcher is over-broad and
must be recalibrated. H-MB1c's zero-invention bar still fails even on the
judge's more permissive reading because 4/45 action findings were confirmed.

**Result:** H-MB1a, H-MB1b, H-MB1c, and H-MB1d are refuted on their absolute
gates. Hosted Q-minus-D remains unmeasured because D is incomplete. See
`VERDICT.md` for the promotion decision and next design.
