# Next batch — camera-search completion, P0 safety, eval debt (2026-08-09, r2)

**Orchestration model (owner-set):** Cursor dispatches the cards to the named
executors (Sol 5.6 Ultra = new pure modules with frozen contracts; Claude Opus =
existing-file wiring). **Fable audits after each wave** (protocol at the bottom
— pre-registered, so the audit is a check against claims, not a re-derivation).

Base: commit `60ecea2`, tree clean, `scripts/ci_gate.py --tier commit` GREEN
(8/8 hard gates, default suite 3140 passed / 0 failed).

**r2:** this plan was adversarially verified against the tree before dispatch
(workflow `wf_7fade49a-a7a`, two skeptics, both initially `needs-edits`); all
blocking and should-fix findings are folded in below. Notable corrections:
S-A's ownership re-mapped to where the safety core actually lives; P0-A/P0-B
split along the runtime.py ownership seam; V-A's mechanism rewritten because
the plain-`radius_m` lever was already measured ineffective (task_12 sweep —
standoff and band are both additive in r, so radius alone never aligns them).

## Why these cards (one paragraph)

The three product goals: search/identify entities, execute voice commands,
navigate seamlessly. The camera-search chain went live this wave ("go to the
red ball" grounds on `candidate_source=pixel_detector`) but stops one step
short of *arriving*, and the recognition floor (lamppost scores 0.28–0.42 vs
the 0.55 gate) needs the designed multi-view evidence absorber, not a lowered
gate. The independent verdict (scrum/20260808/task_1/INDEPENDENT_VERDICT_FABLE.md)
ranked the still-open release blockers: P0-A/P0-B first, then proximity-
convention unification. CI landed but left named debts. This batch finishes
the camera arc via the adjudicated vsearch cards (scrum/20260809/task_4/
README.md — read it; card letters below refer to it), lands the top P0s, and
clears the CI debt.

## Global rules (every card)

1. **Authoritative check:** `.parcel/bin/python scripts/ci_gate.py --tier
   commit` must be GREEN before a card is reported done. A red gate is either
   fixed or STOP-and-reported — never worked around.
2. **Frozen discipline:** frozen digests/rows are immutable. If a change moves
   one, STOP and report to Fable with the 2×2 attribution — no self-service
   re-freezes this batch.
3. **Flag-gating:** new capability is opt-in; flag-off must be byte-identical
   (the model-off-non-inferiority gate enforces this — it will catch you).
4. **No safety weakening:** K0 band constants, collision gate, GoalArbiter
   (instructnav/arbiter.py) veto/lethal semantics, SafetyEnvelope derivations
   — a card that needs one loosened STOPs and reports; it does not edit.
5. **Ownership:** each card lists OWNS / MUST-NOT-TOUCH. Overlap = the later
   dispatch yields (Cursor sequences). runtime.py has ONE owner per wave
   (Wave 1: C-A). A card needing a runtime.py line writes it as an enumerated
   patch in its STATUS doc; C-A (or Fable between waves) applies it.
6. **Honesty:** every status doc records `does_not_prove`. Measured numbers,
   not vibes; a blocker is reported precisely, never faked around.
7. **Records:** status doc in `scrum/20260809/task_15/<CARD>_STATUS.md` (this
   folder), raw-fact final message.

---

## Wave 1 — parallel, disjoint (dispatch all five together)

### Card V-A [opus] — B4 arrival closure (pixel path *arrives*)
The live pixel-ingress run grounds and navigates but stalls at ~1.4 m. The
task_12 sweep PROVED plain `radius_m` cannot fix this (stand-off and band are
both additive in r — radius-invariant misalignment; an oracle candidate stalls
identically). The actual fix: emit the **full near-envelope candidate metadata
field set** from ingress — `radius_m` (box angular width × depth / 2) PLUS
`stand_off_m` / `minimum_vicinity_radius_m` / `vicinity_radius_m` /
`target_min_surface_clearance_m` computed via
`instructnav.scoring.object_near_envelope_m` (CONSUMED, not edited) — the
exact field set `city_semantics` stamps on city objects, which is why city
objects arrive. `approach.py` and `pipeline.py` already read every one of
these fields from candidate metadata, so no edit outside ingress is needed.
If the synthetic b4 rig still can't arrive after honest metadata, fix the RIG
(owned) — never the band constants (rule 4).
- READ FIRST: scrum/20260809/task_12/RUNTIME_ACTIVATION_STATUS.md (the
  characterized blocker + the failed radius sweep), instructnav/scoring.py
  `object_near_envelope_m` (read-only), the city_semantics stamping site.
- OWNS: `src/parcel_robot/camera_channel/ingress.py`,
  `tests/test_runtime_activation.py` (pre-assigned here — C-A must not ruff it),
  `scrum/20260809/task_12/b4_gate.py`, and ONE new additive eval file
  `evals/nav_instruct/cam_arrival.py` (+ its pack entry as a new file).
- MUST NOT TOUCH: runtime.py (C-A owns), instructnav/scoring.py (consume
  only), navigation/**, detection_adapter/**, any EXISTING evals file
  (cam_foundation.py / cam_detector.py stay untouched — V-B is adding its own
  separate new files there).
- GATE: the live b4 gate flips to `arrival=succeeded` via
  `candidate_source=pixel_detector`; the pixel-arrival case lands in
  `cam_arrival.py` (new file, file-disjoint from V-B); flag-off byte-identical;
  ci_gate green.

### Card V-B [sol] — vsearch D1+D2: multi-view evidence + metric localizer
The designed absorber for the recognition floor. D1: M-of-N multi-view
confirmation + false-positive memory over pixel `DetectionMsg`s (pure module),
so a LOWER detector operating point is safe — single-frame misses/FPs get
absorbed by evidence accumulation instead of a per-class gate hack. D2:
monocular metric localizer + covariance fuse (pure). Card details in
scrum/20260809/task_4/README.md (D1, D2 rows — deps landed).
- OWNS: new pure-module files under `src/parcel_robot/detection_adapter/`
  (additive only), NEW T-cam eval cell files (additive, file-disjoint from
  V-A's `cam_arrival.py`; existing cam_foundation.py/cam_detector.py
  untouched), tests.
- MUST NOT TOUCH: pixel_detections.py / owlv2_onnx.py contracts (consume),
  camera_channel/** (V-A), grounding.py/siglip.py, frozen packs,
  `evals/nav_instruct/cam_arrival.py` (V-A's).
- GATE (measurable, two parts): (1) D1 pure-module gate, CI-frozen: fed the
  RECORDED lamppost score sequence (0.28–0.42) at an operating point of
  `PARCEL_OWLV2_THRESHOLD≈0.2`, M-of-N confirms; fed the absent-target/FP
  fixture sequences at the same operating point, confirmations stay 0 (that
  is the false-positive-arrival=0 requirement, now on a frozen substrate).
  (2) live EGL cell (guarded, not CI-gating): the real lamppost render
  confirms end-to-end at that operating point. Plus D2's localization-error
  distribution vs seg-truth + metamorphic rigid-transform. ci_gate green.

### Card V-C [sol] — vsearch C1: SemanticValueMap2D (pure)
The VLFM-style value map that makes search *directed* instead of
rotate-in-place. Pure module, exact formulas, unit-gated; no wiring this wave
(C2/C3 consume it in Wave 2). Card detail: scrum/20260809/task_4/README.md §C1.
- OWNS: `src/parcel_robot/navigation/value_map.py` (NEW file only — named now
  so Wave-2 C2/C3 dispatch blocks cite a stable import path) +
  `tests/test_value_map.py` (NEW). Nothing existing.
- GATE: unit tests on cone/fusion math exact (VLFM formulas); ci_gate green
  (trivially — no existing-file changes).

### Card S-A [sol] — P0-A + P0-B, core side (the verdict-ranked blockers)
From DESIGN_B §P0-A/P0-B. **Ownership reality (corrected r2):** the safety
core is `navigation/collision.py`, `navigation/reactive_safety.py`,
top-level `authority.py` (core/authority.py is a re-export shim),
`core/arbiter.py` (CommandArbiter), `core/motion_shaping.py`,
`core/velocity_smoother.py`. The final dispatch path and the stale-input
holds live in runtime.py, which C-A owns — so S-A is the CORE-SIDE half:
- **P0-A hard stop after all shaping:** deliver the core-side contract — a
  CommandArbiter hard-stop transaction that emits exact `(0,0,0)` plus a
  reset hook every registered shaper/smoother implements (no cached nonzero
  survives) — with property tests that interrupt at EVERY shaping stage and
  assert the next dispatched command is exactly zero. Tests may DRIVE
  runtime's `_dispatch_active` path; they do not edit runtime.py.
- **P0-B stale data fails closed:** one fail-closed convention for required
  inputs (pose/scan/feedback freshness → HOLD or latched STOP by severity),
  as core-side primitives; stub geometry only via an explicitly labeled sim
  fixture. The pose-LOST hold exists — generalize the discipline.
- Any runtime.py line the audit requires = an ENUMERATED PATCH in
  `S-A_STATUS.md` (exact lines + insertion points), applied by C-A or Fable
  (global rule 5) — never edited here.
- OWNS: `src/parcel_robot/navigation/collision.py`,
  `src/parcel_robot/navigation/reactive_safety.py`,
  `src/parcel_robot/authority.py` (+ `core/authority.py` shim),
  `src/parcel_robot/core/arbiter.py`, `core/motion_shaping.py`,
  `core/velocity_smoother.py`, new tests, mutation-panel additions (bump with
  provenance).
- MUST NOT TOUCH: runtime.py, navigation/** EXCEPT the two files above,
  instructnav/**, brain/**.
- GATE: property tests green (interrupt-at-every-stage exact-zero; stale →
  HOLD/STOP); any new mutant killed; existing safety pins (family equality,
  no-literal-drift) untouched-green; **frozen row moves → STOP and report**
  (rule 2 exists for exactly this); ci_gate green.

### Card C-A [opus] — CI debt + N19 clock fan-in (sole runtime.py owner)
One story in four parts:
1. Wire the 4 acoustic-ack latency marks in runtime.py (capture_speech_end,
   semantic_commit, stt_request_start/stt_final, audio_first_sample —
   observability.py STAGES already exist), and add the 5 acoustic stages to
   the `ui/latency.html` metricNames array (display only).
2. Persist a latency snapshot per run to `evals/latency/ledger.jsonl`; point
   the ci_gate latency-tail gate at the ledger WITH: a pinned baseline (first
   N green rows or a committed `evals/latency/baseline.json`), the existing
   percentile-pin pytest gate KEPT, and the ledger ratchet skip-with-note
   (never red) while the ledger has fewer rows than the pinned window.
3. `walk_with_me` emits `hard_collision_total`; ci_gate hard-safety gains a
   walk_with_me ledger read that counts ONLY rows carrying the field
   (legacy stub rows skipped by field-presence — pre-existing rows must not
   redden the gate).
4. Ruff burn-down of the ratcheted fingerprints EXCLUDING every file under
   `camera_channel/**`, `detection_adapter/**`, `core/**`,
   `navigation/collision.py`, `navigation/reactive_safety.py`,
   `authority.py`, and `tests/test_runtime_activation.py` (V-A's this wave);
   re-pin the baseline to the honest remainder.
- OWNS: runtime.py (EXCLUSIVE — including applying S-A's enumerated patch if
  filed before C-A closes), observability.py, `ui/latency.html` (metricNames
  only), `evals/latency/` (new), walk_with_me harness output fields,
  `scripts/ci_gate.py` (latency-tail source switch + the hard-safety
  walk_with_me read) + baseline re-pins.
- MUST NOT TOUCH: the S-A-owned safety files, camera_channel/** (V-A),
  detection_adapter/** (V-B), voice_pipeline.py behavior (marks are
  observational only).
- GATE: marks fire on the duplex product path (prove with the existing duplex
  harness); ledger row written + latency-tail reads it + its self-test still
  reddens on a seeded spike; walk_with_me rows join hard-safety without
  reddening on legacy rows; ruff new=0 with a smaller re-pinned baseline;
  ci_gate green.

---

## Wave 2 — after the Wave-1 Fable audit passes

(C-B and M-A sit here by executor bandwidth, not dependency — Cursor may pull
either forward if a Wave-1 card finishes early.)

| Card | Executor | Deps | One-liner + gate source |
|---|---|---|---|
| V-D: vsearch C2+C3 — value-directed scan + frontier scorer | opus | V-C, B4 | Replace the scripted spin; SR ≥ fixed-spin baseline on paired seeds; Tier C ≥ +10pp vs nearest-frontier (gates verbatim in task_4 README) |
| V-E: vsearch D3+D4 — SEARCH→NAVIGATE lock-on + chance-constrained K0 | opus | V-B, V-A | Detection-triggered commit; T-cam SR within pre-registered margin of oracle path; T0 byte-equal. **Doubles as the P0-C sim-e2e repro** (task_14 handoff): the detection-triggered SE2Goal publish carries the real (task_id, plan_revision) stamp and a mid-run correction is exercised end-to-end |
| S-B: proximity unification + P0-H + arbiter:141 + runtime halves of P0-A/B | sol | S-A, C-A | One clearance convention across authority/collision/reactive_safety; fold the dimensional fix in; harden the mixed-lethal-waypoint `all()` case; extend the family-equality ratchet; apply/verify any S-A runtime patch C-A didn't absorb; tighten the P0-C `_accept_plan` nav-plan filter (task_14 nuance) |
| C-B: counterfactual candidate logging + oracle replay | sol+opus | — | The verdict's "pull forward C's offline measurement only": log candidates at arbitration, replay must reproduce the committed choice bit-identically, report would-a-different-candidate-have-won. Gates any future learned ranker |
| M-A: PC-4 judge + calibration pack + live-summarizer quality run | opus | — | Report-only judge with frozen known-good/known-bad calibration (drift = disqualified); then a `--provider live` PERSONAL_CONVO run so summarizer quality is measured, not just the mechanism |

Wave-2 cards get full READ-FIRST/OWNS/GATE blocks at dispatch time (Cursor:
lift them from scrum/20260809/task_4 card details + the verdict + this table;
same global rules; re-run ownership mapping against the tree AT dispatch —
Wave 1 will have moved files).

## Explicitly deferred (not this batch)

- route_memory proposal-only wiring (verdict miss #4 — after the value map).
- **ABI freeze / K1 contract RFC** (verdict action #1, backlog N10-K1) —
  deferred until the vsearch D-lane lands: DetectionMsg/SE2Goal are still
  gaining fields this batch (SE2Goal grew task_id/plan_revision in P0-C);
  freezing mid-growth would churn the RFC.
- Real SigLIP crop embeddings via the `localize_frame(embed_fn=...)` seam
  (B3 handoff #4) — after D1, so FP-memory consumes them in one design.
- PERSONAL_CONVO Tier A (audio) + the 4/9 acoustic gates — hardware-gated
  (transducer; rig capture contamination needs a real device).
- Owner items: mic recording (backlog N-AUDIO-REC), transducer, Go2 purchase.
- Ruff residue in the ownership-excluded trees; backlog N-items not named in
  this plan (N5 BARN-300, N7 emote schema, N9 Follow-Bench, N21 temperament,
  N22 acoustic) — out of batch scope by prioritization, not oversight.

## Fable audit protocol (pre-registered)

After each wave Fable will, in order:
1. Run `scripts/ci_gate.py --tier commit` fresh — green or the wave is
   returned.
2. Diff-vs-ownership: `git diff` scoped per card against its OWNS list; any
   out-of-scope edit is returned to the card's executor with the diff.
3. Re-run ONE named gate per card independently (not trusting the status doc)
   — e.g. V-A's b4_gate live run, S-A's property tests, C-A's ledger row.
4. Adversarial verify on the safety cards (S-A, S-B) and on any card whose
   claims involve a frozen row: a refute-first review workflow (2–3 skeptics)
   against the actual diff.
5. Verdict per card: CONFIRMED / RETURNED-with-findings, recorded in
   `scrum/20260809/task_15/AUDIT_WAVE<N>.md`. Cross-card conflicts → Fable
   arbitration, same file.
