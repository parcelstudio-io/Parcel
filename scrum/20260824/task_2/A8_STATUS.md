# A8 FOLLOW-COMPOSE — status (Opus executor, 2026-08-24)

Card: `IMPLEMENTATION_PLAN.md` row A8 · HLD Gate 6 · `CLAUDE_RESPONSE.md` A3/A12
(owner chose **(a) Follow IS in M1**) · F5 loss-class policy.
Base: `main` @ `6ca1321`, clean tree. **Not committed.** Guard label `a8-follow`.

## 0 · What landed

| file | what |
|---|---|
| `src/parcel_robot/owner_tracking/install.py` (new, 224 lines) | `OwnerTrackerSettings` (the `owner_follow.tracker` knob, unknown keys refused BY NAME) + `build_owner_tracker` — never raises, `off` builds nothing |
| `src/parcel_robot/navigation/follow_compose.py` (new, 359 lines) | `owner_range_sync_reasons`, `FollowComposer`, the four canned lines, `offline_floor` |
| `src/parcel_robot/runtime.py` (15 hunks, +239/−5) | the product caller, the control-loop veto, the spoken hold, `offline_floor()`, `_stamp_localization_health`, two OT-2 identity corrections |
| `tests/test_a8_follow_compose.py` (new, 1,478 lines, **53 rows**) | the proof |
| `config.py` | **byte-unchanged** (`git diff` empty) — DEC-0 ceiling respected |

No new `# ---- CARD` marker (DEC-0 M7: the count may only fall). Both new modules
are under the 600-line M6 target. Zero `noqa` added on any A8 line.

## 1 · The product wiring — `install_owner_tracker` has a caller

Addendum A3's finding was `install_owner_tracker` had **zero product callers**
(only a docstring and a comment). It now has two build sites:

1. `RobotRuntime.__init__` — reads the knob, and with no camera venue yet says
   so: `unavailable: no encoder resolved (siglip2: PARCEL_SIGLIP2_ONNX is not set…)`.
2. `attach_camera_ingress` — the re-attempt, because the installer's own
   docstring says the tracker waits for "an encoder and a gallery that only
   exist once a camera venue has been resolved". Never replaces a live tracker.

| row | measured |
|---|---|
| `mode: off` | tracker `None`, `owner_identity_snapshot()` `None`, `_ot2_apply_owner_identity` returns **the same object**, attaching a camera installs nothing |
| bare YAML `mode: off` | YAML 1.1 resolves it to the boolean `False`; the knob accepts `False` as `off` and refuses `True` with a "quote it" message (a fail-closed trap that reads as a bug is not fail-closed) |
| `moode: gallery` | `refused: unknown owner_follow.tracker settings: ['moode']`, one **error** event, nothing built; latch/gate/floors bit-identical |
| `mode: gallery` + calibrated gallery + camera venue | `OwnerTracker` installed, threshold published, `calibrated=True` in the detail |
| uncalibrated gallery | **refused** by default, quoting P1-C's 0.9295 stranger score; `require_calibrated: false` is the only way past it |
| gallery from another encoder | refused — "a cosine across two encoders is not a cosine" |
| missing gallery | degrades loudly, does not raise into `__init__` |

### The knob, and the one honest limitation
`owner_follow.tracker:` — nested inside a section the SHA-locked base already
defines, popped and validated at the read site, the shape
`owner_follow.prediction` / `owner_follow.yield_aside` already have.

```yaml
owner_follow:
  tracker:
    mode: "off"              # off (shipped) | gallery ; quote it, YAML eats a bare off
    gallery_path: ""         # "" = owner_tracking.gallery.default_gallery_path()
    require_calibrated: true # P1-C: an uncalibrated boundary claims the stranger
```

**It is settable in a configuration file handed to `--config` (every test row
uses that route) and NOT settable from a profile overlay on the SHA-locked
base**, because `config.py` sits exactly on the DEC-0 1,000-line ceiling and A8
left it byte-unchanged. This is a *standing* property of the section, not new
debt: `owner_follow.yield_aside` has had exactly the same shape since card Y-2,
and the test pins both. The one line a later authorised config.py re-pin needs:

