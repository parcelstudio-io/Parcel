# W0-A status — physical feedback and typed provenance (P0-1, P0-2)

Card: `scrum/20260812/task_2/W0_PRODUCT_CARDS.md` §"Card W0-A", grounding
`scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md` §"Card W0-A" and
§"Versioned boundary contracts", as amended by `../task_1/FABLE_VERDICT.md`
and the board rulings in `BOARD_DECISIONS.md` (D-1, D-2, D-3, D-5).
Audit: **CONFIRMED, zero majors**; the four minors are discharged in §5.7 and
gate rows A1/A2/A4, and the item-3 wording correction is in §5.3 and §6.
Executor: Opus 5. Date: 2026-08-12. **Not committed.** Base: `7242660`.
Concurrent: W0-B (`control/factory.py`, `unitree_control.py`,
`commissioning/**`) and two doc-only cards in `../task_1/`; attribution in §6.

---

## 0. Measurement status

**First pass: STOP-AND-REPORT.** The `Bash` tool died host-wide mid-card
(`/tmp/claude-1000` over quota). Nothing was edited and the tree was left
clean — the record of that stop is preserved in the board's D-4. This pass is
its replacement, and every number below is measured on this tree.

**Second pass: measured** through the `Monitor` channel with `TMPDIR`
redirected off the full volume, scratch under
`/home/jaewoo-jang/.cache/parcel-w0a-scratch/`.

**Still NOT run, and not mine to run: the full `ci_gate --tier commit`.** The
host disk quota still reddens ~25 unrelated tests with
`OSError: [Errno 122] Disk quota exceeded` (`test_viewer_panel.py`,
`test_web_panel.py`, `test_walk_with_me_k8.py`, `test_v4s_search_cells.py`),
exactly as W0B_STATUS.md §0 records at clean `7242660` — i.e. before either
card edited a byte. A full-suite number from this machine would be noise. The
tranche audit runs it after the quota clears (H5).

What I ran instead, because "the environment is noisy" is not an excuse for
not knowing whether my own change broke something: the full `-m "not slow"`
suite **twice** — once on this tree, once on a tree with W0-A's six edited
files reverted to `HEAD` and the new test file removed — and diffed the
failure sets. §5.4.

I did not weaken any gate to make a number, and did not soften a test to make
it more likely to pass. Three problems this pass surfaced were found by
execution and are written up as findings rather than quietly patched: R1
(§5.2), R2 (§5.3), R3 (§5.4).

---

## 1. Frozen contract surface (what the next cards consume)

```python
# parcel_robot.evidence_origin       NEW leaf module: stdlib-only, no package
#                                    weight — see §5.4 for why that is load-bearing
class EvidenceOrigin(str, Enum):        # PHYSICAL | SIMULATION | REPLAY | UNKNOWN
    ...                                 # UNKNOWN is the fail-closed default
SYNTHETIC_ORIGINS: frozenset[EvidenceOrigin]        # {SIMULATION, REPLAY}

# parcel_robot.core.input_health     re-exports both of the above, so
#                                    `from ...core.input_health import EvidenceOrigin` works
def evidence_origin(producer_label) -> tuple[EvidenceOrigin, str | None]
    # ALWAYS (SIMULATION, label). Signature preserved for navigation/**.
def requirements_requiring_physical_inputs(requirements=DEFAULT_REQUIRED_INPUTS)
    # every sim_fixture_allowed=False, SCAN included            (board D-2)

# REMOVED: InputOrigin, is_simulated_source, PHYSICAL_SOURCE_NAMES
# InputEvidence.origin default: PHYSICAL -> EvidenceOrigin.UNKNOWN

# parcel_robot.control.models
@dataclass(frozen=True)
class RobotMotionState:
    ...                                 # unchanged through vendor_extra
    origin: EvidenceOrigin = EvidenceOrigin.UNKNOWN
    source_time_s: float | None = None  # vendor/device clock; received_at
    session_epoch: str = ""             #   remains the HOST receipt

# parcel_robot.control.base
class RobotStateSource(Protocol):       # READ-only; + declared `origin`
class ObservationSink(Protocol):        # SIMULATOR-only: update_observation()
def declared_origin(candidate) -> EvidenceOrigin      # typed; str => UNKNOWN
def is_robot_state_source(candidate) -> bool
def as_observation_sink(candidate) -> ObservationSink | None   # refuses PHYSICAL
class CommissionedStateSource:          # read-only view; declares origin+epoch,
    latched_reason: str | None          #   stateful ordering latch
```

`parcel_robot/control/__init__.py` is deliberately **untouched** (not in OWNS);
`runtime.py` imports the new helpers from `parcel_robot.control.base` directly.

