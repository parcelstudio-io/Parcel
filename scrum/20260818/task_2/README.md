# Task 2 — R5: the default is the good path (prod path flip + SI v2)

**Date:** 2026-08-18 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** two owner directives, verbatim:
1. "Make sure the GPT realtime path and its hybrid path is the default prod
   path. Only use the legacy voice path for e2e testing purposes. During
   simulated manual testing, I want to use the realtime path using GPT."
2. Implement the SI v2 pass (the two-beat tool-turn redundancy the owner hit
   at 20:45 — "Got it, I'll head toward that sidewalk" followed one second
   later by "Okay, let's walk over there together…" — plus the logged
   inability over-claim, e.g. "I can't physically move your way" while a
   gesture executes; carried since AUDIT_R16_R3_FABLE §Carry-forwards 2).

## Part A — realtime hybrid becomes the default production path

1. `scripts/launch_stack.sh`: default `PARCEL_ENABLE_REALTIME` **1**. A bare
   `./scripts/launch_stack.sh` on a machine with the owner's key/config comes
   up on the hosted lane; on a machine without them it keeps the existing
   LOUD refusal — that refusal IS the prod contract (a silently-legacy stack
   is the failure mode this card exists to kill). Add `--legacy` (sets it to
   0) that prints an unmissable banner: the legacy voice path is for E2E
   TESTING ONLY. Keep `--realtime` as an accepted no-op for muscle memory.
2. Panel (`ui/index.html`): typed commands go to `/api/realtime/text`
   whenever the lane is constructed (current default-on toggle behavior is
   already right — keep the owner's-choice memory). Relabel the toggle so
   unchecking it reads as what it now is: "Legacy path (e2e testing only)".
   No silent fallback, ever — errors keep surfacing as "Live session
   refused: …" in the chat.
3. `runtime.py`: when `submit_voice_text` handles a turn WHILE the realtime
   lane is constructed and active, emit a clearly-worded warning event
   ("legacy voice path handled a turn while the live lane is up — e2e
   testing only"). Do NOT refuse: the mic/STT path still enters there until
   the audio gateway (§A) lands, and the e2e suites are the legacy path's
   remaining customers. Visibility, not prohibition.
4. Do NOT ship `configs/realtime.yaml` — the flag-off-is-file-absent pin
   (`test_the_repo_ships_no_realtime_config_so_flag_off_is_file_absent`)
   stays exactly as it is. Prod-default means the LAUNCHER's default, not a
   committed credential surface.

## Part B — SI v2 (`prompting.py` is OPENED for this card)

1. Rewrite the two defective SI behaviors, version-bumped:
   * **Tool-turn cadence:** announce a tool action ONCE — either just before
     the call or in the reply that follows the result, never both. After a
     tool result that matches what was already said, add at most one SHORT
     new sentence (or nothing). A result that DIFFERS from the announcement
     must be narrated honestly — that channel is why the follow-up response
     exists.
   * **Ability wording:** the rule is "never claim an outcome the tools have
     not confirmed", NOT "you cannot act". The robot acts through its tools;
     it must not disclaim physical ability while a gesture/mission executes.
2. `SI_VERSION` → v2; `SI_DIGESTS` updated; fail-closed digest tests updated.
   Persona plumbing untouched.
3. The 25-thread corpus is v1-provenance and MUST NOT be re-scraped; the
   replay/provenance tests must be adjusted provenance-conditionally if they
   pin the SI version, and the status doc must state that the corpus remains
   an SI-v1 artifact pending the owner's human review.

## OWNS / MUST NOT TOUCH

OWNS: `scripts/launch_stack.sh`, `src/parcel_robot/ui/index.html`,
`src/parcel_robot/runtime.py` (legacy-turn visibility only),
`src/parcel_robot/realtime/prompting.py` (SI text/version/digests),
tests (new + extended), `scrum/20260818/task_2/R5_STATUS.md`.
MUST NOT TOUCH: `configs/**`, `evals/**`, `agent.py` (the legacy behavior IS
the e2e baseline being preserved), `realtime/{lane,tool_broker,protocol,
transport,ws_transport,ingress,config,fake_server}.py`,
`conversation_store.py`, `memory.py`, yield/person-stop policy (B22),
`web_panel.py` unless a label string forces it. The owner's stack is UP on
:8765 RIGHT NOW — read-only probes at most; live proof on your OWN port and
socket. Never commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green. ≥6 seeds RED/restored, including at
least: launcher default regressed to 0; the legacy-turn warning removed; a
stale SI digest accepted; the cadence rule dropped from the SI; the ability
wording regressed. ONE live proof on your own stack: a BARE launch (no
--realtime flag) comes up on the hosted lane; one navigation turn produces
ONE acknowledgment beat (not two); "Wave at me please" executes with no
inability claim; paste transcript + costs (authorized: gpt-realtime-2.1-mini,
target well under $1). R5_STATUS.md carries the standard register: gate
verbatim, seed table, deviations, does_not_prove, owner-gated items.
