# Fable audit — Wave-0 tranche 1 (S-1, P-1, W0-A, W0-B), 2026-08-12

## Verdict: all four cards CONFIRMED. The tranche closes green.

Closing gate (Fable's run, streaming channel, `TMPDIR=/home/jaewoo-jang/.t`):
**`RESULT: PASS — every hard gate green`, elapsed 201.3 s**, at the final
post-polish source. The preceding full run at the pre-polish source measured
**4,076 passed / 0 failed** (= 3,943 at sprint close + the tranche's product
tests); the polish passes added 7 more cells, executor-measured green
(W0-A 318/0 across nine suites; W0-B 203/0 including the factory-covering
suites re-run AFTER W0-A landed — cross-card composition confirmed).

## Adversarial audit

Three hunters (W0-A provenance attack, W0-B unreachability/forgery attack,
OWNS/claims/deferred checks), refutation panels armed on any major:
**zero blocking, zero major findings** — no panel fired. Executed-clean:
every spoof lane (no string ever reaches PHYSICAL; adversarial strings incl.
"physical"/"unitree_sport"/str-subclass latch; default-constructed boundary
objects fail closed), the CommissionedStateSource wrapper, the D-2 physical
table, the AF-2 byte-identity digests re-run at final source, W0-B's factory
registry/config-string/duck-typing/CLI unreachability, arming-token and
review-gate forgery attempts, limit refusals (refuse, never clamp), and full
diff-vs-OWNS attribution (21 paths, each to exactly one card).

Minors, all dispositioned in the same tranche:

| finding | disposition |
|---|---|
| ordering-latch equal-keys content-identity gap (unreachable via shipped adapter; matters for W0-C adapters) | fixed + seeded test + over-tightening guard (W0-A polish) |
| None-deref on protocol-violating write-only source | fixed + injected-manager test (W0-A polish) |
| W0A_STATUS "byte-identical" overstatement (AST-identical, 15 comment lines, PIN_DRIFT 0) | doc corrected to what is true |
| `evidence_origin.py` had no leaf-ness pin | pin test added (AST walk + subprocess sys.modules probe) — condition of **D-5** ratification |
| W0-B teardown journal-write failure (Errno-122 class) could still destroy the record one layer down | fixed: best-effort `try_*` journal path, in-memory `JOURNAL_WRITE_FAILED` latch, record survives, degradation fails closed via `missing_evidence()`; 3 seeded EDQUOT tests |
| W0-B §5 line counts were estimates | re-measured (+5,038/−140 card total; `factory.py` +250/−0 confirms additive) |
| H7 transient: one ISC004 fingerprint in W0-A's new test mid-pass | self-caught and fixed by W0-A before close; final gate green confirms |
| infos: epoch latch inert for shipped adapter (matches declared H-handoffs); nav-internal scan gate residual (= D-1/H2, out of OWNS) | recorded, next-tranche/W1 items |

## Environmental incidents — root-caused, none waived

1. **Host quota outage**: `/tmp/claude-1000` quota exhaustion broke the Bash
   tool layer for every session (exit-1-empty signature; test failures with
   `OSError: Errno 122`). Worked around via the streaming Monitor channel +
   `TMPDIR` off the quota'd tmpfs. **RESOLVED 2026-08-13** (owner-approved):
   the stale foreign scratch tree
   `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects` (another project's,
   newest content 2026-08-03) is deleted. It had already shrunk from the
   measured 89 GB to an 82 MB remnant by the time approval landed — the bulk
   was reclaimed out-of-band overnight. Removal needed `chmod -R u+rwX` first:
   the BARN candidate-bundle directories inside it are frozen `dr-xr-xr-x`, so
   `rm -rf` alone hit permission-denied on every file under them. Post-state:
   `/tmp` 3.7 GB / 124 GB (3%), `claude-1000` 77 MB, Bash tool layer healthy;
   this session's own scratch verified intact.
2. **Hard-link clones**: 26 BARN freeze tests reddened because W0-A's scratch
   copies were `cp -al` hard-links, raising `nlink` on repo files (the freeze
   gates assert unique linkage — they worked as designed). Clones removed,
   `nlink` back to 1, 15/15 previously-failing barn tests green. Lesson
   recorded in the channel recipe: plain copies only.
3. **AF_UNIX path length**: one socket test fails under a long redirected
   TMPDIR (~108-char limit). Short redirect (`~/.t`) resolves it; the test is
   sound.

## Board decisions

D-1 (carrier-type authority; `reactive_safety.py` untouched, migration = W1),
D-2 (physical requirements table in scope), D-3 (defaults-fail-closed as named
seeded case), D-4 (outage dispositions), D-5 (`evidence_origin.py` ratified
with leaf pin) — all in BOARD_DECISIONS.md, all discharged.

## What this tranche proves, and does not

Proves: the four confirmed P0 mechanisms this tranche targeted are closed at
the software boundary with seeded-failure evidence (typed provenance with no
string lane to PHYSICAL; commissioning bootstrap without pre-claimed flags,
un-enterable from the autonomous runtime); the hardened spike now enforces
what its invariant list claims (194 tests, 46/46 mutants); plan r2 carries
every verdict-required change.
Does not prove: anything physical — no DDS, no vendor lease, no hardware stop,
no through-air audio. Those remain W0-C+ and the evaluation ladder's upper
rungs. Nothing in this tranche arms anything.

## Next

- **W0-C dispatch** is unblocked: P-1's RC-4 TTL/latency derivation obligation
  is in plan r2; W0-C builds the gateway protocol + fake Sport service against
  it. Then W0-D/E/F/G as tranche 2.
- Owner queue: scratch-tree item discharged (see incident 1). Remaining: B6,
  then B5 — the standing product 2×2s from the sprint.
