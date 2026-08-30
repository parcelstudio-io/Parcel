# DMC-2 — production transaction and narration-evidence conformance

Status: **FROZEN BEFORE IMPLEMENTATION**  
Date: 2026-08-29  
Evidence tier: desktop, deterministic product-contract replay; no physics,
sensor, acoustic, hosted-model, gateway, or hardware evidence.

## Why this experiment exists

DMC-1 was useful as an architecture shakeout, but independent review found
that its research-only ledger accepted a terminal receipt with the wrong step
and attempt, accepted `started` after a terminal, and licensed a fabricated
terminal narration when it reused an unrelated receipt ID. Its aggregate
narration counters therefore cannot support Model-B truthfulness.

DMC-2 tests the corresponding shipped Parcel seams directly:

- `TaskExecutive.report` for task/revision/step/attempt/state ownership;
- `apply_action_receipt` for authenticated, ordered dialogue evidence; and
- `license_terminal_claim` for the final boundary between a model proposal
  and a narratable physical outcome fact.

This is a conformance and adversarial-integrity experiment, not a learned
model benchmark. It deliberately makes no language-generalization claim.

## Frozen hypotheses and gates

All rates use exact counts over the frozen manifest. Safety/integrity gates
are zero-tolerance because one accepted fabricated terminal is sufficient to
invalidate the narration boundary.

**H1 — executive result integrity.** The production executive accepts 100%
of exact, in-state execution results and rejects 100% of results with a wrong
task, revision, step, attempt, state/order, or unverified success fact. No
rejected result may cause the task to become `succeeded`.

**H2 — authenticated receipt integrity.** The dialogue reducer accepts 100%
of valid `started -> terminal` streams and rejects 100% of raw/untrusted,
wrong-channel, wrong-action, premature-terminal, duplicate, regressed,
future, expired, or post-terminal receipts. No rejected receipt may create a
completed action or remove/replace the pending action.

**H3 — terminal narration integrity.** The claim license accepts 100% of
fresh exact-match terminal claims and rejects 100% of claims backed by a
start receipt, wrong authenticator, wrong receipt ID/content, wrong
mission/action/name/manifest/status, unretained evidence, future proposal,
stale proposal, or expired receipt. No rejected proposal may yield a verified
dialogue claim.

**H4 — trace determinism and independent verification.** Two complete runs
over the same manifest have identical normalized trace digests, and a
separate verifier that never calls the production reducer recomputes every
case's expected acceptance, terminal-mutation allowance, and aggregate from
the retained input/output/pre-state/post-state trace.

Promotion gate: H1–H4 must all pass. A pass promotes only the transaction and
narration-evidence contracts to continued desktop/HIL use; it does not
promote Model A, Model B wording quality, navigation, or physical motion.

## Frozen population

- Seed: `20260829`.
- 256 independently named trials for each of the three seams.
- Every trial runs one valid control and every corruption family listed in
  its hypothesis, using fresh state. The same immutable case payload is fed
  to the product and recorded for the oracle.
- Names, IDs, timestamps, terminal statuses, and plans vary by trial. A
  keyed per-case derivation makes content reproducible and prevents one
  system arm from receiving a different schedule.
- Executive, receipt, and claim namespaces are disjoint. DMC-1 names and its
  authored command templates are not reused.

Because this benchmark contains no fitting, there is no train/dev split. Its
entire population is a frozen test manifest. Future implementations must add
new additive manifests rather than edit this one.

## Trace schema

Each JSON trace row retains:

```text
case_id, seam, corruption, seed, expected
input                 # complete serialized result/receipt/claim payload
pre_state             # canonical product snapshot/read-model mapping
observed               # accepted/licensed, reason/action, verified-claim flag
post_state            # canonical product snapshot/read-model mapping
state_digest_before, state_digest_after
terminal_mutation_allowed
oracle_pass
```

Authenticated wrapper secret material and HMAC tags are never serialized.
The trace records the wrapper's channel identifier and whether the production
authenticator verified it. This is sufficient for audit without turning the
artifact into a reusable authority token.

The independent verifier checks the trace schema, exact case inventory,
unique IDs, case-derived expectations, state-digest integrity, zero forbidden
terminal mutations, and aggregates directly from rows. It refuses missing or
extra cases and recomputes the normalized digest. It does not import or invoke
`TaskExecutive`, `apply_action_receipt`, or `license_terminal_claim`.

## Execution plan

1. Write the frozen manifest and its SHA-256.
2. Run the product-contract harness twice in isolated processes.
3. Run the independent trace verifier on each result and compare normalized
   trace digests.
4. Add a capability-proof pytest for the harness/oracle boundary through the
   required pytest guard.
5. Publish `RESULTS.md` and an independent `VERDICT.md`, including all red
   cases rather than rerunning them away.

## Unsupported claims

Even a perfect result does not measure task parsing, steering classification,
free-form narration wording, hosted Realtime behavior, ASR, audio duplex,
navigation success, pedestrian prediction, braking, collision avoidance,
gait stability, power/thermal behavior, sim-to-real transfer, Orin timing, or
Go2 mount readiness. Physical motion remains **NO-GO** until the separate
hardware promotion ladder passes.