```python
        # A8 FOLLOW-COMPOSE: the owner tracker's mode/gallery. Read-site guard:
        # `owner_tracking.install.OwnerTrackerSettings.from_mapping`.
        "owner_follow.tracker",
```

## 2 · Synchronized pixel/range — one epoch or a typed refusal

`owner_range_sync_reasons(snapshot)` is **additive to the spine**: the
assembler's own `health_reasons` are carried through first, then the Follow
pair check. Named reasons: `owner_range:mixed_epoch`, `owner_range:capture_skew`,
`owner:stale`, `scan:stale`.

**No new number.** The skew bound is `min(owner.max_age_ns, scan.max_age_ns)` —
the tighter of the two producers' *own* declared TTLs. Proven at the boundary:
`bound` passes, `bound + 1` refuses. Seeded-RED: swapping `min` for `max` in the
product file makes a 2× skew pass.

A refusal ⇒ `HOLD_UNSYNCHRONIZED`, zero command, the sentence
*"I cannot line up what I see with what I range, so I am holding still."*

## 3 · Ambiguity ⇒ HOLD; loss ⇒ HOLD + reacquire

**Ambiguity is structural, not advisory.** On `snapshot.owner.ambiguous` the
composer does **not call the controller at all** — pinned by a call spy — so an
ambiguous frame never enters the heading filter and the next confident frame
cannot inherit a heading estimated from someone who may not be the owner. That
is what "no track switch" means here; the controller's `owner_id`,
`heading_rad` and `track_status` are asserted unchanged across the hold.

**Two runtime corrections were needed to make ambiguity reachable at all**, and
both are strictly-more-honest and additive:

* `tracker.py`'s frame-level state collapses "I saw two people and could not
  tell which" into `searching` (`reason="no_gallery_match"`), while the
  evidence survives per-track as `reason="ambiguous_margin"` — the margin gate
  saying the best candidate cleared the gallery threshold with a runner-up
  inside `min_margin`. `_ot2_publish_update` now reads that;
* `_ot2_apply_owner_identity`'s degrade branch published a hard-coded
  `searching`. It now publishes `ambiguous` when the tracker said so and
  `searching` otherwise. **A stale `confirmed` can still never be published
  there** — that would hand the reactive gate's relaxed band to a claim nobody
  made this tick. `OWNER_IDENTITY_TRUSTED_STATES == {"confirmed"}`, so ambiguous
  and searching cost the same clearance; the distinction only buys the HOLD the
  ability to say *which* thing went wrong.

Proven through the runtime's own frame door (`_publish_camera_frame` →
`_ot2_apply_owner_identity`) with two people rendered identical: the observation
reaches `state="ambiguous"`, `OwnerBeliefV1.ambiguous` is True, the composer
HOLDs with `AMBIGUOUS_OWNER_LINE`. With the shipped (different-looking) pair the
same corpus produces **no** `ambiguous_margin` at all, so the row measures the
mechanism, not a constant.

| hold | vetoes the controller? | line |
|---|---|---|
| `unsynchronized_owner_evidence` | yes | "I cannot line up what I see with what I range…" |
| `localization_latched` | yes | "I am not sure where I am any more…" |
| `owner_ambiguous` | yes | "I can see two people who might be you, so I am holding still." |
| `owner_lost` | **no** | "I have lost track of you, so I am holding still and looking." |

`owner_lost` is deliberately not a veto: the controller already answers a lost
owner with a zero command **and** the `lost` state string
`_maybe_trigger_owner_search` keys on, so vetoing it would replace a working
reacquisition route with a second one. The composer adds the window instead —
`reacquire_remaining_s`, counted from the last **confirmed** sighting (it does
not restart on each lost tick) and sized from `owner_search.lost_timeout_s`, the
route's own timeout. No new timeout invented. Reacquisition is allowed: one
confident frame ends the hold. It is a safe-HOLD, never stop-and-return (the
wave-2 refutation: contacts 319→323, contact time 89→245 s).

The line is **edge-triggered** — said once per hold transition through
`_brain_vocalize`, not at 10 Hz — and `follow_hold_snapshot()` returns `None`
when not holding (R1: a run that never held is byte-identical on the wire).

