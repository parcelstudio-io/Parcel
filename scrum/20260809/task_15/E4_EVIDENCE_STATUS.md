# Lane E4 — EVIDENCE RE-RUNS on the settled tree

Status: **DONE, UNCOMMITTED.** Base: `HEAD = 6bd945d` plus the uncommitted E1
(import-cycle) + E2 (safety-wiring) + E3 (eval-integrity) repairs.

Charter: Fable's independent audit (`AUDIT_FABLE_INDEPENDENT.md`) returned four
cards on **evidence strength**, not tampering. The E1 cross-card import cycle had
silently disabled the InstructNav ladder **and** the D3 lock-on guard under
several import orders, so every headline in those cards may have been measured
on a tree where the feature was not running. E4 re-earns the evidence or restates
the claim.

**Headline: two cards could not re-earn their claims and stay RETURNED.**
V-D's pre-registered margin is not met (the flag produces **zero** measurable
effect on the frozen minival). V-E's is not met at tier level (its flag **loses**
two Tier-B episodes and produces a real **false arrival 4.779 m** from the goal).
Neither number was massaged.

---

## 1 — V-A: pixel-arrival gate, re-run verbatim. **RE-EARNED.**

```
MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 \
  .parcel/bin/python scrum/20260809/task_12/b4_gate.py A
```

| field | value |
|---|---|
| `arrival` | **succeeded** |
| `candidate_source` | **pixel_detector** |
| arrival distance (`final_distance_m`) | **1.717 m**, inside band `[1.5263, 1.7263]` |
| wall time | **0.41 s** closed loop (68 steps); 2.2 s process wall incl. imports |
| OWLv2 confidence | 0.858 |
| localization error | 0.035 m |
| `candidate_radius_m` | 0.4063 |
| oracle objects seen | 0 |

**Determinism / attribution.** Two consecutive runs: byte-identical except the
four timing fields. Controlled A/B against `git checkout HEAD --
camera_channel/ingress.py headless_city.py`, then restore: **identical modulo
timing**, so the repair lanes move nothing here.

**E3 constants confirmed.** The pixel-clearance constants now derive from
`DEFAULT_STAND_OFF_ENVELOPE` and are **bit-identical** to the literals they
replaced (`struct.pack('<d', …)` equality): `arrival_radius_m 0.06`,
`target_surface_clearance_m 0.8`, `footprint_radius_m 0.32`. Metadata unchanged,
as predicted.

**What did NOT reproduce.** The published row read confidence `0.881`, loc-error
`0.037 m`, radius `0.4156`, band `[1.536, 1.736]`. Today's tree gives `0.858 /
0.035 / 0.4063 / [1.5263, 1.7263]` at both HEAD and HEAD+repairs. The repair
lanes are ruled out; the residual is the detector/render stack across sessions.
V-A_STATUS.md is re-recorded from **this** run, with the superseded numbers kept
visible and **not** restated as current.

---

## 2 — V-B: made the gate match the claim. **Option (a) — the real detector was run.**

The audit's three findings, all confirmed:

* `PARCEL_OWLV2_THRESHOLD` was never exercised by any V-B file;
* `scores = (0.28, 0.35, 0.42)` was a hardcoded literal described as "observed";
* `false_positive_commits=0` was arithmetically guaranteed (one `update()` per
  phantom against a 3-of-5 confirmer).

New live cell `evaluate_live_cells()` (`T-cam-proxy-vb-live`): real OWLv2 ONNX on
live MuJoCo-EGL renders of the b4-gate lamppost, **5 distinct camera poses** on a
3.0 m orbit (azimuths −40…+40°, each facing the target), at each requested
operating point.

| | thr **0.2** | thr **0.55** (unmodified grounder floor) |
|---|---|---|
| views yielding a box | **5/5** | **1/5** |
| recorded scores | `0.4309, 0.4598, 0.5539, 0.3139, 0.2308` | `0.5539` |
| lamppost confirmed (3-of-5) | **yes, view idx 2**, cred `0.86285` | **no** |
| absent class `"fire hydrant"` boxes | **0** / 5 views | **0** / 5 views |
| `live_absent_class_commits` (measured) | **0** | **0** |
| `live_repeated_phantom_commits` (measured) | **1**, view idx 2 | 0 |

Credibility trace at 0.2: `0.43086 → 0.69254 → 0.86285 → 0.90589 → 0.92761`.
Re-run after an internal refactor: identical.

**Claim RESTATED.** "A lower detector operating point is safe" is deleted. What
is supported: on this prop the 0.55 floor makes 3-of-5 *unreachable* (1/5 views
survive), and 0.2 is what makes multi-view confirmation possible at all; the
absent class contributed zero boxes at both points. What is **refuted** in the
same run: an injected view-consistent phantom **commits on exactly the same
view** as the real target. Finite-window M-of-N gives no protection against a
persistent false positive, and `false_positive_commits = 0` may not be quoted
without that sentence.

The pure cell keeps its numbers byte-unchanged (so the two publications stay
comparable) and now self-declares: `operating_scores_are_synthetic: true`,
`false_positive_commits_is_arithmetic: true`.

---

## 3 — V-D / V-E: the nav_instruct SR gates actually ran. **BOTH RETURNED.**

No nav_instruct run of any kind had landed this batch. E4 added a **default-off**
flag seam to the harness and ran four paired arms on the frozen v3 minival.

Seam: `NavInstructRunner(navigator_overrides=...)` — a **closed set**
(`{value_directed_search, detection_lock_on}`), empty by default, expanding to
`**{}` so the flag-OFF call to `from_config` is byte-identical to the one every
frozen row was measured with. CLI `--navigator-flag NAME` (repeatable);
`--freeze` **refuses** a flag-on run; flag-on reports get a `-flagon` report id
and a `navigator_flags` key on the ledger row (stamped only when non-empty).

```
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode candidate --episode-version v3 \
  --budget-policy scaled-path-v1 --max-steps 200 [--navigator-flag ...]
