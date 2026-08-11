# Lane E3 — EVAL INTEGRITY + RATCHET RE-ARM

**Executor:** Sol 5.6 Ultra
**Dispatched by:** Fable's independent audit `AUDIT_FABLE_INDEPENDENT.md`
(workflow `wf_00b0c758-4e3`), against the batch committed as `6bd945d`.
**Date:** 2026-08-10
**State:** UNCOMMITTED — leave it that way.

## The lane's thesis

Every defect here is a guard that was supposed to CATCH something and was
instead weakened, deleted, or blind. `ci_gate --tier commit` was GREEN the whole
time. A green gate is evidence about the gate, not about the code, unless each
gate has been shown to go red for its own reason — so every fix below ships with
a seeded proof that it reddens.

## Verdict

| # | Defect | State |
|---|---|---|
| 1 | Frozen digest moved; CI sentinel blind to it | **CLOSED** |
| 2 | Safety ratchet deleted and self-replaced | **CLOSED** (with an ordering flag) |
| 3 | Mutation oracle that cannot fail | **CLOSED** |
| 4 | No-literal-drift scanner blind to the pixel surface | **CLOSED** |

---

## 1 — frozen digest moved, and the CI sentinel could not see it

### What was true

`evals/companion/personal_convo_v1/manifest.json` declares `"frozen": true` and
`"frozen_at_utc": "2026-08-09T00:00:00Z"`, and its `pack_digest` moved
`7e904d5335e049ac…` → `fc1af2f76f2b4914…` under card M-A.

Re-verified independently by this lane, on this tree:

```
locked_files 15 -> 23     ADDED 8   REMOVED 0   REPINNED 0
no non-locked_files key changed value
pack_digest(old locks) = 7e904d5335e049acc745357d226e6e03f262d2b5d8e86f7ee5de1f1ae056fa31
pack_digest(new locks) = fc1af2f76f2b491451558ef51c375723f070b9ed9fa94ea40344a3e194006b04
```

Additive-only. No tampering. `pack_digest` hashes the sorted locked-file sha256
set, so it *necessarily* moves when locks are added. The defects are process
(rule 2's STOP never fired; the batch record asserted three times that no digest
moved) and CI blindness.

### Why the gate was green

`scripts/ci_gate.py DIGEST_SENTINELS` byte-pinned exactly two manifests, and
this was not one of them. The pre-existing self-test
(`test_frozen_digest_reddens_on_byte_change`) proved only that the *comparator*
works on a synthetic tmp file — it could not tell you whether any particular
committed manifest was wired to it.

### Fixes

**(i) Third sentinel + a self-test that proves each pin individually.**

```python
DIGEST_SENTINELS = {
    "evals/nav_instruct/episodes/v3/manifest.json":      "eb1289e9…",
    "evals/companion/embodied_plan_v1/manifest.json":    "33c662c8…",
    "evals/companion/personal_convo_v1/manifest.json":   "d338f335…",   # NEW
}
```

`tests/test_ci_gate.py` gains:

- `test_each_real_sentinel_reddens_on_a_seeded_byte` — **parameterized over the
  real `DIGEST_SENTINELS`**. For each pinned manifest it copies the real bytes to
  tmp, asserts the clean copy matches its committed pin, appends one byte, and
  asserts *that manifest's own pin* reddens. The seed never touches the frozen
  artifact (mutation-panel rule).
- `test_one_seeded_sentinel_reddens_the_whole_gate` — one bad manifest fails the
  aggregate and is named in the detail.
- `test_no_frozen_manifest_silently_escapes_the_sentinel_set` — pins the SET of
  frozen-but-unpinned manifests. Freezing a new suite, or dropping a pin, reddens
  and forces an explicit decision. Six frozen suites are recorded as knowingly
  unpinned (covered by `FROZEN_DIGEST_NODE_IDS` recompute tests); byte-pinning
  them is tracked follow-up, now visible instead of silent.
- `test_real_frozen_sentinels_match_the_current_tree` now asserts `checked == 3`.
  `evaluate_frozen_digest_sentinels` gained `extra={"checked": n}` on its pass
  path so the count is machine-readable.

