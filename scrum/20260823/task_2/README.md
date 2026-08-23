# PROX-1 — dynamic person proximity (context profiles)

**Wave A · Tier B · Executor: Opus · Verifier: Fable (light).**
Owner directive (2026-08-23): person collision distance should be generally
shorter, and shorter still when the robot knows it is indoors / in close
quarters; a reasoning model decides later — **start simple**.

## What to build

1. Preregistered proximity profiles in `configs/robot.yaml` (BASE, so no
   overlay-admission change): e.g. `safety.proximity_profiles:
   {default: {person_stop_m: 1.2, person_slow_m: 2.5}, indoor: {0.7, 1.6},
   narrow: {0.5, 1.2}}` — exact values yours to derive, but every profile
   must clear the P1-E physics floor (envelope stop distance ≈0.32 m at Go2
   scale) through the EXISTING validator; the floor logic itself is
   MUST-NOT-TOUCH.
2. A pure selector (new small module or a marked region in
   `navigation/reactive_safety.py`): `resolve_proximity_profile(context)` →
   validated (person_stop_m, person_slow_m). Context is a typed enum
   (`default | indoor | narrow`); source of truth today = config/venue
   (`go2_edu_plus` venue may map to `indoor`); a public
   `set_proximity_context(...)` on the safety-config owner so a later
   reasoning-model tool can PROPOSE a context switch (proposal-only: the
   model may never mint a raw distance — architecture rule 2).
3. Apply through the existing `ReactiveSafetyConfig` /
   `SafetyEnvelope.with_person_social_zone` path — a context switch swaps
   which preregistered pair is active; refusal below the physics floor is
   the validator's, unchanged.

## OWNS
`configs/robot.yaml` (safety additions), `navigation/reactive_safety.py`
(marked region `# ---- CARD PROX-1`), `authority.py` (marked region, only if
needed), `tests/test_prox1_proximity_profiles.py`, this folder.

## MUST NOT TOUCH
`runtime.py`, `config.py`, `web_panel.py`, `core/`, `backends/`, the physics
floor / stop-distance math, any other card's fence, git.

## Testing policy (owner, 2026-08-23 — binding)
Capability tests only: profile resolution works; context switch changes the
active pair; a below-floor profile is refused; default behavior with no new
keys is byte-identical to today. No combinatorial suites, no seeded-RED
batteries, no preregistration doc. One short STATUS md when done.

## Execution rules
Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label prox1 …`
with `env -u TMPDIR`; never `-n auto`; never `ci_gate.py --tier`; no `noqa`
(ratchet is 7 fingerprints, add none); ruff clean; don't touch the owner's
live stack (`:8765`, `/tmp/parcel_sim.sock`) or `parcel_memory.sqlite3`;
no commit/push. Baseline: HEAD (clean tree) — `git diff` must show only
your OWNS.
