# Task 15 — M-1: numbers that survive a denominator (the measurement pack)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Authority:** scrum/20260821/benchmarks/SYNTHESIS.md ("no Parcel number
survives contact with a benchmark denominator") — items 1, 4, 6 of its
run-list. **DISPATCH GATE: after the W1–E2 chain closes and audits.**

## Work
1. **pass^k corpus run (k=3)** on the current build via the R17 UI-mounted
   runner: all 52 gold queries × 3 independent trials, per-category pass^1
   vs pass^3 reported with Clopper-Pearson intervals. THE number this
   produces: the spoken e-stop's measured reliability across ≥9 trials
   incl. q34 "Dye. Stop." (finally) and the impostor-estop rows.
2. **SLURP-style joint intent+slot accuracy** over the same runs (categories
   ≈ intents, tool args ≈ slots) — the cheapest benchmark-shaped number.
3. **FDB-v3 latency definitions adopted**: end-of-user-speech → response
   start, task-completion-inclusive separately; replaces our ambiguous
   0.78 s claim everywhere it is cited (append corrections, don't rewrite).
4. Pack in the E1 layout at `evals/2026MMDD/measurement_run_1/`; failures
   recorded as failures and carded.
OWNS: the run pack, runner config, correction appendices, `M1_STATUS.md`.
MUST NOT TOUCH: any source (measurement only — defects found are carded,
never patched inline). Spend cap $6 (156 hosted turns).
DoD: pack complete with denominators + intervals everywhere; e-stop pass^k
headline with its honest bound; standard register (no seeds — no source).
