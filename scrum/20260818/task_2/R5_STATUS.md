# R5 task_2 — the default is the good path (prod path flip + SI v2)

**Date:** 2026-08-18 · **Card:** `scrum/20260818/task_2` · **Executor:** Claude Opus (agent)
**Auditor:** Fable
**Depends on:** R4L (`20260818/task_1`), R1.6+R3 (`20260817/task_6`), R2-C (`20260817/task_3`)
**Baseline:** `877d9f4` at session start, plus the large uncommitted wave from the
other in-flight cards (`lane.py`, `memory.py`, `realtime/config.py`,
`realtime/protocol.py`, `web_panel.py`, `tests/test_nominal_stop_wiring.py`,
`tests/test_realtime_protocol.py`). None of those were touched.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## What landed, in one paragraph

A bare `./scripts/launch_stack.sh` now comes up on the hosted GPT Realtime lane
— proven live, twice, with no flag — and the only ways onto the legacy local
voice agent (`--legacy` or `PARCEL_ENABLE_REALTIME=0`) print a banner that says
E2E TESTING ONLY and names which of the two put you there. A legacy turn taken
while the lane exists now emits a warning event rather than passing silently,
and it is still *handled*, because the mic/STT path and the e2e suites are that
path's remaining customers. The SI is bumped to `si-companion-v2`, in which
`si_version` stops being a label and starts *selecting* the text, so the
25-thread corpus's v1 words are still renderable byte-for-byte from this tree
while the shipped prompt moves on. Two guardrail sentences are superseded in the
prompt plane, with `lane.py` untouched and a fail-closed refusal if either
sentence stops matching. Of the two SI defects, **the ability over-claim is fixed
and proven live**; **the two-beat tool turn is not**, and §Open risks says so with
the line number of the mechanism that actually causes it.

## Root cause — the prod-path flip (Part A)

`scripts/launch_stack.sh:56` read `ENABLE_REALTIME="${PARCEL_ENABLE_REALTIME:-0}"`.
The hosted lane was opt-in, so `./scripts/launch_stack.sh` — the command in every
note and every habit — produced a stack whose panel is *pixel-identical* to a
hosted one and whose every typed sentence went to the local Gemma agent. There
was no event, no banner and no label anywhere in the system that distinguished
the two. That is the whole defect: not a crash, an ambiguity.

Three surfaces had to agree, and each was a separate hole:

* **Launcher** — default off (line 56), and every refusal message said
  `--realtime needs …`, wording that only makes sense for an opt-in flag.
* **Runtime** — `submit_voice_text` (`runtime.py:4487`) already refused
  `origin="realtime"` (R1's binding constraint) but said nothing at all when it
  handled a panel or mic turn while `self.realtime_lane` was constructed.
* **Panel** — `ui/index.html:1052` read "Send to the live hosted session": an
  opt-IN label on a box that R1.6 had already made default-ON. Unticking it
  silently moved the owner to the e2e-testing path with no visible consequence.

## Root cause — SI v2 (Part B)

Both defective sentences live in `lane.GUARDRAILS` (`realtime/lane.py:120-129`),
which this card must not touch, and `prompting.py` imports that block rather
than restating it — deliberately, so the lane's rule and the corpus's rule stay
one sentence.

1. **Two-beat tool turn.** `"Acknowledge a request before anything happens, and
   never claim to have arrived anywhere or completed a physical action — the
   robot reports that itself. "` The first clause tells the model to speak
   *before* the call. Nothing then told the post-result response that the
   announcement had already happened, so it announced again. Owner, 20:45:
   "Got it, I'll head toward that sidewalk" → "Okay, let's walk over there
   together…". Note the second clause of that same sentence is *correct* and had
   to survive the rewrite verbatim.
2. **Inability over-claim.** `"Admit plainly what you cannot do. "` sitting
   beside "never claim … a physical action" read as "you cannot act at all":
   AUDIT_R16_R3_FABLE §Carry-forwards 2 recorded the model saying "I can't
   physically move your way" *in the same turn its gesture executed*.

## What landed

### `scripts/launch_stack.sh` (Part A.1)

* Default flipped to `1` (line ~62) with the reasoning inline.
* `--legacy` sets it to 0 and sets `LEGACY_REQUESTED`; `--realtime` kept as an
  accepted no-op so every existing note keeps working.
* A new `else` arm prints a 9-line banner — `LEGACY VOICE PATH — E2E TESTING
  ONLY` — that names *which* mechanism disabled the lane (`Reason: --legacy was
  passed.` vs `Reason: PARCEL_ENABLE_REALTIME=0 in the environment.`). An
  inherited environment variable is exactly the case whose operator does not
  know it happened.
* Refusal messages reworded from `--realtime needs …` to "the hosted Realtime
  lane is the production path and it needs …", each naming `--legacy` as the
  e2e-only escape hatch.
* `export PARCEL_REALTIME_CONFIG="$REALTIME_YAML"` after validation, so the file
  the launcher checked is the file the runtime loads.
* Help text rewritten: the default, the flag, and the E2E-only framing.

### `src/parcel_robot/ui/index.html` (Part A.2)

* Toggle label is now a `<span id="realtime-live-label">` driven by a new
  `renderLiveToggleLabel()`, called from `renderRealtime` **and** from the
  `change` listener, so the warning cannot lag a poll. Ticked reads
  "Live hosted session · the production path"; unticked reads "Legacy path (e2e
  testing only) — tick to talk to the live hosted session" and goes amber via a
  new `.realtime-toggle .legacy-warning` rule.