```

Seed 20260804, `episode_digest 919a0fea…c556aa` on **all four arms**, n = 25
(5 families × 5 tiers → **each tier is n = 5**).

| arm | overall SR | A | **B** | C | D | E | SPL |
|---|---|---|---|---|---|---|---|
| flag-OFF (control) | **0.24** | 0.60 | **0.40** | 0.00 | 0.20 | 0.00 | 0.20016476583919257 |
| `value_directed_search` only | **0.24** | 0.60 | **0.40** | 0.00 | 0.20 | 0.00 | 0.20016476583919257 |
| `detection_lock_on` only | **0.16** | 0.60 | **0.00** | 0.00 | 0.20 | 0.00 | 0.12016476583919257 |
| both | **0.16** | 0.60 | **0.00** | 0.00 | 0.20 | 0.00 | 0.12016476583919257 |

**Control reproduced the committed candidate row exactly** (sr 0.24, spl
`0.20016476583919257`, identical failure histogram) — which is also the proof
that the new seam is a no-op when unused.

### 2×2 attribution

`value_directed_search` → **0 paired flips**, SPL equal to 17 significant
digits. `detection_lock_on` → **−2 episodes, 0 gained**, and `both == lock-on
alone`. The entire regression is `detection_lock_on`.

| pre-registered gate | measured | verdict |
|---|---|---|
| V-D Tier B SR ≥ fixed-spin | 0.40 vs 0.40 | **VACUOUS** — equal only because the flag changed nothing. Not earned. |
| V-D Tier C ≥ +10 pp vs nearest-frontier | 0.00 vs 0.00 → **+0.0 pp** | **FAIL** |
| V-E `\|SR_lock − SR_oracle\| ≤ 0.10`, aggregate | gap **0.08** | within margin (but 1 episode = 4 pp at n=25) |
| V-E same margin, **per tier** | Tier B gap **0.40** | **FAIL — 4× the margin** |

The flags are confirmed live on the navigator
(`from_config(..., value_directed_search=True).value_directed_search is True`),
so this is not the E1 cycle masking a feature again.

### The two lost episodes

| episode | flag-OFF | `detection_lock_on` ON |
|---|---|---|
| `nav-region_goal-B-05-586317e4` | success, `arrived_verified`, dtg 0.0 m, authority `agreement` | **`false_arrival`** — still reports `arrived_verified` while **4.779 m** from goal |
| `nav-object_relative-B-05-7d441aee` | success, dtg 0.0 m | grounding **RESOLVED → UNSEEN**, `navigation_step_limit_inside_goal` |

The first is the safety-relevant one and is exactly the failure the card's own FP
gate claimed to exclude; the proxy cell (`sr_gap=0.0`, `fp=0`) could not see it
because it never ran the product path.

### Rule-2 compliance

* `episode_digest` **919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa**
  on every arm — unmoved.
* `evals/nav_instruct/episodes/` **untouched** (tree sha256 of all files:
  `0fb1bd4462d8bea8ea0517327140aa43327560dc84401e3f3428087089081beb`, before and
  after).
* **No re-freeze.** All four arms are `--mode candidate` → `frozen_baseline:
  false`; `--freeze` was never passed and now refuses flag-on runs outright. No
  frozen row was moved, so no STOP was required.
* ci_gate hard-safety reads the latest `frozen_baseline: true` row, which none of
  these arms is — the gate is unaffected by the false arrival above.

---

## 4 — T-cam tier: **renamed the cells** (honest and cheaper).

Registering a real `T-CAM` tier means giving `PerceptionChain` a `NoiseTier`
whose candidates come from rendered pixels instead of the GT oracle that `_lift`
reads, then installing it through `use_perception_chain` on the mission path.
That is a wiring card, not a rename, and V-B/V-E explicitly landed no runtime
wiring. Renaming is the honest-and-cheaper option and is what E4 did.

| file | before | after |
|---|---|---|
| `cam_arrival.py` | `T-cam-arrival` | `T-cam-proxy-arrival` |
| `cam_detector.py` | `T-cam-detector` | `T-cam-proxy-detector` |
| `cam_lock_on.py` | `T-cam-ve-lock-on` | `T-cam-proxy-ve-lock-on` |
| `cam_multiview_metric.py` | `T-cam-vb-pure` | `T-cam-proxy-vb-pure` (+ new `T-cam-proxy-vb-live`) |
| `cam_foundation.py` | `T-cam-foundation` | **unchanged — deliberate** |

`cam_foundation.py`'s id is baked into the frozen `cam_foundation_pack.json`,
which `tests/test_cam_foundation.py` byte-pins by sha256. Renaming it would move
a frozen digest to make a label prettier — a rule-2 STOP, not a cleanup. A
comment at the constant records why, and it inherits the same "report id, not a
tier" statement.

Also added `perception_chain.REGISTERED_TIERS = ("T0", "T1")` — the complete set
`from_tier` can build — and `from_tier`'s error now names it, so "is there a
T-cam tier?" is answerable instead of assumable.

---

## 5 — Latency-ledger reachability (C-A debt). **CLOSED — the gate now fires.**

`resolve_latency_ledger_path` returned `None` unless `PARCEL_LATENCY_LEDGER` was
set and nothing set it, so the ledger held 1 seeded row and
`latency-tail-ledger` was permanently `skip`.

Fix (`observability.py`, ledger-path resolution only — **`runtime.py`
untouched**):

1. fall back to `REPO/evals/latency/ledger.jsonl` (`default_latency_ledger_path`);
2. `PARCEL_LATENCY_LEDGER_OFF` — explicit opt-out, restores write-nothing exactly;
3. a **pytest process never resolves the committed ledger** (≈29 test files close
   a runtime; a unit-test teardown is not a measurement). Explicit paths still win;
4. `append_latency_ledger_row` **refuses a turn-less row into the committed
   ledger**. Load-bearing: `evaluate_latency_ratchet` `continue`s on baseline
   metrics a row lacks, so a turn-less row would have made the newly-reachable
   gate return a **vacuous pass**;
5. `run_duplex_v1.py` (ledger emission only) replays the `DuplexVoiceSession`
   stage clocks it already collects for TTFT into a `LatencyTracker` and appends
   one real row per run.

Measured — rows **1 → 5**:

```
before: [  skip] HARD  latency-tail-ledger  ledger rows=1 < window=5; ratchet skipped
after:  [  PASS] HARD  latency-tail-ledger  latest row latency-20260810T082415Z-4d83035f:
                                            6 metric series within 1.2x tail ceiling (rows=5, window=5)
