# PlanSketch v1 result ledger

This append-only ledger indexes immutable runs of the frozen compact planner
challenger. The warm-up row contains one case and is not a five-case baseline.

| UTC | Run | Change | Accepted | TTFT ms median / mean / p95 | Full model ms median / mean / p95 | Output bytes median | Completion tokens median | Physical episodes |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-03 12:53:06 | [`planner-sketch-v1-20260803125306Z-bd0b3304`](planner-sketch-v1-20260803-gemma4-gpu-warmup01.json) | One-case full-CUDA cache warm-up calibration; not a scored baseline | 1/1 | 932.371 / 932.371 / 932.371 | 2,193.317 / 2,193.317 / 2,193.317 | 417 | 150 | 0 |
| 2026-08-03 12:53:37 | [`planner-sketch-v1-20260803125337Z-899f5494`](planner-sketch-v1-20260803-gemma4-gpu-run01.json) | Frozen five-case PlanSketch v1 GPU challenger paired to PlanIR run06 semantics | **3/5** | **751.266 / 615.026 / 765.740** | **2,037.060 / 2,075.735 / 2,551.699** | **417** | **153** | **0** |
| 2026-08-03 13:54:50 | [`planner-sketch-v1-20260803135450Z-a15cbc37`](planner-sketch-v1-20260803-ministral8b-reasoning-gpu-warmup01.json) | Development-only one-case frozen-contract compatibility gate for official Ministral 3 8B Reasoning; stopped before a full run | **0/1** | **343.803 / 343.803 / 343.803** | **12,262.204 / 12,262.204 / 12,262.204** | **3,804** | **1,024** | **0** |

## Paired decision

Against the full-PlanIR GPU run 06, PlanSketch reduced median full model-call
latency 63.99% (5,657.459 to 2,037.060 ms), completion tokens 71.02% (528 to
153), and serialized provider output 71.92% (1,485 to 417 bytes). Median TTFT
fell 12.17% (855.379 to 751.266 ms). Deterministic sketch-to-PlanIR compilation
took a median 0.102 ms.

It also reduced semantic acceptance from 5/5 to 3/5. One owner-relative goal
used the wrong query label; one orbit/follow output violated the rule that
non-navigation skills must set `navigation` to JSON `null` and was rejected.
PlanSketch therefore remains opt-in and is **not promoted**. Those frozen
failures should seed a separately split development corpus; editing this prompt
against the five confirmation cases and calling the replay a quality gain would
be overfitting.

Both suites used the same Gemma artifact, b10236 full-CUDA server, frozen cases,
1,024-token maximum, non-thinking decode, and semantic scorer. Their output
schemas and system instructions necessarily differ. Neither suite executed a
physical skill or establishes navigation, perception, conversation, Unitree,
or external-benchmark quality.

## Ministral Reasoning compatibility decision

The separate Ministral Reasoning row is deliberately **not** a five-case
baseline and must not be averaged or compared as though it were one. Before
running it, the experiment selected the existing frozen PlanSketch contract as
the most appropriate planner-specialist interface, enabled thinking, retained
the same 1,024-token bound, and designated `sidewalk_then_hold` as a one-case
compatibility warm-up. Cases, prompt, response schema, router, snapshot,
compiler, validator, and scorer retained their manifest hashes.

The exact 5,198,910,368-byte Q4_K_M artifact at SHA-256
`894aa3645ef8708a81dbe201c26105ce37c4c741252c89c5a78f81b49ac438c6`
loaded with 35/35 layers on CUDA. It began a schema-shaped answer but then
repeated an invented property name inside the schema's generic `arguments`
object until `finish_reason=length`. The provider therefore rejected the
unclosed 3,804-byte response as invalid JSON after all 1,024 completion tokens.
The verbose, hash-recorded server log preserves the raw malformed completion.

This is an existing-contract compatibility failure, not evidence that a larger
post-hoc budget or edited grammar would pass. The remaining four cases were not
run, and neither the frozen prompt/schema nor the budget was changed after the
failure. Compared only as a gate: its 343.803 ms first output was faster than
Gemma PlanSketch's one-case cold warm-up (932.371 ms), while its 12,262.204 ms
failed full call and 1,024-token exhaustion were much worse than Gemma's
2,193.317 ms valid 150-token result. It also failed before it could approach
Gemma PlanIR's 5/5 semantic parity or beat the 5,657.459 ms median full-call
gate; Ministral Instruct's separate PlanIR control was 3/5 at 382.199 ms median
TTFT, 6,071.293 ms median full call, and 475 median completion tokens.
Ministral Reasoning is therefore rejected for the current PlanSketch boundary
and is not activated for planning or conversation. No physical episode ran.