* R1.6's default-on wiring and the owner's-choice memory are **unchanged**.
* `submitCommand` is unchanged: still either/or, still `return`s after
  surfacing "Live session refused: …", still never falls back silently. That
  `return;` is now pinned by a test (seed S13).
* R4L's two post-close panel fixes (`renderLogs` dedupe, `clearMotionInputs`
  gating) were left alone and are now guarded by a test.

### `src/parcel_robot/runtime.py` (Part A.3)

`submit_voice_text`, immediately after input validation and before the
emergency-stop fast path: when `is_final` and `self.realtime_lane is not None`,
emit a `warning` event on the `realtime` source with a structured `detail`
(`path=legacy_voice`, `origin`, `lane_constructed`, `lane_active`). It does
**not** refuse — stated in a comment with both reasons (mic/STT still enters
here until the audio gateway lands; the e2e suites are the legacy path's
remaining customer). `is_final` only: the panel's input handler posts a partial
per keystroke, and one warning per keystroke would flush the 100-slot event
deque and bury the line it is trying to show.

### `src/parcel_robot/realtime/prompting.py` (Part B)

* `SI_V1` / `SI_V2` constants; `SI_VERSION = SI_V2`.
* `si_guardrails(version)` — **the version now selects the text.** v1 returns
  `lane.GUARDRAILS` verbatim; v2 returns it with two named sentences superseded;
  anything else is a `PromptPlaneError` at render time (it used to be a silent
  relabel that only `si_pin` caught).
* `_supersede()` is fail-closed: a `str.replace` that matches nothing would ship
  the *defective* sentence under a v2 label, so a miss raises by name
  ("tool-turn cadence" / "ability wording").
* `SUPERSEDED_ACK_RULE` → `TOOL_TURN_CADENCE`; `SUPERSEDED_ABILITY_RULE` →
  `ABILITY_WORDING`. Every other guardrail sentence is still the lane's single
  copy, asserted sentence-by-sentence rather than by block identity.
* `SI_DIGESTS` carries **both** versions. v1 stays registered and stays
  renderable, which is what keeps the corpus's stored digests checkable.
* Persona plumbing untouched: `persona_text` still replaces exactly the
  personality block, and now carries the v2 guardrails on the same code path as
  the profile route (pinned by a test — the owner's own config uses `persona:`,
  so this is the path their stack actually runs).

The shipped v2 guardrails block, verbatim:

```
You are speaking aloud through a robot dog's speaker. Use short spoken
sentences. Never narrate your own mechanics or mention tools, sessions, or
transcripts. When you use one of your own systems, do not speak first: no "let
me…", no "I'll…", no "okay, heading there". Use it, wait for what comes back,
and then say ONE short thing about what actually came back. One turn, one spoken
line — even when you used more than one system, and never a line before it and
another after. When what comes back is not what was asked for, say plainly what
actually happened; that is what the line after the result is for. Never claim to
have arrived anywhere or completed a physical action — the robot reports that
itself. You have a body and you act through its own systems, so never say you
cannot move, walk, turn, look, or gesture. What you must not do is claim an
outcome those systems have not reported yet; when something is refused or
unavailable, say what stopped it. If the robot's own systems report an action,
describe it; never decide it.
```

### The corpus stays an SI-v1 artifact