---

## 2. The two defects, and the mechanisms that replace them

### P0-1 — `runtime.py:390-396`, physical feedback discarded

The retired retention was `isinstance(control_manager.state_source,
BufferedRobotStateSource)`. `UnitreeSportStateSource` inherits nothing, so it
was discarded and `_control_state_source` was `None` for every physical
manager — the feedback reads at `runtime.py:4694` and `:5700` saw nothing.

The same predicate also gated *writing* simulator observations into the
source, so simply widening it would have made the runtime write simulated
observations into a physical vendor source. The fix splits the capability:

| seam | field | gate | physical source |
|---|---|---|---|
| READ feedback | `_control_state_source` | `is_robot_state_source` (callable `latest`) | **retained** |
| WRITE sim observations | `_observation_sink` | `as_observation_sink` (has `update_observation` **and** does not declare PHYSICAL) | **refused** |

Two write sites (the control loop, and `_collision_safe`) moved to the sink;
the third is deliberately left on the read handle for the ratchet reason in
§5.3 — it sits under `_synchronous_control_dispatch`, which a physical source
can never reach. Two read sites stayed on the source and now see the physical
stream.

### P0-2 — `core/input_health.py`, authority inferred from strings

`PHYSICAL_SOURCE_NAMES = {"", "unknown", "physical"}` minted physical
authority for three names and classified `unitree_sport` a simulator fixture.
Both boundary dataclasses *default* into that set (`SimObservation.backend`,
`RobotMotionState.source` = `"unknown"`), so declaring nothing was the
strongest authority in the system — board D-3.

Replaced by declared, typed provenance carried ON the datum. The three
declaration routes, none of which is a string:

1. `CommissionedStateSource(inner, origin=PHYSICAL, session_epoch=...)` stamps
   a commissioned vendor stream;
2. the runtime's own wiring declares `SIMULATION` **iff it holds the
   observation sink** — i.e. iff it is synthesizing the feedback itself, a
   structural fact about the wiring rather than a guess about a name;
3. everything else is `UNKNOWN`, which latches.

`evidence_origin` survives with its signature intact (D-1) but can only ever
return `SIMULATION`: the authority is the carrier type (`SimObservation`), the
string is only the fixture label.

---

## 3. Amendments made, with provenance

| # | Amendment | Provenance |
|---|---|---|
| A1 | `InputEvidence.origin` default `PHYSICAL` -> `UNKNOWN` | card "UNKNOWN never physical"; D-3 |
| A2 | new `origin_unknown` LATCHED_STOP fault | card gate "unknown ... hold or latch exactly" |
| A3 | physical branch uses `requirements_requiring_physical_inputs()`, not `DEFAULT_REQUIRED_INPUTS` | **board D-2**, from this card's own first-pass finding |
| A4 | `_sim_fixture_inputs_allowed` structural, not `is_simulated_source(backend.name)` | card "remove string inference"; never weaker (§4) |
| A5 | `input_health_latch()` reports `state_source_origin` | observability for the audit's spoof lane |
| A6 | `CommissionedStateSource` ordering latch | card "reordered ... latch exactly"; verdict RC-1c |
| A7 | `latest()` re-poll is not a disorder | **defect found by my own runtime test** (§5.2, R1) |
| A8 | one write site in `_dispatch_active` deliberately NOT migrated to the sink | **ratchet finding** (§5.3) — keeps `STOPPING_PREDICATE_PIN` unmoved |

`DEFAULT_REQUIRED_INPUTS` itself is byte-unchanged — it is the shipped
simulator default and the card preserves it "until deliberately migrated".
A3 introduces the *physical* table beside it rather than editing it.

### Constants

No new numeric constant. `requirements_requiring_physical_inputs()` derives
from `DEFAULT_REQUIRED_INPUTS` by `dataclasses.replace`, so frames and
`max_age_s` cannot drift from the shipped table; a test pins that the two
tables differ in exactly one cell (`SCAN.sim_fixture_allowed`).

---

## 4. Why the simulator path is unmoved — argued, then measured

`SIMULATION` is rule-equivalent to the retired `SIM_FIXTURE` in every branch
of `_fault_for`, and the fixture labels are the same strings
(`observation.backend` / `state.source`, both non-empty on the sim path). The
only verdict that moves is the one where a producer named `""`/`"unknown"`/
`"physical"` previously minted `PHYSICAL` — which is the defect.

**A4 is never weaker than what it replaced.** Decision table:

