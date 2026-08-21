# R23 — limits that refuse

**Date:** 2026-08-21 · **Card:** `scrum/20260821/task_2/README.md`
**Executor:** Claude Opus (agent) · **Auditor:** Fable — **DEFERRED at the
owner's request.** Written to audit cleanly weeks from now with nobody to ask:
every claim names the file, the line, the test, the seed or the artefact that
carries it, and every place the evidence stops is marked `does_not_prove`.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Tree:** sole executor, one card, one tree. Nothing committed, staged or
stashed. Entered on the tree R22 left (HEAD `2c27496`, plus the uncommitted
wave).
**Trigger:** `scrum/20260820/AUDIT_FULL_FABLE.md` → *Confirmed findings NOT
previously known or carded* → **Safety**, bullet 2 (§Safety-2), CONFIRMED-PARTIAL.

---

## §0 — One paragraph

`ConfigStore.safety_limits()` did a bare `float()` and `SafetyLimits` had no
validation, so a NaN velocity limit was accepted and then silently disabled the
clamp at **both** enforcement sites — `abs(v) > nan` is False for every v, in
`core/arbiter.py` and in `SafetySupervisor` alike — while `inf`, zero and
negative were accepted without complaint. The audit rated it PARTIAL because
the shipped config is digest-pinned; **the exposure is real and I reproduced
it end to end**: with `motion.max_vx: .nan` plus the equally-documented
`control.max_vx/vy/vyaw` keys set, `web_panel.build_runtime` returns a fully
constructed robot whose arbiter and supervisor both **approve `vx = 1e9 m/s`**
(§4.2). Three layers now close it: **the loader refuses by name**
(`configs/robot.yaml: motion.max_vx must be finite, got nan …`), **the
dataclass refuses on construction** so no direct build slips past, and **both
comparison sites refuse an unusable clamp anyway** — the layer that holds when
the first two are bypassed. The card's primary deliverable is the enumeration,
and it is empirical, not read off the page: an AST sweep found **502** candidate
`float()`/`int()` coercions in `src/parcel_robot`, a line-level execution trace
across **10 config-file loaders** narrowed that to **100 actually reachable
from a config load**, and **660 poison cases** (580 over every numeric leaf of
`configs/robot.yaml` driven through the real operator launch path, 80 over
`configs/navigation/default.yaml`) gave each one a measured verdict rather than
an argued one (§3). That sweep found **five further holes the audit did not
name**, all outside this card's OWNS list and all registered owner-gated in
§7 — the largest being that `configs/navigation/default.yaml`'s **own**
`safety.max_vx/max_vy` clamp is the same bug, still open, and that a **negative**
planner clamp does not merely fail open, it *inverts* (a `max_vx: -1` raises a
0.5 m/s request to 1.0 m/s). **12 seeds RED**, every restore byte-identical,
fresh-interpreter canary green. **Full gate PASS at 7377 passed** (7218 → 7377,
**+159, 0 removed**), hard-safety green on the **unmoved** frozen nav baseline,
and `configs/robot.yaml` is **byte-untouched** and loads to the **identical**
effective triple `(1.0, 0.5, 1.5)`. Cost **$0.00** — every proof is local and
in-process; no hosted model was called, no credential was loaded, the owner's
`:8765` stack was never contacted.

---

## §1 — What changed

| File | Lines | What |
|---|---|---|
| `src/parcel_robot/safety.py` | +106 / −11 | `SafetyLimitError`, `is_usable_limit()`, `validated_limit()`, `SafetyLimits.__post_init__`, fail-closed comparison in `_validate_velocity` **and** the pose bound |
| `src/parcel_robot/config.py` | +87 / −8 | `_number` / `_positive_number` / `_whole_number`; `safety_limits()`, `poses()`, `wifi_cards()` routed through them |
| `src/parcel_robot/core/arbiter.py` | +38 / −8 | `_limit_violation` fail-closed on both operands (no threshold changes) |
| `tests/test_fail_closed_limits.py` | +525 (new) | 159 tests + 1 registered-gap skip |

Net **+207 / −24** across the three source files. Nothing else in `src/` was
edited. `configs/robot.yaml` was **not** touched (`git status` clean for it;
`frozen-digest-sentinels` and `release-parity` both green in §2).

### 1.1 The shape of the fix

Three layers, deliberately redundant, because the audit's point is that the
single layer that existed was zero layers:

1. **The loader** (`config.py`). Names the file, the dotted key and the value:
   `…/robot.yaml: motion.max_vx must be finite, got nan. A non-finite value
   here is not a loose setting, it is an absent one.` This is what an operator
   reads at 2 a.m.
2. **The dataclass** (`safety.py`). `SafetyLimits.__post_init__` validates
   every field, so `SafetyLimits(max_vx=float("nan"))` raises wherever it is
   constructed — the loader is not the only constructor
   (`control/factory.py`, `sim_ipc.py`, `agent.py`, tests).
3. **The comparison** (`safety.py`, `core/arbiter.py`). Both sites check that
   the limit *can* clamp before comparing against it. This is the layer that
   matters when 1 and 2 are bypassed, and bypass is not hypothetical:
   `self.limits` is an injected attribute that any caller can rebind.

