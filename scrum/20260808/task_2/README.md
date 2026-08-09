# Sprint 2026-08-08 · task_2 — PERSONAL_CONVO_V1 design (research complete, pending owner approval)

**Ask:** a personal-conversation evaluation integration test, benchmark-
researched, runnable e2e from fixed WAV/MP3 corpora so the eval survives
tokenizer/synthesizer/STT/TTS/LLM updates.

**Research:** workflow `wf_4895cabe-808` (3 researchers + synthesis; full
record in the workflow journal). On approval, the full synthesis becomes
`docs/PERSONAL_CONVO_EVAL_DESIGN.md`.

## Design in one page

**A probe family on existing rails, not a new harness.** Pack at
`evals/companion/personal_convo_v1/` with the proven conventions
(manifest sha-pins every fixture/scorer/judge artifact, refuse-to-run on
edits, immutable results with `does_not_prove`).

**Two tiers, one probe pack** — the same session scripts drive both:
- **Tier T (text, per-commit CI):** multi-turn extension of
  conversation_quality_v1; turns injected as text; scoring sees reply +
  DialogueAct + tool trace + memory rows.
- **Tier A (audio e2e, zero hardware):** the acoustic_loop_v1 virtual
  rig with the live stack inside — frozen WAV → whisper STT → Gemma
  (prompting + weather tool + persona) → Piper → speaker monitor. Turn
  advancement is acoustic (silence-hold). The judged artifact is the
  robot's recorded audio transcribed by ONE PINNED REFERENCE STT (never
  the stack-under-test's) — model swaps reach the eval only through
  behavior.

**Eight probe categories** (each with deterministic + judged halves):
in-session context (anaphora/topic-shift survival), cross-session memory
(LongMemEval's five abilities on a frozen sqlite fixture, fresh process
per session so context carryover can't fake memory), fact+tool
composition (weather + Manhattan profile, incl. tool-outage
no-fabrication), persona consistency (embodiment honesty
machine-checked; style judged; disguised re-asks machine-diffed), affect
handling (ESConv stage structure, never content), clarification,
no-sycophancy, ASR-robustness (degraded audio must degrade to
clarification, never to hallucinated compliance).

**Corpus (the model-update-proof interface):** three labeled strata —
(1) **human-recorded owner pack** (owner + 3–5 volunteers; load-bearing:
the human-vs-TTS gap is ~12.5% measured, so every CI-gating family needs
human coverage), (2) alt-TTS breadth stratum (never Piper —
self-dealing), (3) deterministic Piper stratum for timing-only cases.
Open seeds with licenses: Common Voice (CC0), SLURP audio (CC BY-NC,
flagged), MT-Bench-101/LongMemEval templates (Apache/MIT);
ESConv/DailyDialog structure-only, content never shipped. EBU-R128
loudness + 16 kHz mono normalization; WAV master, MP3 as a
codec-variant axis; sha-pinned corpus versions.

**Scoring:** deterministic-first (tool traces, truthfulness via the
existing DialogueAct claims contract, fact recall/confabulation string
sets, clarification bit, emote policy — CI-gating and
determinism-contracted) → heuristic report-only flags → **local judge,
report-only at first**, with a mandatory **calibration pack** (frozen
known-good/known-bad transcripts re-scored every run; judge drift =
judge disqualified, never scores silently shifted).

**Model-swap protocol:** full provenance block per run (stt/tts/llm/
judge/reference-stt shas); a **single-delta rule** (the comparator
refuses runs differing in more than one component); paired comparison on
the identical frozen corpus; Tier-D exact verdict diff + judged-score
non-inferiority with bootstrap CIs; the reference STT is the measurement
instrument, never swapped casually.

**Implementation cards (dispatch on approval):** PC-1 pack skeleton +
session-script schema → PC-2 deterministic scorer bank → PC-3 text-tier
probe corpus → PC-4 calibration pack + local judge → PC-5 audio tier on
the rig → PC-6 ASR-robustness/hallucination-under-noise → PC-7 swap
comparator + non-inferiority gates. **Owner-gated:** recording the human
utterance pack (~30-minute session from a script we generate; volunteers
optional but valuable).

**Honest caveat up front:** today's ConversationMemory is a recency
window — cross-session recall probes beyond it will fail on day one.
That is a true finding (it motivates the retrieval upgrade), and the
probes target the memory interface so the same frozen pack measures that
upgrade later.

**Status: awaiting owner approval to dispatch PC-1..PC-7.**
