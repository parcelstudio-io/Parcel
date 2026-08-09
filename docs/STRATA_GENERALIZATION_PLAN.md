# Strata generalization plan — de-hardcoding navigation + the robust eval program

**Date:** 2026-08-06 · **Input:** [NAV_GENERALIZATION_AUDIT.md](NAV_GENERALIZATION_AUDIT.md)
(five hardcoded strata) · **Method:** 4-researcher deep-research workflow +
synthesis (`wf_3ba06b92-a88`), sources verified online. · **Constraints
honored:** classical authority (learned proposes, never disposes), K0 single
arrival authority, no new eval harnesses (owner ruling), hardware last.

## Stratum 1 — pose: land the SEAM now, the localizer never (in sim)

`PoseProvider` interface with REP-105 frame discipline: `get_pose(frame) →
(SE2, 3×3 covariance, health)` for **MAP** (globally consistent, may jump;
serves goals/arrival) and **ODOM** (continuous, drifts; serves reactive
control). Two implementations now:

- `TruthPoseProvider` — both frames = sim truth, zero covariance
  (bit-identical migration; a pytest-archon rule then forbids any pose read
  outside providers).
- `DriftingOdomProvider` — the Probabilistic-Robotics alpha odometry model
  (~30 lines, seeded), calibrated to published Go2 leg-odometry drift
  (DogLegs: 0.5–1% of distance, 0.2–0.5°/m yaw; 2% stress tier).

Plus the two fielded GraphNav lessons: an explicit **LOST/DEGRADED health
state that K0 must check** (refuse to declare arrival rather than guess),
and **landmark-relative goal storage** (landmark_id + offset, re-anchored
on re-observation; world-frame only as fallback). Where polygons remain
legitimate (rooms), membership becomes **chance-constrained**
(P(inside) ≥ 0.9 under pose covariance — reduces to today's boolean at
zero covariance). Real SLAM stays a P5 HR-ledger item that slots into the
MAP role with zero consumer changes. **Effort: ~1 week.**
**Gate:** NAV_INSTRUCT T0 byte-equal to frozen baseline (refactor changed
nothing); T1 drift-on paired-seed non-inferiority; walk_with_me with drift
holds zero hard collisions (proves the gate binds to ODOM).

## Stratum 2 — oracle perception: wire the existing chain, classical tracking replaces IDs

The built-but-unwired DetectionMsg adapter chain becomes the only
perception ingress on the mission path (pass-through first = equality
commit; geom-ID matching deleted in the PR where the chain becomes
authoritative). Then the classical standard, zero learned parts:

- **Association:** per-candidate 2D Kalman + covariance, Mahalanobis
  gating at χ²(2, 0.95) = 5.991, Hungarian assignment; M-of-N (3-of-5)
  confirmation, miss-streak deletion (~100 lines numpy/scipy).
- **Verification:** Stubborn-style cumulative evidence per candidate,
  approach-then-verify state, and **rejected candidates remembered as
  false positives** (VLFM documents FP sensitivity as the open weakness
  at SOTA — this is gap-filling).
- **Arrival:** community ObjectNav criterion — 1.0 m radius
  (profile-derived) + viewability + M-of-N confirming frames — through the
  ONE K0 predicate; exact polygons retire from arrival.
- The literal 0.98 dies: sim confidence sampled from a miscalibrated
  overlapping TP/FP distribution; thresholds calibrated on known-absent
  trials. Noise parameters datasheet-traceable (D455 quadratic range
  sigma, dropout 0.1–0.3, FPs 0.5–2/100 frames). IPDA existence
  probability documented as the drop-in upgrade seam — not built.

