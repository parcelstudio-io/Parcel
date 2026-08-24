# H2 — local cognition on the GPU we already have · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A GPU-resident local model can run the dog's **inner-monologue tick** —
given a compact world digest (whisperer digest + noticings + dialogue
state + drives), emit one typed decision `{ignore | remark(text) |
look(bearing) | go_check(place) | ask(question)}` with a one-line reason —
at **≤ 300 ms p50 / ≤ 600 ms p95 end-to-end** on an 8B-class model, while
OWLv2+SigLIP-2 perception shares the GPU at 10 Hz, at **$0**, with decision
agreement ≥ 0.8 against a gold set judged by the 32B local judge; and the
26B admitted reasoner, GPU-resident, serves the *deliberative* role (plans,
distillation) at its measured 855 ms TTFT / 5.7 s usable-plan without
starving the tick.

## Why (host inventory + reasoner profile + surveys)
- The owner's `:8080` gemma-26B runs on the CUDA-less `b10235` binary with
  48 CPU threads: 19.7 s median usable-plan latency. The admitted CUDA
  rootfs (`third_party/llama.cpp-oci/llama-b10236-cuda12`,
  `scripts/launch_reasoner_gpu.sh`) measured 855 ms TTFT / 5.66 s plan on
  this RTX 5000 Ada; the GPU sits ~94 % idle. "Continuously running
  models" is a launch-flag problem before it is a research problem.
- Ministral-3-8B Instruct (`models/reasoner/`, Apache-2.0) was rejected as
  the *planner* (5/10 conversation, 3/5 PlanIR) but measured TTFT 102 ms
  at 35/35 CUDA layers — exactly the profile an ambient triage/monologue
  model needs. Nobody has tested it for that role.
- `brain/` is deterministic by design ("never call an LLM" at control
  rate). The monologue tick is NOT on the 10 Hz loop: it is a 1 Hz-class
  cognition thread whose output is a *proposal* through the existing
  admission doors (`_curiosity_admitted_names`, `_accept_plan`).
- On an Orin NX 16 GB only one small model fits beside perception; the
  VRAM/latency table this experiment produces is the sizing evidence for
  the milestone design (what runs on the dog vs on the desk).

## Objective
Produce the latency/VRAM/quality table for the two-model local cognition
stack (8B tick + 26B deliberation) on the desktop GPU under realistic
perception load, and a typed `MonologueDecisionV1` contract other
hypotheses (H3 drives) can consume.

## Experiment
1. **Servers**: gemma-26B GPU on `:8081` (launcher default) and
   Ministral-8B Instruct GPU on `:8082` (launcher with
   `PARCEL_REASONER_MODEL_PATH`/`PORT`), both `--jinja`, ctx 8192, one slot
   each; record `nvidia-smi` VRAM per server. Keep them up for the session
   (H1 and H5 use `:8081`); stop them at the end and say so.
2. **Contract**: `brain/monologue.py` (new leaf): `WorldDigestV1(frozen)`
   (≤ 600 tokens rendered: robot state, last 3 noticings, dialogue state,
   drive levels, last owner turn age) and `MonologueDecisionV1(frozen)`
   (kind, target, text ≤ 140 chars, reason, confidence) parsed
   fail-closed from JSON (grammar/JSON-schema mode in llama.cpp).
3. **Gold set**: 60 digests authored from sim traces (`simulation/headless_city.py`
   runs + CURIO-1 fixtures) with a gold decision each; adjudicated by the
   32B judge (`evals/autorater/` rails, both orders) — report judge/author
   agreement first.
4. **Latency**: 300 ticks per model idle; then with the H6-style
   perception load running (start the daemon yourself if H6's is not up:
   OWLv2 fp16 + SigLIP-2 at 10 Hz on synthetic frames); then with the 26B
   generating a 512-token plan concurrently. Record TTFT, full decision,
   tokens/s, and the perception p95 during the tick (the contention cost
   from cognition's side).
5. **Quality**: decision agreement with gold for 8B and 26B; false
   "remark" rate on digests whose gold is `ignore` (the annoyance proxy).
6. **Conversation talker check** (feeds H1 P2): 30 owner turns from the
   realtime corpus answered by 8B and 26B streaming; TTFT and first-clause
   latency; the autorater pairwise vs the hosted transcript.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| G1 | 8B tick p50 / p95 idle | ≤ 300 / ≤ 600 ms |
| G2 | 8B tick p50 / p95 under perception + 26B generation | ≤ 450 / ≤ 900 ms |
| G3 | perception p95 during ticks | ≤ 150 ms (H6's contended bar) |
| G4 | VRAM: 26B + 8B + daemon resident | ≤ 28 GB; per-server reported |
| G5 | decision agreement with gold (8B / 26B) | ≥ 0.80 / reported |
| G6 | false-remark rate on `ignore` digests | ≤ 10 % |
| G7 | 8B talker TTFT / first clause | ≤ 150 ms / ≤ 600 ms |
| G8 | pairwise quality local vs hosted (H1 shares this row) | reported |

## What would refute it
G1 fails on 8B ⇒ the tick needs a ≤ 4B model or a non-LLM scorer (H3's
deterministic drives become the primary and the LLM only phrases); G5 <
0.6 ⇒ the digest is the problem (report which fields the judge cites).

## Evidence tier / does not prove
`desktop`. Proves sizing on an RTX 5000 Ada; Orin numbers are extrapolated
by ratio only and said so.

## OWNS
`research/20260823/local-cognition-gpu/**`, new leaf `brain/monologue.py`,
one capability test `tests/test_h2_monologue_contract.py` (parse
fail-closed; schema round-trip). GPU model servers on `:8081`/`:8082` for
the session (never `:8080`). Must not touch: `runtime.py`, `brain/executive.py`,
the owner's `:8080` server, the realtime lane.
