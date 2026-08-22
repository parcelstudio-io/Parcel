# Task 13 — C-3: the cutover (grounding reads the dog's own map)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** recon_groundtruth.md's dependency ledger — the live path reads
MuJoCo ground truth at `extract_city_semantics`/`visible_city_semantics`
(confidence stamped 0.98 by fiat) into `ObservationSemanticMap.query`;
`PerceptionChain` T0 is an identity. PG-3 built the abstention gate beside
R20 default-OFF, waiting for exactly this card.
**DISPATCH GATE: after C-2 closes.**

## Work

1. **Perception tier T1:** `perception.tier: T1` swaps the semantic-candidate
   source from the simulator oracle to C-2's OnlineSemanticMap — same
   `ObservationSemanticMap`/`GrounderV2` consumer contract, honest
   confidences from evidence (never a stamped 0.98). T0 remains the default
   and remains byte-identical.
2. **Shadow mode is the migration instrument:** `tier: T0_shadow_T1` runs
   BOTH — the oracle drives the robot, T1 runs in parallel, and every
   divergence (grounding disagreement, admission disagreement, arrival
   verdict disagreement) is logged to the evidence stream with the frames
   that produced it. The cutover metric is the shadow agreement rate,
   reported per query class with denominators — not a feeling.
3. **The R20 vocabulary cutover:** under T1, `_place_admission`'s known/offer
   vocabularies come from the learned map (via PG-3's gate); corpus rows
   10–13 must STILL refuse (the PG-3 equivalence tests extend to T1), and
   known-place queries must admit. The Narnia property survives the loss of
   the label set — that is this card's single most important assertion.
4. **Scene answerability under T1:** R18's scene block reads the perceived
   map; "what do you see" describes what the dog has actually detected,
   with honest uncertainty ("I think that's a bench — I've only seen it
   once").
5. **Live proof, textured world, own stack:** a full voice session in
   shadow mode — "go to the lamppost", "go to the bench", "go to narnia",
   "what do you see" — with the shadow-agreement table; then ONE mission
   driven end-to-end by T1 alone (oracle consulted by nobody), arrival
   scored by PG-2 convention. Safety stack runs on geometry/dynamic-agent
   channels throughout (unchanged by tier — assert it).

OWNS: `perception_chain`/tier plumbing, `navigation/semantic_map.py` source
selection, `runtime.py` vocabulary/scene wiring under T1, shadow-divergence
logging, tests, `C3_STATUS.md`.
MUST NOT TOUCH: the T0 oracle path's behavior (byte-identical under
default), safety/yield channels, lane/broker, PG-3 gate internals
(consume, don't fork). Standard house rules.

## Definition of done

Gate green with T0 default untouched; ≥10 seeds RED (T1 stamps fake
confidence; shadow divergence unlogged; rows 10–13 admit under T1; safety
reads the tier; T0 not byte-identical). The live shadow table + the
T1-only mission with its scored arrival. `C3_STATUS.md` standard register
including the honest statement of what T1 cannot yet do (classes the map
has not learned, lighting/viewpoint limits).

## REVISION 2026-08-21 (binding; supersedes the above where in conflict)
Evidence: scrum/20260821/cutover_research/*.md — read all five first.

1. **F1, highest priority: the POI grounder is a second oracle and NO card
   owned it.** `PlaceGrounder` fires BEFORE semantic search
   (`pipeline.py:~1000`, `demo_pois.yaml`), grounding "crosswalk"/"coffee
   shop"/"park"-class directives to hardcoded coordinates
   (`goal_source: known_poi`). Under T1 and in every shadow comparison the
   POI arm must be DISABLED/EMPTY, with a RED seed proving the harness
   catches a POI-sourced pass. Without this, C-3's T1-only mission and all
   of E-2 are false-positive-prone and the eval would be retracted.
2. **The grounding chain (benches, measured):** hosted noun → detector-
   vocab/learned-name match (no match ⇒ refuse — Narnia survives) →
   candidates ranked by evidence-weighted label strength → **Qwen3-VL-2B
   veto on the top candidate's crop** (p_yes ≥ 0.5; measured 0/8 absent
   admitted, 5/5 present correct, ~30–55 ms, ECE 0.07) → navigability
   gate. The VLM veto is PG-3's FIFTH signal and is embedding-version-free.
3. **Shadow metric discipline (F4):** pre-register per-class agreement
   thresholds BEFORE any run; classify every divergence as one of
   {benign_miss, localization_delta, admission_flip, refusal_flip} with
   the two flip classes as HARD gates; frustum/occlusion/convention
   mismatches separated from real divergence in the denominators; and
   **≥3 T1-only closed-loop missions** (not 1) — shadow agreement cannot
   see the states T1-driven behavior creates.
4. **F2: re-derive every PG-3 threshold/margin/operating point on textured
   renders before T1 consumes them** — the current calibration was
   measured on the invalidated untextured distribution. The architectural
   conclusions stand; the numbers do not.
5. **The VLM duty-cycle policy is owned HERE:** generation permitted only
   when stationary / between keyframes / behind PG-1's admission; pin it
   with a seed. The high-priority-CUDA-stream option (measured 95.8 ms
   exploratory) may be adopted if it holds under pre-registered
   measurement; otherwise the duty cycle alone is the mechanism. Vendor
   Qwen3-VL-2B with a provenance lock; the 8B leaves residency.