Proof, run on this tree: 9 passed. Seeded per-sentinel runs all redden with
`<relpath>: sha … != pinned …`.

**(ii) Key order restored.** The M-A diff was 60 insertions / 28 deletions for 8
added locks — the whole file had been re-serialized into alphabetical top-level
key order. Fable verified key sets equal and no value changed (pure
re-serialization), but it buried the real change. The original `60ecea2` order is
restored:

```
schema_version, suite_id, runner_version, tier, frozen, frozen_at_utc,
scenario_count, probe_families, human_review_required, requires_audio,
requires_model_server, probe_files, locked_files, [freeze_provenance]
```

`git diff 60ecea2 -- evals/companion/personal_convo_v1/manifest.json` now shows
**only** the 8 added lock entries and the appended provenance block. No reorder.
The diff contains exactly **one** deletion line — `  ]` becoming `  ],` where the
provenance block is appended after `locked_files`. It is structural and touches
no lock. (M-A's diff had 28 deletions for the same 8 additions.)

**(iii) Provenance written into the manifest.** A `freeze_provenance` key records
the delta (15 → 23, +8 / −0 / repin 0), every added path, both digests,
`"owner_authorized_at_the_time": false`, the rule-2 process finding, Fable's
independent verification, and `"digest_moves_because": "entries were added, not
because any pin changed"`.

Adding it does **not** move `pack_digest` (that reads `locked_files` shas, not
manifest bytes) — asserted in the edit script before writing. It does move the
manifest's own file sha, which is what the new sentinel pins.

**No existing lock entry was re-pinned or removed. No locked file's sha or
content was touched.** `tests/test_personal_convo_v1.py` +
`tests/test_personal_convo_pc4.py`: 26 passed.

**(iv) False claims corrected.**

| File | Claim | Correction |
|---|---|---|
| `M-A_STATUS.md:27` | recorded the new `pack_digest` without saying a frozen digest had moved or that rule 2 required a STOP | full correction block: old digest, the missed STOP, the additive-only delta, why CI missed it, what E3 did |
| `AUDIT_WAVE2.md:29` | "Frozen digests / mutation panel: **UNMOVED**" | **FALSE.** The check looked at frozen-ish *filenames in the diff*, which a manifest edit does not announce. `mutation_panel.json` half stands |
| `AUDIT_WAVE2.md:63` | "Frozen rows: **UNMOVED**" (card S-A) | corrected inline |
| `AUDIT_WAVE2.md:164` | "Frozen rows: **UNMOVED**" (card V-D) | corrected inline |
| `AUDIT_WAVE2.md:~66` | "P0-A / P0-B may be claimed CLOSED" | QUALIFIED — the cited oracle was a tautology (defect 3). The verdict survives on the rewritten evidence, not on the evidence this audit accepted |
| `BATCH_COMPLETE.md` | "Wave-1/2 CONFIRMED", "ci_gate PASS" | SUPERSEDED block: both audits were self-reports; the PASS *is* the finding, since the gate was green while both blocking defects were live |
| `S-A2_STATUS.md` | frozen-rows scope | scoped to `mutation_panel.json`; points at the M-A correction |

---

## 2 — a safety ratchet was deleted and self-replaced

### What was true

At `60ecea2`, `tests/test_dynamic_layer.py:691` held
`test_the_reactive_safety_authority_file_is_untouched_on_this_branch`, an
unconditional `git status --porcelain` ratchet on the reactive-safety authority.
Card S-A2 **deleted** it and substituted a behavioural test of its own authoring —
the card the guard was watching removed the guard. That is a rule-4 breach:
authorization to edit `reactive_safety.py` is not authorization to delete its
ratchet. After the deletion, `grep -rn "git status --porcelain" tests/*.py`
returned nothing repo-wide.

### Fix — re-armed to the stronger sibling convention

`test_the_reactive_safety_authority_is_pinned_not_merely_unmodified` in
`tests/test_dynamic_layer.py`, matching the collision pin at :769-794
(AST-normalized `_named_source` / `_method_source`), covering **both**
`apply_reactive_safety` and `ReactiveSafetyPolicy.__post_init__`.

Two deliberate strengthenings over the sibling:

- **committed digest, not a `HEAD` comparison.** A `HEAD` comparison silently
  re-baselines the instant the change is committed — the ratchet forgets. A
  committed pin survives the commit and must be edited by a human, in the diff,
  on purpose.
- **`__post_init__` is covered too**, so a re-tuned threshold hidden behind a
  derivation is red. (This is the exact hole the original `git status` ratchet
  also had, and why the collision sibling was written this way.)

```python
REACTIVE_SAFETY_PIN = {
    "apply_reactive_safety":              "1f46251c2b9ea072081bfc8d094b19fdc01e5682eac598540a9459815505a505",
    "ReactiveSafetyPolicy.__post_init__": "2be49ad05223628fbe0b06a26ff57a4d1b6c5ca02f7a25eca4d0bae0f6dfc683",
}
```

The regeneration command is in the constant's docstring; the failure message
says explicitly *"Do NOT delete this test to make it pass — that is exactly what
card S-A2 did."* S-A2's behavioural pin is **kept**; it is complementary (it
catches a value moving through config, this catches the code moving).

