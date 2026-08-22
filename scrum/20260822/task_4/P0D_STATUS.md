# P0-D — navigation & perception unblocks · status

**Card:** `scrum/20260822/task_4/README.md` · **Board:** `../TASK_BOARD.md`
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22

---

## Headline

**All three defects are fixed, each one seeded RED on the product path first and
each RED output recorded below with the number it was measured at.** The slow
band now delivers `policy × s` instead of `policy × sⁿ` (0.0591 m/s where it
delivered 0.0279); the ranking margin can be non-zero and the prototype signal
set admits 2/2 present queries on both the map API and the C-3 mission path with
`admission_flip` still 0 on every absent query; and a navigation directive can
no longer take the `person` safety lease away from the detector.

**The default configuration did not move.** HEAD's `perception_abstention` and
P0-D's produce **byte-identical** verdicts over the whole PG-3 bench fixture —
147 verdicts, `sha256 575feed9ee131eec3d741a70b04ca0f08b1488586b70f1ef45c949ed0e8fdcc9`
on both sides, under both the default policy and the fixture's own enabled
operating point. `configs/navigation/default.yaml` was **not touched**, so no
`runtime_assets` sync was needed and the frozen `nav_instruct` v4 baseline
cannot have moved.

Two things this card had to touch that are worth reading before the diff: the
J-B stopping-predicate digest was **regenerated** (declared, §6) and one
**known divergence** is declared rather than fixed — the FOLLOW_BENCH dispatch
replica still compounds (§7, handoff 1).

---

## 1. What changed

`git diff --numstat` on the files P0-D touched. `runtime.py`,
`camera_channel/ingress.py` and `navigation/semantic_map.py` carry other cards'
uncommitted work as well, so those rows are **P0-D's share**, measured by
AST-extracting the specific symbols and diffing them against `HEAD`.

