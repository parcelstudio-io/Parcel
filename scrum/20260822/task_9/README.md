# Task 9 — P1-D: ask, don't refuse — the VLM veto and vocabulary that grows

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Roadmap:** audit §10 Phase 1 item 4,
§3 item 4 and 6, §9 "abstention that refuses everything"; cutover research
SYNTHESIS decisions 4 and 5; 20260821 task_21 (PG-4) is SUPERSEDED by this
card under the prototype ruling — P0-D already fixed `ranking_margin ≡ 0`
mechanically; this card gives the gate its replacement signal and its new
posture.

## Why
Six AND-ed abstention signals fitted on an invalidated world made the dog
refuse everything (C-3: 0/18 admitted). The prototype ruling (§9): two
signals (label support + evidence count) plus a VLM veto; below threshold the
dog ASKS — "I think it's over there, want me to go?" — instead of refusing.
The research already chose the veto seat: Qwen3-VL-2B (4.4 GB resident,
89 ms, statistical tie with 8B at n=40) and vocabulary-free naming behind a
k-consistency promotion gate (~82–87 % naming accuracy ⇒ promote only after k
independent-visit agreements).

## Work
1. **`vlm_veto/`:** the 2B verifier as a subtractive signal — given the top
   candidate's best-view crop and the query noun, answer present/absent with a
   confidence; absent ⇒ veto. Runs on the GPU daemon if P1-A has landed, else
   in-process; never inside the 10 Hz loop (AST-assert it, the C-1 way). The
   mission-lease generation refusal (`perception_contention.py`) is relaxed per
   §9: the 2B VLM runs on a high-priority CUDA stream, the detector keeps
   priority, nothing is refused.
2. **Re-cut the gate (`perception_abstention.py`, re-read P0-D's edits
   first):** signal roster = label support, evidence count, VLM veto; the
   three-way outcome is ADMIT / ASK / REFUSE, with ASK the default below the
   admit threshold and REFUSE reserved for veto or zero evidence. Thresholds
   pre-registered and then DERIVED on textured dev-scene renders (C-3's F2
   tail), with pinned fixtures and a CI eval row (the llmdet lesson).
3. **Vocabulary growth:** idle-time batch naming of unnamed map entries via the
   2B VLM with `vlm_proposed` provenance; promotion to a real label after k=3
   independent-visit agreements; demotion on disagreement. The label joins
   `known_places()` only when promoted.
4. **The ASK path in the voice:** when the gate returns ASK the grounder
   produces a candidate + a question; the tool broker's `navigate_to`
   (P0-B's ask-not-refuse) carries it. Consume P0-B's seam; don't rebuild it.
5. Pre-register: ≥ 1 ADMIT reachable from a learned map on perfect-geometry
   data (the exact state that was 0/18); 0/8 admitted on the absent-object set
   (refusal preserved where it should be); ASK rate reported; naming accuracy
   on a 40-entry fixture with the k-gate's false-promotion count.

## Proves
Abstention ON with ≥ 1 admitted place and 0/8 absent-set admissions; a place
the prompt never listed gets a promoted name after three visits.

OWNS: new `vlm_veto/` package, `perception_abstention.py` (post-P0-D),
`perception_contention.py` lease relaxation, `online_map/naming.py` (NEW file;
P1-B owns the rest of `online_map/` — coordinate via the public API only),
`configs/navigation/*` abstention keys, `tests/test_p1d_*.py`, `task_9/` docs.
MUST NOT TOUCH: `ingress.py`, `runtime.py`, the broker (P0-B/P2-A), safety
core, frozen evals.

## Definition of done
Five pre-registered rows measured; seeds RED including "MAD-zero margin
re-introduced" and "promotion without k agreements"; `P1D_STATUS.md`.

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* P0-D made the abstention signal set CONFIGURABLE via
  `configs/navigation/prototype.yaml` — your ADMIT/ASK/REFUSE roster is an
  overlay change plus the new veto signal, not a rewrite.
* The ASK path consumes the broker's structured `unknown_place` result and the
  `unknown_place: ask` key P0-B validated.
