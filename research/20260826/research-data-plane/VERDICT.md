# Verdict

Date: 2026-08-26

## Decision

Proceed with an isolated, local-only research data-plane pilot; do not enable off-robot raw upload or automated learning on the physical prototype yet.

A subsequent P0 package now implements the local/default-off boundary described
in this verdict. Its exact scope is in `IMPLEMENTATION.md`. The original
14,532-event result below remains synthetic evidence and is not reclassified as
a cloud, cryptography, network, deletion, or physical result.

The architecture is technically feasible and the local mechanism probe is encouraging: 14,532 typed events passed a dedicated spool, deterministic content-addressed bundles, a resumable byte-cap simulation, and exact replay; all six predeclared hypotheses passed. Summary volume appears cheap and compatible with a conservative Starlink byte envelope.

Readiness by layer:

| Layer | Verdict | Reason |
|---|---|---|
| Schema + local spool | Ready for a default-off development pilot | versioned typed envelope, isolation/path guard, idempotency, bounded bundles and strict local composition implemented |
| Deterministic bundle/replay | Ready for a development pilot | stable count/digest across two processes; corruption caught |
| Summary-first traffic/cost model | Directionally ready | 0.363 GB/month synthetic projection, but physical cadence is unmeasured |
| Raw physical recording | Reuse existing MCAP/sidecar path | stronger than the sim JSONL path; reference-reader/field-session proof still required |
| Privacy/consent/retention | Not production-ready | local subject/destination binding and expiry/revocation cascade are implemented; arbitrary de-identification and remote/catalog/cache/backup erasure remain unproved |
| Encryption/access control | Provider-verifier seam only | missing providers fail closed, but AES-GCM, KMS, TLS/IAM, restore, rotation, and cryptoshred are not implemented or demonstrated |
| Starlink/object-store sync | Not tested | local simulation is not a network or cloud result |
| Offline learning promotion | Proposal-only contract; not ready for autonomy | immutable splits, safety/eval digests and review/signature/rollback gates exist, but no trainer, trusted signing service, deployer, or activation path exists |

For mounting the broader prototype, this data-plane work is not a blocker if it stays off or local-only and cannot consume control-loop resources. It is a blocker to any claim that the mounted robot can safely upload long-term research data, retain personal data correctly, or improve itself automatically.

## Simulator feasibility

Using the simulator is highly feasible and worthwhile for capabilities that depend on repeatability:

- generate navigation/perception failure families and controlled perturbations;
- test event schemas, drop/gap accounting, byte caps, retention, consent revocation, corruption, and replay determinism;
- compare candidate conversation/navigation policies offline against identical runs;
- build counterfactual labels from logged candidates and committed choices;
- verify that a promoted model improves task metrics without regressing safety/conversation suites.

The simulator cannot validate sensor entropy/noise, visual domain shift, room acoustics, bystander privacy, actual Starlink behavior, Orin thermal/power/storage throughput, physical locomotion, or human consent experience. Sim gains should select candidates for physical evaluation, never waive it.

## Minimum next experiment

Before enabling off-robot sync on a physical session, run one bounded, operator-consented end-to-end pilot:

1. Capture selected physical topics through the existing MCAP + sidecar path with motion safety unchanged.
2. Generate summaries into a new dedicated research spool; prove the process cannot open the owner database.
3. Encrypt each bundle client-side with AES-256-GCM and a managed test KMS key.
4. Upload through a 50 MiB/day fail-closed governor over a deliberately interrupted link; resume without duplicate bytes and verify remote checksums.
5. Revoke the consent and demonstrate deletion from spool, object store, catalog/cache, and one derived dataset while retaining only a non-content receipt.
6. Replay the surviving dataset from an empty workspace and reproduce its manifest, counts, and evaluation metrics.
7. Measure CPU, disk, temperature, power, event drops, physical sensor rates, and actual network bytes. Fail the pilot if safety/control timing changes or evidence gaps are silent.

Only after that experiment should the project decide whether to enable summary sync by default for a named research protocol. Raw audio, image/video, exact location, companion facts, and embeddings should remain off by default and separately consented.

Full architecture, retention, encryption, lineage, cost, and evidence details
are in `DESIGN.md`; measurements and limitations are in `RESULTS.md`; the P0
code ceiling is in `IMPLEMENTATION.md`; primary sources are enumerated in
`source_manifest.json`.
