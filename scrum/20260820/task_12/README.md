# Task 12 — F1-SI: the owner's voice (speech identity for command arming)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Design authority:** SYNTHESIS_EVAL.md speech-identity decisions 1–5,
backed by bench_doa.md (measured on THIS host: titanet_small zero-overlap
separation on 378 pairs, 27 ms median; XVF3800 DoA path confirmed, staged
tooling in `<scratchpad>/evalbench/xvf3800-bench/`). Trigger: F1 — the TV
commanded the robot twice across two owner sessions; `aec.constructed:
false` is named live evidence that AEC cannot defend this anyway.
**DISPATCH GATE: after EV-1 closes AND the owner has (a) run the udev rule
and (b) recorded enrollment audio. If (a)/(b) are missing at dispatch time,
build everything fake-first and mark the live half owner-blocked.**

## Work

1. **Embedding verify in the audio gateway, post-VAD, per-utterance:**
   sherpa-onnx + titanet_small (vendor the ~40 MB model under models/ with
   provenance lock, like the judge). Utterance embedding vs enrolled
   owner profile; cosine ≥ threshold (config, default 0.55) arms the turn.
   In-process, budget ≤50 ms p95 added latency (measured 27 ms median);
   fail-open to REFUSE-to-arm, with a counted `voice_rejected` and a
   whisperer always-band fact on first rejection per minute ("someone who
   isn't you asked me to…" class narration — visible, never silent).
2. **SAFETY ASYMMETRY (binding, seeded):** the emergency latch path runs
   BEFORE and WITHOUT identity — any voice stops the dog. Identity gates
   command arming only. A seed must prove a stranger's "die stop" still
   latches while their "go to the bench" does not arm.
3. **Enrollment:** `tools/enroll_owner_voice.py` — N utterances → averaged
   embedding stored outside the repo (beside the realtime config, mode
   600); loader fail-closed (no profile ⇒ verify disabled ⇒ pre-card
   behavior, loudly noted in snapshot). Re-enrollment overwrites cleanly.
4. **DoA sector prefilter (if the udev rule is in place):** poll
   `DOA_VALUE` on the vendor interface (staged tooling); a configurable
   rejected-sector (the TV's azimuth) drops turns UNLESS embedding verify
   passes — belt and suspenders, cheap. Non-disruption of the audio stream
   proven the bench's way (stream state before/after).
5. **Eval tie-in:** the corpus gains an impostor category (synthetic
   voices + any non-owner recordings) run through the R17 replay harness;
   EV-1's assertion suite gains a voice-provenance check (every armed turn
   carries its verify score). FAR/FRR reported per the dialogue-evals
   wake-word methodology.

OWNS: `realtime/audio_gateway.py` (verify hook), a new
`realtime/voice_identity.py`, `realtime/config.py` (additive keys),
`tools/enroll_owner_voice.py`, models/ vendoring with provenance lock,
tests (fake embedder first), `F1SI_STATUS.md`.
MUST NOT TOUCH: ingress (the latch path is R9/R21 law — asymmetry is
enforced by gating ARMING, not by touching the latch), lane/protocol/
broker, prompting, yield. DoD: gate green; ≥8 seeds RED (asymmetry broken
both directions; threshold ignored; missing profile arms anyway; rejection
silent; DoA claim disturbs the stream (guarded by test double); verify
score dropped from provenance); live proof with the owner's enrolled voice
accepting and a synthetic voice rejected mid-session, costs; standard
register with FAR/FRR honestly small-n.
