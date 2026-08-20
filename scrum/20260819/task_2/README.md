# Task 2 — R9: the owner's e-stop

**Date:** 2026-08-19 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner policy ruling, verbatim (2026-08-19): "Space bar should be
the e-stop. In voice command it should be 'Die Stop'." This ruling closes the
owner-gated wake-word/e-stop question from AUDIT_R7_FABLE and UNFREEZES
`ingress.py` for exactly this change. Context: R7 proved the spoken latch
wiring correct but the exact-phrase set fragile under ASR (whisper heard
"Soap" and "Top"); and the panel's Space currently requests a NOMINAL stop
(`/api/action {action: "stop"}`), not the emergency latch — the owner has now
said Space IS the e-stop.

## Work

1. **Space → emergency stop.** The panel's Space handler
   (`ui/index.html:~1861`) latches the EMERGENCY stop (the same latch the
   e-stop button uses), not the nominal stop. The `isTypingTarget` guard
   stays byte-identical — Space while typing in the chat box must never
   latch. The Stop button and `[data-action]` buttons keep their current
   meanings. While the latch is held: an unmissable panel banner showing
   latched state and the release affordance (a release path exists —
   find it, verify it end-to-end, and make it visible; if none exists
   server-side, that is a card-stopping finding to report, not improvise).
   Document plainly in the status doc: browser keys require panel focus
   (B14's cousin), and the MuJoCo window's own keyboard controls are a
   separate, unchanged surface.
2. **"Die Stop" — the spoken emergency phrase** (`ingress.py`, unfrozen by
   the ruling). Add it to the emergency latch with ASR-robust matching:
   case/punctuation-insensitive, whitespace-normalized, and tolerant of the
   obvious transcription variants of "die" ("dye", "di", "dai") followed by
   "stop". Design for asymmetric cost: a false latch stops a robot dog (cheap,
   releasable); a missed latch is the failure that matters — bias accordingly
   but do NOT latch on "stop" alone inside ordinary sentences beyond what the
   existing phrase set already does. The existing typed phrases (`stop`,
   `stop now`, `halt`, `emergency stop`) remain — they are correct for the
   text box. The latch stays LOCAL-FIRST: it fires on the transcript/typed
   text before any cloud response, on both origins (typed panel text and
   realtime transcript), exactly as the restricted ingress already orders it.
3. **Live proof:** (a) piper-synthesize "Die Stop" (and at least one ASR
   variant, e.g. "Dye stop.") and pump it through the R7 audio gateway on
   your own stack — the transcript must latch the emergency stop while a
   mission is running, and the mission log + events must show the latch and
   its reason; (b) the same phrase typed into the text path latches; (c) an
   ordinary sentence containing the word "stop" mid-thought ("let's stop by
   the store" class) does NOT latch — pin the negative; (d) exercise the
   release path and show the dog can be commanded again after release.

## OWNS / MUST NOT TOUCH

OWNS: `src/parcel_robot/realtime/ingress.py` (the phrase + normalization),
`src/parcel_robot/ui/index.html` (Space handler, latched banner, release
affordance), `src/parcel_robot/web_panel.py` and `runtime.py` ONLY if the
emergency action/release wiring genuinely requires it (smallest possible
touch, justified in Deviations), tests (ingress suite + prod-default panel
pins + new), `scrum/20260819/task_2/R9_STATUS.md`.
MUST NOT TOUCH: `lane.py` and `protocol.py` (R8 lands there TODAY, before
you — treat as frozen), `tool_broker.py`, `prompting.py`, `config.py`,
`agent.py`, `audio_gateway.py`/`browser_sink.py`/`driver.py` (R7 is closed —
gaps are findings, not edits), `configs/**`, `evals/**`, yield/person-stop
policy (B22 — an emergency latch is not a yield change), the fresh R5/R4L
panel work (toggle label, renderLogs dedupe, clearMotionInputs gating —
seed-guarded, do not disturb). Owner's stack: read-only probes at most; own
stack; R5 scratch-memory recipe; never commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green; ≥8 seeds RED/restored, including at
least: Space reverts to nominal stop; the typing-target guard removed (typing
latches); "die stop" variant tolerance removed (exact-only again); the latch
moved AFTER the cloud round-trip (local-first broken); the negative case
latches ("stop by the store" halts the dog); release path broken (latch is
forever). Live proof as above with transcripts + costs (target well under
$1). R9_STATUS.md registers the policy ruling verbatim, the focus caveat,
and what stays owner-gated (a hardware/local hotword detector that works
with zero cloud and zero panel — future, if ever needed).