## 4 · Follow speed obeys the commissioned gate

* **Identity, not equality:** `runtime.follow._safety_policy is
  runtime.reactive_safety_policy`.
* **Wall sweep in replay:** the follow controller driven at a wall from 2.0 m to
  0.2 m; at and inside `obstacle_stop_m` the gate's translation is exactly 0.0,
  and at every distance the gated command's translation is ≤ the controller's.
  The gate can only subtract.
* **A8 adds no clearance number.** `FollowConfig().obstacle_stop_m` 0.65,
  `reactive_safety_policy.obstacle_stop_m` 0.65, `obstacle_slow_m` still derived
  from `DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m`,
  `planner_gate_ring_m == clearance_profile.gate_range_ring_m` (A2's one
  authority). A source scan asserts neither new module contains `stop_m`,
  `clearance_m`, `keepout` or a `_m = 0.` literal.
* A HOLD is a zero command; run through `apply_reactive_safety` it stays zero.

## 5 · The latch and the STOP both beat Follow

**A3's latch.** `LocalizationHealthV1.motion_latched` is the contract's own word
for the latch and **nothing populated it** — every consumer obeying it was
obeying a constant False. `_stamp_localization_health` now publishes it from
`self._localization.latch`. With no localizer commissioned (the shipping
default) the snapshot object is returned **unchanged, by identity**, so A4's
published snapshot is byte-identical. With a latched latch: `translation_allowed`
False, composer `HOLD_LATCHED`, zero command — *and* the runtime's own
`_evaluate_dispatch_input_health` independently reports
`translation_allowed=False`, so this is a composition and not a replacement.
Seeded-RED: disabling the composer's latch check drops the hold while the
dispatch join still refuses.
(`latch.last_margin` is `inf` until a whole-map match answers; the contract
refuses a non-finite margin by design, so it is published as `None`.)

**A6's local STOP.** With Follow enabled, `_stop_hotword_latched` reaches
`arbiter.emergency_stopped` — the *same* flag `action("emergency_stop")`
engages, asserted equal to the panel's own state, with both `panel` and `voice`
rows in the safety log. Follow is preempted by that one emergency route
(`preempt(..., targets=(… "follow" …))`, pinned in source), the arbiter has no
current command, and a re-enable attempt under the latch raises. No parallel
follow-side flag exists.

## 6 · The offline floor

`offline_floor(connected, follow_commissioned)`:

| connected | follow commissioned | line | follow | hold | stop |
|---|---|---|---|---|---|
| yes | either | *(silent)* | per gate | yes | yes |
| no | **yes** | "Sorry but I am currently offline so all I can do is follow you until we are connected to the internet." (the owner's own words) | **yes** | yes | yes |
| no | no | "Sorry but I am currently offline, so all I can do is hold still until we are connected to the internet." | no | yes | yes |

That third row is F5 verbatim: *ship floor until the gate passes = local STOP +
HOLD + the canned line*.

**What is stubbed, named.** The connectivity signal is `_model_status`, which is
`_refresh_model_health`'s HTTP readiness probe over the **configured inference
lanes** every 10 s — not a test of the Internet and not a link-layer signal. It
is the honest proxy this build has ("the model lanes are unreachable" is the
loss class the line is about). A real connectivity check is a named M1/box-day
follow-up, not faked here.

`follow_commissioned` comes from `_owner_identity_commissioned()`: an installed
tracker behind a **calibrated** gallery. Its docstring says, and a test asserts
it says, that this is **necessary and never sufficient** — the half that decides
ENABLE is physical and has no representation in this process.

## 7 · The UWB decision — FROM MEASUREMENT

**Corpus.** P1-C's deterministic two-person clip (20 frames @ 4 Hz, crossing at
frames 8–11, owner fully occluded 13–16), rendered by the real renderer, plus
**10 generated variants** in which the other person's shirt/trouser/skin are
swept from his own toward the owner's (α ∈ {0, 0.5, 0.9, 0.95, 1.0} × pattern
different/same). Enrollment is the owner's: frames 0–5, the other person as
negatives, calibrated (threshold 0.6399, `min_margin` 0.02). Scored on 6–19 so
no cosine is a crop against itself. Tracker: the real `OwnerTracker`.

