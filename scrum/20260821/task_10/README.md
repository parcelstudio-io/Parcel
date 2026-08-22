# Task 10 — W-1: a world worth looking at

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence (binding):** `scrum/20260821/perception/bench_detectors.md` — the
same detectors that score 81–93% person recall on real photos score **0/69 on
our renders**, and a VLM describes our city as "colorful geometric shapes",
naming only the Go2 (the one textured mesh). `city_block.xml` has 48
material references and zero texture images; pedestrians are colored
capsules. **No perception measured in this world means anything until this
card lands.** This is the enabler for the whole cutover.

## Work

1. **Texture the city:** photo-like CC0 textures (Polyhaven-class, downloads
   authorized) for ground/asphalt/sidewalk/grass/crosswalk, building facades
   with distinct storefront/door regions and simple signage, props
   (benches, lampposts, planters) with material detail. MuJoCo `texture` +
   `material` assets; **geoms/collision/physics byte-equivalent** — visual
   only, so every nav baseline and mission test stays untouched.
2. **Make pedestrians look human:** attach textured human-like visual
   meshes to the existing dynamic-agent bodies (capsule COLLIDERS stay —
   physics unchanged; visuals ride along). Diverse enough (≥3 variants)
   that a detector generalizes, not memorizes one mesh.
3. **A held-out scene variant** (`city_block_b`): different layout, different
   textures/facades, same semantic classes — NEVER used during development
   or tuning of any perception component. It exists solely so E-2 can make
   a generalization claim. Mark it clearly; add a gate check that no test
   outside the held-out eval reads it.
4. **Acceptance is measured, pre-registered:** re-render the PG-1 bench's
   frame trajectory in the textured world and re-run its saved detector
   pipeline (artifacts at the bench scratch dirs are reusable). Targets,
   registered before rendering: OWLv2 fp16 person recall ≥0.5 (was 0.0);
   ≥5 of the 8 corpus place classes detected at least once (door,
   storefront included — both currently never fire); the VLM control names
   ≥3 real scene categories. If a target is missed, report the miss with
   the frames — do not tune the target.
5. Scene-truth sidecars for both scenes via the PG-2 surface convention and
   the documented regeneration tooling (sentinels/parity green).

OWNS: scene XMLs + texture/mesh assets (new `assets/` under scenes),
semantics sidecars via regeneration tooling, the re-render acceptance
harness (scratch), tests (asset-integrity: textures referenced exist;
held-out isolation check), `W1_STATUS.md`.
MUST NOT TOUCH: physics/collision definitions, navigation source,
`realtime/*`, yield policy, detector code (PG-1 owns it). Standard house
rules (incremental status doc; final seed sweep after last write; store
isolation is now mechanical but verify your own gate run anyway).

## Definition of done

Gate green (nav baselines unmoved — textures are visual-only, proven by the
frozen baseline not moving); ≥6 seeds RED (a texture path broken → asset
test reddens; held-out scene referenced outside E-2; sidecar hand-edited;
collision geom changed); the measured acceptance table with before/after
recall per class and the VLM control transcript. `W1_STATUS.md` standard
register.
