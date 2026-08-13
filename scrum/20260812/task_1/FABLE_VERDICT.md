# Fable verdict — production companion plan (task_1), 2026-08-12

Reviewer: Fable, refute-first per FABLE_REVIEW_BRIEF.md. Method: 5-hunter
adversarial workflow + 2-refuter panels on every major (25 agents; every
blocking/major claim below carries an executed reproduction, and every upheld
finding survived two independent refuters). Tree at review close: commit
`7242660` (the 20260811–12 batch landed mid-review), ci_gate PASS 3943/0.

```text
VERDICT: ACCEPT_WITH_REQUIRED_CHANGES
```

Iteration 3 (Parcel brain + autonomy sidecars + native sole-writer gateway) is
ACCEPTED as the architecture. Wave 0 is ACCEPTED to begin once the required
changes below are folded into the cards — none of them changes the architecture;
all of them change what Wave 0 must prove.

**What verified clean (coverage, so the acceptance is not polite):** all 11 P0
codebase defects CONFIRMED at their cited mechanisms (line drift ≤1 line; P0-6's
open-loop branch found at grid_navigator.py:370-392 behind
`safe_valley_micro_advance=False`); every "Local evidence reviewed" number
reproduced from artifacts (v4 SR 0.24/SPL 0.19326/failures 3-6-6-4 exact; follow
bench 7/9, band 0.7088, jerk 1.2187 exact; duplex 5/9 gates and all four p50s;
Gemma 6/10 + TTFT 349/469; PersonalConvo 3/13, 1/8); all 24 checked external
primary-source claims VERIFIED with zero mismatch (Unitree Move/StopMove surface,
Humble recommendation, L2 SDK, XVF3800 AEC-reference path, Gemma 4 family +
function-calling docs, NIST 800-63B voice-auth prohibition, all five Nav2
component pages, GLIM/KISS-ICP/ViNT/OpenVLA/openpi caveats as quoted); the spike's
43 tests and ruff pass reproduce; EvidenceEnvelopeV1 anchor exact at
contracts/v1.py:432; ControlManager single-writer/TTL/compensating-stop claims
exact. The research is honest. The gaps below are gaps, not rot.