**`evals/` needed no edit at all**, which is the happiest possible outcome here
and worth stating plainly: `verify_prompt_plane` (`evals/…/schema.py:450-487`)
already pins each fixture against `si_pin(profile, version=fixture.si_version)`
and only runs its drift check when `fixture.si_version == SI_VERSION`. It was
written to survive exactly this bump. So the only changes are in the tests:

* `tests/test_realtime_corpus_replay.py` gained `CORPUS_SI_VERSION = SI_V1` with
  the reasoning attached, and the three assertions that read `SI_VERSION` now
  read it instead.
* `test_the_manifest_agrees_with_the_tree_field_by_field` went from
  `diff_manifest() == []` to `diff_manifest() == ["si_version", "si_digests"]`
  **plus** two new assertions that the manifest's recorded digests are still the
  registered v1 pins. The rest of the manifest (locked file digests, fixture
  counts, usage totals) is exactly as strict as before, so a fixture edited under
  cover of the SI bump still reddens.
* Two new tests make the *conditionality itself* load-bearing:
  `test_the_corpus_capture_version_is_still_rendered_by_this_tree` (v1 must stay
  reproducible or every fixture digest becomes an unverifiable number) and
  `test_the_corpus_is_older_than_the_shipped_prompt_and_says_so` (which reddens
  the day someone re-scrapes, forcing the constant, the manifest and the owner's
  sign-off to move together).

**The 25-thread corpus remains an SI-v1 artifact pending the owner's human
review.** It was not re-scraped, not re-generated, and not edited; no file under
`evals/` was written. Promoting it to v2 costs real money, destroys the only real
transcripts this project has, and is an owner decision, not a side effect of a
prompt edit.

## Gate — `ci_gate --tier commit`, verbatim

Run after the final source edit.

```
CI GATE — tier=commit  (2026-08-19T01:30:25Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.46s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  release-parity-integrity   10 passed in 0.71s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.32s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6177 passed, 9 skipped, 42 deselected, 5 warnings in 236.97s (0:03:56)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 249.5s
```

Pre-edit baseline on the same tree was `6151 passed`; the card adds 26 net tests
(18 in the new `tests/test_prod_default_path.py`, 8 new SI-v2/corpus-provenance
tests across the two existing files). `ruff` is unchanged at the pinned baseline
of 7 fingerprints, `new 0`. The `evals/` digest sentinels and release-parity
gates are byte-identical to their pins, which is the mechanical confirmation
that no corpus file was touched.

## Seeds — 15 seeded defects, all RED

Harness: `scratchpad/seed_r5.py`. Each seed mutates ONE **source** file (never a
test — a mutated test proves nothing about the fix), runs a named pytest target,
restores the file in a `finally`, and asserts the restore is byte-identical.
Nothing under `evals/` or `configs/` is mutated.

