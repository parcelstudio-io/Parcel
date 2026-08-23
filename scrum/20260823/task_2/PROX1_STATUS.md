# PROX-1 status — dynamic person proximity (context profiles)

Executor: Opus. Baseline: HEAD `3792288`. **Two new files, zero edits to any
existing file.**

## What landed

A pure context→profile seam plus the owner object a later card wires in.
Nothing is reachable from the product path yet, by design (`runtime.py` is
MUST-NOT-TOUCH); the wire-in is handed to AWARE-1 below.

`src/parcel_robot/navigation/proximity_profiles.py` (new, 394 lines, the whole
file is the marked region `# ---- CARD PROX-1` … `# ---- END CARD PROX-1`):

| line | symbol | what |
|---|---|---|
| 1 / 394 | region markers | open / close |
| 77 | `PROXIMITY_PROFILES_CONFIG_KEY` | `"proximity_profiles"` |
| 80 | `ProximityContext` | the typed enum: `default \| indoor \| narrow`, plus `parse()` — **the rule-2 gate** |
| 129 | `ProximityProfile` | one `(person_stop_m, person_slow_m)` pair; `apply_to()` / `from_mapping()` |
| 189–199 | `_NARROW_/_INDOOR_/_DEFAULT_PROFILE` | the ladder literals + their derivation |
| 201 | `PREREGISTERED_PROXIMITY_PROFILES` | the shipped Go2-scale table |
| 217 | `VENUE_PROXIMITY_CONTEXT` | `go2_edu_plus → indoor` |
| 222 | `proximity_context_for_venue()` | unknown venue → `DEFAULT` (the *widest*) |
| 230 | `resolve_proximity_profile()` | **the pure selector** |
| 251 | `load_proximity_profiles()` | reads `safety.proximity_profiles`; validates every pair at boot |
| 301 | `ProximityContextOwner` | the safety-config owner |
| 366 | `ProximityContextOwner.set_proximity_context()` | **the proposal seam** |

`tests/test_prox1_proximity_profiles.py` (new, 230 lines, 7 tests).

### The ladder

| context | person_stop_m | person_slow_m | derivation |
|---|---|---|---|
| `default` | 1.20 | 2.50 | the shipped social zone, read off `DEFAULT_SAFETY_ENVELOPE` (no literal) |
| `indoor` | 0.95 | 2.00 | midpoint of narrow and default, to 0.05 m |
| `narrow` | 0.70 | 1.50 | `PERSON_SOCIAL_ZONE_FLOOR_M` (0.68) rounded **up** to 0.05 m |

Slow bands keep the shipped 2.5:1.2 band-to-stop ratio, rounded up to 0.05 m.
Narrow is the tightest pair the **existing** validator admits at Go2 scale;
the 0.02 m over the floor is derivation margin.

### The two rules, enforced not asserted

- **Floor logic untouched.** A profile is validated by *being applied*:
  `apply_to()` is a `dataclasses.replace` onto `ReactiveSafetyPolicy`, whose
  existing `__post_init__` runs `SafetyEnvelope.with_person_social_zone` and
  the physics floor. Nothing here re-implements a floor. The card's own
  illustrative `narrow: 0.5` is refused, in the authority's words, naming
  `PERSON_SOCIAL_ZONE_FLOOR_M`.
- **Rule 2 — no minted distances.** `set_proximity_context` takes an enum or
  its exact name. `0.4`, `0`, `1`, `True` are all `TypeError` (bool checked
  before int); an unknown name is `ValueError`; and the active policy is
  unchanged after every refusal.

## Deviations from the card

1. **`configs/robot.yaml` was NOT modified — blocked, needs owner
   authorisation.** The file is SHA-locked in three places
   (`evals/companion/embodied_plan_v1/manifest.json` `robot_config.sha256`;
   `tests/test_hw5_physical_profile.py:69 BASE_CONFIG_SHA256`; cascading to
   `scripts/ci_gate.py:353 DIGEST_SENTINELS` on the manifest itself, whose
   re-pin protocol at `ci_gate.py:224-260` requires owner authorisation +
   re-measured embodied-plan rows + a dated log entry). I added the block,
   measured it, and got exactly the two reds whose assertion message reads
   *"this card must not move it"* — then reverted. The preregistered ladder
   therefore ships as the code constant, and `load_proximity_profiles()`
   already reads `safety.proximity_profiles` the moment it exists.
   **The exact block, proven loadable and floor-clearing, is
   `PROPOSED_SAFETY_BLOCK` in `tests/test_prox1_proximity_profiles.py`.**
   Landing it after the authorised re-pin needs no code change here; the
   checklist is: edit `configs/robot.yaml` → `.parcel/bin/python
   tools/sync_runtime_assets.py --write` → re-pin the eval manifest →
   `test_hw5_physical_profile.py:69` → `ci_gate.py:353` + log entry.