| deployment | old (`is_simulated_source(name)`) | new (`holds the sink`) |
|---|---|---|
| config-built simulator | allowed | allowed (`_synchronous_control_dispatch`) |
| injected manager, buffered source | allowed (name "fake" etc.) | allowed (sink present) |
| injected manager, **physical** source | allowed if name looked simulated | **refused** (no sink) — stricter |
| `require_physical_inputs: true` | refused | refused |

The one corner where the old test was stricter — a backend object *named*
`"unknown"`/`"physical"`/nameless — is a corner where the old code also
stamped POSE and FEEDBACK `PHYSICAL` and therefore allowed translation
anyway. No configuration loses a denial. Recorded in §7 as the residual.

### 4.1 Measured: AF-2 recipe, before vs after

Protocol: v4 minival, `--mode baseline`, `--budget-policy scaled-path-v1`,
`--max-steps 200`, `--seed 20260804`, run **twice from the identical scratch
tree path** (`/home/jaewoo-jang/.cache/parcel-w0a-scratch/before-tree`) with
only `src/` swapped between the arms — so even the path-dependent digest is a
valid comparison. Out-of-tree, so the runner's unconditional ledger append
(`run_nav_instruct_v1.py:61,442`) never touched `evals/**`. Recipe copied
verbatim from `tests/test_nav_instruct_digest_recipe.py`.

Run **twice** against this card's source: once mid-card, and again against the
FINAL source after the §5.3 revert, so the evidence corresponds to the tree as
delivered rather than to an intermediate state. Both arms identical.

```text
before  nav-instruct-v1-baseline-v4-20260813T020710Z.json   (clean 7242660 src)
after   nav-instruct-v1-baseline-v4-20260813T021557Z.json   (this card's src)
final   re-run after the §5.3 revert                        (delivered src)

episode rows byte-equal        25 / 25
path_dependent                 9f55ae132258006a...  UNMOVED
path_independent_default       897d6ce7ea709415...  UNMOVED   == published pin
path_independent_compact       c172da375ff23987...  UNMOVED   == published pin
episodes_sorted_by_id          bfb21cd25be4db9e...  UNMOVED   == published pin
episodes_report_order_compact  440fd8842854d446...  UNMOVED   == published pin
aggregate sr                   0.24                 identical
aggregate spl                  0.19325925214230982  identical

AF2_VERDICT: BYTE_UNMOVED
```

Four of the five published digests reproduced exactly against
`test_nav_instruct_digest_recipe.py`'s pins. The fifth (`ee234c63…`) is
path-dependent **by construction** — `aggregate.scene` is an absolute path, as
that test's own `test_the_path_dependent_digest_really_is_path_dependent`
documents — so a scratch run cannot match it; `9f55ae13…` is its scratch-path
counterpart and is identical across both arms, which is the claim that matters
here. `sr 0.24` / `spl 0.19325925214230982` are the verdict's exact quoted
frozen values.

---

## 5. Gate evidence

Pre-edit focused baseline, clean tree:
**150 passed in 6.01 s** (`test_core_input_health` + `test_e2_safety_wiring` +
`test_control` + `test_runtime`).
Post-edit, same four plus the new file and the stopping-predicate ratchet:
**216 passed, 0 failed in 6.93 s**.

