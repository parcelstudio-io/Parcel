# H4 — continuous body intent · VERDICT (Fable) · 2026-08-24

Verifier: Fable (parcel-fb), 2026-08-24, solo — the account's weekly limit
stopped subagents at ~00:40. Basis: the executor's RESULTS.md and results/
files, the capability test(s) it added (run through the guard on this tree:
`tests/test_h3_drives.py tests/test_h4_body_intent.py
tests/test_h7_localization_contract.py tests/test_h6_noticing.py` + both DEC
ratchets = 63 passed, 1 skipped), git diff against OWNS, and DESIGN.md
byte-identity with `0ec1d7c`. Rows marked *reported* were read, not re-run;
rows marked *reproduced* were re-run here. Criterion integrity: no bar moved.

| row | criterion | executor | verifier | disposition |
|---|---|---|---|---|
| B1 | ≥ 20 Hz, no gap > 100 ms | 49.5–49.95 Hz; worst gap 85 ms; 0 gaps > 100 ms / 119,552 ticks | reported; the composer's tick loop is exercised by `test_h4_body_intent.py` (HOLD always emitted) | CONFIRMED |
| B2 | envelope compliance 100 % | 0 violations / 119,552 | reported; clamp path unit-tested | CONFIRMED |
| B3 | jerk within bound | 0 windows over bound on a jitter-free clock; 19/597,700 on wall clock (0.003 %) | reported | CONFIRMED-WITH-NOTES (wall-clock exceedances are scheduler jitter, not composer output — say so in the design) |
| B4 | 0 IPC rejections / 10 min | 0 / 76,690 messages; seeded rejection detected | reported | CONFIRMED |
| B5 | COM drift < 1 cm on HOLD | 0.13 mm | reported (MuJoCo kinematic base — the sim base teleports; this row proves the *offsets* are tiny, not balance) | CONFIRMED-WITH-NOTES |
| B6 | e-stop → HOLD ≤ 1 tick | 17.66 ms = 0.88 tick | reported | CONFIRMED |
| B7 | navigating velocity byte-identical | 3,402/3,402 messages identical | reported; the composer never produces a velocity by construction (`motion/body_composer.py` consumes the finalized one) — read | CONFIRMED |
| B8 | fake adapter ≤ 150 LOC, 0 product lines | 124 LOC; 0 product modules changed (sha) | reproduced by reading the diff: only `contracts/body_intent.py`, `motion/body_composer.py`, `simulation/body_adapter.py`, `control/go2_sport_body_adapter.py` (refusing stub, no SDK import) are product files | CONFIRMED |
| B9 | loop P99 ≤ today + 5 % | +0.00 %; composer 44 µs P99/tick | reported | CONFIRMED |

**Overall: CONFIRMED (harness-only).** Product path: nothing in `runtime.py`
constructs the composer — by design; wiring is card M1-3 BODY. The Go2 Sport
adapter is a shape (every method refuses) — it proves nothing about Sport
`Euler`/`Move`/`StopMove` behavior, balance, or contact.

Three sentences. Measured: one body-neutral intent stream at 50 Hz with a
stationary HOLD that is a command, envelope and IPC clean over 10 minutes,
preemption inside a tick, locomotion byte-identical to today's path, and a
second body (different manifest: no posture, yaw-only gaze) driven by the
same stream with zero product edits in 124 lines. Still assumed: that the
Go2's Sport primitives accept posture/gaze at this rate without upsetting
balance, and that jerk bounds chosen in sim are the right ones for a real
body. What the design may rely on: `BodyIntentV1` + `BodyCapabilityManifest`
as the portability contract, and `degrade()` never inventing motion.