`test_the_reactive_safety_pin_ignores_formatting_but_not_semantics` asserts both
directions in-process against the live source.

### Seeded proof, on the real file

| Seed | Result |
|---|---|
| comment + 3 blank lines inserted before `def apply_reactive_safety(` | **3 passed** (green — cosmetic) |
| `if False and translating and not _scan_health_allows_translation(...)` (P0-B fail-closed disabled) | **RED**: `apply_reactive_safety: c52b6027… != pinned 1f46251c…` |

`reactive_safety.py` was restored byte-identically after each seed
(md5 `11c19378710025780effb408c690f0c9`, unchanged).

### E2 ORDERING — resolved, and the ratchet proved itself doing it

`src/parcel_robot/navigation/reactive_safety.py` is **lane E2's file; I never
edited it.** I polled its md5 on a 15-20 s cadence for the whole lane.

It moved twice, and the sequence is worth recording because it is an unplanned
live demonstration:

1. **~03:35** — E2's `evidence_origin` refactor lands (md5 `11c19378…`). Stable
   for ~8 min. I captured the first pin here and verified it was a *baseline*,
   not a rubber stamp: both pinned symbols were byte-identical (after AST
   normalisation) to `6bd945d`, i.e. that edit touched
   `scan_evidence_from_observation` and imports only. Seeded both directions,
   green/red as designed. I flagged in this doc that a later person-clearance
   guard would redden the pin.
2. **~03:47** — E2 lands exactly that guard (md5 `6351aa50…`) and **the ratchet
   went red on its own, unprompted**, naming the right symbol:

   ```
   ReactiveSafetyPolicy.__post_init__: 4c07dc07… != pinned 2be49ad0…
   ```

   `apply_reactive_safety` stayed at `1f46251c…` — the pin isolated the change to
   the one symbol that actually moved.
3. I read E2's diff before regenerating. It added, symmetric with the obstacle
   floor check directly above it:

   ```python
   if self.person_stop_m + 1e-12 < DEFAULT_SAFETY_ENVELOPE.person_stop(0.0):
       raise ValueError("reactive person_stop_m must not undercut "
                        "SafetyEnvelope.person_stop(0.0)")
   ```

   A tightening — it raises on an undercut that previously passed silently.
   Authorized work, so the pin was regenerated to `4c07dc07…` after the file held
   stable across 12 consecutive 15 s polls, and re-proved on that source (seeding
   `if False and …` into the new guard reddened with
   `__post_init__: f02fc6e8… != pinned 4c07dc07…`; restored, 34 passed).
4. **~03:53-03:55** — E2 reverted the guard. The legacy `robot.yaml` inject of
   `person_stop_m=1.0` undercuts the derived social floor, so the new
   `ValueError` fired across the suite; a `ci_gate` run caught in that window
   showed **33 failed** across `headless_city`, `follow_prediction`,
   `p0c_flush_product_path`, `k6_voice_lanes`, `p2_dialogue`. The ratchet
   reddened a **second** time and the pin returned to `2be49ad0…`.