| # | Gate | Verdict | Evidence |
|---|---|---|---|
| 1 | physical `unitree_sport` feedback satisfies a commissioned join | **PASS** | `test_commissioned_unitree_sport_feedback_satisfies_a_physical_join` — a real `UnitreeSportStateSource` driven through its shipped `_on_message` decode with a fake DDS message; ALLOW under the physical table |
| 2 | simulator/replay cannot satisfy physical requirements | **PASS** | `test_synthetic_origins_cannot_satisfy_a_physical_requirement` (6 cells: 2 origins x 3 inputs), all `sim_fixture_forbidden` LATCHED_STOP |
| 3 | `unknown` holds/latches exactly | **PASS** | `origin_unknown` LATCH; severity table cell + `test_default_constructed_boundary_objects_never_satisfy_a_physical_join` |
| 4 | stale holds exactly | **PASS** | severity table `("stale", HOLD)` |
| 5 | reordered holds/latches exactly | **PASS** | `test_out_of_order_physical_feedback_latches_exactly` (duplicate / reordered / receipt_backward) |
| 6 | future latches exactly | **PASS** | severity table `("future", LATCHED_STOP)` |
| 7 | wrong-frame latches exactly | **PASS** | severity table `("wrong_frame", LATCHED_STOP)` |
| 8 | invalid latches exactly | **PASS** | severity table `("invalid_payload", "nan_timestamp", LATCHED_STOP)` |
| 9 | no missing-scan/geometry path emits physical translation, incl. D-2 table | **PASS** | `test_missing_geometry_holds_exactly...` (exactly HOLD, exactly `{SCAN: missing}`) + amended `test_simulated_pose_latches_under_physical_commissioning` now shows SCAN joining POSE/FEEDBACK in `sim_fixture_forbidden` |
| D-3 | default-constructed boundary objects never satisfy a physical join | **PASS** | dedicated cell asserting both defaults are `"unknown"` and both fail closed |
| 10 | simulator behaviour + frozen evals BYTE-UNMOVED | **PASS** | §4.1, `AF2_VERDICT: BYTE_UNMOVED`, 25/25 rows |
| 11 | focused suites + new tests green | **PASS** | **311 passed / 0 failed** over 9 suites incl. both W0-B files (§5.5) |
| 12 | ruff zero new fingerprints | **PASS** | `ci_gate.evaluate_ruff()` = `pass, 7 violation(s), baseline 7, **new 0**`; W0-A's 8 files individually clean (§5.5) |
| 13 | no pre-existing pin or ratchet moved | **PASS** | `PIN_DRIFT_COUNT 0` over `STOPPING_PREDICATE_PIN` (§5.3) |
| 14 | full-suite attribution (no failure is W0-A's) | **PASS** | §5.4, differential run |
| A1 | colliding `(sequence, received_at)` with a different payload cannot launder provenance | **PASS** | Fable audit item 1 — `test_seeded_failure_colliding_keys_with_a_different_payload_latch`, plus `test_an_equal_valued_rebuild_of_the_same_sample_is_still_not_a_disorder` for the other side (§5.7) |
| A2 | a write-only (sink, no reader) source cannot crash the collision gate | **PASS** | Fable audit item 2 — `test_a_write_only_source_does_not_crash_the_collision_gate` (§5.7) |
| A4 | `evidence_origin` stays a stdlib-only leaf | **PASS** | board D-5 condition — `test_evidence_origin_module_is_a_stdlib_only_leaf`: AST import walk + a subprocess probe asserting `sys.modules` is exactly `['parcel_robot', 'parcel_robot.evidence_origin']` |
| 15 | full `ci_gate --tier commit` | **NOT RUN — not mine** | §0; host quota |

### 5.1 Seeded-failure companions

Each names the mutant, runs it, and shows the oracle rejects it. Without
these, a green cell only proves the code agrees with itself.

| Mutant | Cell | Oracle rejects it |
|---|---|---|
| The retired `PHYSICAL_SOURCE_NAMES` whitelist, re-implemented verbatim | `test_seeded_failure_the_retired_whitelist_would_have_minted_physical` | mutant gives `"unknown"` -> PHYSICAL and `"unitree_sport"` -> SIMULATION; `no_string_mints_physical_oracle` raises on it, passes on shipped |
| Skip commissioning, trust the vendor name | `test_seeded_failure_uninstrumented_unitree_source_cannot_reach_physical` | raw source is `UNKNOWN` -> `origin_unknown` LATCH |
| "A label proves it is honest" | `test_seeded_failure_a_well_labeled_fixture_is_still_not_physical` | same datum: ALLOW under fixtures-allowed, LATCHED_STOP under physical |
| Downgrade a future-dated latch to HOLD | `test_seeded_failure_severity_oracle_rejects_a_hold_where_a_latch_is_due` | severity oracle raises on HOLD |
| Stateless latch (judge each sample independently) | `test_seeded_failure_a_stateless_latch_would_reauthorize_on_recovery` | latch-persistence oracle raises on ALLOW after a clean tick |
| Spoof by naming the attribute right | `test_a_string_origin_attribute_is_not_a_declaration` | `origin = "physical"` (a str) reads back `UNKNOWN` |

### 5.2 R1 — a defect this card's own tests caught before it shipped

The first `CommissionedStateSource` compared sequence numbers only. But
`latest()` is a **poll**, not a queue pop, and the runtime calls it twice per
tick (`:4694` dispatch idle check, `:5700` health join). Re-reading one
buffered sample therefore read as `sequence_duplicate` and latched the
deployment on its first healthy tick —
`test_runtime_reads_an_injected_physical_source_and_never_writes_to_it` failed
with `payload_malformed`. Fixed by treating same-sequence-**and**-same-receipt
as the same sample; a same-sequence sample with a *different* receipt is still
a real re-delivery and still latches. Pinned by
`test_polling_the_same_sample_twice_is_not_a_disorder`.

Worth stating plainly: a static review would not have found this. It needed
the runtime cell.

### 5.3 R2 — a stopping-predicate ratchet this card moved, and then did not

The first cut of the seam split migrated **all three**
`update_observation` sites to `_observation_sink`. One of them lives inside
`RobotRuntime._dispatch_active`, which is pinned by
`STOPPING_PREDICATE_PIN` in `tests/test_nominal_stop_wiring.py` (card J-B's
AST-normalised ratchet, so comments are green and only a semantic move is
red). Measured drift, exactly one symbol:

```text
DRIFT src/parcel_robot/runtime.py RobotRuntime._dispatch_active
      90ebdad8822b681733adaa74f30821bf0a1157e2f18a47f7880398af36a6b640
```

Attribution control, on a tree with W0-A's six files reverted to `HEAD` and
the new test file removed: `tests/test_nominal_stop_wiring.py` **21 passed**.
So the movement was unambiguously this card's.

The ratchet's own docstring permits regeneration-with-a-reason, and there is a
regeneration log with two prior entries. **I did not take that route.** The
pin exists so the product and the FOLLOW_BENCH replica agree about *which
stops may ramp*, and this card changes nothing about stop classification —
moving a safety-adjacent ratchet as a side effect of a provenance fix is
exactly the kind of quiet erosion the ratchet is there to catch.

Instead the site's **executable content** was restored: that block is guarded
by `_synchronous_control_dispatch`, which is True **only** on the config-built
simulator path (where `control.controller` must be `"simulator"`), and there
the source and the sink are the same `BufferedRobotStateSource`. A physical
source cannot reach it, because hardware requires an explicitly injected
manager and that sets the flag False. The safety property is unchanged; only
the two sites a physical source *can* reach needed the sink. Re-measured:

```text
PIN_DRIFT_COUNT 0 []
tests/test_nominal_stop_wiring.py   21 passed
```

**Correction (Fable audit item 3).** An earlier revision of this section, and
of §6, said `_dispatch_active` was "reverted to byte-identical". That was
overstated and is corrected here: it is **AST-identical, not byte-identical** —
15 comment lines were added at the site, 0 non-comment changes. The AST digest
is equal, which is the property the ratchet pins and the property the safety
argument rests on, but "byte-identical" is a stronger claim than what was
measured and it should not have been written.

The residual wart — one write reached through the read-typed handle — is
documented in a comment at the site, and is enumerated as H6 for the card that
next has a legitimate reason to move `_dispatch_active`.

### 5.4 R3 — a cross-card regression the differential run caught

Running the full `-m "not slow"` suite twice — once on this tree, once on a
tree with W0-A's six edited files reverted to `HEAD` and the new test file
removed — and diffing the failure sets:

```text
CUR: 27 failed, 4049 passed, 9 skipped, 36 deselected   in 188.66s
REV: 31 failed, 3996 passed, 13 skipped, 36 deselected  in 186.61s

--- ONLY IN CURRENT (i.e. candidates for "W0-A's fault") ---
FAILED tests/test_w0b_commissioning.py::test_importing_commissioning_does_not_import_the_runtime
```

**That one was mine, and it was a real defect, not a test artifact.** W0-B's
`parcel_robot.commissioning` is specified as a leaf. My first cut put
`EvidenceOrigin` in `core/input_health.py` and imported it from
`control/models.py`, which executes `parcel_robot/core/__init__.py` — and that
transitively imports `brain` and `instructnav`. Measured leak:

```text
['parcel_robot.brain', 'parcel_robot.brain.compiler', ..., 'parcel_robot.instructnav',
 'parcel_robot.instructnav.arbiter', ...]     (truncated; 15+ modules)
```

Fixed by moving the enum to a new stdlib-only leaf module,
`src/parcel_robot/evidence_origin.py`, which `core/input_health.py`
re-exports so every existing import path still resolves. `parcel_robot.models`
was the reference point for "what a leaf costs": importing it pulls exactly
`['parcel_robot', 'parcel_robot.models']`.

The fix then tripped a *second* W0-B cell,
`test_no_module_outside_the_commissioning_seam_imports_it`, which greps every
`src/parcel_robot/**` source for the literal string `parcel_robot.` +
`commissioning`. The new module's **docstring** named that package while
explaining why the split exists — prose, not an import. Reworded to describe
the seam without the dotted path; W0-B's test was not touched. Recorded
because "I edited a comment and a neighbouring gate went red" is exactly the
kind of thing a status doc is supposed to say out loud.

This is the clearest argument in this document for the differential run: the
focused suites, the AF-2 digests, ruff, and the ratchet were all green while
the leak was broken. Only a neighbouring card's invariant caught it, and only
because the failure sets were compared rather than eyeballed against a
remembered baseline.

**The four "only in reverted" failures are scratch-tree artifacts, not
regressions I fixed** — `test_barn_all_ray_shield_v8_corpus`,
`test_habitat2020_*`, and `test_dynamic_layer` read corpora and pinned source
paths through `.cache/external-evals/` and absolute repo paths that the
attribution tree does not reproduce (the traceback shows
`generator_root=.../attrib/.cache/external-evals/...`). They are noise from the
comparison method and are claimed as nothing.

The remaining 27 failures on this tree are the host's pre-existing
`OSError: [Errno 122]` disk-quota class recorded in W0B_STATUS.md §0 at clean
`7242660`, plus the same corpus-path class; **none is attributable to W0-A**,
which is what the diff establishes.

### 5.5 Final state, re-measured after every fix above

Re-measured after the audit polish pass (§5.7); the pre-polish numbers were
311 passed / ruff `new 0`.

```text
pytest -q -m "not slow"  over  test_w0a_physical_provenance, test_core_input_health,
  test_e2_safety_wiring, test_control, test_runtime, test_nominal_stop_wiring,
  test_w0b_commissioning, test_unitree_control, test_portability_proof
                                      318 passed, 0 failed        15.96 s
  (of which tests/test_w0a_physical_provenance.py alone: 48 passed)

ruff check  (8 W0-A files)            All checks passed!
ci_gate.evaluate_ruff()  (the gate    GateResult(name='ruff', status='pass',
that actually ratchets, vs            detail='7 violation(s), baseline 7, new 0')
scripts/ci_ruff_baseline.json)        == W0B_STATUS.md §0's clean-7242660 line
ruff check  src/parcel_robot/         12 findings under this WIDER scope — all
(broader than the gate's scope)       in camera_channel/ (4) and
                                      detection_adapter/ (8); none in any W0-A
                                      or W0-B file. Pre-existing debt.
STOPPING_PREDICATE_PIN                PIN_DRIFT 0
commissioning leaf invariant          LEAKED: NONE
AF-2 v4 minival vs clean 7242660      BYTE_UNMOVED, 25/25 rows
```

Both ruff numbers are reported because they disagree and the disagreement is
scope, not drift: the ratcheted gate is the authority (`new 0`), and the wider
manual scan's 12 are in modules no card in this tranche touches.

The 318 deliberately includes W0-B's two suites: this card imports into their
package's dependency graph, so "my tests pass" was not a sufficient claim.

One honest note on the ruff line: the polish pass **did** redden it briefly.
The new leaf-ness test's subprocess argv used an unparenthesized implicit
string concatenation inside a list — `ISC004`, `new 1`, caught by
`ci_gate.evaluate_ruff()` and fixed by hoisting the probe source to a named
variable. Recorded because a "green after fixing it" line is only meaningful
if the red one is also on the record.

### 5.7 Fable audit polish pass — two seam defects, executed

The tranche audit returned CONFIRMED with zero majors and four minors. Two
were real seam defects, both **new to this card's split** and both found by
executed attack rather than reading:

**A1 — key collision could launder provenance.**
`CommissionedStateSource._ordering_fault` exempted a re-polled sample when
`(sequence, received_at)` matched the previous one. That is a *key*, not
*evidence of sameness*: the audit swapped a different payload under colliding
keys and drew a clean physical `ALLOW`. Unreachable through the shipped
Unitree adapter (host monotonic receipt, per-message sequence) — but this seam
is public and W0-C's adapters are unwritten, which is precisely when a
"unreachable today" hole gets built on. The exemption now requires the datum
to *be* the accepted one (`is`), falling back to full field equality for a
source that rebuilds an equal value; anything else is `sequence_duplicate` and
latches. Both directions are pinned, so the fix cannot be over-tightened into
latching the normal double-poll either.

**A2 — a write-only source crashed the final brake.**
The split made the read and write seams independent, which is the point — but
`_collision_safe` guarded on `_observation_sink is not None` and then called
`_control_state_source.latest()` unconditionally. A protocol-violating source
that implements the sink but not the reader therefore raised `AttributeError`
inside the reactive brake. It fails loud rather than authorising anything, but
a crash in the final gate is still a failure mode this card introduced. Now
guarded; absent reader reads as "no prior sample", which is exactly the
refresh case.

Also in this pass: the §5.3 wording correction (audit item 3, above), and the
D-5 leaf-ness pin (item 4) — `test_evidence_origin_module_is_a_stdlib_only_leaf`,
which walks the module's AST for any `parcel_robot` or non-stdlib import and
then measures the property directly in a subprocess, since the AST walk is
only a proxy for it.

Both A1 and A2 are worth recording rather than folding in silently: neither
was reachable from the shipped configuration, and both were found only because
someone attacked the seam instead of reading it.

### 5.6 H6 audit — `ControlManager.close()` throwing teardown

W0-B's H6: `manager.py:905-907` raises `ControlNotReadyError` on undelivered/
unconfirmed stop, a hazard for any caller closing in a `finally`.

**Audited `runtime.py`'s shutdown path (`:2448-2520`). No change made, and
that is the finding, not an omission.** `self._close_complete = True` sits
*after* `self.control_manager.close()` deliberately (the comment at `:2515`
says so): when close raises, `_close_complete` stays `False`, the guard at
`:2450` lets the next `close()` re-enter, and teardown is **retried**. An
unconfirmed physical stop is exactly the thing that must surface rather than
be swallowed in a `finally`. Wrapping it would have been a safety weakening
sold as a bug fix. Enumerated as H3 for the `ControlManager` owner instead.

One pre-existing nuance recorded, not fixed (outside the narrow wiring scope):
if `control_manager.close()` raises, an earlier `auxiliary_error` from
camera/mic/voice teardown is masked by it. The control error is the more
severe of the two, and the behaviour predates this card.

---

## 6. OWNS compliance

`git diff --numstat` + untracked, this card only (measured):

```text
 191    3   src/parcel_robot/control/base.py
  24    0   src/parcel_robot/control/models.py
  72   38   src/parcel_robot/core/input_health.py
 102   30   src/parcel_robot/runtime.py
  15    5   tests/test_core_input_health.py
  24    7   tests/test_e2_safety_wiring.py
  56        src/parcel_robot/evidence_origin.py        untracked (new)
 955        tests/test_w0a_physical_provenance.py      untracked (new, 48 cells)
            scrum/20260812/task_2/W0A_STATUS.md        untracked (this file)
```

For contrast, the same `git diff --numstat` shows the concurrent cards'
files — `control/factory.py` (+250), `unitree_control.py` (+371/-105),
`tests/test_unitree_control.py` (+415/-35), `commissioning/**`,
`test_w0b_commissioning.py` (W0-B); `task_1/*.md` and `design_spike/**` (P-1,
S-1). **No W0-A edit appears in any of them, and no concurrent edit appears in
any W0-A file.** The tranche's file-disjointness held.

Every path is inside the card's OWNS (`control/base.py`, `control/models.py`,
the narrow `runtime.py` state-source wiring, `core/input_health.py`, focused
tests + amendments, the status doc) — **with one deviation, declared here
rather than left for the audit to find:**