```

Real row: `turns=2`, `TurnTotal p95 40.635 ms` (pin 1250 ms), 10 genuinely
observed stages.

**Honest limit.** The duplex text path has no mic/endpointer/audio sink, so the
four acoustic pins are **absent by omission** from its rows, and the ratchet
reads only `rows[-1]` — so it presently compares **2 of 6** pinned metrics while
its detail string says "6 metric series" (it counts baseline metrics, not
compared ones). That string is misleading; fixing it belongs to the
`scripts/ci_gate.py` owner, outside E4's OWNS. `latency-tail` (percentile-pin
pytest) remains the authoritative hard check, so nothing was lost.

---

## Authoritative CI — `scripts/ci_gate.py --tier commit` @ 2026-08-10T08:31:52Z

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v3-20260809T161252Z:
                                          collisions=0 false_arrival=0 | mutation panel clean | follow-bench 5 rows
[  PASS] HARD  frozen-digest-sentinels    3 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        rows=5, window=5  (was: skip, rows=1 < window=5)
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3340 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.   elapsed 104.7s
```

3327 → **3340** passed (+13 = `tests/test_e4_evidence_seams.py`). Ruff
unchanged at baseline. `latency-tail-ledger` moved skip → PASS.

**Append-only proved, not asserted.** The first 17 rows of
`evals/nav_instruct/results/ledger.jsonl` are byte-identical to `HEAD`'s whole
file (4 new rows appended); `evals/latency/ledger.jsonl`'s seed row is
byte-identical to `HEAD`'s whole file (4 rows appended). No row was rewritten.

