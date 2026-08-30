# C7 · HARNESS-TRUTH-1 — research harnesses must never say "arrived" without a receipt

**Executor:** Opus · **Verifier:** Fable · **Wave:** A (research files only — no product code)

## Defects

1. LIT-1 `research/20260829/sim-loop-1/sim_loop.py` narrated "I've reached the bench. I can't check whether your keys are there…" on FAILED receipts in 5/5 base runs — deterministic harness code, not an LLM (`sim-loop-1/VERDICT_FABLE.md`).
2. NAV-INT-1 `research/20260829/nav-interrupt-1/harness.py`: a held queue utterance re-issued verbatim is refused — the harness must strip the cue on re-issue and record both the raw and stripped utterance (`nav-interrupt-1/VERDICT_FABLE.md` item 2, second defect). (The first defect — owner-referring amendment parks the robot — is C6's; the harness records it, does not work around it.)
3. NAV-GEN-1 record hygiene: `RESULTS.md` prose numbers not in `results.json` (3.25 m, 7.17 m, 0.2750), host-load and worker-count inconsistencies, `arm_config_facts` pre-A2 schema (`nav-gen-attribution-1/VERDICT.md §5.3`); MB-2: the llama-server log of the 180-turn run was overwritten by a smoke run — add a per-run log path.

## Acceptance

- LIT-1: r1–r5 re-run (fake voice tier, `PARCEL_MEMORY_PATH` → scratch, unique socket) narrate the receipt's kind on every failed receipt (`failed` → the failed act; never an arrival phrase); the 5/5 receipt-kind sequence unchanged; RESULTS.md §2–§8 PENDING stubs filled from the artifacts.
- NAV-INT-1: the re-issue row admits after cue-stripping; `gold_blind.json` sha256 `c253df2f…` unchanged (the blind set is frozen).
- NAV-GEN-1/MB-2: `analyze.py` renders every prose number; `results.json` schema corrected; README "no number typed by hand" true again.
- No product files touched; research folders of other authors untouched.