> `src/parcel_robot/evidence_origin.py` is a NEW module at the package root,
> which the card's OWNS list does not name. It exists because the measured
> constraint in §5.4 left no in-OWNS home for the enum: defining it in
> `core/input_health.py` breaks W0-B's leaf invariant, and the natural
> alternative — `parcel_robot/models.py`, the proven-leaf module — is a file
> no card owns and every card imports. A new file was chosen as the lowest-
> risk option: it has zero conflict surface with the three concurrent cards,
> modifies nothing unowned, and is 56 lines of stdlib-only enum. If the board
> prefers the enum in `parcel_robot/models.py`, that is a two-line move.
>
> **RATIFIED as board decision D-5** (`BOARD_DECISIONS.md`), with the standing
> condition that its leaf-ness be pinned by a test — discharged by
> `test_evidence_origin_module_is_a_stdlib_only_leaf` (gate row A4).

`parcel_robot/control/__init__.py` is deliberately untouched (not in OWNS);
`runtime.py` and `control/` reach the new helpers by direct submodule import.

**MUST-NOT-TOUCH, verified untouched:** `control/factory.py`,
`unitree_control.py`, `commissioning/**` (W0-B's, landed);
`navigation/**` — including `reactive_safety.py`, the frozen `evidence_origin`
consumer, which is why D-1 preserves that signature; `route_memory/**`;
`evals/**` (the eval ran out-of-tree precisely so its ledger append could not
reach it); `configs/**`; the K0 arrival predicate; `apply_collision_brake` /
`collision.py`; frozen episodes and digests. `control/state.py` and
`control/unitree_sport.py` are also untouched — the seam split was designed so
that `BufferedRobotStateSource` satisfies `ObservationSink` *structurally* and
the Unitree source is declared *from outside*, which is what kept the change
inside OWNS.

`runtime.py` is a scalpel edit: the two imports, the state-source wiring, the
fixture-allowance decision, two sink call sites, the feedback stamping, one
observability key, the audit item-2 reader guard, and comment corrections. No
behavioural line outside the state-source seam was touched, and
`_dispatch_active` is **AST-identical** to `HEAD` — 15 added comment lines, 0
non-comment changes, equal AST digest (§5.3; the earlier "byte-identical"
wording here was corrected per Fable audit item 3).

---

## 7. does_not_prove

- **The full suite is not green on this host and this card does not claim it
  is.** ~25 unrelated tests fail with `Errno 122` disk-quota from the
  environment, at clean `7242660`, before either card's edits. Gate 13 is open.
- Gate 1 proves physical *controller feedback* can satisfy a commissioned
  join. It does **not** deliver a physical POSE or SCAN channel — under D-1
  those still stamp `SIMULATION` through `evidence_origin`, so a real physical
  deployment holds until W0-C/W0-D supply typed pose/scan sources. That is
  fail-closed and intended, but it means "a physical robot can drive" does not
  follow from this card.
- The ordering latch lives at the `CommissionedStateSource` seam. A vendor
  source used **without** that wrapper gets no ordering check — it gets
  `UNKNOWN` and latches for a different reason. Nothing here forces the
  wrapper to be used; that is W0-B/W0-C's factory obligation (H1).
- `CommissionedStateSource` trusts its caller's `origin=` argument. Spoofing
  by *string* and by *omission* are both closed; a caller that deliberately
  declares `PHYSICAL` over a simulator is not, and cannot be at this layer —
  that is what `CommissioningRecordV1` evidence is for.
- The A4 corner in §4 (a backend object literally named `"unknown"` emitting
  differently-labelled observations) is unreachable in this repo but was not
  executed.
- The AF-2 evidence covers the v4 nav_instruct minival baseline arm. It does
  not cover companion/duplex/follow-bench harnesses, which were not re-run.
- The differential attribution in §5.4 is sound in the direction that matters
  (nothing fails here that passes reverted) but is *asymmetric*: the reverted
  tree lives in a scratch directory and fails four extra corpus/path-dependent
  cells. A W0-A regression in one of those four would have been masked. I read
  their tracebacks — corpus root and pinned-path resolution, nothing touching
  provenance or control — but I did not build a path-faithful control tree.
- Nothing in this card arms anything. No physical auto-arm path was created,
  and the physical branch is strictly more restrictive than before.

---

## 8. Handoffs

- **H1 (to W0-B / `control/factory.py`, enumerated — not edited).**
  `build_unitree_sport_control_manager` constructs the
  `UnitreeSportStateSource` and is the only place that can wrap it:
  `CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL,
  session_epoch=<boot id>)`. Un-wrapped, physical feedback is `UNKNOWN` and
  holds — fail-closed, and correct until a reviewed `CommissioningRecordV1`
  exists. W0-B's H1 asked for the typed `EvidenceOrigin` for
  `CommissioningRecordV1`: it is `parcel_robot.core.input_health.EvidenceOrigin`,
  a 4-member `str`-Enum, importable with no `control` dependency.
- **H1b (to W0-B, informational — no action needed).** Two of W0-B's gates
  caught real problems in W0-A during this pass (§5.4): the leaf-import
  invariant, and the source-text scan for the commissioning package name.
  Both are fixed on W0-A's side; neither W0-B file was touched. The second one
  fires on *prose*, so a future card writing a docstring that names the
  package will hit it too — worth a word in the test's message.
- **H2 (to W0-F/W1, per D-1).** Migrate `navigation/reactive_safety.py`'s
  `scan_evidence_from_observation` onto a typed carrier so SCAN provenance
  stops flowing through a preserved-signature shim.
- **H3 (to the `ControlManager` owner).** `manager.py:905-907` raises on
  teardown. `runtime.py` handles it deliberately (§5.6) and W0-B fixed its own
  session close; a documented contract note on `close()` would stop the next
  caller rediscovering it in a `finally`.
- **H4 (to whoever owns `control/unitree_sport.py`** — nobody, this tranche).
  `_on_message` (`:149`) has `SportModeState`'s own stamp available and should
  populate `source_time_s`; `control/state.py` may later declare
  `origin = EvidenceOrigin.SIMULATION` directly instead of relying on the
  runtime's by-construction declaration. Neither is required for W0-A.
- **H5 (to the tranche audit).** Run `ci_gate --tier commit` once the host
  quota clears. Adversarial lanes worth pointing at this card: spoof by string
  (§5.1 row 1), spoof by omission (D-3 cell), and whether the seam split
  really leaves the sim path byte-identical (§4.1 is the falsifier).
- **H6 (to the next card with a legitimate reason to move
  `_dispatch_active`).** One `update_observation` write there still goes
  through the read-typed `_control_state_source` handle, purely to keep
  `STOPPING_PREDICATE_PIN` unmoved (§5.3). It is safe where it sits, but when
  that symbol's digest moves for a real reason, migrate this line to
  `_observation_sink` in the same change and note it in the regeneration log.