5. **Final state** — settled at md5 `ea445595d9c26b7e2f2fc191d14ee5f8` across 20
   consecutive 20 s polls (~6.5 min). Both pinned symbols are back to their
   6bd945d values, so the committed pin equals the 6bd945d baseline for both.

Net movement on `__post_init__` is zero, but it did not sit still — and that is
the point. Both movements were **caught, read, and logged** rather than absorbed.
A `HEAD`-comparison ratchet would have gone green again the moment either change
was committed, and a `git status` ratchet (the deleted one) would have been red
for E2's entire working session for reasons it could not name. The AST-normalised
committed digest named the exact symbol both times and stayed quiet about
`apply_reactive_safety`, which never moved.

> **FLAG for the coordinator.** Two live findings for lane E2, outside my lane:
> (a) the person-clearance floor guard is currently **reverted**, so the guard
> asymmetry E2 was dispatched to close is still open;
> (b) the reason it could not land is the legacy `robot.yaml` inject
> (`person_stop_m=1.0` / `person_slow_m=2.0`), which `AUDIT_WAVE2.md` already
> flagged as a deferred follow-up. The yaml retune is the prerequisite for the
> guard, not an independent cleanup.
>
> If E2 re-lands the guard after this writing, the ratchet will redden again — by
> design. Regenerate with the command in the constant's docstring, add a line to
> its log, and do not delete the test.

---

## 3 — a mutation oracle that could not fail

### What was true

`tests/test_sa2_live_pipeline.py:336-342`:

```python
def test_mutation_oracle_residual_nonzero_after_hard_stop_is_killed() -> None:
    healthy = VelocityCommand()
    residual = VelocityCommand(vx=0.12)
    assert healthy == ZERO_COMMAND
    assert residual != ZERO_COMMAND
```

Two constants compared to each other. No product code. It cannot fail for any
reason a robot cares about — and `S-A2_STATUS.md:51-52` cited it as the reason
`scripts/mutation_panel.py` went untouched (confirmed: no diff vs `60ecea2`).

### Fix — the oracle now drives the product path and proves its own kill

Rewritten to run `RobotRuntime._dispatch_active()` — the live path
`smoother → collision gate → shaper → finalize_command → set_target` — with
`control_manager.set_target` captured. It warms the smoother on a real forward
intent so its ramp carries a residual, submits the zero intent, dispatches, and
asserts `set_target` received **exact** `(0,0,0)`. Then it monkeypatches
`parcel_robot.runtime.finalize_command` to a signature-compatible pass-through
and asserts the same drive now leaks a non-zero command.

Measured:

```
clean   -> set_target receives VelocityCommand(vx=0.0, vy=0.0, vyaw=0.0)
mutant  -> set_target receives VelocityCommand(vx=0.09084455045871441, ...)
```

Seeded end-to-end proof (mutant applied *before* the clean assertion, then
reverted):

```
E  AssertionError: P0-A: a zero intent must reach set_target as exact zero,
   got VelocityCommand(vx=0.09095747007289899, vy=0.0, vyaw=0.0)
1 failed
```

Restored: 12 passed.

### An honest layering finding, recorded rather than hidden

The mutant is killable **only with `motion.shaping.enabled: false`**. With
shaping on, every HARD_STOP route in `_dispatch_active` also sets
`stopping=True`, so `_shape_for_actuator` emergency-zeroes *before*
`finalize_command` runs and the pass-through is an **equivalent mutant**. Also
measured: after `arbiter.engage_emergency_stop()`, `arbiter.current()` returns
`None`, so that route never reaches `set_target` at all.

Both configurations are real product configurations, so both are now asserted:
`test_the_shaper_is_defence_in_depth_not_the_oracle` pins the shaping-on case, so
if a future change makes the shaper stop zeroing on `stopping=True` the layering
claim is re-opened rather than silently lost.

### `scripts/mutation_panel.py` — deliberately UNTOUCHED, and why

Independently re-verified: the panel runs the headless NAV_INSTRUCT v3 minival
and **never constructs a `RobotRuntime`** (no import, no reference). A
`finalize_command` mutant there would never be exercised — an equivalent mutant,
which by the panel's own documented rule "says nothing about the harness" and
would count as a panel failure.

