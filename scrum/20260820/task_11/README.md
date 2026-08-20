# Task 11 — EV-1: the eval model (assertions gate, persisted evidence, judged nightly)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Design authority:** scrum/20260820/research/SYNTHESIS_EVAL.md decisions
1–9, backed by bench_eval_designs.md (four prototypes tested on real data)
and res_agent_evals/res_dialogue_evals. The winning prototype's code is at
`<scratchpad>/evalbench/fable-bench/proto/` — productionize it, don't
reinvent it.
**DISPATCH GATE: after R21 closes.**

## Work

1. **Session evidence persistence (the substrate):** a per-session JSONL
   event log (every runtime event, uncapped, rotated per session) + ASR
   metadata capture (n-best/deltas — the 88 provider events currently
   dropped as unknown types get typed no-op-with-retention treatment in the
   codec's EXISTING lifecycle pattern), written beside the R17 audio
   recordings' layout. The 100-slot UI ring stays as the UI's view; evals
   read the persisted stream.
2. **The assertion suite** (`evals/assertions/` — Prototype B's 11 checks
   productionized): script-anomaly provenance, completion-claim vs
   terminal-event, blindness-claim vs perception state, amnesia-claim vs
   store contents, rollover hygiene, tool provenance, unanswered turns,
   ordering inversions, latch/negative-latch outcomes, refusal-on-invalid
   place, beat suppression vs answer delivery. Runs over any session
   folder; wired into ci_gate as a HARD gate over a small frozen fixture
   set + the latest committed run folders.
3. **Harness self-test:** null agent / always-claims-success agent /
   random-tool agent fixtures through every suite — any suite they pass
   fails the gate (assertion-on-the-assertions).
4. **Dimension matrix + pass^k:** verdict output as the fixed
   dimension × suite matrix (no blended scalar; safety gates
   independently); e-stop behaviors scored pass^k fail-closed (k≥3 in
   nightly, k=1 smoke in commit tier for cost).
5. **Nightly runner:** the provenance-aware rubric judge (trend + review
   queue, never gating) + the phonetic e-stop review queue; config-capped
   spend; outputs a dated folder in live_run format.
6. **Meta-eval scaffold:** the frozen owner-verdict set format + agreement
   tracking (population of the set itself is an owner task, listed
   owner-gated).

OWNS: `evals/assertions/` (NEW), the JSONL event persistence
(`runtime.py` + a small writer), `realtime/protocol.py` ONLY for typed
retention of the currently-dropped ASR event types (additive, the
LifecycleEvent precedent), `scripts/ci_gate.py` (ONE new hard gate entry —
this is the first card allowed to touch it since R1; smallest possible
diff, gate list documented), nightly runner script, tests, `EV1_STATUS.md`.
MUST NOT TOUCH: lane behavior, broker, ingress, prompting, whisperer bands,
existing frozen eval packs (they become fixture INPUTS, read-only), yield.
DoD: full gate green INCLUDING the new assertion gate; ≥10 seeds RED
(each F-check disabled one at a time must redden the suite via the frozen
fixtures; null-agent passes a suite; event log capped/evicted again;
blended scalar introduced); the assertion suite reproduces the live_run_1
scoring's F-findings from raw artifacts alone; standard register.
