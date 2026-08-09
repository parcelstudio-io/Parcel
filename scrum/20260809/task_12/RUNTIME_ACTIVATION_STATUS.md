# RUNTIME-ACTIVATION — camera on the mission path (B4) + the memory write-path

Executor: Opus (sole runtime.py editor this wave). Two cards, one runtime:
**B4** wires the real open-vocab detector onto the reactive navigation path behind
an opt-in flag (default = the byte-identical oracle), and the **memory write-path**
makes tiered memory LIVE (live turns feed it; a real LLM summarizer is injected over
the provider seam; default-off is byte-identical).

## Headline (read first)

- **B4 camera pixel-ingress is LIVE on the production navigator.** With the flag ON,
  the navigator grounds a goal on a **PIXEL detection** — `candidate_source =
  pixel_detector`, `grounding_outcome = RESOLVED`, `candidate_confidence ≈ 0.86` — with
  `oracle_objects_seen_by_navigator = 0` (the scene carries no oracle semantics), and
  drives the PROVEN closed-loop nav rig toward the pixel-detected target. Detection is
  async (~570 ms/query on the worker thread); the reactive read is **0.13 ms** — a
  ~4400× margin, so the reactive gate + A* never block on detection.
- **A full "succeeded" arrival did NOT flip in the scratch gate** — reported honestly,
  not faked. The remaining gap is a navigator arrival-VERIFICATION nuance that is
  **provably independent of the pixel path** (an exact-position ORACLE candidate stalls
  identically in the same synthetic rig; the same harness DOES arrive on city objects
  that carry footprint metadata). Exact blocker below.
- **Memory write-path is LIVE.** Live `_chat_item` turns flow into `TieredMemory`; an
  aged-out fact ("dog's name is Pickle") survives into a Tier-2 rolling summary and
  `retrieve()` surfaces it into the prompt sections. Default-off leaves the composed
  prompt byte-identical (proven).
- **Both flags OFF = byte-identical frozen baselines** (both digests unmoved), full
  suite **3138 passed / 9 skipped / 0 failed**, ruff clean.

## CARD B4 — camera on the mission path

### What landed (opt-in behind a flag; oracle default byte-identical)

- **`src/parcel_robot/camera_channel/ingress.py` (NEW, owned).** `CameraIngress`: the
  async pixel→`semantic_candidates` producer. `from_model_data(model, data, ...)` builds
  the EGL backend (deferred to the worker thread — EGL contexts are thread-affine) +
  loads `OwlV2Detector`. A background worker renders RGB+depth per relevant tick, runs
  `OwlV2Detector(query = active goal noun)` → `localize_frame` → world point →
  `semantic_candidates` dicts (`kind=object`, `source=pixel_detector`, metric
  `position`), published to a lock-guarded buffer. `set_query`/`set_pose`/
  `latest_candidates` are cheap, thread-safe, non-blocking. Optional
  `embed_fn` seam for SigLIP crop embeddings.
- **`runtime.py` (owned):**
  - `_navigation_extras` now calls `self._semantic_candidates(observation)` instead of
    the oracle directly. When camera ingress is enabled AND attached AND has published a
    frame, it returns the PIXEL candidates (having pushed the live robot pose to the
    detector); otherwise it returns the exact oracle read
    `semantic_candidates_from_observation(observation)` — so **flag-off is byte-identical
    by construction**.
  - `attach_camera_ingress(ingress)` / `detach_camera_ingress()` / `close()` teardown;
    the runtime never imports MuJoCo (the caller with the model/data sets `MUJOCO_GL=egl`
    before the first import and builds the ingress — the EGL-before-import constraint is
    kept at the sim/gate boundary and documented in the module).
  - Flag: env `PARCEL_CAMERA_INGRESS` (truthy/falsy) OR `camera_ingress.enabled: true`
    in config; default OFF.
  - `start_navigation` sets the detector query from the directive noun
    (`_camera_query_from_directive`: "go to the lamppost" → "lamppost").
- Consumed (not changed): `detection_adapter.owlv2_onnx.OwlV2Detector`,
  `pixel_detections.localize_frame`, `camera_channel.backends.factory`,
  `mujoco_egl` backend.

### GATE — live product-path run (real OWLv2 int8 ONNX + EGL, this machine)

`scrum/20260809/task_12/b4_gate.py` (also in scratchpad). Drives the PROVEN
`HeadlessCityQualityHarness` (the same `DirectiveNavigator` + reactive-safety +
arrival-verification loop the frozen nav_instruct arrivals use), with its ONE semantic
ingress redirected to the async `CameraIngress`, over a scene with **no** city-semantic
annotations (oracle empty by construction). `PARCEL_OWLV2_THRESHOLD` = **0.1** (default).