### Arm A — vision only

| | measured |
|---|---|
| owner **swaps** | **0 / 100** visible scored frames, across all 10 variants |
| correct claims | 90 / 100 |
| refusals (`no_claim`) | 10 / 100 — **all** at total appearance identity (α=1.0, same pattern), every one carrying `ambiguous_margin` |
| claims during the 4 occluded frames | **0** |

The sweep reaches the failure point, so the zero is not vacuous — and the
failure direction is **refusal, never a wrong claim**. That is what makes A8's
HOLD a safe floor rather than a fig leaf.

### Arm B — would a range beacon have disambiguated?

Rule is parameter-free: assign the owner to whichever candidate the beacon's
noisy sample is closest to. No threshold, no k-σ. Shipped model:
σ_range 0.25 m, σ_bearing 0.08 rad, 200 draws/frame.

| frame | owner visible | sep 2-D | sep range | beacon range-only | beacon range+bearing |
|---|---|---|---|---|---|
| 0 | yes | 4.989 | 0.550 | 0.905 | 1.000 |
| 5 | yes | 2.380 | 0.410 | 0.840 | 1.000 |
| 8 | yes | 0.828 | 0.277 | 0.760 | 0.925 |
| **9** | yes | **0.345** | 0.226 | **0.700** | **0.780** |
| **10** | yes | **0.313** | 0.174 | **0.660** | **0.755** |
| 11 | yes | 0.789 | 0.120 | 0.610 | 0.940 |
| 13–16 | **no** | 1.8–3.4 | 0.02–0.13 | 0.525–0.600 | 1.000 |
| 19 | yes | 4.949 | 0.236 | 0.675 | 1.000 |

*crossing mean: range-only **0.682**, range+bearing **0.850**.
occlusion mean beacon range error **0.185 m**.*

Separation sweep (owner 3 m ahead, other displaced laterally):

| 2-D separation | range-only | range+bearing (AoA) |
|---|---|---|
| 0.3 m | 0.535 | 0.715 |
| 0.5 m | 0.550 | 0.795 |
| **0.75 m** | 0.575 | **0.935** |
| 1.0 m | 0.665 | 0.975 |
| 1.5 m | 0.810 | **1.000** |
| 3.0 m | **0.990** | 1.000 |

### Recommendation: **DEFER — UWB stays OUT of the M1 BOM.** (A recommendation with evidence. Not a purchase.)

Four reasons, in order of weight:

1. **A beacon does not solve the problem it was proposed for.** At the crossing
   the two people are 0.31–0.35 m apart in 2-D and 0.12–0.28 m in range, against
   a 0.25 m range σ. Range-only is 0.66–0.70 there — barely better than a coin
   toss exactly when it is needed. Even AoA is 0.755–0.780. Buying UWB to
   disambiguate a corridor crossing is buying the wrong thing.
2. **The hazard it was to buy down did not appear.** Vision-only with a
   calibrated gallery swapped **0/100**; it refuses instead, and A8 turns a
   refusal into a HOLD plus a sentence. The safety case does not need the beacon.
3. **Where a beacon would pay is CONTINUITY, not safety.** Through the four
   occluded frames — where appearance has nothing — the beacon holds the owner
   to 0.185 m mean range error and AoA assignment is 1.000. That is a comfort
   improvement over a HOLD the floor already performs correctly.
4. **It is a purchase and a firmware change, not a wire.** `uwb/__init__.py`
   declares "No real UWB hardware"; `GroundTruthUwb`/`SimUwbPose` are single-fob
   by construction (there is no second-person UWB sample anywhere in the tree);
   and `OwnerFusionStub(primary="uwb")` with no vision reaches `ambiguous` by
   construction — **UWB alone can never produce a `confirmed` owner in this
   codebase** (asserted). Adding it means a driver on `rt/uwbstate`, an
   AoA-capable anchor (not a cheap range-only tag — the table above says
   range-only never reaches 0.95 inside 3 m), a fob, and a fusion rewrite.