**Effort: weeks (this IS Phase-1 Track B).**
**Gate:** zero `false_arrival` rows at T0/T1 in voice_nav_e2e (closes
U32's class); noise-ladder attribution splits FP-accepted vs dropout vs
drift; N11 traffic xfail flips on the final-approach work.

## Stratum 3 — vocabulary: three registries replace 3×N scattered surfaces

1. **RelationSpec registry** (SLOOP-shaped): each relation = one unit —
   name+aliases, anchor kinds, frame-of-reference policy, predicate,
   goal-region builder — the SAME predicate serves planning and K0
   verification. ~6 relations covers ~81% of natural reference (Sr3D); a
   new relation is <10 lines (QSRlib precedent). JEPD exactly-one-label
   property tests catch envelope drift for free.
2. **Per-scene semantics sidecar** (YAML, USD-LabelsAPI-shaped, joined by
   MJCF names — MJCF has no per-element metadata, so sidecar is the
   MuJoCo-native form and the forward seam to real perception). One
   loader, three derived views: class/alias tables (replaces 4 code
   files), detector query set (NanoOWL prompt list), and **eval landmark
   tables — generated, never transcribed**.
3. **Language lanes:** deterministic grammar stays for reflexes; the
   verb-gate gains a fallback-to-clarification (novel verbs get "I don't
   know how to do that yet" instead of silence); schema-constrained LLM
   decode + SigLIP unstub (U25) is the open-vocab step, Wave 2.

**Effort: weeks.** **Gate:** N12 + both N13 xfails flip; every
ClosedIntent gains a product-path case (closes U33); paraphrase variants
assert invariant resolution, one misleading variant asserts NON-compliance.

## Strata 4+5 — derivation, not exposure (the authority triple)

Nav2's own history proves YAML exposure alone reproduces footprint-drift.
Instead, ONE authority triple, low in the import graph:

- **RobotProfile** (exists; gains decel_max, reaction_latency) —
- **SpeedRegime** (CRUISE/SEARCH/APPROACH/RECOVER with accel pairs, a
  `from_froude` constructor; arbiter takes elementwise min — unifies the
  5 speed authorities both speed raises partially missed) —
- **SafetyEnvelope** (ISO-TS-15066 shape: `stop = r_foot + v·τ + v²/2a +
  intrusion + Z_r`, where `Z_r` = pose uncertainty, 0.0 now — one field
  that widens every envelope automatically when stratum 1 covariance
  goes live; `person_stop = max(1.2 m social zone, stop + 1.4·τ)`; the
  live 1.25-vs-1.2 drift resolves to 1.2 by measured quadruped proxemics,
  a provenance decision).

Every field carries PX4-style metadata (unit, source, date, **scaling
bucket**): embodiment (∝L), dynamics (∝√L), latency (v·τ, τ invariant),
human/environment (**never scales** — a half-size dog does not get half a
personal-space zone). Migration = branch-by-abstraction per family, two
commits each: (1) bit-for-bit equality with a test proving it, (2) any
value change separately under paired seeds; old constants poisoned via
PEP 562 `DeprecationWarning`-as-error. Stratum-5 first steps: fix the four
default-argument bindings an injected profile can never reach; decompose
the 1.32 composite; pin grid resolution as cells-per-footprint.
**Effort: stratum 4 ~1 week; stratum 5 ~days.**
**Gate:** drift property tests + bit-equality per family (frozen baselines
must not move); the half-scale-profile NAV_INSTRUCT smoke at constant
Froude, xfail → pass; scale-covariance metamorphic pair; Hypothesis
property: person_stop ≥ 1.2 m at every scale.

## The robust eval program — six instruments, zero new harnesses

1. **Scene-generalization split → NAV_INSTRUCT:** val_seen vs val_unseen
   (5–10 procedurally generated scenes, frozen seeds, never tuned
   against; ProcTHOR-style navigability rejection filters; generator
   emits scene + truth manifest as one artifact). The seen–unseen gap is
   the headline generalization number (R2R's val_unseen is 11 scenes —
   small is legitimate).
2. **Noise ladder → NAV_INSTRUCT + walk_with_me:** tier per episode — T0
   clean (frozen substrate), T1 calibrated (Go2 drift + D455 sigma +
   dropout + FPs), T2–T3 stress. Degradation curve reported
   ImageNet-C-style. T0 hard gate; T1 non-inferiority with pre-registered
   margin; T2–T3 honest xfails promoted when they first pass; **never
   tuned against stress tiers**.
3. **Metamorphic relations → NAV_INSTRUCT** (label-free): rigid-transform
   equivariance (strongest single fault detector in robot MT work), scale
   covariance (the stratum-5 probe), obstacle monotonicity,
   detector-dropout monotonicity. Violation = Wasserstein distance z-test
   against N≈8 repeat variability (exact equality would false-alarm on
   the reactive gate's nondeterminism).
4. **Language MRs → voice_nav_e2e:** paraphrase/ambiguity/noise variants
   per existing episode + one MISLEADING variant where non-compliance is
   the pass.
5. **Differential authority → all three:** log scorer + navigator arrival
   verdicts every episode; assert the one-way implication scorer-arrival
   ⇒ navigator-arrival (scorer is a derived view, not a peer);
   `authority_disagreement` and `false_arrival` become first-class
   attribution categories. Closes U31 (paired re-scoring of persisted
   traces as NEW DERIVED ROWS — frozen rows untouched, no re-freeze
   decision needed) and U32 systematically. Nightly boundary-fuzz near
   arrival radii where disagreements concentrate.
6. **Eval integrity → CI:** golden-file discipline (all tables generated
   from the sidecar manifest; a hand-edited table is a red build) + a
   nightly **mutation-of-the-evals panel**: six seeded defects (radius
   drift, gate disabled, pose offset, inverted relation, dropped
   detections, doubled envelope) must each redden at least one harness —
   a surviving mutant is itself a failure. This is the only direct test
   that the harnesses would catch what this program risks introducing.

## Sequencing

**Wave 0 — truth-keeping first (days):** U31 derived re-scoring + U32
false_arrival class + differential verdict logging + the
manifest→derived-tables generator. Every later delta is uninterpretable
without these; zero behavior changes.

**Then four parallel lanes (the P1 four-track shape):**
- **Lane A** embodiment/config (strata 4+5): default-arg fixes → authority
  triple → drift tests → family-by-family migration. Ends with the
  half-size xfail pinned.
- **Lane B** pose seam (stratum 1): provider → injector → frame-role
  binding → health/LOST → landmark-relative goals. `Z_r` lands as a Lane A
  field simultaneously.
- **Lane C** vocabulary (stratum 3): registry → sidecar → clarify-fallback
  → router coverage. Contains N12 (land first — flips its xfail), N13
  compile half, U33.
- **Lane D** perception (stratum 2 = Phase-1 Track B): chain pass-through
  → tracker → M-of-N arrival → noise tiers on. **N11-residual schedules at
  Lane D midpoint** (consumes tracker predictions + Lane A envelopes +
  parked proxemic_approach as fail-closed veto); flipping it also
  completes N13.

One cross-lane touchpoint only: the QDC envelope tables (Lane A derivation
× Lane C semantics) land as a joint PR. **Wave 2 (late P1/P2):** SigLIP
unstub, schema-constrained decode, T1 gates promoted, unseen-split gates.

## Anti-goals (binding)

No new harnesses; no SLAM/EKF in sim (seam only); no learned components in
dispositive positions; no IPDA yet; no second proxemic/arrival authority;
no ontology engine (~6 data-parameterized relations); no config-framework
adoption (the hand-rolled frozen-dataclass pattern stays); **no
expose-everything-to-YAML sweep — the knob count goes DOWN via
derivation**; no global scale factor (bucket-aware formulas only); no
ruff magic-number lint (plain AST-walking pytest with shrinking
allowlist); no big-bang rewrite; no tuning against stress tiers or the
unseen split; no photorealistic sim; no hardware before P5.

Full research reports + sources: workflow `wf_3ba06b92-a88` journal.
Key sources: Probabilistic Robotics odometry model · DogLegs (Go2 leg
odometry) · REP-105 · GraphNav anchoring · Stubborn · VLFM · GOAT ·
ObjectNav eval criterion · SLOOP · Sr3D · QSRlib · ISO/TS 15066 ·
quadruped proxemics study · PX4 param metadata · ProcTHOR/R2R splits ·
robot metamorphic-testing literature · D455 datasheet.
