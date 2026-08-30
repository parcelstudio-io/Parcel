# DMC-4 results

Date: 2026-08-29  
Decision: **DMC4_COMPOSED_PASS** for the preregistered desktop transaction property

## Gate results

| Gate | Result | Retained evidence |
|---|---|---|
| H1 completeness and exact-once lineage | PASS | 64 cases for each of 7 families; 1,824 accepted mutations per run; zero oracle mismatches; required outcomes present; rejected/no-op journal deltas were zero |
| H2 bridge composition | PASS | All 1,824 journal rows mapped one-to-one, authenticated, and were consumed in sequence; exact replay rejected; parent/child lineage exact; invalid-success failures consumed silently |
| H3 fail-closed corruption | PASS | 256/256 corruptions handled across all 20 preregistered classes; no corrupt/gap/overflow wording frame and no snapshot recovery |
| H4 concurrency and boundedness | PASS | 32 producer threads plus consumer completed without error/deadlock; normal sequence 1–32 exact; capacity-8 run retained 8, reported 24 overflows, and exposed `journal_overflow` before any post-gap event |
| H5 non-actuation and regression | PASS | Static surfaces/imports clean; focused guard 28 passed; broad guard 307 passed, 4 retained skips, 2 existing deprecation warnings |

Both fresh runs produced the same normalized trace
`4814882460c6101c202c21d6e49d5c47d4ffe14b5dbcec70b49c82109db2c45e`
and chain root
`a928bdaba0c5900b87648fdd0ae36f5e5bf2062d60d5bb62e2648e516b2874c2`.
Each retained JSON file has SHA-256
`d81adf575b76d92a787ac935238896525bc4ca5c824bc152a6fe5693db217bb3`;
each embedded result digest is
`d42e40ef3dbd094747e842109b6beb21aa72be5a6db004a24cd2c5bfb469ea48`.

The independent verification artifact passed H1–H5 static on both runs with no
errors. File SHA-256:
`9407a917a3785023fdde7cc827b187681bac326181c5546c8fe04cafdf26500a`;
embedded verifier digest:
`53a1f85a6325fb7914e0023f137869db4f78f1356e0f5b76445cc7cff757d8f6`.

The tamper artifact detected all five mutations. File SHA-256:
`6b93f49fcb75d211374ef8ec1ab56113ae73026d123ccdf2de8cb2f6b656cf75`;
embedded digest:
`b57518ed87aeb103f83c23028711ce5b1be74fe4496044f27713afef10b0229c`.

The reported peak process RSS was 1,820,604 KiB in each fresh run. This is the
process high-water mark of the repository Python environment, not an isolated
journal allocation measurement; DMC-4 had no preregistered RSS threshold.
Boundedness was instead directly verified from journal/event capacities and
overflow counts.

The prior DMC-3 evidence was not edited. Its retained `run_a.json` and
`run_b.json` each remain at SHA-256
`27e5228f35037c8bb9342e3159791b8e2eba963e8a0cdd80c1b74539305ffaa0`.

## Post-evidence maintenance

A later static pass found an unresolved public type annotation and a lost
resource-conflict diagnostic on failed in-place resume. The separately frozen
[maintenance study](MAINTENANCE_RESULTS.md) fixed those defects and reproduced
the original normalized trace and chain root in two valid fresh runs. Its
verdict is `DMC4_MAINTENANCE_EQUIVALENCE_PASS`; the original artifacts remain
unchanged.

## Files

- `run_a.json`, `run_b.json`: complete raw evidence
- `verification.json`: independent verifier output
- `tamper_results.json`: five-part tamper capability result
- `source_manifest.json`: pre-evidence frozen hashes
- `regression_evidence.json`: pre-freeze and post-evidence guarded test counts