**Honesty bounds on these numbers, stated rather than buried.**
* The vision arm's encoder is P1-C's 72-dimension histogram fixture on a
  SYNTHESIZED clip. It measures the MECHANISM. The real-encoder margin is
  P1-C's own: SigLIP-2 separated owner from stranger by **≥ 0.05** on held-out
  frames with a calibrated gallery, against `min_margin` 0.02 — about **0.03 of
  headroom**, and clothing/lighting change is exactly what eats it.
* The UWB noise model is zero-mean Gaussian with dropouts and **no NLOS bias
  term** (asserted: the word "bias" does not appear in `uwb/noise.py`; the model
  draws `rng.gauss(0.0, …)`). Real indoor NLOS adds a *positive* range bias
  typically well beyond 0.25 m, so **every beacon rate above is an optimistic
  bound** — which strengthens the defer, not weakens it.
* One crossing-geometry family, one camera, one enrollment.

**Re-open trigger (the box-day measurement this defers to).** If the box-day
study measures **any** vision-only owner-identity swap (F5: any identity swap ⇒
Follow stays disabled), or a refusal rate that makes Follow unusable, then an
**AoA-capable** UWB module becomes a BOM candidate and its acceptance bar is:
≥ 0.95 correct assignment at ≥ 0.75 m of 2-D separation, measured **through the
real module on the real body mount, with the NLOS bias measured**, not modelled.

## 8 · Suites (all through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label a8-follow`)

| suite | result |
|---|---|
| `test_a8_follow_compose.py` | **53 passed** |
| `test_follow_bench_v1 / _formation / _prediction / _yield_wiring`, `test_ot2_identity`, `test_ot2_memory_principal` | 130 passed, 5 skipped |
| `test_p1c_owner_tracker / _fusion_seam / _gallery / _enroll_appearance`, `test_p2_uwb_noise`, `test_a2_navglue`, `test_a3_discontinuity_latch`, `test_a4_spine`, `test_a6_stop_local` | 236 passed |
| `test_runtime`, `test_navigation` | 94 passed |
| `test_person_aware_nav`, `test_navigation_tracker`, `test_pose_consumers`, `test_dynamic_layer`, `test_door1_doorway`, `test_p0b_companion_unlocks`, `test_aware1_head_turn` | 263 passed |
| `test_core_hard_stop`, `test_brain_safety_wiring`, `test_safety_log`, **`test_dec0_debt_ratchet`**, **`test_decig2_import_ratchet`** | 73 passed |
| `test_e2_safety_wiring`, `test_prototype_profile` | 79 passed, **1 pre-existing failure — not A8's** |

**Ports named:** two rows in `test_a8_follow_compose.py` were written against
the wrong accessor and corrected to the product's own —
`RobotRuntime.snapshot()["events"] / ["safety_log"] / ["chat"]` (there is no
`.state()`), and `FollowOwnerController.heading_snapshot()` rather than
`.snapshot()` for the owner/heading anchor. One assertion was ported from a
hand-built `ClearanceProfile` to the runtime policy's **own**
`clearance_profile`, which is the correct identity claim.

**The one red, and why it is not mine.**
`test_prototype_profile::test_introducible_keys_are_exactly_the_three_documented_families`
fails because card **A6** added `"stop_hotword"` to
`config.OVERLAY_INTRODUCIBLE_KEYS` (commit `81dfd34`) without extending that
test's allowlist. Both files are byte-identical to HEAD (`git status` clean for
both; `config.py` absent from `git diff`), and A8 added nothing to that
frozenset — so it fails at `6ca1321` with or without this card. **Filed for the
integrator: A6 owes that test one line.**

## 9 · A defect found in this card's own harness (fixed, and worth reading)

The seeded-RED helper mutates a product FILE and reloads the module. Two of the
seeds swap `min` for `max` — **three bytes for three bytes, inside the same
second** — and CPython invalidates a `.pyc` on `(mtime, size)`. The restore
therefore left a **poisoned bytecode cache**: the file on disk read correctly
while the imported module still ran the mutant, and the *next* test in the file
silently measured the seed instead of the product. It surfaced as one
inexplicable failure and could just as easily have surfaced as a false green.
`_reload()` now deletes the module's `__pycache__` entries and calls
`importlib.invalidate_caches()` before every reload, and the sha check runs
after the restore. **No other suite in the repo uses this pattern** (grepped:
`tests/test_a8_follow_compose.py` is the only file combining `importlib.reload`
with `write_text`), so nothing else is exposed — but any future card that adopts
same-length source seeding must copy the cache drop.

