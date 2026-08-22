# P0-A — prototype profile & launcher · STATUS

**Executor:** Claude Opus · **Verifier:** Fable · **Card:** `README.md` · **Board:** `../TASK_BOARD.md`
**Date:** 2026-08-22

## Headline

`configs/robot.prototype.yaml` + `configs/realtime.prototype.yaml.example` exist,
`scripts/launch_stack.sh --prototype` selects both, and `ConfigStore` deep-merges
`configs/robot.<profile>.yaml` on top of the shipped file when `PARCEL_PROFILE`
(or `--profile NAME`) names one — refusing any overlay key path the base does
not define, so a misspelled key is a refusal and not a silent shipped default.
The two camera GROUNDING switches (`camera_ingress.enabled` /
`PARCEL_CAMERA_INGRESS`, and `perception.camera_ingress`) now resolve together
instead of refusing each other. **They are not one flag: the C-1 stream still
follows the config key alone**, so the env alias moves grounding and not the
stream — corrected under verification; scope stated below and pinned by a test.
**With no profile the resolved config is byte-identical to before this card
(sha256 `0eebb529…` before and after) and `configs/robot.yaml` still hashes to the
digest the embodied-plan manifest locks.**

**One deliverable is NOT delivered:** `safety.person_stop_m: 0.7` is impossible
from a config file — the safety authority floors it at 1.2 and a 0.7 overlay
would stop the prototype from booting. Blocker recorded below and pinned as a
test rather than only as prose.

## What changed

| File | + / − | Note |
|---|---|---|
| `src/parcel_robot/config.py` | +243 / −3 | profile resolution, deep merge, overlay load, **overlay key walk** |
| `scripts/launch_stack.sh` | +83 / −2 | `--prototype`, `--profile NAME`, `--dry-run`, realtime-lane selection |
| `src/parcel_robot/runtime.py` | +54 / −23 | **only** the two camera-flag regions (currently 1511–1539 and 9461–9500) |
| `tests/test_c1_camera_stream.py` | +31 / −8 | 2 tests re-pinned; **declared deviation**, see below |
| `configs/robot.prototype.yaml` | +156 (new) | the overlay |
| `configs/realtime.prototype.yaml.example` | +486 (new) | the prototype voice lane |
| `tests/test_prototype_profile.py` | +766 (new) | 42 tests |

`runtime.py` and `test_c1_camera_stream.py` are edited concurrently by other
cards (and `test_c1_camera_stream.py` is untracked), so `git diff --stat` against
HEAD is not attributable. Their numbers above come from reconstructing the
pre-P0-A text of exactly my two hunks per file and diffing that:

```
$ git diff --numstat -- src/parcel_robot/config.py scripts/launch_stack.sh
83      2       scripts/launch_stack.sh
243     3       src/parcel_robot/config.py

$ git diff --no-index --numstat <reconstructed>/runtime.py src/parcel_robot/runtime.py
54      23      runtime.py
$ git diff --no-index --numstat <reconstructed>/test_c1_camera_stream.py tests/test_c1_camera_stream.py
31      8       test_c1_camera_stream.py
```

Every edit to an existing file was an exact-match single-occurrence replacement
(the patch scripts refuse if a pattern matches 0 or >1 times) applied against the
file as re-read at that moment. No `git add/commit/stash/checkout/reset/restore`
was run. No file outside the table was written.

### The overlay, in full

`configs/robot.prototype.yaml` carries exactly two effective sections; the rest of
the file is the reasoning, including a long comment explaining the person-standoff
blocker and one explaining why voice identity is not in this file.

```yaml
perception:
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queries: [person, chair, table, door, couch, laptop, cup, backpack]

agent:
  affect:
    minimum_confidence: 0.5
```

### The prototype voice lane

`configs/realtime.prototype.yaml.example` is a copy of
`configs/realtime.yaml.example` — regenerated from it *after* P0-B landed
`hosted_affect`, `proactive_motion_tools` and `unknown_place`, so the two files'
key sets are currently identical — with five marked departures and every
explanatory comment kept verbatim:

