# AUDIT — R7 "ears and mouth" · Fable

**Date:** 2026-08-19 · **Card:** `scrum/20260818/task_4` · **Executor:** Claude Opus (agent, via workflow)
**Verdict:** **ACCEPT_CLOSE** — §A finally lands, four cards after it was
first carried. `mode: audio` constructs, a synthesized spoken sentence became
a real mission through the real gateway, and real audio came back.

## Independently verified

1. **Fresh full gate, auditor's own run: PASS, 6242 passed**, ruff `new 0`.
2. **All 21 seeds re-run by the auditor: 21/21 RED**, byte-identical restores
   — including S18, which the executor disclosed came back GREEN first and
   was fixed by strengthening the test, not deleting the seed (the standard,
   held).
3. **Read-only verifier (workflow, structured):** fail-closed handshake
   confirmed at code level (loopback Host + same-origin + CSRF token as a WS
   subprotocol — kept out of the URL because the panel logs request lines,
   with `hmac.compare_digest` on the check); bounded buffers on every path
   (256-frame/8 MiB oldest-drop outbound, 32 KiB policy + 1 MiB codec caps
   inbound); mic opens only on the owner's per-session gesture through the
   handshake token; `lane.py`/`protocol.py` untouched by this card (mtime
   attribution clean against R6's window); text mode undisturbed (R5's
   routing test re-verified, seed S21); live-proof artifacts internally
   consistent down to the scratch-ledger rows ("Soap", "Top",
   "[interrupted after 0 ms]") and the owner-DB mtime. Its four findings are
   minor: 215 vs 212 chunk-count conflation (gateway counter includes 3
   barge-in-discarded frames), an overstated same-origin POST contrast (same
   gate both places, absent-Origin passes both — fine for real browsers,
   disclosed in the docstring), a one-character sha-suffix typo, and some
   live counters that are executor-attested rather than persisted. None
   material.
4. **Deviation 1 accepted:** `audio_gateway.py` (new, 940 lines) sits outside
   the card's literal OWNS but is the exact module `runtime._build_realtime_
   sink` had been importing-and-failing on since R1.6 — the card's own work
   product landing at the seam the runtime designed for it, declared not
   hidden. The sweep found no protected-surface modification anywhere
   (one evals mtime anomaly is byte-identical to HEAD — an external-evals
   runtime rewrote a file with identical content; content clean, noted so
   future mtime-based sweeps know evals timestamps are not pristine).

## Bonus fix verified

**R4L open risk 6 is closed:** the `DuplexVoiceSession output is live` pump
failure was a false positive — `assert_sink_free` guards the shared PortAudio
queue, which the lane's browser/discard sinks never are. Fixed at the
injection point (`duplex_output_active`), fail-closed for unrecognized sinks,
`driver.failures == []` across 4,695 live steps.

## The two honest failures — both now owner-decisions, not defects

1. **The spoken emergency latch never fired in three attempts.** Wiring
   proven correct; the exact-phrase latch (`stop`, `stop now`, `halt`,
   `emergency stop`) is reasonable for a text box and fragile under ASR —
   whisper produced "Soap", "Top", and a correctly-transcribed sentence that
   exact-match missed. `ingress.py` was correctly left frozen. **This is the
   strongest evidence yet for the owner-gated always-local wake-word/e-stop
   (the ChatGPT-rec constraint), and I put it above R8 in safety priority:
   until it lands, the SPACE bar and the panel Stop button are the emergency
   stop, and the owner should know that plainly.**
2. **Barge-in mark integrity is future work:** the interrupt fired live
   (210 ms) but the played-clock ack protocol meant the provider was told the
   owner heard 0 ms of a reply they heard 13 chunks of. Disclosed, not
   papered over.

## Live-proof standing

Four sessions, $0.102282: piper-synthesized speech → provider transcription →
`navigate_to` through the normal broker/router/admission chain
(`mission accepted: sidewalk`) → 45 audio chunks back through the gateway →
both sides ledgered. Barge-in stop frame delivered live. No human has spoken
to it or heard it — the first human-witnessed spoken session is the owner's,
deliberately.

## Carried forward

Local wake-word/e-stop (owner-gated, now evidence-backed, safety-first);
R8 protocol content types (from R6 — also required before narration can ever
be HEARD in audio mode); barge-in mark/truncate integrity; ASR-robust latch
phrasing as part of the wake-word card; the voice-turn repay signal (R6
carry-forward, now live-relevant since audio landed).