`is_usable_limit()` is the single predicate all three share, so the answer to
"is this a clamp?" is the same at every site by construction rather than by
three copies of a condition that can drift apart.

### 1.2 What I did **not** change

* **No threshold moved.** The loader's historical fallbacks stay `(0.6, 0.4,
  1.0)` and the dataclass defaults stay `(1.0, 0.5, 1.5)`. They differ, and
  they differed before this card; harmonising them is a threshold change the
  card forbids. Registered in §7.
* **Existing refusal messages are byte-identical.** `"vx exceeds the configured
  safe limit"` etc. are unchanged; the fail-closed path emits a *new, distinct*
  message (`"max_vx is not a usable clamp (nan); motion refused"`) so the two
  causes are never confused in a log. Pinned by
  `test_arbiter_and_supervisor_still_accept_and_still_refuse_normally`.
* **Zero is refused, deliberately.** A `max_vy: 0` clamp is fail-*closed*, not
  fail-open, so refusing it is a judgement call. I follow the card ("refuses …
  non-positive") and the repo precedent — `ControlLimits.__post_init__` has
  refused a zero limit at the control boundary all along, so accepting one at
  the safety boundary was already inconsistent. **Consequence to know:** a
  robot with genuinely no lateral motion cannot express that as `max_vy: 0`;
  it belongs in `robot.profile.max_vy_mps`, which is explicitly documented as
  non-negative and already accepts 0.

---

## §2 — The gate, verbatim

Baseline on entry (my own run, before any edit — the chain baseline of "7164
passed" predates R22's +54):

```
CI GATE — tier=commit  (2026-08-21T07:31:42Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.44s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.28s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              7218 passed, 9 skipped, 42 deselected, 5 warnings in 270.97s (0:04:30)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 283.9s
```

Final, after the last edit (`R23_FINAL_GATE`):

```
CI GATE — tier=commit  (2026-08-21T08:04:18Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.36s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.32s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.33s
[  PASS] HARD  default-suite              7377 passed, 10 skipped, 42 deselected, 6 warnings in 276.81s (0:04:36)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 289.9s
```

**Reading it.** `default-suite` **7218 → 7377 = +159 added, 0 removed**, which
is exactly the new module (159 passed + 1 skipped; skips 9 → 10 is the one
registered-gap skip in §7.2). `hard-safety` names the **same** baseline id
`nav-instruct-v1-baseline-v4-20260811T070536Z` with the same
`collisions=0 false_arrival=0` and the same follow-bench/walk_with_me rows —
**the frozen nav baseline did not move**, which is the card's stop condition.
`frozen-digest-sentinels` (4 manifests byte-identical) and `release-parity`
(91 packaged assets byte-identical) are the independent proof that
`configs/robot.yaml` and its two packaged mirrors were not edited. `ruff` holds
at the 7-violation baseline with `new 0`.

---

## §3 — The enumeration (the card's primary deliverable)

### 3.1 Method, and why it is not a reading exercise

Three passes, each narrowing the previous, none of them relying on my judgement
about what "reachable" means:

**Pass A — static.** An AST walk over all of `src/parcel_robot` collecting every
call to `float()`/`int()` whose argument subtree contains a `.get()`, a
mapping-ish subscript, or a mapping-ish name. `src/parcel_robot` contains
**2,057** `float()`/`int()` calls in total; **502** are candidates by this
filter. (`scratchpad/coercion_sweep.py`, output `r23/sweep_post.txt`.)

**Pass B — reachability, measured.** `sys.settrace` line tracing while driving
**every** config-FILE loader in the repo — the complete set of `yaml.safe_load`
call sites in `src/parcel_robot` that read configuration:

| Config file | Loader | Driver result |
|---|---|---|
| `configs/robot.yaml` | `config.py:19` `ConfigStore`, full public API | ok |
| `configs/robot.yaml` | `web_panel.build_runtime(use_llm=True)` — the operator `--config` path | ok |
| `configs/navigation/default.yaml` | `navigation/pipeline.py:807` `DirectiveNavigator.from_config` | ok |
| `configs/navigation/models/*.yaml` | `navigation/registry.py:23` | ok |
| `configs/skills/**.yaml` | `skills/catalog.py:30,48` `SkillCatalog.load` | ok |
| `configs/navigation/pose.yaml` | `pose.py:771` | ok |
| realtime.yaml | `realtime/config.py:796` | ok |
| scene-semantics yaml | `scene_semantics.py:184` | ok |
| `configs/robot.acoustic.yaml` | `ConfigStore` | ok |
| yield-policy yaml | `core/yield_policy.py:431` | **driver failed** — `load_personality_policy_config()` needs an explicit path I did not supply; see `does_not_prove` §8 |

Intersecting executed lines with Pass A: **100 of the 502 candidates are
reachable from a real config load.** The other 402 are wire/JSON/protocol
parsers, brain contracts and eval fixtures — not config. (`r23/reachability.py`,
output `r23/reach.json`.)

**Pass C — poison, measured end to end.** For **every** numeric leaf of the two
config files that carry velocity clamps, a scratch copy with that one leaf set
to `nan` / `inf` / `0` / `-1` / `"fast"`, driven through the real loader in a
**forked child** so a half-built runtime can never contaminate the next case:

* `configs/robot.yaml` — **116 numeric leaves × 5 = 580 cases**, through
  `web_panel.build_runtime`. Run before the fix (`r23/before.json`) and after
  (`r23/after.json`).
* `configs/navigation/default.yaml` — **16 leaves × 5 = 80 cases**, through
  `DirectiveNavigator.from_config` (`r23/nav.json`).

Both runs include a control: the shipped bytes, unpoisoned, must load.

**The `"fast"` poison doubles as a reachability oracle.** `float("fast")` raises.
So a key that ACCEPTS the string poison was never coerced on that path — which
is how I distinguish "guarded" from "not consumed here" without guessing. Every
key that accepted the string poison was then re-probed through the loader that
*does* consume it (`r23/offpath_groups.txt`).

### 3.2 The 100 reachable coercions, with verdicts

Verdicts: **NOW GUARDED** (R23 fixed it) · **GUARDED** (already fail-closed,
verified by poison, not by reading) · **BENIGN** (accepts only values that are
legal for that key) · **OPEN** (a real hole, outside this card's OWNS — §7).

| File | Sites | Config keys | Verdict | Evidence |
|---|---:|---|---|---|
| `config.py` (`safety_limits`, `poses`, `wifi_cards`) | **5 → 0 bare** | `motion.max_v*`, `poses.*.joints/duration`, `wifi_cards.*.ros_domain_id` | **NOW GUARDED** | Pass A finds **zero** remaining bare coercions in `config.py` (was 5: lines 26/76/77/78/86). Poison: 5/5 refused for `motion.max_vx`; §4.3 |
| `runtime.py` | 38 | `safety.*`, `spatial_behaviors.*`, `owner_follow.*`, `metrics.*`, `agent.affect.*`, `agent.brain.*`, `battery.*`, `expression.*`, `speech.*`, `motion.smoothing.*` | GUARDED (37) / **OPEN (1)** | 580-case probe. `safety.obstacle_stop_m` etc. refuse NaN via the chained comparison at `runtime.py:1209-1213`; `motion.smoothing.*` via `VelocitySmoother.__post_init__`; `spatial_behaviors.*` via `SpatialBehaviorConfig.__post_init__`. **OPEN: `battery.simulated_percent` (runtime.py:1656)** — §7.3 |
| `navigation/pipeline.py` | 16 | nav `safety.*`, `semantic_search.*`, `progress_watchdog.*`, `terminal_verification.*` | GUARDED (13) / **OPEN (3)** | 80-case nav probe. **OPEN: `safety.max_vx`, `safety.max_vy`, `safety.max_vyaw` (pipeline.py:1298-1300)** — §7.1 |
| `control/factory.py` | 14 | `control.*` | GUARDED (13) / **OPEN (1)** | `ControlLimits.__post_init__` + `ControlTiming.__post_init__` both check `isfinite and > 0`. **OPEN: `control.command_refresh_s` (factory.py:75)** — the one `control.*` key that reaches neither dataclass — §7.4 |
| `providers.py` | 13 | `language_model.*` | GUARDED (11) / **OPEN (2)** | `LlamaCppProvider.__post_init__` range checks. **OPEN: `timeout`, `plan_timeout`** — `self.timeout <= 0` is NaN-blind — §7.5 |
| `skills/schema.py` | 8 | `configs/skills/**.yaml` velocity/gait/rl fields | GUARDED | Skill velocities are re-validated at every dispatch by `SafetySupervisor` (finite check at `safety.py:136`) and at the transport by `sim_ipc._finite_float` |
| `context/models.py` | 2 | `query_context.timeout_ms/max_age_s` | GUARDED | `ContextBuildConfig.from_mapping` explicit `isfinite` + range |
| `navigation/grid_navigator.py` | 2 | map safety margins | GUARDED | 80-case probe: refused |
| `motion.py` | 1 | `motion.rl.control_dt` | **OPEN** | §7.6 |
| `dynamic_prompting.py` | 1 | `prompting.turn_budget_chars` | BENIGN | `int()` raises on NaN/inf natively; a wrong-but-finite budget truncates a prompt, reaches no actuator |
| `core/preemption.py` | 1 | source priority table (not config-derived) | BENIGN | reads a module constant, not a file |
| `instructnav/memory.py` | 1 | injected `min_confidence` | BENIGN | not file-derived on this path |
| `instructnav/siglip.py` | 1 | `PARCEL_SIGLIP2_THRESHOLD` env var | BENIGN | env, not config file; a bad value raises at import |
| `pose.py` | 1 | `configs/navigation/pose.yaml` threshold | GUARDED | probe: refused |
| `navigation/lock_on_verify.py` | 1 | `float(spec.n_stops)` from a validated spec | BENIGN | spec is validated upstream |

**A structural fact worth recording:** every `int()` coercion in the reachable
set is *inherently* non-finite-safe — `int(float("nan"))` raises `ValueError`
and `int(float("inf"))` raises `OverflowError`. The 580-case probe shows this
directly (10 of the refusals are `OverflowError`). `int()` sites therefore never
carry the NaN class of this bug; they carry only the zero/negative class.

### 3.3 The measured `robot.yaml` matrix, summarised

Of 116 numeric leaves, **76 refuse all five poisons**. The 40 that accept at
least one break down as:

* **23 keys — not consumed on the `web_panel --no-llm` path at all** (they
  accept the `"fast"` string, which proves non-coercion): `simulation.*`,
  `control.unitree_sport.*`, `motion.sport.domain_id`, `language_model.*`,
  `speech.echo_guard_scale`, `wifi_cards.*`. Each was re-probed through its real
  consumer (§3.1 Pass C, `r23/offpath_groups.txt`); results folded into §3.2.
* **13 keys — accept `0` only, and `0` is legal for them**:
  `safety.time_to_collision.min_scale` (robot.yaml **ships** `0.0`),
  `expression.beats.lag_compensation_s` (ships `0.0`),
  `agent.affect.*`, `owner_follow.prediction.min_confidence`,
  `control.settled_*_speed`, `motion.shaping.calm_below_arousal`,
  `battery.critical_threshold_percent`. **BENIGN.**
* **2 keys — accept `0`/negative and are seeds**: `duplex.rng_seed`,
  `expression.seed`. **BENIGN.**
* **2 keys — genuinely OPEN**: `battery.simulated_percent`,
  `motion.rl.control_dt`. Plus `control.command_refresh_s` (accepts nan/inf).
  All in §7.

### 3.4 The `robot.yaml` velocity keys, before and after

The row the card is about, measured through the operator launch path:

| Case | Before R23 | After R23 |
|---|---|---|
| `motion.max_vx: .nan` (shipped config otherwise) | refused — **but by `ControlLimits`, at `runtime.py:1117`, AFTER the arbiter was already built with the NaN clamp at `runtime.py:1107`** | refused by `SafetyLimitError` in the loader, naming `motion.max_vx` |
| `motion.max_vx: .nan` **+ `control.max_v*` set** | **ACCEPTED — robot builds, both clamps NaN** (§4.2) | refused, same named error |
| `motion.max_vy: .inf` | refused (same accidental backstop) | refused, named |
| `motion.max_vyaw: 0` | refused (same) | refused, named |
| `motion.max_vx: -1` | refused (same) | refused, named |
| `motion.max_vx: fast` / `true` | refused (`float()` / silently 1.0) | refused, named |

**This is the most important correction I have to make to the audit's write-up.**
The audit says NaN "silently disables the clamp in BOTH enforcement sites"; at
the *code* level that is exactly right and I confirmed it. But on the *shipped*
launch path a lone NaN was already fatal — by accident, downstream, from a
layer that has nothing to do with safety validation and only fires because
`control.max_vx` happens to be absent from `configs/robot.yaml` so
`control/factory.py:430` falls back to the poisoned `SafetyLimits`. Setting the
equally-documented `control.*` keys removes that accident and the finding lands
in full. I pin exactly that composite in
`test_operator_config_that_defeated_the_control_backstop_is_refused`, because
it is the case that would have regressed silently if I had only tested the
easy one.

---

## §4 — Live proof

All local, all in-process, on my own constructed runtime. **The owner's `:8765`
stack was never contacted — not even a read-only GET.** No credential was ever
loaded (`~/.config/parcel/realtime.env` untouched), no hosted model was called,
`~/.config/parcel/realtime.yaml` untouched, the owner's `parcel_memory.sqlite3`
never opened. **Cost: $0.00.**

### 4.1 The control

```
CONTROL — shipped configs/robot.yaml, unchanged:
   SafetyLimits(max_pose_duration=10.0, max_abs_joint_position=3.2, max_vx=1.0, max_vy=0.5, max_vyaw=1.5)
```

Identical to the pre-R23 value. The digest-pinned config passes validation
unchanged and **no effective limit moved** — the card's stop condition is not
triggered.

### 4.2 BEFORE — the fail-open, reproduced (`r23/before_failopen.txt`)

Scratch config: shipped `robot.yaml` + `motion.max_vx: .nan` + `control.max_vx:
1.0, max_vy: 0.5, max_vyaw: 1.5`.

```
BEFORE-FIX: scratch robot.yaml with motion.max_vx=.nan + explicit control.* limits
  store/arbiter/supervisor max_vx = nan nan nan
== ARBITER core/arbiter.py:_limit_violation ==
  vx=         2.0  accepted=True  reason='accepted voice motion'
  vx=        50.0  accepted=True  reason='accepted voice motion'
  vx=1000000000.0  accepted=True  reason='accepted voice motion'
== SUPERVISOR safety.py:_validate_velocity ==
  vx=         2.0  accepted=True  message='Velocity approved: vx=2.00 vy=0.00 vyaw=0.00'
  vx=        50.0  accepted=True  message='Velocity approved: vx=50.00 vy=0.00 vyaw=0.00'
  vx=1000000000.0  accepted=True  message='Velocity approved: vx=1000000000.00 vy=0.00 vyaw=0.00'
```

A billion metres per second, approved by both. That is the finding, not a
paraphrase of it.

### 4.3 AFTER — refused at launch, with a message an operator can act on (`r23/after_failclosed.txt`)

```
REFUSED   motion.max_vx: .nan (with control.* set, the composite that defeated the backstop)
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vx must be finite, got nan. A non-finite value here is not a loose setting, it is an absent one.
REFUSED   motion.max_vx: .nan (shipped config otherwise untouched)
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vx must be finite, got nan. …
REFUSED   motion.max_vy: .inf
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vy must be finite, got inf. …
REFUSED   motion.max_vyaw: 0
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vyaw must be greater than zero, got 0.0. A zero or negative clamp reads as a typo, not as intent.
REFUSED   motion.max_vx: -1
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vx must be greater than zero, got -1.0. …
REFUSED   motion.max_vx: "fast"
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vx must be a number, got 'fast'
REFUSED   motion.max_vx: true
            SafetyLimitError: /tmp/.../robot.yaml: motion.max_vx must be a number, got True
```

The card's live-proof requirement — *"a scratch config with `max_vx: .nan` is
REFUSED at launch with a clear message rather than producing an unclamped
robot"* — is line 1 and line 2 of that output, and the refusal now comes from
the safety loader rather than from a downstream accident.

### 4.4 The planner clamp arithmetic, measured (`r23/nav.json`)

Why the still-open nav finding in §7.1 is not cosmetic — this is what
`pipeline.py:1301` `vx = max(-max_vx, min(max_vx, vx))` actually does:

```
min(nan, 0.5) = nan
max(-nan, min(nan,0.5)) = nan                 -> NaN command emitted
max(-inf, min(inf, 1e9)) = 1000000000.0       -> clamp removed
max(-0.0, min(0.0, 0.5)) = -0.0               -> pins to zero (fail-closed)
max(1.0, min(-1.0, 0.5)) = 1.0                -> NEGATIVE clamp INVERTS
```

The last line is the one to read twice: a `max_vx: -1` misconfiguration does
not clamp to −1 and it does not fail open to 0.5 — it **raises** a 0.5 m/s
request to **1.0 m/s**. The clamp becomes a floor.

---

## §5 — Tests

New module `tests/test_fail_closed_limits.py` — **159 passed, 1 skipped**.
Organised in the order the exposure runs (§1.1). Named tests:

| Test | Pins |
|---|---|
| `test_shipped_robot_yaml_loads_unchanged_with_identical_limits` | the digest-pinned config still loads to `(1.0, 0.5, 1.5)` — the card's stop condition, as an assertion |
| `test_shipped_robot_yaml_poses_and_wifi_cards_still_load` | the sibling coercions stay silent on real data |
| `test_safety_limits_loader_refuses_an_unusable_velocity_limit` | 27 cases (3 axes × 9 shapes): the loader refuses, and the message carries file + dotted key + value |
| `test_safety_limits_loader_names_the_axis_not_just_the_field` | `motion.max_vy`, not `max_vy` |
| `test_pose_loader_refuses_a_non_finite_joint_or_unusable_duration` | the sibling pose coercions |
| `test_wifi_card_domain_id_refuses_a_non_integer` | the sibling `int()` coercion |
| `test_safety_limits_dataclass_refuses_every_unusable_field` | 45 cases (5 fields × 9 shapes) |
| `test_safety_limits_default_construction_still_works` | validation did not break the default |
| `test_is_usable_limit_rejects_everything_that_cannot_clamp` / `…accepts_ordinary_positive_numbers` | the shared predicate |
| `test_arbiter_refuses_when_a_limit_is_not_usable` | 12 cases; comparison-site fail-closed **with validation bypassed** |
| `test_supervisor_refuses_when_a_limit_is_not_usable` | 12 cases, same |
| `test_arbiter_refuses_a_non_finite_command_value` | the other operand of the same comparison |
| `test_supervisor_pose_bound_refuses_when_the_joint_limit_is_not_usable` | the pose bound had the identical hole |
| `test_arbiter_and_supervisor_still_accept_and_still_refuse_normally` | **no threshold moved**, existing messages byte-identical |
| `test_operator_config_with_nan_max_vx_is_refused_at_launch` | the card's live proof, as a test |
| `test_operator_config_that_defeated_the_control_backstop_is_refused` | the composite of §3.4 |
| `test_shipped_config_still_launches` | the other half — a good config is not refused |
| `test_every_documented_fail_closed_loader_refuses_a_malformed_number` | **the doctrine test** — 7 loaders × 4 malformed values |
| `test_documented_fail_closed_loaders_that_R23_owns_also_refuse_infinity` | 7 loaders × `+inf` (1 skip, §7.2) |
| `test_realtime_positive_still_accepts_infinity_registered_gap` | §7.2, pinned not hidden |
| `test_documented_loaders_still_coerce_true_to_one_registered_gap` | §7.7, pinned not hidden |
| `test_r23_owned_loader_rejects_true_unlike_the_registered_gap` | the contrast that makes §7.7 a gap and not a convention |

### 5.1 The doctrine test, and what it actually guarantees

`FAIL_CLOSED_LOADERS` is a registry of the seven loaders that **document
themselves** fail-closed — `realtime/config.py`'s docstring ("Unknown keys
raise, wrong types raise, and negative budgets raise") plus the six
`robot.yaml` blocks whose in-file comments say "Unknown keys fail closed at
startup". Each is paired with one numeric key it owns, and every one must refuse
`nan` / `0` / `-1` / `"soon"`.

**What it guarantees, precisely:** a new numeric key added to one of those seven
loaders *without* validation reddens this test **only if the row's paired key is
changed to it**. It does not automatically cover a brand-new key. That is a real
limit and I state it rather than overclaim: what the test genuinely prevents is
a loader *losing* its validation wholesale, and what it genuinely provides is a
single named place where "which loaders are fail-closed" is written down and
checkable. Marked in §8.

---

## §6 — Seeds — 12, all RED

Harness `r23/seed_r23.py` (house rule R9): snapshot exact bytes → mutate →
run the guarding tests in a **fresh interpreter** → restore → purge every
`src/**/__pycache__` **and** `tests/__pycache__` → assert byte-identity. A
stale `.pyc` from a mutated source passes a byte-identity check while still
being what the interpreter imports, so the purge runs on **both** sides of every
seed and the final canary is a separate fresh process.

| # | Seed | Target | Re-opens | Result |
|---|---|---|---|---|
| S1 | `loader-bare-float` | `config.py` | `safety_limits()` back to the pre-R23 bare `float()` — the audit's original line | **RED** 28 failed |
| S2 | `dataclass-no-post-init` | `safety.py` | `SafetyLimits.__post_init__` gutted | **RED** 46 failed |
| S3 | `nan-inf-accepted-again` | `safety.py` | `validated_limit` stops checking finiteness | **RED** 10 failed |
| S4 | `zero-negative-accepted-again` | `safety.py` | `validated_limit` stops checking positivity | **RED** 10 failed |
| S5 | `non-numeric-accepted-again` | `safety.py` | `validated_limit` stops type-checking (string/bool reach the clamp) | **RED** 21 failed |
| S6 | `loader-finiteness-only` | `config.py` | `ConfigStore._number` stops checking finiteness | **RED** 2 failed |
| S7 | `comparison-fail-open-restored` | `safety.py` | `is_usable_limit` always True — **both** comparison sites become rubber stamps | **RED** 34 failed |
| S8 | `arbiter-original-comparison` | `core/arbiter.py` | `_limit_violation` restored to the exact pre-R23 three-line body | **RED** 13 failed |
| S9 | `supervisor-original-comparison` | `safety.py` | `_validate_velocity` restored to its exact pre-R23 body | **RED** 12 failed |
| S10 | `pose-bound-fail-open` | `safety.py` | the pose joint bound loses its usability check | **RED** 1 failed |
| S11 | `arbiter-command-finiteness` | `core/arbiter.py` | the arbiter stops checking the command side | **RED** 1 failed |
| S12 | `doctrine-test-deleted` | `tests/…` | the doctrine test file deleted outright — the DoD's explicit seed | **RED** collection error |

The DoD asked for ≥8 covering *"NaN accepted again at each site; inf; zero;
negative; the comparison-site fail-open restored; the doctrine test deleted"* —
S3 (nan/inf), S4 (zero/negative), S5 (non-numeric), S7/S8/S9/S10/S11 (five
distinct comparison-site restorations), S12 (deletion), plus S1/S2/S6 on the
two validation layers.

**Integrity:** every `restored=` sha matches its pre-seed snapshot
(`sha_before == sha_after` asserted in-harness for all 12; recorded in
`r23/seeds.json`). Fresh-interpreter canary after all restores:

```
FRESH-INTERPRETER CANARY: OK
CANARY OK SafetyLimits(max_pose_duration=10.0, max_abs_joint_position=3.2, max_vx=1.0, max_vy=0.5, max_vyaw=1.5)
POST-RESTORE tests/test_fail_closed_limits.py: GREEN — 159 passed, 1 skipped
```

No seed came back GREEN; nothing needed re-strengthening.

---

## §7 — Open, owner-gated

Everything here was found by this card's sweep and **not** fixed by it, because
every one lives outside the card's `OWNS` list (`config.py`, `safety.py`,
`core/arbiter.py`, tests, this doc). I did not expand scope on my own authority.
Ordered by how much I would want them fixed.

### 7.1 `configs/navigation/default.yaml` `safety.max_vx/max_vy/max_vyaw` is the same bug, still open — **highest**

`navigation/pipeline.py:1298-1300` reads its own velocity clamp with a bare
`float()` and applies it at :1301-1305. The 80-case nav probe: `safety.max_vx`
and `safety.max_vy` accept **all four** of nan/inf/zero/negative;
`safety.max_vyaw` accepts inf. Effects measured in §4.4: NaN emits a NaN
command, inf removes the clamp, **negative inverts the clamp into a floor that
raises speed**. Today the downstream layers catch the NaN case
(`MotionIntent.__post_init__` refuses non-finite, and R23's arbiter now does
too) and the inf case is re-bounded by `robot.yaml`'s `SafetyLimits` at the
arbiter — so this is defence-in-depth loss, not an open actuation path on the
shipped config. **Fix:** route :1298-1300 through `safety.is_usable_limit` /
`validated_limit`, which now exist and are importable. Owner call because
`pipeline.py` is a nav-baseline-bearing file.

### 7.2 `realtime/config.py::_positive` accepts `+inf` — **registered, MUST NOT TOUCH**

`_positive` (line 441) tests `not number > 0.0`, which refuses NaN (because
`nan > 0` is False) but **accepts `+inf`**. Measured:
`realtime_config_from_mapping({"stall_timeout_s": inf})` returns `inf`. In that
file `+inf` means an infinite stall timeout, an unbounded session, a microphone
that never idle-closes, and an unlimited `monthly_budget_usd` — which compounds
the audit's separate finding that the arming gate never reads the budget at all
(R25). The realtime package is explicitly MUST NOT TOUCH for this card, so I
**pinned the behaviour instead of changing it**:
`test_realtime_positive_still_accepts_infinity_registered_gap`, with the
one-line fix in its docstring (`if not math.isfinite(number) or number <= 0.0:`)
and the instruction to delete the test and unskip
`test_documented_fail_closed_loaders_that_R23_owns_also_refuse_infinity` when it
lands. I am aware a test that asserts a bug persists is unusual; the alternative
was to omit `inf` from the doctrine set silently, and a registered gap that
reddens when fixed is more honest than a quiet exclusion.

### 7.3 `battery.simulated_percent` accepts NaN — the guarded neighbour makes it worse

`runtime.py:1656`. The threshold pair immediately below it *is* checked
(`runtime.py:1661`, and its chained comparison refuses NaN correctly), but the
**percent itself** is not. With `simulated_percent: .nan`, `percent <= critical`
and `percent <= low` are both False forever, so the `battery_critical`
procedures — `ReturnToSafePose` — become permanently unreachable. That is the
exact failure the block's own config comment says it exists to prevent
("keeps the brain's battery_critical procedures reachable and testable").
Measured: accepts nan/inf/zero/negative, refuses only the string.

### 7.4 `control.command_refresh_s` accepts NaN/inf

`control/factory.py:75`. It is the one `control.*` key that reaches neither
`ControlLimits.__post_init__` nor `ControlTiming.__post_init__` — both of which
check `isfinite and > 0` for everything they do own. Consequence is a broken
command re-send period on the vendor path.

### 7.5 `language_model.timeout` / `plan_timeout` accept NaN and inf

`providers.py:130,138`. `LlamaCppProvider.__post_init__` tests
`self.timeout <= 0`, which is False for NaN. A NaN HTTP timeout is not a safety
path, but it is the same one-character class of bug and it is in a file that
already validates ten neighbouring keys properly.

### 7.6 `motion.rl.control_dt` accepts NaN/inf/zero/negative

`motion.py:213`. Feeds the RL policy step. Zero in particular is a division
hazard.

### 7.7 Five documented fail-closed loaders coerce YAML `true` to `1.0`

Measured (`r23/bool_gap.txt`): `safety.time_to_collision.brake_s`,
`motion.shaping.linear_max_accel`, `owner_follow.prediction.lead_s`,
`owner_search.sensor_radius_m`, `duplex.frame_hz` — and also
`grid_v1 dynamic_agents.weight`, `spatial_behaviors.step_length_m`,
`authority SafetyEnvelope.decel_max_mps2`. YAML parses `brake_s: yes` as a
bool, `float(True)` is `1.0`, and the value is accepted. `realtime/config.py`
and R23's own loader both reject bools explicitly; these do not. Pinned by
`test_documented_loaders_still_coerce_true_to_one_registered_gap` (5 rows, the
ones inside the doctrine registry) so the gap is visible and reddens when fixed.
`owner_search.max_search_s` refuses `True` — but only by an unrelated
cross-field invariant (`goto_timeout_s >= max_search_s`), not by a type check,
so it is luck rather than design.

### 7.8 Two default triples that disagree — recorded, not touched

`ConfigStore.safety_limits()` falls back to `(0.6, 0.4, 1.0)`;
`SafetyLimits`'s dataclass defaults are `(1.0, 0.5, 1.5)`. So a config with a
`motion:` section but no `max_vx` gets 0.6, while `SafetyLimits()` gets 1.0.
Pre-existing and harmless on the shipped config (which sets all three
explicitly), but it is a threshold difference and the card forbids threshold
changes, so it is recorded here rather than harmonised.

---

## §8 — `does_not_prove`

* **The 100-reachable figure is a floor, not a ceiling.** It is the union of
  what ten drivers executed. One driver failed outright
  (`core/yield_policy.py`'s loader needs an explicit path I did not supply), and
  branch-guarded coercions inside consumers I did construct — a vendor
  controller, a disabled backend, a code path behind a flag that is off in the
  shipped config — were not executed and are therefore counted as unreached.
  The five OPEN findings in §7 are ones I *did* reach; there may be more behind
  flags I did not turn on.
* **The 580-case and 80-case probes poison ONE leaf at a time.** They do not
  explore interactions between two poisoned keys. The one composite that
  mattered here (§3.4) I constructed by hand after reading the traceback, not by
  search — a systematic pair sweep would be 116² and I did not run it.
* **"Refused at launch" is proven for `web_panel.build_runtime`.** `cli.py`,
  `ros_node.py`, `sim.py` and `unitree_control.py` also call
  `store.safety_limits()` and therefore inherit the loader refusal by
  construction, but I exercised only the `web_panel` path end to end.
* **Nothing here reaches a joint.** Every "approved"/"refused" in §4 is a
  dispatch-record verdict on the kinematic rig, exactly as the audit's "executed
  ≠ performed" note says. This card changes what the software *permits*; it does
  not demonstrate a physical outcome.
* **The doctrine test's coverage is bounded** — see §5.1. It catches a loader
  losing its validation; it does not automatically catch a brand-new key added
  beside a validated one.
* **`is_usable_limit` is a predicate about clamps, not about correctness.** It
  cannot tell a plausible-but-wrong `max_vx: 5.0` from a right one. Nothing in
  R23 defends against a limit that is finite, positive and simply too large;
  that is what the commissioning band and `ControlLimits` are for.
* **The registered-gap tests (§7.2, §7.7) assert current behaviour, including
  behaviour that is wrong.** If someone fixes those loaders, these tests fail —
  by design, to force the register to be updated — but a reader who does not
  read the docstring could mistake them for endorsement.

---

## §9 — Deviations

1. **The card says "fix every safety-relevant one" (work item 2); I fixed only
   the ones inside `OWNS`.** Five reachable holes (§7.1, §7.3–§7.6) and one
   cross-cutting class (§7.7) are real and unfixed. The card's `OWNS` list is
   `config.py`, `safety.py`, `core/arbiter.py`, tests and this doc, and §7.1
   in particular sits in `navigation/pipeline.py`, a file that bears the frozen
   nav baseline. I judged that touching it on my own authority was the larger
   risk, and registered each with its file, line, measured behaviour and
   one-line fix instead. **This is the deviation most worth the owner's
   attention.**
2. **I extended validation to two sibling coercions in `config.py` that the
   card mentions only generically** — `poses()` joint/duration and
   `wifi_cards()` `ros_domain_id`. Both are inside `OWNS`; both are covered by
   the "any sibling numeric safety key that currently coerces bare" clause; both
   are proven not to change behaviour on the shipped config
   (`test_shipped_robot_yaml_poses_and_wifi_cards_still_load`).
3. **I added a fail-closed check to the SafetySupervisor's *pose* bound**, not
   just the velocity bound. The card names velocity/accel; the pose joint bound
   turned out to have the identical `abs(j) > nan` hole two lines away and is in
   the same owned file. Seeded as S10.
4. **The chain baseline in my brief was "7164 passed".** The tree I entered had
   R22's landed work and measured **7218** on my own pre-edit gate run (§2). I
   report against 7218 because that is what I actually measured; the +54 is
   R22's, documented in `scrum/20260821/task_1/R22_STATUS.md`.
5. **`bool` and `+inf` were removed from the shared doctrine poison set** and
   moved to explicit registered-gap tests (§7.2, §7.7). Keeping them in would
   have made the doctrine test red for loaders I am forbidden to touch.

---

## §10 — Artefacts

Scratchpad root:
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/`
— **`/tmp` evaporates**; the audit flags this and it applies here. Everything
load-bearing is quoted inline above so this document stands alone.

| Artefact | What it is |
|---|---|
| `coercion_sweep.py`, `r23/sweep_post.txt` | Pass A — AST sweep, 502 candidates on the final tree |
| `r23/reachability.py`, `r23/reach.json` | Pass B — line trace over 10 config loaders, 100 reachable |
| `r23/probe_config_surface.py` | Pass C driver — `robot.yaml`, 116 leaves × 5, forked per case |
| `r23/before.json`, `r23/after.json` | 580 cases each, pre- and post-fix |
| `r23/probe_nav_surface.py`, `r23/nav.json` | 80 cases over `configs/navigation/default.yaml` |
| `r23/offpath_groups.txt` | the 23 keys not consumed on the panel path, re-probed through their real consumers |
| `r23/bool_gap.txt` | the §7.7 bool/inf matrix across 11 loaders |
| `r23/before_failopen.txt`, `r23/after_failclosed.txt` | §4.2 / §4.3 live evidence |
| `r23/seed_r23.py`, `r23/seeds.json` | the 12-seed harness and its record |
| `r23/gate_baseline.txt`, `r23/gate_1.txt`, `r23/gate_final.txt` | gate runs |

**Repo-resident** (these survive): `src/parcel_robot/safety.py`,
`src/parcel_robot/config.py`, `src/parcel_robot/core/arbiter.py`,
`tests/test_fail_closed_limits.py`, and this document.


## Audit correction — Fable, 2026-08-21

§5/§7.2 cite `test_realtime_positive_still_accepts_the_documented_examples`, which does not exist in the tree; the module's suite runs 160 passed without it. The protective property those sections describe is real and covered by the `_positive` validation tests; only the cited name is phantom. Corrected by the auditor after verifier finding.