| key | shipped | prototype |
|---|---|---|
| `model` | `gpt-realtime-2.1-mini` | `gpt-realtime-2.1` |
| `idle_close_after_s` | `600.0` | `0` (never; P0-B's spelling) |
| `whisperer.max_updates_per_minute` | `2` | `6` |
| `whisperer.min_gap_s` | `15.0` | `4.0` |
| `voice_identity.enabled` | `true` | `false`, with the `tools/enroll_owner_voice.py` command in the comment |

## Fix pass after Fable's verification (2026-08-22)

Two deliverables were under-delivered against this card. Both are fixed here;
neither changes the flag-off path (sha unchanged, above).

**1. Deliverable 4 — post-merge validation now covers every section.** The
merge had no opinion about spelling, so `agent.affect.minimum_confidenc: 0.5`
merged cleanly, added a key nothing reads, left the threshold at the shipped
0.75, and booted. Only wrong *types* and `perception.camera_ingress*` typos
refused. `config.check_overlay_keys` now walks the overlay against the base
mapping recursively before the merge and refuses any key path the base does not
define, naming the dotted path and offering a `difflib` "did you mean". Two
explicit exemptions, both listed in code with reasons:

* `OVERLAY_FREEFORM_PATHS` = `{poses, wifi_cards, prompting.user_profile}` —
  children are DATA (pose names, card names, owner facts), not schema.
* `OVERLAY_INTRODUCIBLE_KEYS` = the `perception.camera_ingress*` family and the
  legacy `camera_ingress.enabled` section — real, separately-validated keys that
  the SHA-locked base omits and therefore cannot grow. This set is the escape
  hatch the refusal message names.

The existing type/value checks are untouched; the two layers catch different
mistakes. Cost, stated plainly: an overlay can no longer set an optional key
that has a code default and is absent from `configs/robot.yaml` (e.g.
`owner_follow.yield_aside.enabled`) without an `OVERLAY_INTRODUCIBLE_KEYS` entry.
That is the deliberate trade for catching `minimum_confidenc`.

Seeded RED — key walk replaced by `pass`, suite re-run, file restored (sha
`cfbca768…` verified identical before and after):

```
FAILED …test_a_misspelled_overlay_key_refuses…[nested-scalar-typo]     agent.affect.minimum_confidenc
FAILED …test_a_misspelled_overlay_key_refuses…[section-key-typo]       safety.person_stop_mm
FAILED …test_a_misspelled_overlay_key_refuses…[top-level-section-typo] perceptoin
3 failed, 38 passed
```

**2. Deliverable 3 — the "one flag" claim was too strong, and is withdrawn.**
The env alias is one-directional: `_attach_configured_camera_ingress`
(runtime.py ~9688, **outside this card's region**) gates the C-1 stream on
`self._camera_stream_config.enabled` alone and never consults
`_camera_ingress_enabled()`. So:

| | grounding | stream |
|---|---|---|
| `PARCEL_CAMERA_INGRESS=1`, no `perception.camera_ingress` | ON | **off** |
| `PARCEL_CAMERA_INGRESS=0`, `perception.camera_ingress: true` | OFF | **on** |

What card P0-A actually delivered is narrower and is now stated that way
everywhere: **the two GROUNDING spellings resolve together instead of refusing
each other; the stream follows the config key.** Reworded in the
`_camera_ingress_enabled` docstring, in `configs/robot.prototype.yaml`'s camera
comment, and in this doc's headline. Pinned by
`test_the_env_alias_reaches_grounding_only_not_the_stream`, which asserts both
rows of the table above, so the docs cannot drift back up. Setting the config
key — which is what the profile does — moves both consumers; only the env var is
partial. Finishing the collapse is a one-line change at the attach site and is
handed off below.

**3. Documentation corrections.** Hunk line ranges refreshed (1511–1539 /
9461–9500); the `separators=(",", ":")` of the flag-off digest is now stated;
`configs/realtime.prototype.yaml.example`'s header said "four values changed"
while carrying eight (the verifier merged P0-B's prototype values —
`unknown_place: ask`, `proactive_motion_tools: [play_gesture, set_pose]`,
`hosted_affect: true`) and now lists all eight, attributing those three to P0-B.
The list is asserted complete: the test diffs the two example files over the key
paths both carry and requires every differing path to appear in the header.

## Resolved values under `--prototype`

```
$ PARCEL_PROFILE=prototype .parcel/bin/python -c "…"
profile        : prototype | overlay: configs/robot.prototype.yaml
plain  sha256  : 0eebb5290e20fed7dab8f0fcb7b0829871fcbe173b60ed20a4b296df83ff94dc
proto  sha256  : ad1bf61da279fa521151458370037a5092ad0ec50b32e98d7c277c4e6a380898
person_stop_m  : 1.2  (plain 1.2)          <- NOT 0.7; see the blocker
owner_keepout  : 1.75                       (derived: person_stop + 0.55)
affect min conf: 0.5  (plain 0.75)
camera_ingress : True | rate 2.0 | queries ['person','chair','table','door','couch','laptop','cup','backpack']
top-level sections changed by the overlay: ['agent', 'perception']
```

Through a live runtime built on the real overlay
(`test_the_shipped_prototype_overlay_boots_a_runtime`):

| thing | value under `--prototype` |
|---|---|
| `runtime.person_stop_m` | `1.2` |
| `runtime.follow.config.owner_keepout_m` | `1.75` (derived, not copied) |
| `runtime.follow.config.desired_distance_m` | `1.85` (derived, not copied) |
| `runtime._camera_stream_enabled` | `True` |
| `runtime._camera_ingress_enabled()` | `True` |
| `runtime._affect_minimum_confidence` | `0.5` |
| voice-identity gate | `false` (in the realtime file, not this one) |

## How verified

### The card's gates

```
$ .parcel/bin/python -m pytest -q tests/test_prototype_profile.py tests/test_runtime.py \
      tests/test_c1_camera_stream.py tests/test_runtime_activation.py \
      tests/test_authority_config_drift.py tests/test_release_parity.py \
      tests/test_release_parity_wheel.py tests/test_fail_closed_limits.py \
      tests/test_runtime_assets.py
359 passed, 4 skipped, 3 warnings in 11.47s

$ .parcel/bin/python -m pytest -q tests/test_prototype_profile.py
42 passed

$ .parcel/bin/ruff check src/parcel_robot/config.py src/parcel_robot/runtime.py \
      tests/test_prototype_profile.py tests/test_c1_camera_stream.py
All checks passed!

$ bash -n scripts/launch_stack.sh          # exit 0
$ .parcel/bin/python tools/sync_runtime_assets.py --check
release parity OK: 91 packaged file(s) match source
```

The card also names `tests/test_config*.py`: **no such file exists** in this tree
(`ls tests/ | grep '^test_config'` is empty). The nearest real coverage —
`test_fail_closed_limits.py`, `test_authority_config_drift.py`,
`test_runtime_assets.py` — was run instead and is in the set above.

Also run: `tests/test_agent.py tests/test_dynamic_prompting.py
tests/test_owner_store_isolation.py tests/test_prod_default_path.py
tests/test_unitree_control.py tests/test_move1_patrol.py
tests/test_e2_safety_wiring.py tests/test_c3_cutover.py tests/test_c2_online_map.py`
— **255 passed** (every remaining test file that mentions `ConfigStore`,
`camera_ingress`, `launch_stack` or `PARCEL_PROFILE`).

### Flag-off proof (byte identity)

The digest is over the **compact, key-sorted** JSON dump — separators matter to
the bytes, so they are stated rather than defaulted:

```
$ .parcel/bin/python -c "
import hashlib, json
from parcel_robot.config import ConfigStore
blob = json.dumps(ConfigStore('configs/robot.yaml', profile='').data,
                  sort_keys=True, separators=(',', ':')).encode()
print(hashlib.sha256(blob).hexdigest(), len(blob))"

before this card : 0eebb5290e20fed7dab8f0fcb7b0829871fcbe173b60ed20a4b296df83ff94dc  5274 bytes
after  this card : 0eebb5290e20fed7dab8f0fcb7b0829871fcbe173b60ed20a4b296df83ff94dc
after  the key-walk fix pass : 0eebb5290e20fed7dab8f0fcb7b0829871fcbe173b60ed20a4b296df83ff94dc
```

Pinned as a test three ways: the resolved mapping equals `yaml.safe_load` of the
file (`test_no_profile_resolves_the_shipped_file_and_nothing_else`), an ambient
`PARCEL_PROFILE` in the shell is ignorable by the caller
(`test_an_ambient_profile_env_is_ignorable_by_the_caller`), and
`configs/robot.yaml`'s own sha256 still equals the one
`evals/companion/embodied_plan_v1/manifest.json` locks
(`test_the_overlay_did_not_move_the_sha_locked_shipped_config` — it reads the
existing lock rather than adding a new digest).

### Seeded RED — every new guard

`config.py` was mutated in place, the suite re-run, and the file restored (sha256
verified identical before and after: `ecb57a05…`):

| mutation | result |
|---|---|
| missing-overlay refusal → `return {}` | `1 failed` — `test_a_named_profile_with_no_file_refuses_by_name` |
| profile-name path guard removed | `5 failed` — all `test_a_profile_may_not_name_a_path[…]` |
| explicit `profile=""` ignored (env leaks into the default path) | `11 failed`, including the byte-identity test |

Launcher guard, seeded RED on a scratch copy (`~/.cache/parcel-p0-a/redroot/`,
never in the repo): with `[[ -f "$ROBOT_OVERLAY" ]] || die` deleted,
`--profile nope --dry-run` prints `robot_overlay=…/robot.nope.yaml` and exits **0**;
the real launcher exits **1** with `--profile nope selected but …/configs/robot.nope.yaml
does not exist` (pinned by `test_launcher_refuses_a_profile_it_cannot_find`).

The camera collapse is a REMOVAL, not a guard, so its RED is the inverse: the
pre-existing `test_c1_and_the_legacy_b4_authority_flag_cannot_both_be_on` passed
before this card and would fail now, which is exactly why it was rewritten (see
deviations). The removed `raise ValueError("… cannot both be on …")` is visible in
the reconstructed diff.

### The launcher, exercised end to end

`--dry-run` was added (inside OWNS) so the launcher's own flag handling is
testable without starting a service or reading a credential. Four subprocess
tests drive a **throwaway `$ROOT`** (a tmp dir holding a copy of the script, a
`configs/`, and a symlink to `.parcel`), so no test touches the real checkout:

```
$ bash scripts/launch_stack.sh --dry-run                 # no flag
profile=-  robot_overlay=-  realtime_config=…/configs/realtime.yaml  realtime_config_source=default

$ bash scripts/launch_stack.sh --prototype --dry-run     # with the file present
profile=prototype  robot_overlay=…/configs/robot.prototype.yaml
realtime_config=…/configs/realtime.prototype.yaml  realtime_config_source=profile

$ bash scripts/launch_stack.sh --profile prototype --dry-run   # realtime file absent
Note: …/configs/realtime.prototype.yaml is absent, so the hosted lane falls back to …/configs/realtime.yaml.
      For the prototype voice lane: cp …/configs/realtime.prototype.yaml.example …/configs/realtime.prototype.yaml
```

### Release parity, re-checked at the end of the fix pass

`tools/sync_runtime_assets.py --check` was clean (91 files) when this card's
work landed and is **not** clean now:

```
release parity FAILED (4 problem(s)):
  MANIFEST.json / prompts/personalities/{calm_guardian,gentle_companion,playful_companion}.yaml
```

Those are `prompts/**`, which this card never touched (its only new config,
`configs/robot.prototype.yaml`, is not in the mirror's INCLUDE globs at all).
Deliberately NOT resolved here: running `--write` would sweep another card's
un-synced prompt edits into the packaged tree under this card's name.

### Full suite

`.parcel/bin/python -m pytest -q tests/` on the shared tree (short `TMPDIR`;
a long one fails `AF_UNIX` path-length tests unrelated to any card):

```
9 failed, 8092 passed, 27 skipped, 2 xfailed, 17 errors in 398.89s
```

Attribution of all 26, none of them this card's:

| what | whose |
|---|---|
| 17 × `test_voice_nav_e2e.py` setup errors | pre-existing: card R27's memory guard refuses `configs/robot.yaml`'s owner store under pytest without `PARCEL_MEMORY_PATH`. Unrelated to profiles; the no-profile resolved config is byte-identical. |
| `test_p0d_navigation_unblocks.py` × 2, `test_c3_cutover.py::test_E2_…` | P0-D, in flight |
| `test_realtime_idle_hangup.py::…[0]` / `[0.0]` | P0-B, in flight (they made `0` legal) |
| `test_prototype_profile.py::…carries_its_four_changes` | **mine, and already fixed** — the run started before the prototype voice lane was regenerated against P0-B's updated example; the test is now `…carries_its_departures` and passes |
| `test_c1_camera_stream.py::test_the_control_loop_calls_no_producer_method_for_the_camera`, `test_nominal_stop_wiring.py`, `test_barn_experiment_harness.py` | transient: source-inspecting (`inspect.getsource` + AST) tests that read `runtime.py` while another executor was writing it. All three **pass on re-run** — `135 passed` for those files plus `test_prototype_profile.py` together. |

An earlier full run showed the same shape plus
`test_runtime_activation.py::test_start_navigation_sets_camera_query`
(`[('lamppost',)] == ['lamppost']`) — P0-D's `set_query` person-drop changed the
argument from a string to a tuple. Recorded here only so it is not mistaken for
this card's, since it lives in a file this card also reads.

A whole-tree gate is Fable's, per the board.

## What this does not prove

* **No camera actually ran.** Turning the flag on is the runtime's consent; the
  stream still needs `_attach_configured_camera_ingress`, an EGL-capable
  same-process simulator and a detector. Nothing here measures a frame, a
  detection, a rate or a latency, and the eight-phrase indoor query batch has not
  been run against OWLv2 — it is validated as config, not as perception.
* **No live voice session.** `configs/realtime.prototype.yaml.example` is
  validated by `realtime_config_from_mapping` and by nothing else. `model:
  gpt-realtime-2.1` has not been talked to; every latency and cost figure in the
  status docs was measured on the mini, so nothing in this file is backed by a
  measurement. `idle_close_after_s: 0` depends on P0-B's change and is verified
  only against the loader as it stands right now.
* **`--prototype` was never launched.** The launcher is proved by `bash -n` and
  by `--dry-run` subprocesses against a fake root. No stack, sim, panel or
  hosted lane was started (the board forbids disturbing the live MOVE-1 sim, and
  a real launch needs a credential).
* **The affect change is a threshold, not an outcome.** 0.75 → 0.50 makes
  proposals reachable; whether the companion reads as more present is unmeasured.
* **Nothing about a packaged install.** The profile works from a checkout only —
  see the handoff.
* **Concurrency.** The tree was being written by four other executors throughout.
  Every number here was taken from the tree as it stood at the moment of the
  command shown.

## Blocker (not deliverable from this card)

**`safety.person_stop_m: 0.7` cannot be set by a config overlay.**

```
parcel_robot.authority.SafetyEnvelope.person_social_zone_m = 1.2
  ⇒ DEFAULT_SAFETY_ENVELOPE.person_stop(0.0) == 1.2
navigation/reactive_safety.py:125 refuses any configured person_stop_m below it:
  ValueError: reactive person_stop_m must not undercut SafetyEnvelope.person_stop(0.0)
```

`RobotRuntime.__init__` builds `ReactiveSafetyPolicy` from the merged config
(runtime.py:1646), so an overlay carrying 0.7 does not relax the robot — **it
stops the prototype from booting at all.** Lowering the floor means editing
`authority.py` or `reactive_safety.py`: both are the physical-safety core the
board keeps untouched, both are outside this card's OWNS, and the value-change
protocol wants a paired run. The overlay therefore carries no `safety:` block,
carries a comment saying all of this, and
`test_indoor_person_standoff_is_floored_by_the_safety_authority` pins the refusal
so the blocker is greppable as code. The derived follow numbers (1.75 / 1.85)
still re-derive at construction and will move on their own the day the floor does.

## Deviations from OWNS (declared)

1. **`tests/test_c1_camera_stream.py` (+31/−8, 2 tests).** Not in OWNS. Card
   deliverable 3 retires a refusal that this file pinned, so the file had to
   change or the deliverable could not land.
   `test_c1_and_the_legacy_b4_authority_flag_cannot_both_be_on` →
   `…_are_one_switch_now` (both spellings resolve on, no raise), and
   `test_the_stream_never_touches_navigation_grounding` now asserts
   `_camera_ingress_enabled() is True` **and** `_camera_ingress is None` — the
   property it was always about (no attached ingress ⇒ the oracle read is
   untouched) is unchanged and still asserted. No other test in that file moved.
2. **Voice identity is in the realtime file, not the robot overlay.** The card
   lists it under deliverable 1, but the key the runtime reads at
   runtime.py:6633-6660 is `voice_identity.enabled` in the **realtime** config
   (`parcel_robot.realtime.config`), a different file with a different loader.
   `ConfigStore` silently ignores unrecognised top-level keys, so a
   `voice_identity:` block in `configs/robot.prototype.yaml` would look like a
   setting and be nothing at all. It is set (`false`) in
   `configs/realtime.prototype.yaml.example` with the enroll command; the robot
   overlay carries a comment saying where it went and why.
3. **`idle_close_after_s: 0`, not "the largest value the validator accepts".**
   The card allowed for this ("P0-B may later add `0 = never`"); P0-B landed it
   during this wave and the shipped example now documents it, so the prototype
   uses the honest spelling instead of a big finite number. If P0-B's change is
   reverted, this file stops loading — the coupling is deliberate and named here.
4. **`--profile prototype` is not a new argparse flag.** `resolve_profile(argv)`
   in `config.py` parses `--profile NAME` / `--profile=NAME` and is unit-tested,
   and the launcher accepts both spellings — but `parcel_robot.web_panel` and
   `parcel_robot.cli` were NOT given the flag, because they are not in OWNS and
   `argparse` would reject an unknown option before `ConfigStore` is reached. The
   transport to those processes is the exported `PARCEL_PROFILE`, which is how one
   launcher flag reaches the panel and the sim at once. `python -m
   parcel_robot.web_panel --profile prototype` therefore still errors; use
   `PARCEL_PROFILE=prototype python -m parcel_robot.web_panel …`.
5. **`--dry-run` added to the launcher.** Inside OWNS but beyond the card. Without
   it the card's own test suggestion collapses to "`bash -n` only"; with it the
   flag handling, the overlay refusal and the realtime-lane selection are all
   exercised as real subprocesses against a throwaway root.
6. **Nothing was regenerated in `runtime_assets/`.** Deliverable 6 is conditional
   and its condition is false: `tools/sync_runtime_assets.py`'s INCLUDE list names
   `configs/robot.yaml` as a literal, not a glob, so `configs/robot.prototype.yaml`
   is not mirrored and `--check` is clean (91 files). `MANIFEST.json` was not
   hand-edited and the sync tool was not modified (it is not in OWNS). See handoff.
7. **The prototype realtime example was regenerated mid-card** after P0-B changed
   `configs/realtime.yaml.example`, so it currently carries P0-B's new keys at
   their shipped defaults. `configs/realtime.yaml.example` itself was never
   written by this card (read only).

## Handoffs

* **Card P1-E (`scrum/20260822/task_12`, another session) — the indoor person
  standoff.** Fable worked out the minimal change during verification and it is
  recorded here verbatim so P1-E does not have to rediscover it. **P0-A did not
  make it.**
  * add `envelope: SafetyEnvelope = DEFAULT_SAFETY_ENVELOPE` to
    `ReactiveSafetyPolicy`;
  * use `self.envelope` in the three `__post_init__` floor checks
    (`reactive_safety.py` ~110, ~125);
  * pass `envelope=replace(DEFAULT_SAFETY_ENVELOPE, **safety_config.get("envelope", {}))`
    at `runtime.py` ~1657, via `SafetyEnvelope.from_mapping`;
  * the overlay then needs `safety.envelope.person_social_zone_m: 0.7`,
    `safety.person_stop_m: 0.7` **and** `owner_follow.owner_keepout_m: 1.25`,
    because `follow.py:51,60` derive from `DEFAULT_SAFETY_ENVELOPE` at import
    time and `robot.yaml:62` carries a literal `1.75`.

  Note for whoever lands it: the overlay's new key paths
  (`safety.envelope.person_social_zone_m`) do not exist in `configs/robot.yaml`,
  so they need an `OVERLAY_INTRODUCIBLE_KEYS` entry or a base that defines them —
  the key walk added in this card's fix pass will otherwise refuse the overlay,
  which is the guard working.

  Until then the prototype's person clearance is the production 1.2 m.
* **Release / packaging:** a wheel install cannot use `--prototype`.
  `tools/sync_runtime_assets.py` INCLUDE needs `configs/robot.prototype.yaml`
  (and, if the lane is to ship, the realtime example) for the overlay to resolve
  next to the packaged `runtime_assets/configs/robot.yaml`. Left undone on
  purpose: a prototype dev profile inside a released wheel is a product decision,
  and the sync tool is not in this card's OWNS.
* **P0-B:** `configs/realtime.prototype.yaml.example` is a manual copy of
  `configs/realtime.yaml.example`. Their key sets match as of this writing and
  `test_realtime_prototype_example_validates_and_carries_its_departures` asserts
  the prototype invents no key — but it deliberately does **not** assert the
  reverse, so a key you add later will not fail a gate and will not appear in the
  prototype file. Re-copy it when the production example changes.
* **P0-D / whoever measures the prototype perception stack:**
  `configs/navigation/prototype.yaml` says "point `navigation.config` at it in a
  robot profile". This IS that robot profile and the line is written into
  `configs/robot.prototype.yaml` **commented out**, with the reason: P0-D's own
  header calls every threshold in it PROVISIONAL and unmeasured (read off a
  bench that scored 0/69 person recall), and switching an unmeasured abstention
  gate on by default in the owner-facing profile risks a companion that refuses
  every place it is asked about — the opposite of this wave's ask-over-refuse
  directive. It is a decision about P0-D's calibration, not about profiles, so
  P0-A did not make it silently. Verified it is a decision and not a defect: a
  runtime built with `navigation.config` pointed at that file constructs exactly
  as one pointed at `default.yaml` does. **This is the one open integration
  decision in this card — one uncommented line.**
* **Whoever owns the C-1 attach site:** finishing the camera collapse is one
  line. `_attach_configured_camera_ingress` (runtime.py ~9688) reads
  `config is None or not config.enabled`; reading `_camera_ingress_enabled()`
  alongside it would make `PARCEL_CAMERA_INGRESS` move the stream as well as the
  grounding gate, in both directions. That site is outside card P0-A's region,
  so P0-A narrowed its claim instead of widening its diff.
* **P0-D:** `_camera_ingress_enabled()` now returns True for
  `perception.camera_ingress: true` as well, so a runtime that attaches a B4
  ingress under the C-1 flag will ground `_semantic_candidates` on pixels where it
  previously fell through to the oracle. Nothing attaches one today except
  `attach_camera_ingress`.
* **Owner:** the prototype voice lane is not live until
  `cp configs/realtime.prototype.yaml.example configs/realtime.prototype.yaml`
  (the launcher prints exactly this line when the file is missing). Voice identity
  stays off in it until `tools/enroll_owner_voice.py` has been run.