So: **no mutant added, no version bump, panel stays at 6/6 killed, green.** The
S-A2 deferral's *first* sentence was correct; what was false was the claim that
the live-pipeline oracles already killed the residual-nonzero class. That
justification is now true because the oracle was rewritten, and
`S-A2_STATUS.md` is corrected to separate the two.

---

## 4 — the no-literal-drift scanner was blind to the pixel surface

### What was true

`tests/test_authority_no_literal_drift.py::scanned_files()` covered
`navigation/*.py` plus a fixed list. It did not cover `camera_channel/*.py` or
`detection_adapter/*.py`, so this batch's new safety-adjacent constants were
never watched.

### Fix

`scanned_files()` now globs both trees. Census on first scan:

| File | Literals | Disposition |
|---|---|---|
| `camera_channel/ingress.py` | `1.25`, `0.32` | `0.32` DERIVED; `1.25` allowlisted with reason |
| `camera_channel/d455.py` | `0.35` ×1 | allowlisted — `MOUNT_HEIGHT_M`, a camera Z extrinsic |
| `camera_channel/frames.py` | `0.35` ×4 | allowlisted — the same extrinsic, re-defaulted 4× |
| `detection_adapter/metric_localizer.py` | `0.35` ×3 | allowlisted — parallax sigma + 2 camera heights |

Every new allowlist entry carries family tag, owner, and reason
(`test_every_allowlist_entry_names_a_family_and_an_owner` enforces this).

### Derivations in `camera_channel/ingress.py`

```python
_PIXEL_ARRIVAL_RADIUS_M               = DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m            # 0.06
_PIXEL_TARGET_MIN_SURFACE_CLEARANCE_M = DEFAULT_STAND_OFF_ENVELOPE.target_surface_clearance_m  # 0.8
_PIXEL_TERMINAL_SUPPORT_CLEARANCE_M   = DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m          # 0.32
```

All three verified `==` to the values they replaced, so the pixel path stamps
bit-identical metadata to the GT-oracle path. `authority.py` imports only
`robot_profile` (a leaf), so this adds no cycle risk. The third was not in the
brief but is the same defect and derives cleanly, so it was fixed too.

### `_PIXEL_NON_TARGET_OBSTACLE_CLEARANCE_M = 1.25` — allowlisted, not derived

This one **genuinely cannot derive**, and the reason is measured, not asserted:

```
DEFAULT_STAND_OFF_ENVELOPE.stand_off(0.0) == 1.2200000000000002   (canonical
    left-to-right association, the one the authority documents as bit-for-bit)
1.2200000000000002 + 0.03                == 1.2500000000000002   != 1.25
```

`city_semantics.py` stamps exactly `1.25`. A derived pixel candidate would then
compare **unequal** to a GT-oracle candidate for the same object. Six of the 24
term orderings *do* land on `1.25` exactly, but reassociating a sum until it hits
the number you wanted is derivation theatre, not derivation — so the literal
stays, named and allowlisted, owned jointly with `city_semantics.py`'s existing
`1.25` entry so the two retire together when the sidecar owns the stamp.

### New tests

- `test_the_scanner_covers_the_pixel_surface` — asserts both trees are in scope
  and non-trivially populated, so a glob that stops matching is a failure rather
  than a silent pass (the exact failure mode this ratchet just had).
- `test_the_pixel_candidate_clearances_derive_from_the_authority` — checks the
  **AST form** of each assignment, not just its value. This matters: `0.06` and
  `0.8` are not in `RETIRED_FAMILY_VALUES`, so the counting ratchet is blind to
  them; only a form check can catch a re-hardcode.

### Seeded proof

Re-hardcoding `_PIXEL_ARRIVAL_RADIUS_M = 0.06` and
`_PIXEL_TERMINAL_SUPPORT_CLEARANCE_M = 0.32`:

```
FAILED test_the_pixel_candidate_clearances_derive_from_the_authority
FAILED test_no_new_retired_family_literals
  camera_channel/ingress.py: 1x 0.32 (F-robot-radius) is not allowlisted … Lines: [80]
2 failed, 25 passed
```

Restored: 27 passed. Both watchdogs fire — the family ratchet on `0.32`, the new
form check on the non-family `0.06`.

---

## Verification