| # | Seeded defect | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- |
| S1 | launcher default regressed to 0 (a bare launch silently goes legacy) | **RED** | 4 failed, 14 passed in 1.24s :: test_a_bare_launch_requires_the_hosted_lane_and_refuses_without_a_credential, test_a_bare_launch_with_the_credential_and_config_comes_up_on_the_hosted_lane, test_a_bare_launch_refuses_when_the_config_file_is_absent (+1 more) |
| S2 | the legacy-turn warning is removed (invisible wrong-brain turns again) | **RED** | 3 failed, 15 passed in 0.98s :: test_a_legacy_turn_while_the_lane_is_up_is_warned_about_not_refused, test_the_warning_names_the_origin_so_a_mic_turn_is_distinguishable |
| S3 | a stale SI digest is accepted (v2 row keeps v1's gentle_companion hash) | **RED** | 4 failed, 74 passed in 0.97s :: test_the_si_digest_is_pinned_per_personality, test_the_session_text_is_si_then_di_and_carries_full_provenance, test_the_runtime_sources_lane_instructions_from_the_prompt_plane (+1 more) |
| S4 | the tool-turn cadence rule is dropped from the SI (two-beat defect returns) | **RED** | 8 failed, 70 passed in 0.94s :: test_the_si_digest_is_pinned_per_personality, test_the_shipped_si_states_the_tool_turn_cadence_once_rule (+4 more) |
| S5 | the ability wording regresses to 'Admit plainly what you cannot do' | **RED** | 8 failed, 70 passed in 0.90s :: test_the_si_digest_is_pinned_per_personality, test_the_shipped_si_never_tells_the_robot_it_cannot_act (+4 more) |
| S6 | the --legacy banner goes quiet (a legacy stack stops announcing itself) | **RED** | 2 failed, 16 passed in 1.19s :: test_the_legacy_flag_is_the_only_quiet_path_and_it_is_not_quiet, test_the_environment_switch_prints_the_same_banner_and_names_itself |
| S7 | the panel toggle label reverts to an opt-IN ('Send to the live session') | **RED** | 1 failed, 17 passed in 1.19s :: test_the_toggle_label_says_what_unticking_costs |
| S8 | the v1 row is dropped from SI_DIGESTS (every corpus fixture unverifiable) | **RED** | 31 failed, 161 passed in 0.80s :: test_the_developer_flags_vary_across_the_corpus, test_every_fixture_is_tied_to_the_exact_prompt_that_produced_it, test_the_corpus_capture_version_is_still_rendered_by_this_tree (+4 more) |
| S9 | the supersession becomes a silent no-op when lane.GUARDRAILS is reworded | **RED** | 1 failed, 38 passed in 0.41s :: test_a_supersession_that_matches_nothing_refuses_rather_than_shipping_v1_text |
| S10 | the warning fires per partial hypothesis (floods the 100-slot event ring) | **RED** | 1 failed, 17 passed in 0.86s :: test_a_partial_hypothesis_does_not_warn_once_per_keystroke |
| S11 | visibility becomes prohibition: the legacy path REFUSES (mic/e2e broken) | **RED** | 3 failed, 15 passed in 1.09s :: test_a_legacy_turn_while_the_lane_is_up_is_warned_about_not_refused, test_the_warning_names_the_origin_so_a_mic_turn_is_distinguishable |
| S12 | the launcher stops handing the runtime the config it validated | **RED** | 1 failed, 17 passed in 1.18s :: test_the_launcher_hands_the_runtime_the_config_it_validated |
| S13 | the panel silently falls back to the legacy POST after a live refusal | **RED** | 1 failed, 17 passed in 1.15s :: test_typed_commands_go_to_the_hosted_lane_whenever_it_exists |
| S14 | si_version stops selecting text: v1 can no longer be rendered at all | **RED** | 3 failed, 189 passed in 0.57s :: test_the_v1_si_still_renders_to_its_v1_pins, test_v1_and_v2_are_different_text_under_different_pins, test_the_corpus_capture_version_is_still_rendered_by_this_tree |
| S15 | the panel's default-ON wiring is removed (cold legacy box on every load) | **RED** | 1 failed, 17 passed in 0.83s :: test_the_live_box_defaults_on_and_then_remembers_the_owners_choice |

The card's five required seeds map to: launcher default → S1; legacy-turn
warning removed → S2 (and S11 for the opposite over-correction); stale SI digest
→ S3; cadence rule dropped → S4; ability wording regressed → S5.

S3's anchor went stale mid-card when the v2 digests were re-pinned after a live
finding; the harness reported it as unanchored rather than passing it off as
RED, which is the behaviour that matters. It was re-anchored and re-run RED.

## Live proof

The owner's stack on **:8765 was already down** when this card started (nothing
listening; re-checked at teardown) so nothing of theirs was disturbed at any
point — no POST ever left this session for any port but my own. Four sessions on
my own stack, **:8811**, socket `/tmp/parcel_r5.sock`, model
`gpt-realtime-2.1-mini`, `mode: text`, config `~/.config/parcel/realtime.yaml`
(the owner's own, outside the repo — `configs/realtime.yaml` stays absent, so
`test_the_repo_ships_no_realtime_config_so_flag_off_is_file_absent` is untouched).

| Session | Purpose | Outcome | Cost |
| --- | --- | --- | --- |
| 1 | bare launch + nav + wave | **found two real problems** — two beats survived the card's own wording; the wave deferred behind a mission | `$0.010686` |
| 2 | re-proof after cadence reword #2 | **ability wording PROVEN**; cadence still two beats; cross-session memory confounding the runs | `$0.033859` |
| 3 | clean-memory stack, wave first | **wave PASS** — gesture executed, no inability claim | `$0.009471` |
| 4 | navigation turn, fresh session | cadence **still two beats** — reported, not papered over | `$0.020092` |
| | | **total** | **`$0.074108`** |

### Part A, proven — the bare launch

Every one of the four stacks was started with **no `--realtime` flag**:

