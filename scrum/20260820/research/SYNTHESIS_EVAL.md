# Eval-model + speech-identity synthesis · Fable · 2026-08-20

Inputs: five reports in this folder (three research sweeps, two prototype
benches — four eval-model prototypes tested on real project data; hardware
feasibility measured on the owner's actual mic array). Total spend ≈ $0.05
of $4 authorized. Every decision below cites its evidence.

## Eval-model decisions (→ card EV-1, task_11)

1. **The commit gate gets Prototype B: programmatic assertions over
   persisted session artifacts.** Evidence: 5/6 of the real owner-session
   failures caught with ZERO false positives across 194 ledger rows, $0,
   <1 s, byte-identical reproducibility — vs the rubric judge's 2 hard
   FPs/run and unstable incident lists (Jaccard 0.41–0.78). Effect size:
   0/6 failures caught automatically today → 5/6.
2. **Prereq elevated to first-class: persist the full event stream.** Every
   false positive in B's extended checks was a 100-slot ring-buffer
   eviction artifact; the run-scoring agent hit the same wall attributing
   the e-stop latch. A per-session JSONL event log (plus ASR n-best and,
   post-R17, audio provenance) is the substrate the whole eval model
   stands on.
3. **Verdicts anchor in sim ground truth and goal predicates, never in the
   conversation** (τ-bench's database-state lesson; BEHAVIOR's
   goal-literals; our queries.tsv expected column is already this shape).
   Dimension scores report as a fixed matrix — per-dimension gates, NO
   blended scalar, safety never averaged against charm (HELM's lesson).
4. **pass^k for reliability-critical behaviors:** e-stop scored fail-closed
   across k independent trials — F6-class misses are invisible to
   single-run scoring by construction.
5. **The eval harness itself gets seeded-defect treatment:** a null agent,
   an always-claims-success agent, and a random-tool agent run through
   every suite; any suite they pass is broken (Agentic Benchmark Checklist
   — benchmarks mismeasure by up to 100% relative from exactly these bugs).
6. **Nightly, never gating:** the 7-dimension rubric judge WITH the
   provenance-aware rubric line (ablation flipped F1 from 0/3 missed to
   caught, $0.003), trend lines + incident review queue only; plus the
   e-stop phonetic review queue at 0.55 (~4 flags/session). ~$0.02/night.
7. **Per-release:** pairwise AutoRater with PER-PAIR direction gold written
   at authoring time (era-level gold measurably fails: 40% of extracted
   pairs had wrong-direction gold); BLOCKED on a GPU llama.cpp build
   (4.6 h CPU for 14 pairs today). User-simulator only after an ASR-noise
   injection layer (real spoken input is 23% fragments; the simulator
   produced 0% — decisive realism fail).
8. **Meta-eval:** a frozen owner-labeled verdict set (~50–100), judge-owner
   agreement tracked as its own regression metric; judge stays a different
   model family from the policy (self-preference neutralization).
9. **Recorded-vs-live rank consistency** checked periodically (Gemini
   Robotics practice): variant orderings on recorded fixtures must match
   live-session orderings, or the fixtures have drifted.

## Speech-identity decisions (→ card F1-SI, task_12)

1. **Primary gate: post-VAD speaker-embedding verify in the audio gateway**
   — titanet_small (40 MB, sherpa-onnx, CPU): same/cross cosine 0.802 vs
   0.033, zero overlap on 378 pairs, 27 ms median added latency, 115 ms
   one-time load. Threshold starts 0.50–0.55 (midpoint of the measured
   worst gap), fail-closed for COMMANDS.
2. **Safety asymmetry, binding:** the EMERGENCY LATCH is NEVER
   identity-gated — anyone may stop the dog; only command/conversation
   arming requires the owner's voice. (Fail-closed means: unverified voice
   cannot start motion; it can always stop it.)
3. **Prefilter: XVF3800 DoA sector + hardware VAD** — the read path exists
   on this host (vendor interface free, tooling staged in scratch), blocked
   solely by a udev permission the owner must grant (exact 2-line command
   in the bench report). TV-sector rejection is nearly free once readable.
   AEC is NOT a defense here (it cancels the robot's own speaker only) —
   confirmed by both the research and live evidence.
4. **Enrollment:** 5–10 owner utterances, averaged embedding; the material
   gap is that NO real owner audio exists on disk (all prior probes were
   room tone; corpus WAVs were never recorded) — enrollment recording is
   an owner action, cleanly done via record.sh with the stack paused, or
   extracted from the first R17-captured session.
5. **Transcript-level heuristics stay as the eval layer, not the defense:**
   the Unicode-script anomaly check catches the Korean-TV instance
   deterministically but a same-language TV defeats every transcript-level
   layer — which is precisely the eval-gap-as-capability-evidence argument
   for this card.

## Owner actions on file

(a) the udev rule for DoA (2 minutes, sudo, does not disturb the stream);
(b) an enrollment recording (~1 minute of speech); (c) the standing
questions: reply-language policy for Korean, and the q34 "Dye. Stop."
matcher-widening measurement.
