# Task 1 — R4-lite hardening: the mission you can see, the session that survives

**Date:** 2026-08-18 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** live owner incident, diagnosed against the RUNNING stack. Evidence:
- Owner's realtime mission started ("Navigating to sidewalk.") then ended with
  NO terminal event visible anywhere; nav detail left `enabled: false,
  goal: sidewalk, reason: navigation_disabled`; the panel showed nothing.
- After `lane reconnected: stall` (stalls: 1, reconnects: 1), a submitted turn
  was accepted (202, ledgered, utterance_sequence advanced) and NEVER answered:
  no response, no tool call, broker counters frozen. Reproduced by the auditor
  on the live stack, provider session `sess_EE6KVCjRUHmSgzwAowUl6`.
- Legacy-path control on the same stack: the dog scans, resolves, and WALKS
  (0,0)→(−0.22,1.83) with constant `person_stop` interruptions from the
  pedestrian stream near the sidewalk — navigation itself is healthy.

## Defect A — deaf lane after stall-reconnect (BLOCKING)

Reproduce offline first: FakeRealtimeServer script = normal turn → silent
stall (watchdog fires, lane reconnects) → next `send_text`. Expected: the new
session answers. Find why it does not (candidate classes: `_expecting_server`
state carried across reconnect; the pending `response.create` raced the old
socket and the new session never got one; tail reinjection leaving the session
mid-item; `_response` state not reset). Fix in `lane.py` (surgical), pin with:
(1) the offline reproduction as a permanent test, (2) a seed restoring the
defect, (3) one PAID live check: force a stall (drop transport mid-turn), then
prove the next turn answers. The R1.5 audit's backoff note applies: if
reconnect still has no bounded backoff after task_6, add it here.

## Defect B — missions end invisibly (BLOCKING for the demo experience)

1. Every mission terminal (arrived / failed / gave up / preempted / released)
   MUST emit an event AND survive event-queue eviction: add a small
   `mission_log` ring (last ~20 mission lifecycle entries with timestamps and
   reasons) to the runtime snapshot, independent of the chatty event deque.
2. Panel: render the mission log; while a mission is active show a live status
   line (state/goal/distance/blocked-reason) near the chat so "blocked by a
   person" is VISIBLE while the dog waits.
3. Realtime lane: on mission terminal, post the outcome into the session as a
   system item (floor-gated) so the MODEL narrates it — "someone's in my way
   near the sidewalk, I'm waiting for them" instead of silence. This is the
   design's §4 defer/rejoin R2 applied to R4-lite; keep it to terminal +
   blocked-entry events only (no per-tick spam).
4. Find and fix WHY the owner's realtime mission ended with no terminal event
   (trace `_reconcile_semantic_tasks` / navigation release path for a silent
   disable that leaves goal+directive populated). If it legitimately arrived
   (spawn-adjacent instance), then arrival must say so — that IS a terminal.

## Defect C — polish that rode along (small, do last)

- Broker `navigate_to` detail: replace the legacy ack string it currently
  returns with structured text ("mission accepted: sidewalk") — last survival
  of the template on the realtime path.
- Obstacle chatter ("Slowing near an obstacle"/"Obstacle clearance restored")
  must not be able to evict everything else: rate-limit the pair into a
  coalesced event or divert to a debug channel.

## OWNS / MUST NOT TOUCH

OWNS: `realtime/lane.py` (defect A + terminal narration hook),
`realtime/tool_broker.py` (C), `runtime.py` (mission_log ring + emission
sites), `web_panel.py` + `ui/index.html` (mission log + status line),
tests (new: `tests/test_realtime_reconnect.py`, `tests/test_mission_log.py`;
extend lane/broker suites), `scrum/20260818/task_1/R4L_STATUS.md`.
MUST NOT TOUCH: `configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`,
`evals/**`, `tools/`, `realtime/{protocol,transport,ws_transport,ingress,
fake_server,config,prompting}.py`, `conversation_store.py`, `memory.py`,
yield/person-stop policy (owner-gated B22 — narrate it, never weaken it),
anything uncommitted from other cards. Never commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green; ≥8 seeds RED/restored (must include:
reconnect-deafness restored, terminal event dropped, mission_log evicted by
chatter, narration spams per-tick); ONE live end-to-end proof on the running
stack pattern: submit "walk over to the sidewalk" via `/api/realtime/text`,
watch the mission run, see the mission log fill, and if a pedestrian blocks,
hear the model SAY so; paste the transcript + costs. The status doc names what
remains owner-gated (yield patience itself = B22).
