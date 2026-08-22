# Task 7 — P1-B: the map learns from pixels — embeddings, depth, persistence, a runtime writer

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Roadmap:** audit §10 Phase 1 item 2,
§3 items 3 and 5, §4 item 3; chain audit AU-C2-1.

## Why
The online semantic map has **zero product writers** (audit §1): it is only
ever constructed in its own test. On the real stream
`_attach_configured_camera_ingress` passes no `embed_fn`, so entries fall back
to an 8-dim label hash and `observation_from_record` gets `embedding=None`;
the planarity gate reports `relief_unverified` because no depth reaches it;
and the REVISION §6 source crop is dropped on persist (AU-C2-1, round-trip
proven). A map that cannot be written by the robot, embedded, or reloaded
cannot learn anything.

## Work
1. **Wire the encoders into the ingress:** SigLIP-2 image `embed_fn`
   (`instructnav/siglip2_onnx.py`, GPU per P0-C) on detection crops, and depth
   patches from `CaptureBuffers` when present, so every observation carries a
   real `EmbeddingStamp` (`online_map/entries.py`: model_id/revision/dim) and
   the depth-planarity defense has something to measure.
2. **The runtime writer:** under `perception.semantic_source: shadow` or
   `learned_map` (C-3's axis) the runtime feeds ingress observations into an
   `OnlineSemanticMap` instance it owns, and **persists it on `close()`** to the
   env-gated store path (`PARCEL_ONLINE_MAP_PATH`, R27 refusal gates untouched).
   A restart reloads it. This is the first parameter that persists from the
   robot's own experience.
3. **AU-C2-1:** persist + restore the bounded thumbnail bytes (`entries.py`
   `as_dict`/`from_mapping`, `store.py` schema bump with migration) with a
   round-trip test that would have caught the drop.
4. **`set_query` union (audit §3 item 5, P0-D may have landed the person-drop
   half — re-read `ingress.py` first and do not duplicate):** patrol/directive
   batches union with a pinned safety batch; under `learned_map` the batch is
   `known_places()` + a curiosity list, under `oracle` it is
   `scene_semantics.detector_query_set()`.
5. **Stamp `EvidenceOrigin`** on every entry from its source frames; a store
   mixing `PHYSICAL` and `SIMULATED` entries must be refused at load (seed it).

## Proves
In the dev scene (textured, sim origin) with the patrol driver (MOVE-1): the
map persists on close and reloads byte-faithfully including thumbnails and
stamps; entries carry real 768-d SigLIP-2 embeddings; planarity reports a
measured relief value, not `relief_unverified`. Pre-register the entry-count
and reload-fidelity rows before running. With a camera (P1-A, owner-gated) the
same code path builds the room map — that row is listed, not claimed.

OWNS: `camera_channel/ingress.py` (embed/depth/query-batch regions), the
runtime's camera→map region (NEW region in `runtime.py`, marked with a card
comment; re-read before every edit — P0-A/B/D regions are elsewhere),
`online_map/{ingest,entries,store,online_map}.py`, `configs/navigation/*`
(map persistence keys), `tests/test_p1b_*.py`, `task_7/` docs.
MUST NOT TOUCH: `perception_abstention.py` (P1-D), `uwb/`, the daemon (P1-A),
frozen evals, safety core.

## Definition of done
Pre-registered rows measured; persistence round-trip + origin-mix refusal +
missing-stamp seeds RED; `P1B_STATUS.md` register; targeted tests + ruff
green on OWNS.

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* Map-persistence and query-batch keys live in `configs/navigation/prototype.yaml`;
  C-3's `semantic_source` axis is the switch and P0-D's `set_query` fix is the
  base — re-read `ingress.py` before touching the batch logic.