## 10 · Undone, and why

**Box-day — every one of these needs the robot, the camera or both, and none of
them can be faked on this host (no robot hardware; only the XVF3800 array).**

1. **Real camera identity.** Every identity row here uses P1-C's histogram
   fixture encoder on a synthesized clip. The real measurement is SigLIP-2 (or
   its successor) on real crops of the real owner, through the deployment
   camera, at the deployment mount height.
2. **Mounted tracking.** Gait vibration, motion blur, rolling shutter, the
   camera's real FOV and occlusion geometry, and the real detector's box quality
   — all absent. The clip's boxes come from a pinhole projection of ground truth.
3. **Clothing / lighting.** The α sweep changes flat RGB patches. Real clothing
   change, backlighting and mixed indoor colour temperature are what eat the
   0.03 of real-encoder margin, and they are the study's actual subject.
4. **The two-person crossing and occlusion/reacquisition trials themselves**
   (HLD Gate 6: "prove ambiguity/loss→HOLD, reacquisition transaction and local
   STOP in one- and two-person trials"). Proven here in simulation; the trial is
   physical.
5. **THE ENABLE DECISION.** A8 builds the capability and its floor. It does
   **not** enable Follow. `_owner_identity_commissioned()` is the software half
   and says in its own docstring that it is never sufficient. Per F5, **any**
   identity swap in the box-day study ⇒ Follow stays disabled and the shipped
   floor is STOP + HOLD + the canned line, which `offline_floor(connected=False,
   follow_commissioned=False)` already returns.
6. **UWB, if the trigger fires** — the AoA module, the fob, the `rt/uwbstate`
   driver, and the NLOS bias measurement named in §7.

**Software follow-ups (not box-day, not A8's OWNS):**

7. **`config.py` re-pin** for `owner_follow.tracker` (and, on the same visit,
   `owner_follow.yield_aside`, which has had the same unreachable-from-overlay
   shape since card Y-2). One line each; blocked only by the DEC-0 ceiling. The
   exact line is in §1.
8. **A real connectivity signal** for `offline_floor()`. `_model_status` is a
   model-lane readiness probe, which is the honest proxy but is not "the
   Internet is gone".
9. **`OwnerBeliefV1.ambiguity_reason` / `last_confirmed_monotonic_ns`** are not
   populated by `observation/simulator_adapter.py` (they default). A8 reads
   `ambiguity_reason` when present and does not depend on it; the composer keeps
   its own confirmed-sighting clock because of that gap.
10. **`FollowDecision` has no hold field.** The hold rides
    `follow_hold_snapshot()` beside `_follow_detail` rather than inside it,
    because `FollowDetail.from_dict` is a fixed shape several panels read. A
    later card that owns `FollowDetail` should fold it in.
11. **The frame-level ambiguity collapse lives in `owner_tracking/tracker.py`**
    (its no-owner branch reports `searching`/`no_gallery_match` even when the
    per-track reason is `ambiguous_margin`). A8 reads the per-track evidence in
    the runtime rather than editing P1-C's tracker; the tidier fix is a
    frame-level `STATE_AMBIGUOUS` in the tracker itself.

## 11 · Hard-rule compliance

`config.py` byte-unchanged · no `noqa` added · git untouched (three new files +
one modified, uncommitted) · no `ci_gate --tier` · never `-n auto`, every run
through the guard with label `a8-follow` · `obstacle_stop_m` 0.65,
`apply_reactive_safety`, `finalize_command`, `core/hard_stop.py`, the A3 latch
and the A6 stop path all **unmodified** — composed with, never edited · no new
lock (the composer is single-threaded by construction, driven from the one
control-loop thread that already holds the runtime's lock; the reason is written
in its class docstring) · owner's live stack (`:8765`, `/tmp/parcel_sim.sock`,
`:8080`) untouched · `parcel_memory.sqlite3` never opened · no hosted calls ($0)
· no audio/camera device settings changed.