2. **New module, not a marked region in `reactive_safety.py`.** The card
   allowed either. The new module avoids editing that file's shared import
   block (which is outside the marked region and would have been an E402 or a
   fence collision) and avoids an import cycle, since the module imports
   `ReactiveSafetyPolicy`. `reactive_safety.py` and `authority.py` are
   **byte-unchanged**; the `navigation/__init__.py` barrel is untouched, so
   consumers import from `parcel_robot.navigation.proximity_profiles`.
3. **`ReactiveSafetyConfig` does not exist** anywhere in the repo. The real
   type is `ReactiveSafetyPolicy` (`navigation/reactive_safety.py:175`), and
   that is what the card's step 3 was routed through.

## Tests

`env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label prox1
.parcel/bin/python -m pytest …` — never `-n auto`, never `ci_gate.py --tier`.

- `tests/test_prox1_proximity_profiles.py` — **7 passed**:
  `test_the_shipped_ladder_shortens_and_every_rung_clears_the_existing_floor`,
  `test_a_context_switch_swaps_the_active_pair_on_the_real_gate`,
  `test_a_below_floor_profile_is_refused_by_the_unchanged_validator`,
  `test_no_new_config_keys_leaves_todays_behaviour_byte_identical`,
  `test_a_reasoning_model_may_propose_a_context_but_never_mint_a_distance`,
  `test_an_unknown_venue_gets_the_widest_profile`,
  `test_the_ladder_literals_still_match_their_stated_derivation`.
- No-regression neighbours, **197 passed**: `test_prototype_profile`,
  `test_hw5_physical_profile`, `test_authority_config_drift`,
  `test_release_parity`, `test_runtime_assets`, `test_e2_safety_wiring`,
  `test_p1e_social_zone_is_config`, `test_door1_doorway`, `test_e6_owner_band`.
- Ratchets/oracles, **67 passed**: `test_authority_no_literal_drift` (run with
  `-m ""`; the new navigation module adds no retired-family literal),
  `test_import_order_no_cycle`, `test_hw1_py310_clean`.
- `.parcel/bin/ruff check` on both new files: clean, no `noqa`, baseline still
  7 fingerprints.

## Handed off

**To AWARE-1 — the `set_proximity_context` wire-in.** Everything below is
outside this card's fence and deliberately not done:

1. `RobotRuntime.__init__` (`runtime.py:1763`) builds `ReactiveSafetyPolicy`
   directly. The wire-in is to keep that as the *base* policy and hold a
   `ProximityContextOwner(base_policy, load_proximity_profiles(safety_config,
   base_policy=base_policy), proximity_context_for_venue(venue))`, then read
   `owner.policy` where `self.reactive_safety_policy` is read today.
   `owner.policy` is a single atomic attribute read of a frozen dataclass —
   no lock, safe from the 10 Hz tick, and it must stay that way.
2. **`owner_follow.owner_keepout_m` does not follow the context.** `runtime.py`
   derives `minimum_owner_keepout = person_stop_m + owner_collision_envelope_m`
   and pushes `person_stop_m`/`person_slow_m` into `follow_config` once, at
   construction. A context switch that shortens `person_stop_m` leaves the
   follow stand-off where it was — safe (wider than required), but the
   formation will not tighten indoors until someone derives those from the
   active policy too. Naming it so it is a decision, not a surprise.
3. `headless_city.py:1025 _reactive_safety_from_store` is the second
   construction site and would need the same treatment for parity.
4. The reasoning-model tool surface: expose `set_proximity_context` taking
   **only** the three context names. `ProximityContext.parse` already refuses
   anything number-shaped, so the tool schema should be an enum, not a float.
5. `VENUE_PROXIMITY_CONTEXT` maps `go2_edu_plus → indoor` today. If AWARE-1
   wants per-venue contexts in config rather than in code, that is a second
   card — the map is deliberately in code so a venue file cannot mint one.

## Notes for the integrator

- `git diff` is empty; `git status` shows exactly two untracked files, both
  mine. `configs/robot.yaml` and its three mirrors/`MANIFEST.json` are back at
  HEAD bytes (`tools/sync_runtime_assets.py --check` → *release parity OK*).
- `CODEBASE_INDEX.md` reports STALE, but it was **already stale at HEAD before
  this card's files existed** (verified by removing the new module and
  re-running `--check`). Regeneration is the close-out step, not mine.
- The owner decision this card needs: authorise the `configs/robot.yaml`
  SHA re-pin so the preregistered table moves from code into base config.