**Pytest-suppression proved.** `evals/latency/ledger.jsonl` still has exactly 5
rows *after* the full 3340-test suite ran — the default path is genuinely inert
under pytest.

## Frozen-digest proof (before → after this lane)

| artifact | sha256 | moved? |
|---|---|---|
| `evals/nav_instruct/episodes/v3/manifest.json` | `eb1289e9723e008336b33bff83f2e4c9a91e07d1e6552866f6ede52da7f57858` | no |
| `evals/companion/embodied_plan_v1/manifest.json` | `33c662c8d3611f39bb1fc56dabbebb2c4c7c913a8499449107cd5add95c6e54f` | no |
| `evals/companion/personal_convo_v1/manifest.json` | `d338f3352cd9597aeb9977f75c139d926bdfba1fe1d6b036b9a3ace08a1cf114` | no |
| nav_instruct v3 `episode_digest` | `919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa` | no |
| `evals/nav_instruct/episodes/` (all files) | `0fb1bd4462d8bea8ea0517327140aa43327560dc84401e3f3428087089081beb` | no |
| `evals/nav_instruct/cam_foundation_pack.json` | pinned by `tests/test_cam_foundation.py` | no (that is why its TIER_ID was left alone) |

Append-only artifacts that *did* grow, by design: `evals/nav_instruct/results/`
(4 new candidate reports + 4 ledger rows), `evals/latency/ledger.jsonl` (+4
rows), `evals/companion/duplex_v1/results/` (4 reports + 4 rows).

## Files touched

| path | change |
|---|---|
| `evals/nav_instruct/cam_multiview_metric.py` | live OWLv2 operating-point cell; honest restatement; proxy tier id |
| `evals/nav_instruct/cam_arrival.py`, `cam_detector.py`, `cam_lock_on.py` | tier id → `T-cam-proxy-*` |
| `evals/nav_instruct/cam_foundation.py` | comment only — why its frozen id is NOT renamed |
| `evals/nav_instruct/runner.py` | default-off `navigator_overrides` closed-set seam |
| `evals/nav_instruct/run_nav_instruct_v1.py` | `--navigator-flag`; `--freeze` refuses flag-on; flag provenance on report + ledger row |
| `evals/companion/duplex_v1/run_duplex_v1.py` | latency-ledger emission from existing stage clocks |
| `evals/latency/README.md` | reachability, suppressions, coverage caveat |
| `src/parcel_robot/observability.py` | ledger-path resolution + turn-less-row refusal |
| `src/parcel_robot/detection_adapter/perception_chain.py` | `REGISTERED_TIERS` + a naming error message |
| `tests/test_e4_evidence_seams.py` | **new** — pins all of the above |
| `scrum/20260809/task_15/{V-A,V-B,V-D,V-E,C-A}_STATUS.md` | re-recorded / restated |

MUST-NOT held: `runtime.py`, `navigation/**`, `instructnav/**`, `core/**`,
`configs/**`, `camera_channel/ingress.py`, `scripts/ci_gate.py`,
`tests/test_authority_*`, `tests/test_dynamic_layer.py`,
`evals/nav_instruct/episodes/**`, `evals/companion/personal_convo_v1/manifest.json`,
every DIGEST_SENTINELS-pinned file — all untouched.

## does_not_prove

- The V-B live cell is one prop, one orbit, five views on non-photoreal renders.
  It is an operating-point probe, not a precision/recall curve, and not a D455
  field claim.
- The nav_instruct minival is n = 25 with **n = 5 per tier**. A single episode is
  4 pp overall and 20 pp within a tier. These numbers separate the arms; they do
  not estimate the arms.
- "`value_directed_search` never enters the first-UNSEEN VLFM state on this pack"
  is a *hypothesis* for its zero effect, not a measurement.
- The reachable latency ledger measures the **text** duplex path only; the
  acoustic-ack ratchet stays aspirational until a real capture/playback run
  writes the newest row.