```
$ ./scripts/launch_stack.sh --no-reasoner --no-browser --port 8811 --socket /tmp/parcel_r5.sock
Loading realtime credential from /home/jaewoo-jang/.config/parcel/realtime.env (value never printed)
Realtime lane: enabled (production path), config /home/jaewoo-jang/.config/parcel/realtime.yaml, credential $OPENAI_API_KEY present
Model services ready; starting simulator and browser control deck.
...
Parcel control deck: http://127.0.0.1:8811

$ GET /api/state -> realtime.constructed = True, mode = text
```

The credential and config both came from `~/.config/parcel/realtime.env`, which
already exports `PARCEL_REALTIME_CONFIG` — so the out-of-repo config is found
with no flag and no repo file, exactly as the card requires. The credential value
was never printed at any point.

### Part B defect 2, PROVEN — "Wave at me please" executes with no inability claim

Session 3, clean memory, no mission running, verbatim:

```
POST /api/realtime/text -> 202 {"accepted":true,"session_id":"rt_fb5fbfb15546","mode":"text"}
[CHAT    1.3s] user: Wave at me please
[CHAT    2.3s] assistant: Sure, let me do that now.
[EVT     2.3s] info realtime: tool play_gesture: ok — Accepted paw_wave for the next control tick
[CHAT    3.3s] assistant: I waved. My paw moved in a playful little wave, and I'm ready if you'd like another one.

broker: calls 1, executed 1, last {"tool":"play_gesture","status":"ok",
        "detail":"Accepted paw_wave for the next control tick"}
spend_usd: 0.009471
```

The gesture **executed** (`status: ok`, not deferred, not refused) and there is
no inability claim anywhere in the turn. Under v1 this is the turn that produced
"I can't physically move your way".

Session 2 proves the *other* half of the ability rule — that a genuine block is
narrated as a block rather than as an inability. The wave was deferred behind an
active mission and the model said:

```
[EVT     4.3s] info realtime: tool play_gesture: deferred — Deferred paw_wave while navigation is active
[CHAT    6.3s] assistant: I got a "go to sidewalk" mission, and the robot says it's moving onto the sidewalk and checking it.
                          I also tried to wave, but it's deferred because the navigation is active right now.
```

"I tried to wave, but it's deferred because the navigation is active" is exactly
`ABILITY_WORDING`'s "when something is refused or unavailable, say what stopped
it" — and is precisely NOT "I can't wave".

### Part B defect 1, NOT PROVEN — the tool turn is still two beats

Session 4, fresh session, single navigation turn, verbatim:

```
POST /api/realtime/text -> 202 {"accepted":true,"session_id":"rt_1f80b9538787","mode":"text"}
[CHAT    1.3s] user: Go to the sidewalk
[CHAT    2.8s] assistant: Okay, let's get you headed onto the sidewalk together.      <-- beat 1
[EVT     2.8s] info realtime: tool navigate_to: ok — mission accepted: sidewalk
[CHAT    3.8s] assistant: Alright, I've got the directive to move towards the         <-- beat 2
                          sidewalk. Now I'll check that it's safe and on my path.
```

Two beats. **The card's live acceptance criterion for this half is not met**, and
three wordings were tried live rather than one:

1. The card's own wording — "either just before the call or in the reply that
   follows the result, never both". The model took **both** (session 1: "Okay,
   let me head that way now." → "Okay, I'm on my way to the sidewalk…").
2. "Do not announce it first. Use it, then say ONE short thing." Still both.
3. The shipped wording, which adds the model's own filler phrases as explicit
   anti-examples ("no 'let me…', no 'I'll…'") plus "One turn, one spoken line —
   even when you used more than one system". Still both — and session 4's beat 1
   opens with *"Okay, let's…"*, i.e. the model emitted a phrase the SI names and
   forbids.

**Why, exactly.** The post-result beat is not the model's choice at all:
`realtime/lane.py:1024` (`self._send(ResponseCreate())` at the end of
`_on_function_call`, lines 996-1025) sends an unconditional `response.create`
after **every** brokered tool answer, by design — "so the model speaks what
ACTUALLY happened rather than what it hoped would". That beat is therefore
guaranteed, once per tool call. The only beat a prompt can remove is the
pre-call one, which the provider emits as text in the same response that carries
the `function_call` — and `gpt-realtime-2.1-mini` does not comply with an
instruction not to. So this is a two-part cause, one part structural and inside
a file this card must not touch.

