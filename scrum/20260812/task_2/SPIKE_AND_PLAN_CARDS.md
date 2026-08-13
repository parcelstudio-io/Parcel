# Cards S-1 and P-1 — design-artifact lane (no product code)

Both cards edit ONLY `scrum/20260812/task_1/` artifacts. MUST-NOT-TOUCH:
everything under `src/`, `configs/`, `evals/`, `tests/`, `scripts/`.

## Card S-1 [sol] — harden the design spike to its own invariant list (RC-1)

The Fable audit proved the spike's enforcement is weaker than its claims:
prior-epoch leases authorize, NaN timestamps fail open, LATCHED_STOP is a
stateless label, and 12 of 20 invariant-killing mutants survive the 43-test
suite (`../task_1/FABLE_VERDICT.md` RC-1, all upheld 2-0 with executed repros).

Implement, in `../task_1/design_spike/`:

1. **Epoch enforcement (RC-1a):** a lease whose epoch predates the gateway's
   current boot epoch must refuse authority; model restart-disarm statefully
   (gateway state carries `current_epoch`; a fresh instance starts disarmed)
   or explicitly descope with a named product-test obligation in the README.
2. **Fail-closed on malformed time (RC-1b):** NaN/None/inf in ANY clock,
   timestamp, or TTL field of candidate_verdict / terminal_verdict /
   behavior_verdict inputs → HOLD or LATCHED_STOP, never PASS. Add these as
   corruption classes to the seeded campaign.
3. **A real latch (RC-1c):** LATCHED_STOP persists across subsequent clean
   ticks until an explicit operator-clear event with fresh stationary
   feedback — model the state, don't rename the enum.
4. **Kill the mutants (RC-1d):** re-run the audit's 20-mutant campaign
   (12 survivors enumerated in the audit workflow record; reconstruct from
   RC-1's classes: epoch drop, source-clock-for-receipt swap, UNKNOWN-origin
   admit, disposition max→min, settled-feedback skip, second-writer-after-
   release, sender-absolute-TTL, AMBIGUOUS-translation admit, and the NaN
   family). Every one must be killed by a named test. State the final
   kill count in S1_STATUS.md.
5. **Verdict N-items:** align the Resource enum to the canonical 6 (N-4);
   add a composed physical-translation pipeline test threading origin/frame/
   freshness end-to-end (N-2); zero-gate dominant_verdict must not PASS and
   at least one gate must produce CLAMP (N-3).
6. **RC-2 contract fixture:** add the pose-uncertainty reserve field to
   TerminalWitnessV2 in the spike and a B5-shaped fixture (MAP margin 0.007 m
   < claim-tick pose error 0.239 m ⇒ terminal_verdict must NOT pass; the
   numbers are backlog/BLOCKED.md B5's measured episode). Read-only reference
   to backlog/BLOCKED.md permitted.
7. Honesty fix: the campaign description ("200-case") states its true class
   count (RC-1d / verdict "claims to downgrade").

GATE: spike suite 100% green (count will grow past 43 — state the new count);
ruff clean; 20/20 mutants killed with the mutant list in S1_STATUS.md;
`git diff --check` clean. does_not_prove preserved and extended.

## Card P-1 [sol] — plan revision r2 (RC-2..RC-6 + N-5..N-8 text)

Revise `../task_1/PRODUCTION_COMPANION_PLAN.md`, `RESEARCH_LEDGER.md`,
`VALIDATION.md` per the verdict. Every edit cites its RC/N item:

1. **RC-2:** TerminalWitnessV2 spec gains the required localization-
   uncertainty reserve term; required-test list gains the pose-reserve
   arrival regression named on B5's episode. State that product arrival
   changes remain owner-gated (B5 2×2).
2. **RC-3:** the final-governor/speed-envelope section gains directional/
   closing-relevance semantics language and cites B6; the bearing-relevance
   brake regression joins the required-test list; Wave-2/3 exit gates are
   explicitly conditioned on the B6 owner decision.
3. **RC-4:** W0-C's card text gains the TTL/latency derivation table
   obligation (live `command_timeout_s = 0.35 s` vs each proposed p99 gate vs
   the 50 Hz loop) as a pre-freeze deliverable, and states whether Wave 0
   retunes the TTL (recommend: derive first, retune only with measurement).
4. **RC-5:** P0-9 and the ledger row corrected to the 10 Hz runtime semantic
   loop (which dispatches motion); W0-G budget analysis language updated.
5. **RC-6:** re-baseline every W0 card on commit `7242660`; VALIDATION.md
   gains the re-run gate figure (3943) and discloses the 3,889 transient.
6. **N-5:** define W0-F's "Fable gate" (what it gates, when it runs, what
   reddens it). **N-6:** reconcile the load-shed order with the stated
   priorities. **N-7:** add abandonment criteria for RPP and for the hybrid
   architecture itself (brief Q12), and mark every numeric target "proposed
   pending hazard/ODD derivation" where not already. **N-8:** record the
   210/211 selection as unreproducible; fix the Piper "service" wording.

GATE: every RC/N item traceable to a diff hunk (list them in P1_STATUS.md);
no other content drift; `git diff --check` clean; VALIDATION re-run executed,
not hand-edited.
