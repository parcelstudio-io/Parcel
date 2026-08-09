# REVIEW — Opus on Sol Phase-1 (pure)

**Reviewer:** Opus stand-in (cross-review) · **Date:** 2026-08-05 ·
**Subject:** Sol Phase-1 pure deliverables — K4 instructnav modules, K5
CameraChannel / DetectionNoiseAdapter / low-viewpoint gates, K8 walk-with-me
generator (K1 contracts treated as already approved baseline) ·
**Criteria:** pure-only where claimed; fail-closed validators;
DetectionMsg/contracts alignment; honest `does_not_prove`; no invented
runtime coupling.

**Sources read:** `K4_SOL_STATUS.md`, `K5_SOL_STATUS.md`, `K8_STATUS.md`,
`instructnav/{memory,grounding,scan,search_entity}.py`, `camera_channel/`
(pure layer), `detection_adapter/{adapter,noise}.py`, `low_viewpoint/`,
`evals/walk_with_me/generator.py`, `contracts/`, plus Sol CI tests
(`test_k4_instructnav.py`, `test_k5_camera_detection_gates.py`,
`test_walk_with_me_k8.py`).

**Out of this review (Opus lane / not claimed as Sol pure):**
`camera_channel/backends/*`, `detection_adapter/sim_bridge.py`, K4/K5 Opus
wiring tests, `evals/walk_with_me/runner.py`.

## Verdict

**APPROVE**

Sol Phase-1 pure work matches the adjudicated cards: new/extended instructnav
APIs stay free of `runtime`/`agent`/MuJoCo; CameraChannel refuses pixel
invention without an attached backend; DetectionNoiseAdapter
produces/consumes `contracts.DetectionMsg` with envelope TTL; low-viewpoint
and K8 packs carry explicit HR-4 / `does_not_prove` honesty; CI for the Sol
suites is green (`44 passed` across contracts + K4 + K5 Sol + K8 smoke).

## Criteria checklist

| Criterion | Result |
|---|---|
| Pure-only where claimed | Pass — K4 modules and K5 pure packages (`channel`/`d455`/`frames`, `adapter`/`noise`, `low_viewpoint/gates`) import no `runtime`/`agent`/MuJoCo/EGL; K8 `generator.py` imports only stdlib + `instructnav.scoring`; Scan/Search emit PlanIR-**shaped** dicts without brain imports; `search_owner.py` untouched |
| Fail-closed validators | Pass — dataclass `__post_init__` gates on memory entities, scan/search specs, noise config, frame metas, gate samples/thresholds; CameraChannel `capture` raises without backend and `validate_envelope` rejects spec mismatch; K8 freeze load rejects digest / empty `does_not_prove` |
| DetectionMsg / contracts alignment | Pass — memory `observe_detections` / Grounder accept `DetectionMsg`; adapter builds full `EvidenceEnvelopeV1` + `DetectionMsg` (bearing∈[-π,π], range≥0, score∈[0,1], embedding 1..2048) and round-trips via `from_mapping`; defaults use `DEFAULT_DETECTION_TTL_NS` / `expires_from_ttl` |
| Honest `does_not_prove` | Pass — CameraChannelSpec, low-viewpoint `DOES_NOT_PROVE`, K5 status HR-4 non-claims, K8 generator+manifest seven boundaries (sensors, AEC, ReID, curb physics, camera-grounded semantics, full voice→PlanIR, Orin) |
| No invented runtime coupling | Pass — Sol pure surfaces stop at protocols/dicts/helpers; Opus backends/bridge are labeled and not required to import Sol pure modules |

## Findings

### Strengths

1. **K4 API shape matches hillclimb rungs without owning recovery I/O.**
   `SemanticMemory2D` co-registers instance + region channel with non-compounding
   decay; `GrounderV2` emits typed
   `RESOLVED`/`MEMORY_HIT`/`UNSEEN`/`AMBIGUOUS`; `recovery_for_outcome` is a
   pure ladder; SearchEntity exposes swappable `FrontierScorer` with
   semantic−geodesic scoring and injectable geodesic costs.
2. **CameraChannel honesty is coded, not only documented.** No backend →
   `RuntimeError` (never synthesizes pixels); stub envelopes are metadata-only;
   `as_dict()["does_not_prove"]` and `assert_nominal_d455_contract` pin the
   bag/HR-4 nominal (1280×720, fx/fy=644, mount 0.35 m,
   `d455-intrinsics-nominal`).
3. **Detection adapter is a real contract producer.** GT → cutoff /
   `p_detect(d)` / confusion / jitter → validated `DetectionMsg`; confusion
   rows must sum to 1.0; unknown predicted labels collapse into vocabulary
   fail-closed.
4. **Low-viewpoint gates are named predicates over caller metrics.** Pass/fail
   + reason for the four adjudicated ids; thresholds labeled sim-not-field;
   mount-height band enforced on OCR/ReID/VPR stress cases.
5. **K8 freeze discipline is enforceable.** Seed-stable
   `generate_frozen_pack` → digest; `load_frozen_manifest` fail-closes on
   mismatch; themes cover the ten companion scripts; absent-target /
   barge-in / curb notes stay stub-honest.

### Non-blocking issues (fix before/with Opus wiring; not Phase-1 pure blockers)

1. **Batch ingest soft-skips bad rows.** `SemanticMemory2D.observe` /
   `observe_detections` `continue` on `KeyError`/`TypeError`/`ValueError`
   instead of rejecting the batch. Dataclass construction remains fail-closed,
   but garbage mappings disappear silently. Prefer a strict mode (or count /
   raise) when Opus wires live DetectionMsg streams.
2. **Freshness is not applied inside memory/grounder.** Contracts require
   consumers to run `require_fresh` before acting; these pure scorers/stores
   accept any structurally valid `DetectionMsg` regardless of envelope expiry.
   Document caller obligation at the Opus bind site (do not treat memory
   ingest as a freshness gate).
3. **Embedding seam between adapter and Grounder.** `label_embedding` defaults
   to dim=8; Grounder `_hash_embed` uses dim=32 — cosine boost only runs when
   lengths match, so adapter detections usually rely on SigLIP/string path.
   Align dims or document “string/SigLIP primary” before claiming embedding
   match in sim.
4. **Package `__init__` blurs Sol/Opus for detection_adapter.** Sol
   `detection_adapter/__init__.py` re-exports Opus `sim_bridge` helpers
   (`detections_for_agent`, …). Functionally fine and labeled in K5_STATUS,
   but pure-lane imports should prefer `adapter`/`noise` directly so Sol
   “pure” stays mechanically separable.
5. **`color_meta_from_mapping` is softer than contract parsers.** Uses bare
   `int(...)` / `str(...)` rather than bool-rejecting helpers used elsewhere;
   bag round-trip tests cover the happy path only.
6. **K8 absent-target still carries an off-map `GoalRegion` disc.** Success is
   keyed by `honest_absent` + `absent_target=True`, which is correct if the
   runner honors the predicate — ensure headless never scores geometric
   arrival at (40, 40) as success.

### Not in scope / correctly deferred

- Opus: navigator/runtime bind of Scan/Search, memory populate from sim
  DetectionMsg, MuJoCo EGL / synthetic backends, sim_bridge agent path
- Pixel detector cascade / real D455 bags (HR-4 P5)
- K6 voice lanes / acoustic barge-in
- Nightly headless attribution over full walk-with-me pack (stub SR ≠ L1/L2)

## Must-fixes

None — verdict is APPROVE.
