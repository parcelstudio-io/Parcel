# 2026-08-12 task 2 — Wave-0 tranche 1 (post-verdict)

Parent: `scrum/20260812/task_1/` (Sol 5.6 companion plan) as dispositioned by
`../task_1/FABLE_VERDICT.md`: **ACCEPT_WITH_REQUIRED_CHANGES** — Iteration 3
accepted, Wave 0 may start once the verdict's required changes are folded in.
This board IS that fold-in plus the first two product cards.

**Base:** commit `7242660` (clean tree; the 20260811–12 batch landed).
**Orchestration:** Sol/Opus execute; **Fable audits the tranche** (fresh
ci_gate, diff-vs-OWNS, one independent re-run per card, adversarial verify on
W0-A's provenance semantics). Working agreements inherit
[../../20260804/task_1/README.md](../../20260804/task_1/README.md).

## Board

| Card | Owner model | Files (OWNS) | Est. | Depends on |
|---|---|---|---|---|
| S-1 spike hardening (RC-1, RC-2 contract, N-1..N-4) | sol | `../task_1/design_spike/**` only | 4–6 h | — |
| P-1 plan revision r2 (RC-2..RC-6 text, N-5..N-8) | sol | `../task_1/*.md` only | 2–3 h | — |
| W0-A physical feedback + typed provenance (P0-1, P0-2) | opus | `control/base.py`, `control/models.py`, runtime state-source wiring, `core/input_health.py`, focused tests | 8–12 h | — |
| W0-B commissioning-only path (P0-3) | opus | `control/factory.py`, `unitree_control.py`, new commissioning record module + tests | 8–12 h | — |
| Fable tranche audit | fable | `AUDIT_TRANCHE1_FABLE.md` here | — | all four |

All four cards are pairwise file-disjoint and run in parallel. Cards are
specified in [SPIKE_AND_PLAN_CARDS.md](SPIKE_AND_PLAN_CARDS.md) and
[W0_PRODUCT_CARDS.md](W0_PRODUCT_CARDS.md).

Deliberately NOT in this tranche: W0-C (gateway — blocked on P-1's RC-4
TTL/latency derivation table), W0-D/E/F/G (next tranche; W0-F additionally
consumes S-1's hardened spike), everything Wave 1+.

## Global rules (binding on every card)

1. `ci_gate --tier commit` GREEN to close; red = fix or STOP-and-report.
2. Frozen artifacts immutable; frozen-row movement = STOP + 2×2.
3. Flags/config default to today's behavior; any behavior change on the
   simulator path needs byte-identity proof or an explicit migration note.
4. **No safety weakening.** The B5 (arrival predicate) and B6 (collision
   brake) product surfaces are owner-gated — no card here touches
   `apply_collision_brake`, the K0 arrival predicate, or their configs.
5. OWNS/MUST-NOT-TOUCH per card; `runtime.py` single-owner = W0-A.
6. Constants derive or carry documented provenance; no tuning to a gate.
7. Measured claims, `does_not_prove`, seeded-failure proofs for property
   tests. Status docs in this folder (`S1_STATUS.md`, `P1_STATUS.md`,
   `W0A_STATUS.md`, `W0B_STATUS.md`).
8. **No physical arming.** Nothing in this tranche may create a path that
   moves a real robot; W0-B's commissioning manager must be un-enterable from
   the autonomous runtime (its own gate).

## Definition of done (tranche)

- S-1: 20/20 mutants killed, epoch/NaN/latch enforced, campaign classes
  extended, spike still 100% green and ruff-clean.
- P-1: plan r2 carries every verdict-required text change; VALIDATION re-run
  at `7242660` recorded.
- W0-A/W0-B: card gates from the plan (quoted in the card files) green;
  simulator behavior and frozen evals byte-unmoved.
- Fable audit CONFIRMS all four; verdict recorded here.

## Handoffs expected out of this tranche

- W0-C dispatch brief (needs P-1's TTL derivation).
- Any product defect S-1's B5/B6 contract fixtures reveal beyond the known
  owner items goes to `backlog/`, not into scope creep here.
