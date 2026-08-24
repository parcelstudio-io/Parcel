# [SUPERSEDED 2026-08-24: offline grammar/8B arms DROPPED per the owner's simplified floor and RTP-2 F6; the folder's live contract is DESIGN_v2_CONNECTED_PLANNER.md as amended by CLAUDE_RESPONSE Addenda (hosted-only arms; grammar arm removed). This file is kept for the record.]

# H9 — offline-first cognition and compound instructions without gemma · DESIGN (Fable) · 2026-08-24

## Owner's ask
Handle compound instructions without the gemma-26B, because the body's
computer may not hold it; the dog must keep basic capabilities offline —
degraded is acceptable, "internet-only" is not.

## Hypothesis (falsifiable)
On ≤ 8 GB of VRAM (Orin-NX-class), a **typed compound-instruction grammar**
(sequence / conjunction / until-condition / return) compiled into PlanIR by
the existing deterministic compiler, with a local 8B model used only to
normalize paraphrases into the grammar (never to author plans), achieves
PlanIR validity ≥ 0.90 and step-order correctness ≥ 0.85 on a 60-item
compound corpus — matching or beating gemma-26B's own PlanSketch on the same
corpus — at ≤ 1.5 s p95 on the desk GPU throttled to 8B-only; and the
**offline floor** (local ear → local ASR → grammar/8B → local TTS; stop;
follow; go to a known place; remember/recall a fact; refuse the rest
honestly) runs end-to-end with the hosted lane disabled and the network
unplugged, with every capability in the floor table measured pass/fail.

## Why (2026-08-23 surveys + H2 results)
- Planning is already deterministic below the sketch: `brain/compiler.py`,
  `brain/validator.py`, `voice/local_plans.py` (deterministic local
  sketches), `voice/closed_intents.py`. The LLM's only planning job is the
  PlanSketch; Ministral-8B scored 3/5 on it and gemma-26B 5/5 — the 8B
  cannot be trusted to *author* plans, but H2 measured its talker at TTFT
  126 ms, and the hosted lane's tool broker already handles compound
  requests when online.
- The Orin NX 16 GB (Go2 EDU Plus) can hold an 8B Q4 (6.2 GB measured) plus
  whisper + piper + Silero; it cannot hold the 26B (15.3 GB) beside anything.
  An AGX Orin 32/64 GB could — the platform memo (H10) weighs that.
- The local lane already listens wake-free and answers offline (EAR-1 fact);
  what is missing is a *measured* floor and a compound grammar that does
  not depend on the 26B.

## Experiment
1. **Grammar** (`voice/compound_grammar.py`, pure): typed AST for `seq(a,b)`,
   `and(a,b)`, `until(a, cond)`, `then_return`, with the noun/place/person
   slots the existing `local_plans` already parse; `compile_to_planir()`
   through `brain/compiler.py` + validator; a normalizer seam
   `Normalizer(Protocol)` with two impls: regex/deterministic and
   `Llama8BNormalizer` (prompt: rewrite into the grammar's canonical form,
   fail-closed if unparseable).
2. **Corpus** (`corpus/compound_v1.jsonl`, 60 items, 4 forms × 15
   paraphrases, gold PlanIR steps authored BEFORE any run; 20 items are
   deliberately outside the grammar to measure honest refusal).
3. **Arms**: (a) grammar + regex normalizer; (b) grammar + 8B normalizer
   on `:8082`; (c) 8B PlanSketch directly (the H2/VOICE_AI_MODELS path);
   (d) gemma-26B PlanSketch on `:8081` (reference); (e) hosted mini via the
   corpus replay rails (reference, $0).
4. **Offline floor**: `configs/robot.offline.yaml` overlay (hosted lane
   absent, `speech` local, `planner` = grammar+8B); run the floor table
   through the voice pipeline with the fake mic (`frames=` seam) and the
   network namespace blocked (`unshare -n` or an env flag the transport
   honours) — every row pass/fail with the command that proves it.
5. **Sizing**: VRAM/RAM/latency of the 8B + whisper + piper + Silero set;
   the same numbers scaled to Orin NX by the published TOPS/bandwidth
   ratio, labeled *extrapolated*.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| O1 | PlanIR validity (validator accepts), arms a/b/c/d/e | b ≥ 0.90; others reported |
| O2 | step-order correctness vs gold | b ≥ 0.85 |
| O3 | honest refusal on the 20 out-of-grammar items | ≥ 0.95 (no invented plans) |
| O4 | p95 latency arm b (8B-only GPU) | ≤ 1.5 s |
| O5 | offline floor table: listen, answer, stop (spoken + panel), follow, go-to-known-place, remember/recall, refuse-unknown | every row pass with the network blocked |
| O6 | VRAM/RAM for the floor set | ≤ 8 GB VRAM; RAM reported |
| O7 | quality of floor answers (autorater vs hosted, both orders) | reported — the floor is allowed to be worse |

## What would refute it
O1/O2 < 0.7 in arm b ⇒ the grammar covers too little of natural phrasing
and the milestone must budget a bigger on-body model (AGX Orin) or accept
"compound only when online"; O5 any row fails ⇒ that capability is not in
the floor until fixed — the design says which.

## Evidence tier / does not prove
`desktop` + `replay`. Proves grammar coverage, the 8B's normalizer fitness,
and the offline floor on this host; Orin numbers are extrapolated.

## OWNS
`research/20260824/offline-first-cognition/**`, new pure
`voice/compound_grammar.py`, `configs/robot.offline.yaml` (new overlay;
`robot.yaml` untouched), one capability test
`tests/test_h9_compound_grammar.py`. Must not touch `runtime.py`,
`brain/compiler.py` semantics, the hosted lane, the owner's stack.
