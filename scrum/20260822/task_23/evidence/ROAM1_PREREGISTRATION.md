# ROAM-1 pre-registration (written BEFORE any measurement or source edit)

Card: scrum/20260822/task_23/README.md · Executor: Claude Opus · HEAD 8862220

## Acceptance rows, numbers fixed now

R1  Spoken/typed "go explore" through the hosted ingress starts the roam
    behavior and the patrol is TICKING within <= 2.0 s (measured as
    ledger/emit row timestamp delta from submit_realtime_transcript return to
    the first roam-sourced motion submission).
R2  Three consecutive 120 s roam runs in `--static-city`, each:
      R2a  path length >= 5.0 m
      R2b  net displacement >= 1.0 m      <-- Go2-purchase input, reported exactly
      R2c  0 robot-initiated contacts (collision_ticks == 0)
      R2d  prototype social zone respected: person clearance never below the
           configured `safety.person_stop_m` (0.7 m prototype) at any sample
R3  "stop roaming" latches roam to idle in ONE control tick (<= 1 loop period
    after the intent is executed; measured as roam_snapshot()["active"] False
    immediately on return of the ingress call).
R4  The dynamic city is a SECOND ARM, reported, not a gate (MOVE-1 D3).
R5  `_navigation_extras` supplies `time_s`; a paired nav_instruct run at
    loop_hz 10 is unchanged vs the frozen-clock behaviour, and a seeded
    loop_hz 20 shows tracker dt moving off the 0.1 literal.
R6  Four seeded-RED proofs, each seeded, observed red, restored byte-identical,
    __pycache__ purged, re-run green:
      S1 roam running past its budget
      S2 roam surviving an e-stop
      S3 roam reachable from a system-initiated turn
      S4 `time_s` absent from _navigation_extras again
R7  Targeted pytest + ruff green on OWNS; ruff ratchet still exactly 7
    baseline fingerprints, none added.

## Predictions (stated before measuring)

P1  Net displacement will EXCEED MOVE-1's 0.134 m, because MOVE-1's patrol was
    refused by the person predictive-stop gate at person_stop_m = 1.2 m and the
    prototype profile commissions 0.7 m (P1-E measured 0.313 -> 0.843 m on the
    static standoff arm). Point prediction: 1.0-4.0 m net over 120 s.
P2  Path length will exceed 5.0 m comfortably (MOVE-1 measured 5.0 m).
P3  R2b is the row most likely to MISS: a bounded random-walk patrol in a
    static city block can return near its start. If it misses, it misses and is
    reported as a miss — it is a purchase input, not a target.

## Rules

- Misses are misses. No row is re-defined after measurement.
- The displacement number is reported to 6 dp exactly as measured, for all
  three runs, plus the dynamic-city second arm.
