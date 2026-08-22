# Task 2 — P0-B: hosted-lane companion unlocks

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(read its standing rules first — concurrent writers, Edit-only, git read-only).

## Why

The production hosted lane (gpt-realtime) is the companion's voice, and four
production refusals make it feel inert: it may never move unless the owner
spoke first, it refuses any place noun outside a list before consulting any
map, it hangs up after ten quiet minutes, and "I'm feeling sad" does nothing
because affect only runs on the legacy lane. Audit §5 and §9.

## Deliverables (every one config-gated, production default unchanged)

1. **Proactive motion allowlist.** `realtime/tool_broker.py:748` refuses every
   motion tool when the response provenance is system-initiated. Add a
   validated config key (e.g. `proactive_motion_tools: []`) and allow exactly
   the listed tools from system-initiated turns. Allowed values are limited to
   the low-risk set `play_gesture`, `set_pose`; `navigate_to`, `circle_owner`,
   `follow_owner` remain owner-initiated only (the validator must refuse them
   in this list). Everything still goes through `SafetySupervisor.validate`.
2. **`navigate_to` asks instead of refusing.** `tool_broker.py:882-948` gates on
   a known-place list. For a noun not on the list, return a structured tool
   result (`status: unknown_place`, with the nearest known names if any) so
   the model asks the owner or offers to look — **no motion** on unknown.
   Keep the existing behaviour for known places. Config key to select the
   mode (`unknown_place: refuse|ask`), default `refuse`.
3. **Idle stays live.** `realtime/config.py:346` `idle_close_after_s`: accept
   `0` meaning never (validated, documented), so the prototype lane can stay
   open while the owner is around. Do not change the default.
4. **Narration cap configurable** (`whisperer.py`, the per-minute cap that the
   example config documents as 2/min): make it a validated key; default
   unchanged.
5. **Affect on the hosted lane.** In `submit_realtime_transcript`
   (`runtime.py` ~6127–6275, the `KIND_NONE` path) run the existing
   `explicit_affect_from_text` (`brain/router.py:101-127`) and, when a label
   clears the configured confidence (`configs/robot.yaml:218-221`; P0-A's
   profile sets 0.5), (a) write an `affect` meta row through the existing
   memory writer, (b) propose the persona's `affect_actions` gesture through
   `propose_action(kind="pose"|"gesture")` — never through
   `_brain_return_to_safe_pose`. Config-gated (`hosted_affect: false` default).
6. **Document the new keys** in `configs/realtime.yaml.example` with the same
   comment style, defaults off. Put the *prototype* values in your status doc
   (P0-A owns the prototype example file; Fable merges).
7. **Tests**, each seeded RED first: allowlist admits only listed tools and the
   validator refuses high-risk names; unknown-place result shape and no motion;
   `idle_close_after_s: 0`; cap key; hosted affect writes the row and proposes
   the gesture only above threshold and only when enabled.

## OWNS

`src/parcel_robot/realtime/tool_broker.py`, `src/parcel_robot/realtime/config.py`,
`src/parcel_robot/realtime/whisperer.py`, `src/parcel_robot/runtime.py` **only**
the `submit_realtime_transcript` region (~6100–6300) — P0-A and P0-D edit other
regions concurrently: Edit-only, re-read first — `configs/realtime.yaml.example`,
`tests/test_realtime_*.py` additions and a new `tests/test_p0b_companion_unlocks.py`,
this folder.

## MUST NOT TOUCH

`src/parcel_robot/realtime/ingress.py` (the closed-intent / emergency scanner —
the e-stop path is sacred), `voice_identity.py` emergency asymmetry,
`SafetySupervisor`, `docs/**`, `backlog/**`, `README.md`, `scrum/20260821/**`,
`configs/robot.yaml`, `configs/robot.prototype.yaml` (P0-A), `evals/**` frozen
fixtures (`evals/companion/realtime_convo_v1` replays must stay green — if a
fixture depends on the old refusal text, your change must be config-off by
default so the fixture is unchanged).

## Gates

* `.parcel/bin/python -m pytest -q tests/test_realtime_*.py tests/test_p0b_companion_unlocks.py tests/test_tool_broker*.py -x` green.
* `.parcel/bin/ruff check src/parcel_robot/realtime tests/test_p0b_companion_unlocks.py` no new violations.
* SI/DI digest pins (`tests/test_realtime_prompting.py`) untouched and green —
  you are not changing prompts.

## Status doc

`P0B_STATUS.md`, per the board's register, plus the prototype values for every
new key.
