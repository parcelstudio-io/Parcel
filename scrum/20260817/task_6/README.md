# Task 6 — R1.6+R3 "Ears, Mouth, and Body": live manual testing + real tool execution

**Date:** 2026-08-18 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Supersedes:** task_4 (R1.6 card — its executor stalled with zero files and was
cancelled; that card's scope is folded in here VERBATIM by reference, one
executor owning `runtime.py`).
**Owner directives this card exists to satisfy:**
1. Manual tests in simulation must actually use the OpenAI Realtime API.
2. The robot dog must ACTUALLY perform gestures/poses (and bounded navigation)
   when the voice model proposes them — in MuJoCo, visibly.
3. (Friendliness was verified separately — SI unchanged, no version bump.)

## Architecture ruling (binding, from the audited design + audits)

The voice model supplies INTENT as tool-call proposals with arguments. It never
commands. Execution authority is the deterministic admission chain, not any
model. Specifically, per the R1 audit carry-forward: **every tool the broker
executes goes through `ToolCall` + `SafetySupervisor.validate` first**, then
the existing doors — no direct calls, no new authority. `navigate_to` is
bounded R4-lite: the broker renders directive text and routes it through
`DeterministicIntentRouter` with a fresh turn id; only router-recognized
navigation grammar proceeds to the existing sketch admission; anything else
returns `rejected(reason)` for the model to voice. No second model enters this
card (grounding-by-reasoner is R4-full, later).

## Scope — OWNS

**A. Browser audio path** — implement scrum/20260817/task_4/README.md exactly
as written (audio_gateway.py, browser_sink.py, ui mic button + worklets, mark
integrity with clamping, arming per-connection, its S1–S6 seeds). Read that
card in full; its MUST-NOTs apply except where superseded below.

**B. Lane driver + runtime wiring** (`runtime.py` — this card now owns it):
- A pump/tick driver for the lane (thread or existing-loop hook; injectable
  clock), calling `realtime_instructions.refresh(lane)` at session boundaries.
- Construct gateway + BrowserSink and pass the sink when `mode: audio`;
  in `mode: text` no gateway is needed.
- Expose lane/arming/session/cost state in the existing snapshot surface.

**C. Manual live testing path (owner directive 1):**
- `configs/realtime.yaml.example` (documented; enabled true, model mini,
  `mode: text`) — the real `configs/realtime.yaml` stays absent in the repo.
- `scripts/launch_stack.sh --realtime` flag: sources
  `~/.config/parcel/realtime.env` if present, refuses loudly if the key is
  absent, starts the stack with the lane constructed.
- Panel: in text mode the existing text box gains a "live" indicator and owner
  text goes to the live session (conversation item + response.create through
  the lane), replies render in the chat panel AND the ledger. This makes a
  bare `./scripts/launch_stack.sh --realtime` + browser a REAL end-to-end
  manual test against the API with zero audio hardware.

**D. Tool broker (owner directive 2)** — replace the refuse-all stub via a
`tool_handler` seam on the lane (minimal `lane.py` diff; default handler stays
the refusal, proven byte-identical when unset):
- `get_status` → validated → snapshot digest reply.
- `recall_memory(query)` → ledger/TieredMemory deterministic read.
- `play_gesture(name, intensity)` → validate → `_brain_gesture` →
  ActivityCoordinator (intensity clamped by broker; cooldown result surfaced
  as `dropped(reason)` so the model can respond gracefully).
- `set_pose(name)` → validate → `propose_action(kind="pose")` — NEVER the
  recovery door; nav/follow/e-stop outrank by arbitration.
- `navigate_to(place)` → the R4-lite router-first path above.
- Utterance-scoped dedupe vs the deterministic ingress (one authority per
  utterance); thinking pose fires on dispatch via ReactionHooks.
- Every result returns as `function_call_output` with a `response.create` so
  the model narrates what actually happened.

**E. The proof (owner directive 2, literally):** a live sim smoke, env-gated
(`PARCEL_REALTIME_LIVE=1`, slow marker): headless MuJoCo runtime + text-mode
lane; send "wave at me please" → assert a gesture activity actually DISPATCHED
(activity record + ledger rows + function_call_output showing `ok`); send
"go to the sidewalk" → assert a navigation mission was ADMITTED through the
sketch path (mission state, not arrival). Run it once live; paste the evidence
into the status doc. This is the first time the voice model moves the sim dog.

**F. Tests + seeds (≥10):** task_4's S1–S6, plus: pose-under-e-stop refused
through the broker (the audit carry-forward, now pinnable), navigate dedupe
(ingress already executed ⇒ broker drops the matching call), tool-handler
unset ⇒ refusal byte-identity, text-mode flag-off ⇒ runtime boots identically.

## MUST NOT TOUCH

`configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`, `evals/**`,
`tools/`, `realtime/{protocol,transport,ws_transport,ingress,fake_server,
config}.py` (audited; `config.py` may gain the `mode` key ONLY if its
fail-closed shape is preserved and tested), `conversation_store.py` /
`memory.py` (R2-D just landed — read-only), other cards' scrum docs. `lane.py`
edits are limited to the `tool_handler` seam + driver hooks; if more seems
needed, STOP and report. Never commit/stage/stash. Credentials: env reference
only; never in repo, logs, or output.

## Definition of done

Full `ci_gate --tier commit` green (live/slow tests deselected); all seeds RED
then restored; the live smoke evidence in the status doc with measured cost;
`R16_R3_STATUS.md` register complete, honest about what only a human with a
browser can still verify (real mic audio, barge-in feel, gesture timing).

## Addendum 2026-08-18 — owner directive: persona is just prompt text

Personality must be authorable as PLAIN PROSE in config, e.g.
`persona: "You are a lively conversational agent that likes to go around New
York."` — no YAML profile required. Scope change:

- `configs/realtime.yaml` (and the .example) gains an optional `persona` key:
  free text. When present it REPLACES the personality-profile block in the SI
  verbatim; `si_profile` becomes an optional preset fallback (default
  behavior unchanged when `persona` is absent).
- `realtime/prompting.py`: `render_system_instruction` accepts
  `persona_text=` overriding the profile lookup. The companion preamble, voice
  guardrails, and DI contract sections are NOT personality and stay exactly as
  they are — they ride along regardless of persona source.
- The digest/version discipline is unchanged and is the point: a persona edit
  produces a new SI digest recorded per session/fixture, so corpus comparisons
  stay attributable. `SI_DIGESTS` pins apply to the preset profiles only;
  free-text personas are pinned by digest-in-ledger, not by a constant.
- Tests: persona render is deterministic; empty/whitespace persona refused
  (fail-closed, not silently blank); profile fallback byte-identical when the
  key is absent; one seeded failure — persona text edited ⇒ session digest
  moves (proving attribution).