```text
BLOCKING FINDINGS (all upheld 2-0 by refutation panels):

RC-1  Design spike enforcement is far weaker than its invariant list claims.
      (a) LeaseV1.epoch is dead data — a prior-boot-epoch lease AUTHORIZES
          motion; restart-disarm has zero enforcement.
      (b) NaN fail-open: malformed clocks/timestamps in candidate_verdict,
          terminal_verdict, behavior_verdict AUTHORIZE instead of holding —
          the exact "malformed payload latches" invariant, inverted.
      (c) LATCHED_STOP is a stateless enum label; nothing latches. A
          frame-mismatch latch is followed by PASS on the next clean call.
      (d) Mutation campaign: 12 of 20 invariant-killing mutants SURVIVE the
          43-test suite; the "200-corruption campaign" is 200 draws over 12
          single-fault classes, evidence-stream-only.
      Owner: spike (fix before W0-F ports anything). Falsifiable: 20/20
      mutants killed; epoch/NaN/latch corruption classes added to the
      campaign; a stateful latch (or an explicit descope moving the latch
      obligation to a named W0-F product test).

RC-2  B5 absorption: TerminalWitnessV2 as specified does NOT close the
      arrival-honesty class this repo already measured (backlog B5 — the
      predicate consumes 100% of the K0 band; 3/7 reanchoring-arm arrivals
      TRUE-outside; covariance 3.6x optimistic). The contract needs a
      required localization-uncertainty reserve term, and the required-test
      list needs the pose-reserve arrival test with B5's measured episode as
      the named fixture. Product-side arrival changes stay owner-gated (B5
      2x2) — but the CONTRACT must not re-create the defect.
      Owner: plan §contracts + W0-F. Spike change: yes. Product: gated on B5.

RC-3  B6 absorption: the plan's speed-from-evidence envelope uses bare scalar
      clearance with no directional/closing-relevance semantics — it
      REPRODUCES the wedge class B6 measured (apply_collision_brake zeroing
      commands for an obstacle 88 deg off-axis at exactly the stop radius;
      40/42 route-memory eval cells failed wedge-like, flag-OFF). And the
      plan's Wave-2/3 exit gates (follow band >=90%, SR -> >=90%) are
      unreachable while B6 stands. Required: the final-governor spec states
      bearing/closing-relevance semantics and cites B6; the bearing-relevance
      brake test joins the required list; Wave-2/3 exit gates are explicitly
      conditioned on the B6 owner decision.
      Owner: plan revision. Product: gated on B6 (2x2).

RC-4  Brief Q7 was never answered: the live control TTL is 0.35 s
      (control/models.py:69, configs/robot.yaml:116, factory default) and the
      plan's proposed p99 gates (sensor-invalidation <=100 ms, e-stop
      <=150 ms, client-loss <=150 ms, 50 Hz jitter <2 ms) are stated without
      reconciling against it. W0-C must publish the derivation table (TTL vs
      each gate vs the 50 Hz loop) BEFORE freezing protocol constants, and
      state whether Wave 0 retunes command_timeout_s.
      Owner: W0-C card text + a pinned derivation test.

RC-5  Rate-figure correction: P0-9 and its ledger row say the duplex
      sync-logging runs in "the 50 Hz control step". Executed: it runs in the
      10 Hz RobotRuntime semantic loop (loop_hz=10, frame_hz=10) — the loop
      that dispatches motion; the 50 Hz ControlManager thread does no duplex
      logging. W0-G's fix stays correctly aimed; its budget analysis must use
      the real loop.
      Owner: plan + ledger text; W0-G unchanged in substance.

RC-6  Re-baseline: the plan's parent "current dirty worktree" landed as
      commit 7242660 during this review; VALIDATION.md's 3,889-test figure
      was an unrepeatable mid-batch transient (today: 3943) and its
      undisclosedness is exactly the class the ledger polices elsewhere.
      Wave-0 cards re-baseline on 7242660; the file-overlap stop-condition
      is moot (verified: no W0-owned file carries uncommitted edits).
      Owner: VALIDATION.md note + every W0 card's base pointer.

NON-BLOCKING FINDINGS (record; do not gate Wave 0):
  N-1  Q6 (panel split 1-1): yaw-only candidates pass owner_motion_verdict in
       AMBIGUOUS by design (scoped identity gate; composition is the guard) —
       but bounded in-place search still lacks a fresh-surrounding-collision-
       evidence contract. Becomes a REQUIRED TEST (below), not a redesign.
  N-2  candidate_verdict ignores evidence origin/frame/freshness — physical-
       translation gating relies on caller composition the spike never
       enforces end-to-end; add a composed-pipeline test in W0-F.
  N-3  dominant_verdict of zero gates returns PASS; CLAMP is never produced
       by any gate in the model.
  N-4  Spike Resource enum has 4 values; the plan mandates the canonical 6.
  N-5  W0-F's "new Fable gate" is undefined — define what it gates.
  N-6  Load-shed order keeps the learned nav challenger longer than
       conversation despite "lowest physical priority" — reconcile.
  N-7  Q11 conceded: no numeric target carries a hazard/ODD derivation; all
       remain "proposed" until the hazard log exists. Q12 partially open: no
       abandonment criteria stated for RPP or the hybrid itself.
  N-8  "210/211 focused run" has no recorded test selection (unreproducible);
       Piper is a subprocess, not a health-checked service.

CONTRACTS ACCEPTED:
  EvidenceEnvelopeV2 (as v1 evolution), HardwareCapabilityManifestV1,
  CommissioningRecordV1, TaskTransactionV2, OwnerBeliefV1, NavigationSnapshotV2,
  MotionCandidateV2, RobotGatewayV1 (with RC-1a epoch enforcement + RC-4
  derivation).

CONTRACTS REJECTED/REVISED:
  TerminalWitnessV2 — REVISED per RC-2 (pose-uncertainty reserve required).
  SafetyDispositionV1 — REVISED per RC-1c (latch must be a stateful semantic
  or an explicitly named product obligation).

MISSING FAILURE CASES (fold into the spike campaign and W0-F):
  prior-epoch lease; NaN/None/inf in every clock and timestamp field; latch
  persistence across a subsequent clean tick; B5 fixture (MAP margin < pose
  error at claim); B6 fixture (perpendicular obstacle at stop radius must not
  zero a lateral-clear path under the governor spec); in-place search without
  fresh 360-deg collision evidence; composed physical-translation pipeline
  with SIMULATION/REPLAY/UNKNOWN origin at each stage; zero-gate dominant
  verdict; CLAMP production.

REQUIRED TESTS: the plan's own 23-item list stands, PLUS the missing failure
  cases above, PLUS: 20/20 spike mutants killed; TTL/latency derivation pinned;
  pose-reserve arrival regression; bearing-relevance brake regression.

WAVE 0 OWNERSHIP/CONFLICTS: mooted by the 7242660 landing — verified no
  W0-owned file (control/base.py, control/models.py, runtime.py wiring,
  core/input_health.py, control/factory.py, unitree_control.py, providers.py,
  duplex/*) carries uncommitted edits. W0-A/W0-B/W0-C/W0-D/W0-E/W0-F/W0-G OWNS
  are pairwise disjoint as written; keep runtime.py single-owner (W0-A).

CLAIMS THAT MUST BE DOWNGRADED:
  "The isolated reference model executes 43 tests and a seeded 200-case
  corruption campaign" -> "...a seeded campaign of 200 draws over 12
  single-fault evidence corruption classes" (until RC-1d lands).
  P0-9 / ledger "50 Hz duplex step" -> "10 Hz runtime semantic loop".
  VALIDATION.md gate figure -> re-run at 7242660 (3943) with the transient
  disclosed.

NEXT GO/NO-GO GATE: Wave-0 exit review (Fable) = all W0 card gates green on a
  fresh ci_gate at a stated commit, hardened spike ported and deleted, RC-2/
  RC-3 contract language landed, TTL derivation published. Physical motion
  remains gated regardless on P0 1-4 closure + commissioning evidence +
  independent operator stop — no verdict in this file arms anything.
```

The refuted-and-dismissed finding, recorded for honesty: the claim that the
plan never contains the Nav2 second-writer invariant was REFUTED 2-0 — decision
record 5 and the gateway sections state proposal-only ROS controllers and the
sole-writer rule; W0-C's gates already test writer exclusivity. No change
required beyond N-2's composed test.