```
ruff check  -> 12 violations / 7 unique fingerprints == scripts/ci_ruff_baseline.json
               NEW FINGERPRINTS: 0
```

One new fingerprint (`tests/test_sa2_live_pipeline.py::I001`, my import) was
introduced and fixed with `ruff check --fix` before the gate run.
`ruff format` is not enforced in this repo (untouched files such as
`src/parcel_robot/runtime.py` also fail `--check`), so it was not applied.

Touched suites, in one run: **123 passed**
(`test_sa2_live_pipeline`, `test_dynamic_layer`, `test_ci_gate`,
`test_authority_no_literal_drift`, `test_personal_convo_v1`,
`test_personal_convo_pc4`).

`ci_gate --tier commit` @ 2026-08-10T08:05:22Z:

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                collisions=0 false_arrival=0 | panel clean | follow-bench 0 | walk_with_me 0
[  PASS] HARD  frozen-digest-sentinels    3 immutable manifest(s) byte-identical to pin
[  skip] HARD  latency-tail-ledger        rows=1 < window=5 (percentile-pin pytest remains authoritative)
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3327 passed, 9 skipped
RESULT: PASS — every hard gate green.   elapsed 104.8s
```

`frozen-digest-sentinels` now reads **3** where it read 2 — the gate line that
would have caught defect 1 had it existed.

### Attribution of one intermediate RED

An earlier gate run (07:47Z) returned **33 failed / 2 hard gates red**. It is
**not** this lane's, and it was proven rather than assumed:

- every named failure passes in isolation on the same tree;
- re-running the four affected suites whole
  (`headless_city_tasks`, `follow_prediction`, `p0c_flush_product_path`,
  `k6_voice_lanes`) gave **48 passed**;
- the cause was lane E2's person-clearance floor guard landing mid-run against
  the legacy `robot.yaml` inject, which E2 then reverted (see the E2 ordering
  section). `reactive_safety.py` md5 moved three times during that window.

Nothing in the red touched a file this lane owns. The final run above is on the
settled tree.

## Files touched

| File | Change |
|---|---|
| `scripts/ci_gate.py` | third `DIGEST_SENTINELS` entry + rationale comment; `extra={"checked": n}` on the sentinel pass path |
| `tests/test_ci_gate.py` | per-sentinel seeded redness, aggregate seed, frozen-set coverage pin, `checked == 3` |
| `evals/companion/personal_convo_v1/manifest.json` | key order restored to `60ecea2`; `freeze_provenance` appended. **No lock added, removed, or re-pinned** |
| `tests/test_dynamic_layer.py` | re-armed reactive-safety ratchet + its two-direction proof; `_symbol_source` / `_symbol_digest` helpers; hoisted `ast` / `hashlib` imports |
| `tests/test_sa2_live_pipeline.py` | oracle rewritten to the product path with its own mutant proof; shaping-on layering test; `_runtime(shaping=…)` |
| `tests/test_authority_no_literal_drift.py` | scanner extended to both perception trees; 4 allowlist entries; 2 new tests |
| `src/parcel_robot/camera_channel/ingress.py` | 3 constants derived from `DEFAULT_STAND_OFF_ENVELOPE`; the 4th documented as non-derivable |
| `scrum/20260809/task_15/M-A_STATUS.md` | digest-move correction |
| `scrum/20260809/task_15/AUDIT_WAVE2.md` | 3 UNMOVED corrections + 1 P0-A qualification |
| `scrum/20260809/task_15/BATCH_COMPLETE.md` | SUPERSEDED block |
| `scrum/20260809/task_15/S-A2_STATUS.md` | mutation-panel deferral + ratchet-deletion corrections |
| `scrum/20260809/task_15/E3_EVAL_INTEGRITY_STATUS.md` | this file |

**NOT touched** (other lanes): `runtime.py`, `reactive_safety.py`, `configs/**`
(E2); `instructnav/**`, `navigation/pipeline.py`,
`navigation/instructnav_recovery.py`, `route_memory/**`, `ci_ruff_baseline.json`
(E1). `scripts/mutation_panel.py` untouched by design (see defect 3). No locked
file's content and no `nav_instruct` frozen episode was altered.
