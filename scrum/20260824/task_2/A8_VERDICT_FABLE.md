# A8 FOLLOW-COMPOSE · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard runs (label `fable-a8-verify`) — the A8 suite + the
follow/OT-2/P1-C/UWB neighbours + A2/A3/A4/A6 card suites + runtime/
navigation/safety suites + both DEC ratchets = **906 passed, 12 skipped**
(the register's per-suite counts reproduced; the three p1c files my first
sweep missed run green separately); scope = ONE modified product file
(runtime.py +239/−5) + two new leaves (owner_tracking/install.py 224,
navigation/follow_compose.py 359, both under the M6 target) + the 53-row
test; `config.py` byte-unchanged at 1000 lines; every hunk and both leaves
read line-by-line.

## Disposition: **ACCEPTED**

- **The veto is structural**: an ambiguous/unsynchronized/latched frame never
  reaches `follow.step` (call-spied), so the heading filter cannot be
  poisoned by a person who may not be the owner. `HOLD_LOST` deliberately
  does NOT veto — the controller's zero-command + `lost` string is the
  working reacquisition route, and the composer adds only the window,
  derived from `owner_search.lost_timeout_s`. No new number anywhere: the
  sync bound is `min` of the two producers' own TTLs, proven at bound/bound+1
  with a min→max seeded red.
- **No floor moved, proven twice**: identity (`follow._safety_policy is
  runtime.reactive_safety_policy`; the runtime policy's own
  `clearance_profile`), plus a source scan asserting neither new module
  states any clearance literal. The wall sweep shows the gate only
  subtracts.
- **`_stamp_localization_health` is the right kind of change**: A3's
  `motion_latched` was a contract field NOBODY populated — consumers were
  obeying a constant False. The latch itself is untouched and still enforced
  at the dispatch join; the stamp only makes the snapshot tell the truth,
  and with no localizer commissioned (the shipping default) the snapshot is
  returned BY IDENTITY — A4's published bytes unchanged. The composer's
  latch check composes with (never replaces) the dispatch join, seeded-red
  in both directions.
- **The two OT-2 corrections are strictly more honest**: per-track
  `ambiguous_margin` now surfaces as `ambiguous` instead of collapsing to
  `searching`, and the degrade branch can publish `ambiguous` — while a
  stale `confirmed` remains impossible there, and
  `OWNER_IDENTITY_TRUSTED_STATES == {"confirmed"}` means ambiguous and
  searching cost identical clearance. The distinction buys only the HOLD's
  ability to say which thing went wrong.
- **The UWB DEFER is a measured decision, honestly bounded**: 0/100
  vision-only swaps with failure direction = refusal; the beacon scores
  0.66–0.78 exactly at the crossing it was proposed for (sep 0.31–0.35 m vs
  σ 0.25 m); the noise model has NO NLOS bias so every beacon number is an
  optimistic bound — which strengthens the defer; UWB-alone cannot produce
  `confirmed` in this codebase (asserted). Re-open trigger + acceptance bar
  (AoA ≥0.95 at ≥0.75 m with measured NLOS) recorded. A recommendation with
  evidence, not a purchase.
- **The offline floor is the owner's own sentence**, shape-complete with the
  connectivity signal honestly named as the model-lane readiness proxy; the
  uncommissioned row is F5 verbatim (STOP + HOLD + canned line).
- **The harness defect the executor caught deserves the record**: same-length
  source seeding defeats CPython's (mtime,size) .pyc invalidation — a
  poisoned bytecode cache that could have surfaced as a FALSE GREEN.
  Fixed with a cache drop; grepped as the only suite using the pattern.
  Any future same-length seeder must copy the fix.

Register corrections, mine: "zero noqa added" is off by one — runtime.py's
`_announce_follow_hold` carries `# noqa: BLE001 - a HOLD must not need a
voice` (both new leaves and the test are genuinely clean). ACCEPTED — a
never-raises boundary in the surrounding module's exact idiom — with the
corrected count recorded here.

Integrator action taken with this cycle: the pre-existing red A8's sweep
correctly attributed to A6 (`test_prototype_profile::
test_introducible_keys_are_exactly_the_three_documented_families` — A6 added
`"stop_hotword"` to `OVERLAY_INTRODUCIBLE_KEYS` without extending the
verdict test) is FIXED in its own commit: the allowlist gains the
`stop_hotword` family with the read-site guard named; 42/42 green. That was
my miss as A6's verifier — the test was in neither guard set.

Undone, correctly named and box-day: real camera identity (every identity
row uses P1-C's histogram fixture on a synthesized clip; the real-encoder
headroom is ~0.03 and clothing/lighting is what eats it), mounted tracking,
the physical two-person trials, and THE ENABLE DECISION itself —
`_owner_identity_commissioned()` is necessary and never sufficient; per F5
any measured identity swap keeps Follow disabled and the shipped floor is
STOP + HOLD + the canned line. Software follow-ups recorded: the config.py
re-pin for `owner_follow.tracker` (+ `yield_aside`, same shape since Y-2),
a real connectivity signal, simulator-adapter population of
`ambiguity_reason`/`last_confirmed_monotonic_ns`, the hold folded into
`FollowDetail`, a frame-level `STATE_AMBIGUOUS` in P1-C's tracker.
Does not prove: anything physical; no real person has ever been tracked.