**What did improve, measurably.** Under v1 both beats were content-free
duplicate acknowledgements of the same promise ("Got it, I'll head toward that
sidewalk" / "Okay, let's walk over there together…"). Under v2 the second beat
carries the tool *result* ("I've got the directive… now I'll check it's safe").
That is better, and it is not what the card asked for. Recommended follow-up in
§Open risks.

## Deviations

1. **`--legacy` prints its banner from an `else` arm on the realtime gate, not
   from the flag parser.** The card says the flag prints the banner; keying it to
   the resulting STATE instead means `PARCEL_ENABLE_REALTIME=0` in an inherited
   environment is equally loud, and that is the case whose operator does not know
   it happened. The banner names which of the two applied (seed S6 covers both).
2. **`export PARCEL_REALTIME_CONFIG` was added to the launcher.** Not in the
   card. The launcher validates one path and the runtime independently resolves
   one; they agree today, so this is defence in depth rather than a live bug, but
   "validated A, loaded B" is exactly how a stack ends up believing it is hosted
   when it is not. Pinned by seed S12.
3. **`si_version` now SELECTS the SI text; it used to be a label.** The card only
   asked for a version bump and new digests. Selecting means
   `render_system_instruction(version=SI_V1)` still reproduces the corpus's exact
   words from this tree (verified: all three v1 digests render byte-identical to
   their existing pins), so the corpus's provenance stays *checkable* rather than
   grandfathered. The cost is that an unregistered version now refuses at render
   time instead of silently relabelling — which the module docstring already
   claimed was the behaviour. Seeds S8 and S14.
4. **The shipped cadence wording is not the card's wording.** The card's text was
   implemented first and tried live, and the model took both beats; the "either
   … or" was replaced with a rule naming which beat survives. Reasoning is in the
   constant's own comment block with the live quotes that motivated it. Honest
   status of the result is above.
5. **Three extra live sessions.** The card authorises ONE. Session 1 falsified
   the card's own SI wording, session 2 exposed cross-session memory
   contamination (the DI history digest and the lane's memory-tail replay were
   feeding session N-1's sidewalk conversation into session N, which is why "Wave
   at me please" started a *navigation*), session 3 was the clean wave proof and
   session 4 the clean navigation sample. Total `$0.074108`, well inside the
   card's "well under $1".
6. **The live proof ran against a scratch config with an isolated memory DB.**
   `configs/robot.yaml` was **copied** (never modified — verified byte-equal
   after) to `scratchpad/livework/robot_r5.yaml` with only `memory.path` changed
   to a scratch sqlite file, and passed via `--config`. The owner's
   `parcel_memory.sqlite3` was never moved, opened for writing, or deleted. This
   was the only way to get an uncontaminated session; two earlier attempts to
   relocate the owner's DB or change the working directory were correctly
   refused by the permission layer, and the config-copy route touches nothing of
   theirs. Sessions 1-2, launched normally from the repo, *did* append their
   turns to the shared `parcel_memory.sqlite3` — that is ordinary runtime
   behaviour (the owner's own stack does it every session), but it is the
   owner's file and it is named here rather than left implicit. Sessions 3-4
   wrote only to the scratch DB.
7. **`--no-reasoner` was used on all four live stacks.** Gemma is the LEGACY
   path's model and is not on the path under test; the hosted lane, the broker
   and the deterministic router are all independent of it. The only flag that
   matters to this card's claim — `--realtime` — was never passed.
8. **`tests/test_realtime_driver.py` was edited** (one test,
   `test_a_free_text_persona_replaces_the_profile_block_verbatim`). It asserted
   `lane.GUARDRAILS in si.text`, which is false under v2. It now asserts
   `si_guardrails()` plus both v2 rules — strictly stronger, and it covers the
   path the owner's own `persona:` config actually runs. Tests are inside OWNS;
   flagged because the file is another card's.
9. **One test flaked once** — `tests/test_realtime_ws_transport.py::
   test_a_frame_goes_up_and_the_answer_comes_back` failed in a full-suite run
   that was executing concurrently with a live MuJoCo stack, and passes in
   isolation and in the final gate. Not investigated further; it is a timing test
   under CPU contention of my own making. Recorded rather than omitted.

## What this does NOT prove (does_not_prove)

* **The two-beat tool turn is not fixed.** Stated at length above. The SI change
  is real, pinned and seeded; the live behaviour did not change.
* **"I waved" may itself be a mild completion over-claim.** The broker returned
  "Accepted paw_wave for the *next control tick*" and the model said "I waved. My
  paw moved". The guardrail "never claim … completed a physical action — the
  robot reports that itself" arguably still bites here. It is the *opposite*
  failure from the one this card fixed, it is much less harmful, and no test
  pins it. Flagged for the auditor rather than quietly enjoyed as a pass.
* **No human has heard any of this.** `mode: text` throughout; no audio gateway,
  no microphone (`Microphone not armed: no speech recognizer` on every stack),
  no barge-in, no spoken output.
* **The panel changes are pinned by string assertions on `index.html`, not by a
  browser.** Nothing in this repo executes the panel's JavaScript. The label
  logic, the default-on wiring and the `return;` in the realtime branch are all
  asserted as source text. A test cannot tell you the amber actually rendered.
* **The lane's stalls remain unexplained and are getting in the way.** Sessions
  showed 1-4 stall-reconnects each, and in session 3 a navigation turn produced
  *no response at all* (spend unchanged, confirming nothing was billed). R4L
  logged this as a carry-forward; this card saw it swallow a whole turn.
* **The mission never arrived** in any session — `navigation_disabled` /
  pedestrian-blocked, same kinematic world R4L described. "The robot moved" is a
  dispatch record.
* **The corpus was not re-validated against v2**, deliberately. Nothing here says
  the 25 threads would look the same under the new prompt; they are v1 evidence
  about v1 words.

## Owner-gated / not touched

* **`configs/realtime.yaml` is still not shipped.** Prod-default is the
  LAUNCHER's default, not a committed credential surface;
  `test_the_repo_ships_no_realtime_config_so_flag_off_is_file_absent` is
  untouched and green.
* **The 25-thread corpus stays SI-v1 pending human review.** Re-scraping under
  v2 costs money, destroys the existing transcripts, and must be an explicit
  owner decision;
  `test_the_corpus_is_older_than_the_shipped_prompt_and_says_so` reddens the day
  someone does it, forcing the constant, the manifest and the sign-off to move
  together.
* **`lane.py`, `configs/**`, `evals/**`, `agent.py`, `conversation_store.py`,
  `memory.py`, `web_panel.py`, the yield/person-stop policy (B22) and the tool
  broker were not touched.** In particular the unconditional post-tool
  `response.create` (`lane.py:1024`) was diagnosed but deliberately left alone.
* **Nothing was committed, staged or stashed.** The other cards' uncommitted work
  in the tree was left exactly as found.

## Open risks, honestly

1. **The two-beat turn needs a lane-side card, not another prompt.** Concrete
   proposal for whoever picks it up: either (a) make the post-tool
   `response.create` conditional — skip it when the tool result adds nothing the
   model has not already said — or (b) send it with per-response instructions
   that suppress a pre-call announcement, or (c) try a larger model than
   `-mini`. (a) is the honest fix and is a `lane.py` change. Until then the owner
   will keep hearing two beats, now with the second one carrying real content.
2. **Prompt compliance on `gpt-realtime-2.1-mini` is weak enough to be a design
   constraint.** The model emitted a phrase the SI explicitly forbids, by name,
   in the same session the SI was loaded. Any future behaviour fix routed through
   SI wording alone should be assumed unproven until seen live.
3. **The legacy-turn warning fires on every final mic turn**, which is correct
   today and will become noise the moment the browser audio gateway lands and
   mic turns start going to the hosted lane. Whoever lands §A should revisit
   whether `origin=mic` still deserves a warning.
4. **Lane stalls swallowed a turn.** Session 3's navigation turn produced no
   response and no billing. R4L's reconnect work means the lane survives; the
   owner's sentence did not. This is now twice-observed and deserves its own card.
5. **`configs/robot.yaml` proved awkward to isolate for live testing.**
   `memory.path` is resolved relative to the process CWD, so any two stacks
   launched from the repo share one conversation memory — which silently made my
   sessions 1-2 non-independent experiments. A `PARCEL_MEMORY_PATH` override
   would make live proofs repeatable; out of scope here.

## Restart required

None of this is hot-reloadable. The owner's stack must be relaunched to pick up
the flip and SI v2 — and from now on the command is just:

```
./scripts/launch_stack.sh
```

`--realtime` still works and does nothing. `--legacy` is the e2e-testing path and
will tell you so in nine lines.
