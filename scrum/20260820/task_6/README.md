# Task 6 — R17: keep the voice, replay the voice (audio capture + UI-mounted corpus runner)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner directive: "Store these valuable audio as test cases. Make
sure to use them for high-fidelity testing. And make sure you can show me the
UI of the robot when you run this eval sequentially with a UI mount." The
owner spoke the 52-query corpus live (voice_corpus_v1/live_run_1) and the
gateway did NOT persist the audio — transcripts survive, WAVs do not.
**DISPATCH GATE: after the R12–R16 chain closes and audits.**

## Work

1. **Session audio capture, config-gated.** `capture_audio: true` under the
   realtime yaml's gateway/whisperer block family (fail-closed validation):
   the gateway tees inbound PCM (owner) and outbound PCM (robot) to
   per-session WAV files under a configured directory (default
   `recordings/<session_id>/{owner,robot}.wav`, dir created lazily,
   NEVER inside evals/). Per-utterance index JSON (utterance id →
   byte/time range) so single turns are extractable as fixtures. Bounded:
   a max-minutes cap per session; hitting it logs and stops capture, never
   the session. Default OFF (the owner opts in per config).
2. **The UI-mounted sequential corpus runner** (`tools/run_voice_corpus.py`):
   takes a corpus dir of WAVs + queries.tsv, drives a LIVE stack (own port
   by default; `--stack owner` refused unless `--i-am-the-owner`), injecting
   each WAV through the REAL gateway path one query at a time — waiting for
   the turn to settle (reply + tool + mission terminal or timeout) before
   the next, with a `--pace` gap so a human can watch. The panel and MuJoCo
   window stay fully live during the run — that IS the owner's "UI mount":
   they watch the dog execute the eval in real time. Runner writes a scored
   run folder (per-query verdicts vs the gold column, transcripts, costs)
   in the live_run format the scoring agent established.
3. **E-stop hygiene in the runner:** after any estop-pos query, the runner
   RELEASES the latch (owner-authorized for eval runs) before continuing,
   and separately asserts the latch fired — live_run_1's lesson (90 s of
   BLOCKED_BY_LATCH results) must be impossible in the harness.
4. **First replay:** once the owner records WAVs via
   `evals/20260820/voice_corpus_v1/record.sh` (or a captured session
   yields per-utterance audio), run the corpus UI-mounted on your OWN
   stack as the card's live proof; the owner-witnessed run on THEIR stack
   is theirs to trigger.

OWNS: `realtime/audio_gateway.py` (tee only — bounded, never blocking the
relay path), `realtime/config.py` (additive keys), `tools/run_voice_corpus.py`
(NEW), `configs/realtime.yaml.example`, tests, `R17_STATUS.md`.
MUST NOT TOUCH: lane/protocol/ingress/broker/whisperer bands, prompting,
`evals/**` fixtures (runner OUTPUT goes to new run folders only), owner's
config/processes. DoD: gate green; ≥8 seeds RED (capture unbounded; tee
blocks the relay; runner proceeds past an unreleased latch; runner POSTs to
the owner stack without the flag; per-utterance index drifts); live UI-mounted
run with scored output + costs; standard register.