| File | + | − | Note |
|---|---:|---:|---|
| `src/parcel_robot/core/velocity_smoother.py` | 36 | 0 | whole-file; clean at HEAD, all P0-D |
| `src/parcel_robot/perception_abstention.py` | 274 | 23 | whole-file; clean at HEAD, all P0-D |
| `src/parcel_robot/runtime.py` | 29 | 4 | **P0-D's share**: `_dispatch_active` + `_set_camera_query_from_directive` only |
| `src/parcel_robot/camera_channel/ingress.py` | 72 | 5 | **P0-D's share**: `SAFETY_LEASE_QUERY` (14 lines), `pinned_queries` (7), `set_query`/`_with_pinned`/`_set_query_batch`/`clear_query` (51 lines replacing 5) |
| `src/parcel_robot/navigation/semantic_map.py` | 24 | 9 | **P0-D's share**: `_abstention_filtered` background only |
| `tests/test_nominal_stop_wiring.py` | 20 | 1 | regenerated digest + its regeneration-log entry (§6) |
| `tests/test_runtime_activation.py` | 7 | 1 | `set_query` contract moved from a bare noun to a batch |
| `tests/test_c3_cutover.py` | — | — | untracked (C-3's); `test_E2_*` converted from a git-diff pin to a structural one (§6) |
| **new** `configs/navigation/prototype.yaml` | 253 | — | opt-in profile; nothing selects it by default |
| **new** `tests/test_p0d_navigation_unblocks.py` | 804 | — | 19 tests, the three seeded-RED properties |

`src/parcel_robot/online_map/**` was read and **not modified** — the C-2 half of
the ranking-margin fix turned out to be already correct (its background is
already `strength if matching else 0.0`), so the fix belonged entirely in the
estimator and in the C-3 call site.

Not touched: `navigation/reactive_safety.py`, `core/hard_stop.py`,
`core/arbiter.py`, `control/**`, `patrol/**`, `scrum/20260821/`, `docs/`,
`backlog/`, `README.md`, `configs/robot*.yaml`, `realtime/**`, `evals/**`,
`configs/navigation/default.yaml`, `runtime_assets/**`. No git write command was
run. The MOVE-1 sim (pid ~910287) and the :8765 panel were left alone; this card
opened no socket and no port.

---

## 2. Defect 1 — MOVE1-D1, compounding gate attenuation

`runtime.py` force-synced the velocity smoother to the **post-gate** command, so
the reactive gate's slow scale was re-applied to its own output every tick.

**Fix.** `VelocitySmoother.sync_after_gate(disposed)` — new method, `force` is
untouched and still used by `reset` and by the emergency reset roster. Per axis:
an axis the gate **zeroed** collapses the ramp (byte-identical to `force`); an
axis the gate merely **scaled** keeps the pre-gate policy value. One call site
changed, `_dispatch_active`, `force(command)` → `sync_after_gate(command)`. No
threshold moved; the gate order is unchanged; every predicate below that line
(`emergency_stopping`, `zero_intent`, `stopping`, `nominal_ramp`) is
character-identical.

**Bench** (`test_MOVE1_D1_a_constant_gate_scale_is_applied_once_per_tick`): a
real `RobotRuntime` on the product dispatch path, shaping off, 60 ticks at a
test-owned 100 ms clock, one obstacle held at 0.78 m — inside the slow band
(`obstacle_stop_m` 0.65, `obstacle_slow_m` 1.2), gate scale `s = 0.23636` —
against a 0.25 m/s voice intent.

**SEED-RED** (shipped `force(post-gate)`):

```
E  AssertionError: the gate scale must land once: delivered 0.027857142857149197
   vs one application 0.0590909090909091
E  assert 0.027857142857149197 == 0.0590909090909091 ± 5.9e-11
```

Ratio **0.4714** — a 2.12× speed loss, and the compounding fixed point
`s·a·dt/(1−s) = 0.02786` to 12 digits. This lands inside MOVE-1's measured
0.0216–0.0277 band and reproduces its D6 discriminator ("below 0.9× a single
application"), which MOVE-1 confirmed on 100 % of 255 slowing ticks.

**GREEN:**

```
39 sent= VelocityCommand(vx=0.0590909090909091, vy=0.0, vyaw=0.0)
   smoother= VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)  prox= slowing
```

`delivered == single application` to `rel=1e-9`, and the ramp now holds the
policy value (0.25) rather than the scaled one.

**The stop band did not move** (`test_a_stop_still_stops_and_the_ramp_restarts_from_rest`):
obstacle at 0.30 m, 20 ticks, every delivered command exactly `vx=0.0, vy=0.0`,
`proximity_state == "stopped"`, smoother at rest.

**Equivalence envelope, measured** (400 randomised ticks per arm, HEAD's
`VelocitySmoother` loaded side-by-side with P0-D's from `git show HEAD:`):

| gate disposition | `force` vs `sync_after_gate` |
|---|---|
| clear band (pass-through) | **identical** (`3a84eafa4b5ca85f`) |
| stop band (zeroes everything) | **identical** (`326cd4dae3b41ef4`) |
| rotate-in-place brake (translation zeroed, ramped yaw kept) | **identical** (`4be0f2159f65afc5`) |
| mixed clear/stop, randomly | **identical** (`fe67271bca5fe36e`) |
| **slow band (scale 0.2364)** | **differs — this is the fix.** steady \|vx\| 0.1331 vs 0.0330 |

---

## 3. Defect 2 — a ranking margin that can be non-zero

`ranking_margin` is a robust z-score, `(top − median) / (1.4826·MAD)`, fitted on
a **cosine** background where every place carries a score. The online map's
background is one non-zero label strength among zeros, so median = 0 and
MAD = 0 and the "degenerate map" guard fires on every healthy map.

**Fix, in three parts.**

1. `label_strength_margin(strengths)` — new estimator. Top-vs-second label
   strength **among matching candidates** (zeros dropped, because a place that
   does not carry the queried label is not an alternative). A lone match is
   scored against `STRAY_LABEL_STRENGTH = 0.12`, the strength the 2026-08-21
   retrieval bench measured for a stray single-detection label, so one lamppost
   is decisive (ratio ≈ 24) and one stray is not (ratio exactly 1.0).
   `ranking_margin` keeps its signature and its body; `ABSTAIN_INDECISIVE_RANKING`
   is unchanged and is the reason code for both estimators.
2. `AbstentionPolicy.signals` — which gates run.
   `DEFAULT_SIGNALS = (label_probability, label_frames, label_support,
   evidence_count, navigability, ranking_margin)`, i.e. today's six in today's
   order. `AbstentionPolicy.ranking_margin_mode` selects the estimator, default
   `robust_z`. Unknown signal names and unknown modes are hard errors; an
   enabled policy with an empty signal set is a hard error; the "a gate at zero
   is a gate that is not there" invariant is now checked **per active signal**.
3. `navigation/semantic_map.py::_abstention_filtered` — under `label_strength`
   the background is the **matching** candidates' own strengths. See §3.2: the
   whole-map background reproduces the same structural failure on the mission
   path, one estimator later.

### 3.1 Seed-RED and green on the map API

C-2's two-place fixture (8 frames, one lamppost, one tree, entry strength
2.909294 each), prototype thresholds, run against the **shipped** module:

```
SEED-RED (robust_z)
entry strengths: {'tree': 2.909294, 'lamppost': 2.909294}
PRESENT 'lamppost'  admitted=False reason='indecisive_ranking' ranking_margin=0.0
                    background_mad=0.0 background_size=2
PRESENT 'tree'      admitted=False reason='not_navigable'      ranking_margin=0.0
ABSENT  'fire hydrant' / 'Narnia' / 'my office' / 'the moon' / 'a coffee shop'
                    admitted=False reason='no_detector_support'
RESULT admitted_present=0 admission_flip_absent=0
ranking_margin([2.9, 0.0, 0.0, 0.0]) = 0.0
```

```
GREEN (prototype signal set + label_strength)
PRESENT 'lamppost'  admitted=True reason='grounded' ranking_margin=24.24411984964591
PRESENT 'tree'      admitted=True reason='grounded' ranking_margin=24.24411984964591
ABSENT  (all five)  admitted=False reason='no_observations'
RESULT admitted_present=2 admission_flip_absent=0
label_strength_margin([2.9,0,0,0])   = 24.166666666666668
label_strength_margin([0.12,0,0])    = 1.0
label_strength_margin([8.2,2.8,0])   = 2.9285714285714284
label_strength_margin([3.2,2.8])     = 1.142857142857143
```

Both arms are kept in the suite
(`test_the_prototype_signal_set_admits_what_the_map_saw_and_nothing_else`,
parametrised over the estimator), so the RED does not disappear with the fix.

### 3.2 A second structural zero, found on the C-3 mission path

The card's acceptance names the **C-3 shadow-corpus fixtures**, so the mission
path was measured too — `ObservationSemanticMap.query` →
`_abstention_filtered`, which is what a directive actually traverses under
`semantic_source: learned_map`. It reaches the gate with a *different*
background: `evidence_confidence` per candidate, not C-2's label strength. Both
C-3 fixture places score **0.8647**, so:

```
SEED-RED (label_strength, whole-map background — the estimator alone was NOT enough)
'bench'    -> 0 cands, verdict=(False, 'indecisive_ranking', 1.0)
'lamppost' -> 0 cands, verdict=(False, 'indecisive_ranking', 1.0)
SEED-RED (robust_z)
'bench'    -> 0 cands, verdict=(False, 'indecisive_ranking', 0.0)
```

A perfect tie is a ratio of exactly 1.0, which no threshold above 1.0 can pass:
the same defect wearing a new hat. Query-conditioning the background fixes it:

```
GREEN
'bench'          -> 1 cands, verdict=(True, 'grounded', 7.2055)
'lamppost'       -> 1 cands, verdict=(True, 'grounded', 7.2055)
'Narnia' / 'my office' / 'the moon' / 'a coffee shop'
                 -> 0 cands, verdict=(False, 'no_observations', -)
```

`admission_flip` is **0** on every absent query, on both paths, under both
estimators. This is `test_the_c3_mission_path_admits_under_the_prototype_signal_set`.

### 3.3 The provisional thresholds

`configs/navigation/prototype.yaml`, `perception.abstention`. Every one of these
is **provisional and was not derived on real frames**: they are read off the
2026-08-21 retrieval bench, which ran on an untextured scene in which three
detectors score 0/69 person recall (`SYNTHESIS.md` §2).

| key | value | why, and how provisional |
|---|---|---|
| `signals` | `[label_support, evidence_count, ranking_margin]` | the three the online map can evidence. Dropping `label_probability`/`label_frames` also drops the "never asked" refusal (absent queries now refuse as `no_observations`); dropping `navigability` drops the gate that refuses "the moon". **Provisional** — restore `navigability` once depth returns populate `ground_evidence_fraction`. |
| `ranking_margin_mode` | `label_strength` | the only separable arm the bench found. **Provisional.** |
| `min_ranking_margin` | **1.5** | a RATIO on this scale, not a z-score. Rejects a lone stray (exactly 1.0) and near-ties; admits a lone corroborated place (23–68). **Provisional, arbitrary within [1.0, 2.0].** |
| `min_evidence_frames` | **3** (from 7) | loosened per the owner directive. 7 was fitted on a 120-frame archived sweep. **Provisional.** |
| `min_label_purity` | 0.5 | unchanged from PG-3's fitted value. |
| `STRAY_LABEL_STRENGTH` | **0.12** | quoted from the bench ("corroborated 2.8–8.2, stray single-detection 0.12"). **Provisional** — and see §7 open risk 1, it is scale-dependent. |

The profile also sets `perception.semantic_source: learned_map`. That is a
declared deviation and it is not decoration: an *enabled* evidence gate over
**oracle** candidates, which carry no evidence metadata at all, refuses every
place. A prototype profile that enables abstention and leaves the source on
`oracle` is a profile that cannot navigate. §5.

No new frozen digest or allowlist was added. `default.yaml` did not move.

---

## 4. Defect 3 — `set_query` unions instead of replacing

`CameraStreamConfig.from_section` refuses a configured batch that does not name
the whole word `person`. That guarded the **config**. It did not guard
`CameraIngress.set_query`, which *replaced* the batch — so one directive took
the PG-1 safety lease away at runtime.

**SEED-RED**, against the shipped ingress and the shipped runtime method:

```
configured batch          : ('person', 'lamppost')
after directive 'bench'   : ('bench',)
person still present      : False
runtime sent to ingress   : [('bench',)]
```

**Fix.** `SAFETY_LEASE_QUERY = "person"` and a `pinned_queries` field on
`CameraIngress`; `set_query` returns `pinned + requested`, de-duplicated in that
order, with `person` guaranteed by the same **whole-word** test the config check
uses (so `"a person"` satisfies it and `"personnel carrier"` does not, and the
two guards cannot disagree). `_set_camera_query_from_directive` re-supplies the
configured `camera_ingress_queries` and appends the noun.

**GREEN:**

```
configured batch          : ('person', 'lamppost')
after directive 'bench'   : ('person', 'lamppost', 'bench')
person still present      : True
runtime -> live batch     : ('person', 'lamppost', 'bench')
after clear_query         : ()   has_query: False
```

`clear_query()` is deliberately **not** covered by the pin: it is an operator
switching the eye off, and a pinned `person` surviving it would leave the
detector polling forever. A `None`/empty request is still an empty batch, so a
bare ingress that was never given a query is unchanged.

`tests/test_c1_camera_stream.py` stays green (66 passed, file unmodified) — the
lease test the card names among them.

---

## 5. Flag-off byte identity

**`perception_abstention`.** HEAD's module and P0-D's were loaded
side-by-side in one interpreter (HEAD's from `git show HEAD:…` under a separate
module name) and run over all 49 PG-3 bench rows × 3 entry paths (full signals,
`support=None`, `places=()`) = 147 verdict dicts:

```
default (enabled=False, shipped defaults)
  rows          : 147
  HEAD  sha256  : 575feed9ee131eec3d741a70b04ca0f08b1488586b70f1ef45c949ed0e8fdcc9
  P0-D  sha256  : 575feed9ee131eec3d741a70b04ca0f08b1488586b70f1ef45c949ed0e8fdcc9
  IDENTICAL     : True
bench operating point (enabled=True, six signals)
  HEAD/P0-D     : 575feed9…  IDENTICAL : True
ranking_margin over all 49 backgrounds identical: True
default policy fields identical: True
```

(The two arms share a digest because PG-3's fitted operating point *is* the
module's default, and `assess_place_query` has never consulted `enabled` — the
callers do.)

**Velocity smoother.** Not flag-gated, and cannot be: the fix is unconditional
by design. The equivalence envelope is measured instead and is in §2 — identical
on clear, stop, rotate-in-place and mixed dispositions; different only in the
slow band, which is the defect.

**Config.** `configs/navigation/default.yaml` is byte-unchanged by this card
(it carries an earlier card's uncommitted +38, which P0-D neither added nor
touched), so `tools/sync_runtime_assets.py` was not needed and was not run.
`configs/navigation/prototype.yaml` is a new file that nothing selects.
`test_the_prototype_profile_is_default_yaml_with_one_block_changed` pins the
copy against drift: the only permitted differences are
`perception.semantic_source` and five keys under `perception.abstention`.

---

## 6. Ratchets moved, and why

Two existing guards had to move. Neither was deleted and neither was replaced
with something weaker.

**(a) `tests/test_nominal_stop_wiring.py::STOPPING_PREDICATE_PIN` —
regenerated for `RobotRuntime._dispatch_active`**
(`7a830d4c…` → `51a50847…`). The pin is AST-normalised, so this moved for the
one call change and nothing else; verified by AST-extracting `_dispatch_active`
from `HEAD` and from the worktree and diffing — **the only difference is the
`force` → `sync_after_gate` line and its comment.** What the pin protects is
stop classification, and `sync_after_gate` is byte-identical to `force` for
every stop. Reason recorded in the pin's own regeneration log, as its docstring
requires.

**(b) `tests/test_c3_cutover.py::test_E2_the_abstention_gate_is_not_modified_by_this_card`
— converted from a `git diff` emptiness pin to a structural one.** That test
asserted `git diff -- perception_abstention.py` is empty. P0-D was chartered to
change that file, so the assertion could no longer be true and no
regeneration could make it true. It is replaced by the property it stood in
for, which is what E2 actually meant and is stronger than an emptiness check:
C-3's five owned modules must **call** the shipped gate and must not re-declare
its verdict vocabulary, its evidence types or its thresholds — checked against
`ABSTENTION_REASONS` and a list of declaration spellings — plus a positive check
that `semantic_map.py` really does import and call `assess_place_query`, so "no
fork" cannot be satisfied by "no gate at all". `test_the_online_map_package_is_not_modified_by_this_card`
is untouched and still green.

---

## 7. What this does NOT prove

1. **`STRAY_LABEL_STRENGTH` is scale-dependent, and the two paths are on
   different scales.** 0.12 was measured on C-2's `_entry_score` (range
   0.12–8.2). On the C-3 mission path the candidate score is
   `evidence_confidence` (range 0–0.999), where 0.12 happens to land near
   "seen once" (`saturation(1 frame) = 0.133`) — which is a *coincidence that
   reads sensibly*, not a calibration. A single constant serving two scales is
   a latent bug waiting for either scale to change. Fix properly by making the
   stray reference a policy field, or by putting both paths on one score.
2. **Nothing here was measured on real frames.** Every threshold in §3.3 comes
   from an untextured scene. The abstention numbers are an operating point to
   measure *from*.
3. **The prototype profile has never been run end-to-end.** It is validated by
   config load, by the signal-set semantics, and by the two fixture corpora. No
   mission was driven with it.
4. **The fixtures are small.** Two places, two present queries, five absent
   ones. `admission_flip = 0` on five absent queries is directional, not a false
   accept rate.
5. **The slow-band fix is arithmetic, not a physical measurement.** It says the
   actuator receives `policy × s`. Whether the *body* then moves at that speed
   is a claim only a sim or a dog can make, and neither was run.
6. **The delivered slow-band speed is now ~2.1× higher than before** in the same
   geometry. That is the intended correction, and it is a real behavioural
   change in the *less* conservative direction inside the slow band. The stop
   band, the e-stop latch, `reactive_safety` semantics, `hard_stop.finalize_command`
   and the arbiter are all untouched, and the stop-band test asserts exact zero.
7. **One transient failure was observed and is not explained.**
   `tests/test_runtime.py::test_runtime_streaming_text_executes_only_final_transcript`
   failed once, in one randomised-order run of a 16-file selection. It passes in
   isolation and passed in 3 subsequent randomised runs of the identical
   selection, in the deterministic run, and in the full-suite run. It sits in
   the `submit_realtime_transcript` region **P0-B is editing concurrently**, so
   the most likely cause is a file changing under collection. Recorded rather
   than dismissed.

---

## 8. How it was verified

Every command with `.parcel/bin/python` / `.parcel/bin/ruff`. Scratch under
`/home/jaewoo-jang/.cache/parcel-p0-d/`.

| Gate | Result |
|---|---|
| Card gate, verbatim: `pytest -q test_velocity_shaping test_runtime test_perception_abstention* test_c2_online_map test_c3_cutover test_c1_camera_stream test_move1_patrol -x` | **342 passed** |
| `pytest -q tests/test_p0d_navigation_unblocks.py` | **19 passed** |
| Card gate + P0-D + 8 collateral files (`nominal_stop_wiring`, `runtime_activation`, `sa2_live_pipeline`, `follow_bench_v1`, `ci_gate_jerk_ratchet`, `motion_shaping`, `core_hard_stop`, `e2_safety_wiring`) | **509 passed, 5 skipped** — deterministic (`-p no:randomly`) and 3× randomised |
| Whole tree, `pytest -q tests/` | **8100 passed, 27 skipped, 2 xfailed, 17 errors in 419 s.** All 17 errors are `tests/test_voice_nav_e2e.py` setup errors from the owner-store guard refusing `parcel_memory.sqlite3` under pytest — MOVE1-D2, pre-existing, nightly tier only, unrelated to this card |
| `ruff check` on OWNS (7 source files + 4 test files) | **All checks passed** |
| `ruff check` (whole tree) | 12 pre-existing errors, **none in a file P0-D touched** (`camera_channel/__init__.py`, `camera_channel/backends/factory.py`, `camera_channel/channel.py`, `detection_adapter/noise.py`, `detection_adapter/sim_bridge.py` — all clean vs HEAD) |
| Flag-off identity | §5 |

`scripts/ci_gate.py` was **not** run (P0-E owns it). No git write command was
run. No process was killed.

---

## 9. Deviations from OWNS, declared

1. **`configs/navigation/prototype.yaml` sets `perception.semantic_source:
   learned_map`.** The card asked only for the abstention block. Reason in §3.3:
   an enabled evidence gate over oracle candidates refuses everything, so the
   two keys are one decision. `default.yaml` did not move and nothing selects
   the profile.
2. **`tests/test_c3_cutover.py::test_E2_*` was rewritten**, and
   **`tests/test_nominal_stop_wiring.py`'s digest was regenerated.** Both are
   other cards' ratchets that this card's chartered change necessarily moved.
   §6. Neither was deleted; neither was replaced with a weaker check; no new
   ratchet was added.
3. **`tests/test_runtime_activation.py::test_start_navigation_sets_camera_query`
   was updated** (7 lines) — it asserted the old `set_query` contract. In OWNS
   as a test of a module P0-D owns, listed here because the file as a whole is
   not named on the card.
4. **`src/parcel_robot/navigation/semantic_map.py` was edited.** OWNS permits it
   "only if the abstention call site needs the config plumbed". It did — see
   §3.2, the estimator alone left the mission path refusing everything.
5. **`configs/navigation/prototype.yaml` is a full copy of `default.yaml`, not
   an overlay.** `DirectiveNavigator.from_config` has no `extends`/merge
   support and `navigation/pipeline.py` is outside OWNS, so a partial file would
   silently pick up code defaults instead of the shipping ones. The copy is
   pinned against drift by test (§5).

---

## 10. Handoffs

1. **`evals/companion_nav/runner.py:608` still compounds.** The FOLLOW_BENCH
   dispatch replica (`_DispatchReplica.step`) calls
   `self._smoother.force(command, now=now)` on the post-gate command — the exact
   line this card fixed in the product. It is **not** a pinned symbol, so the
   J-B ratchet cannot see the divergence. Consequence: **the bench's slow-band
   speeds now measure the compounding the product no longer has.** `evals/**` is
   outside P0-D's OWNS and the bench publishes numbers, so this is handed off
   rather than changed. The one-line fix is `force` → `sync_after_gate`; it does
   not move any pinned digest. Noted in the pin's regeneration log too.
2. **P0-A / the `--prototype` launcher:** `configs/navigation/prototype.yaml` is
   *not* in `tools/sync_runtime_assets.py`'s explicit asset list, so it does not
   ship in the wheel's `runtime_assets`. A robot profile that points
   `navigation.config` at it resolves from the repo root only. Add it to the
   sync list (and to `test_release_parity.py`'s `DEFAULT_FILE_ASSETS`) if an
   installed wheel is supposed to be able to select it.
3. **MOVE-1's D6 number is now stale in the good direction.** Any slow-band
   latency, throughput or path-length figure taken before 2026-08-22 was
   measuring the compounding; re-measure before comparing.
4. **`STRAY_LABEL_STRENGTH` should become a policy field** (§7 open risk 1)
   before a second scoring scale reaches the gate.
5. **Re-enable `navigability` in the prototype signal set** once
   `ground_evidence_fraction` is populated from depth returns rather than from
   robot traversal. It is the gate that refuses corpus row 12 ("take me to the
   moon"), and it is off today.