| mission | grounding | source | oracle seen | OWLv2 conf | loc err vs truth | motion | reactive read vs detect | outcome |
|---|---|---|---|---|---|---|---|---|
| **A — "go to the red ball"** | **RESOLVED** | **pixel_detector** | **0** | **0.86** | **0.28 m** | 3.0 m → **1.67 m** (approach standoff) | **0.13 ms vs 567 ms (~4400×)** | grounds+navigates via pixels; verification not flipped |
| B — "go to the lamppost" | not grounded | — | 0 | **0.28–0.42** | **0.12–0.13 m** | scan only | 0.005 ms vs 583 ms | recognition FLOOR (see below) |

Stages proven in isolation (guarded live cell
`test_camera_ingress_live_owlv2_localizes_object`, and the gate warm-up): EGL render ✓,
OWLv2 recognition on pixels ✓, `localize_frame` world point (0.12–0.28 m) ✓, candidate
dict → grounding on `pixel_detector` ✓, production A* drives toward the pixel target ✓,
reactive gate never blocks on detection ✓.

### The exact blockers (no faked arrival)

1. **Terminal arrival-VERIFICATION did not flip to `succeeded` in the scratch rig — and
   this is NOT a camera-ingress issue.** The robot grounds on the pixel candidate and
   the production approach controller drives to its standoff goal (~1.4 m), but the
   arrival band (`[1.12, 1.32]` m around the candidate) sits ~0.08 m inside that
   standoff, so terminal verification rejects. Proven independent of pixels three ways:
   (a) an **exact-position ORACLE candidate** (confidence 0.9) stalls at the *identical*
   1.40 m with `semantic_arrival_verification_failed` in the same synthetic rig;
   (b) a radius sweep (0.0→0.5 m of candidate `radius_m` metadata) shifts the standoff
   but never aligns band-vs-standoff; (c) the **same harness DOES arrive** ("go to the
   lamppost" → `arrived`/`arrived_verified`) on real **city** objects, which carry
   footprint/region metadata the synthetic pixel candidate lacks. So the gap is a
   candidate-footprint-metadata / arrival-band calibration in the synthetic rig, not the
   ingress. Closing it cleanly = give the pixel candidate an honest object radius derived
   from the detection box + depth AND calibrate the band/standoff to it (a bounded
   follow-up), or run inside the full runtime loop with real object geometry.
2. **Recognition FLOOR on the literal "lamppost" (the honest P0 finding).** OWLv2 scores
   the non-photoreal lamppost prop **0.28–0.42**, below the grounder's `minimum_confidence`
   **0.55**, so it does not ground (it localizes accurately, 0.12–0.13 m, when it fires).
   This is exactly the B3-predicted recognition floor on non-photoreal sim textures — a
   detector operating-point vs grounding-gate calibration (`PARCEL_OWLV2_THRESHOLD` = 0.1
   detection gate; the 0.55 grounding gate was tuned for the oracle's 0.75–0.98 score
   distribution). A recognizable landmark ("red ball", 0.86) clears it and grounds.

`does_not_prove`: rendered MuJoCo textures are NOT photoreal — OWLv2 recall here is a
FLOOR of recognition, not field D455 recognition (a hardware re-earn). No field
recall/precision claimed.

## CARD memory write-path

### What landed

- **Config enable:** `prompting.memory.enabled: true` (+ `tier1_max_turns`, …) makes
  `build_prompting_stack` register the 3 memory sections (read path already existed).
  Default config has no `prompting.memory` block → memory `None` → OFF.
- **Write feed (`runtime.py`):** `_chat_item` (the single turn-commit hook for
  user/assistant turns, reached by `handle_text`) now calls `_remember_turn(role,
  content)` → `self.prompting.memory.append(role, content)` for role ∈ {user, assistant,
  tool}. A no-op when memory is disabled; guarded so a memory write can never break a
  turn.
- **Real summarizer injected (`runtime.py`):** `LLMSummarizer` adapts the existing
  `LanguageModel.decide()` provider seam into `summarize(previous, aged_turns) -> str`
  (updates a rolling summary, preserving durable facts). Injected onto the tiered store
  when a conversation model is wired; **degrades to the deterministic `ConcatSummarizer`
  fixture when no model** (guarded `hasattr` swap; `dynamic_prompting.py` / `tiered_memory.py`
  untouched — the injection lives entirely in the runtime I own). Its failure path also
  falls back to the deterministic fixture, so a bad model reply never breaks a turn.

### GATE — offline-deterministic

`tests/test_runtime_activation.py`:
- `test_live_turns_flow_and_aged_fact_surfaces_into_prompt`: 14 live turns fed through
  the production `_chat_item`; `memory.turn_count() == 14`; the turn-1 fact ("dog's name
  is Pickle") is **gone from verbatim Tier 1** but **present in the Tier-2 rolling
  summary**, and **"Pickle" appears in the composed prompt** with the `memory_tier*`
  sections registered.
- `test_handle_text_feeds_memory_turns`: the public `handle_text` path commits turns
  into the store.
- `test_write_feed_is_noop_when_memory_disabled_prompt_byte_identical`: prompting enabled
  but memory disabled → the composed prompt is **byte-identical before/after** feeding
  turns, and no `memory_tier` sections exist.

`does_not_prove`: the **real-LLM summary quality is not exercised live** here (no
conversation model wired in this env) — the deterministic `ConcatSummarizer` degrade path
runs, which proves the retrieval MECHANISM (aged fact → summary → prompt), not that a live
model writes good summaries. That needs a `--provider live` run (deferred).

## VERIFY

- **Full default suite** `pytest -q -m "not slow"`: **3138 passed, 9 skipped, 34
  deselected, 0 failed** (97 s). The 9 skips are env-gated real-weight OWLv2/SigLIP cells.
- **ruff**: clean on `runtime.py`, `camera_channel/ingress.py`,
  `tests/test_runtime_activation.py`.
- **Both flags OFF byte-identical (both digests proven unmoved):**
  - camera-ingress OFF → frozen **nav_instruct v3** `episode_digest =
    919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa` (test_nav_instruct_episodes_v3
    green; the `_semantic_candidates` swap returns the exact oracle read when off, also
    asserted equal in `test_semantic_candidates_default_is_oracle_byte_identical`).
  - memory OFF → frozen **PERSONAL_CONVO** `pack_digest =
    7e904d5335e049acc745357d226e6e03f262d2b5d8e86f7ee5de1f1ae056fa31` (test_personal_convo_v1
    green; composed-prompt byte-identical asserted directly).
- Live cells (real int8 OWLv2 ONNX + EGL, `MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1`):
  `test_camera_ingress_live_owlv2_localizes_object` passes (localizes a red ball within
  the arrival band); the B4 gate ran with the real numbers above.

## Files touched (mine only)

- **NEW** `src/parcel_robot/camera_channel/ingress.py` — `CameraIngress` (async
  render→OWLv2→localize→candidate producer).
- **MOD** `src/parcel_robot/runtime.py` — `_semantic_candidates` + camera-ingress
  attach/flag/query wiring; `_remember_turn` write feed in `_chat_item`; `LLMSummarizer` +
  its injection over the provider seam; `import os`, `import ConcatSummarizer`.
- **NEW** `tests/test_runtime_activation.py` — 17 offline tests + 1 guarded live OWLv2 cell.
- **NEW** `scrum/20260809/task_12/b4_gate.py` — the live product-path gate.
- **NEW** `scrum/20260809/task_12/RUNTIME_ACTIVATION_STATUS.md` — this file.

NOT touched: `instructnav/arbiter.py`, `brain/executive.py`, `.github/`, nox/Makefile,
`instructnav/grounding.py`/`siglip.py`, `tiered_memory.py`, `dynamic_prompting.py`
(enabled via config + fed + summarizer injected from the runtime, per ownership),
`owlv2_onnx.py`/`pixel_detections.py` (consumed), frozen packs/digests, prompts.

## Handoffs / follow-ups

- **B4 clean arrival**: give the pixel candidate an honest `radius_m` (detection box
  angular width × depth / 2) AND calibrate the arrival band/standoff to it, OR run the
  ingress inside the full `RobotRuntime` loop against real object geometry — then the
  terminal verification flips `succeeded`. The wiring is done; this is a bounded
  arrival-geometry calibration, not new plumbing.
- **B4 threshold**: `PARCEL_OWLV2_THRESHOLD` = 0.1 (detection). The grounder's
  `minimum_confidence` 0.55 rejects the non-photoreal lamppost (0.28–0.42); calibrate a
  camera-ingress-specific confidence gate against a FP tier (never the unseen split).
- **Memory**: exercise the real `LLMSummarizer` with a live conversation model
  (`--provider live`) to earn summary QUALITY (mechanism already proven).
