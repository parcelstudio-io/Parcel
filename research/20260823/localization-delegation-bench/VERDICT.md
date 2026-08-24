# H7 — localization by delegation · VERDICT (Fable) · 2026-08-24

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
| L1 | ATE ≤ 0.15 m, two scenes | 0.0098 / 0.0160 m | reported (numpy ICP fallback — `kiss-icp`/`open3d` have no Python 3.14 wheel) | CONFIRMED-WITH-NOTES (planar sim scans are noise-free; real Mid-360 clouds will not be) |
| L2 | yaw RPE ≤ 1 °/m | 0.070 / 0.117 °/m | reported | CONFIRMED-WITH-NOTES (same caveat) |
| L3 | jump magnitude reported | 0.053 / 0.086 m nominal; 7.15 m on kidnapping; 10.47 m on relocalization | reported — the `localization_jump_m` term is now MEASURABLE from a provider | CONFIRMED |
| L4 | DEGRADED ≤ 1 s on dropout; LOST on teleport; recovery reported | dropout rows confirmed; **pre-registered teleport MISSED on city_block** (6.3 m, never DEGRADED/LOST, post-ATE 8.66 m, covariance millimetric — RESULTS.md:95-127; `teleport_far` was post-hoc) | correction 2026-08-24 (RTP-2 F3): the first verdict read the summary table and over-credited | **dropout CONFIRMED; teleport REFUTED (false-healthy) on one of two scenes** — see the milestone's discontinuity rule |
| L5 | NEES in [0.5, 2.0] | ANEES 104 / 234 | reported | **REFUTED** — the covariance is 50–100× overconfident; any health threshold that trusts it will be wrong |
| L6 | 0 false arrivals; SR per rung | 0 false arrivals, 0 collisions on all 5 rungs; SR falls 17–100 % INTO refusals | reported (frozen NAV_INSTRUCT set, read-only replay) | CONFIRMED — the consumers refuse rather than fail, which is the seam doing its job |
| L7 | latency ≤ 30 ms p95 | 2.25 ms p95 (relocalization ticks 45–78 ms) | reported | CONFIRMED |
| L8 | fake-quadruped run, 0 provider diff | ATE 0.010/0.018 m; three provider files sha-identical | reproduced by reading: `localization/` is odometry-agnostic | CONFIRMED |

**Overall: CONFIRMED-WITH-NOTES; L5 REFUTED; L4 teleport REFUTED (correction 2026-08-24).** Product path: `localization/`
is constructed by nothing in `src/` (harness-only); `pose.py` consumers are
untouched. The design may rely on the CONTRACT (`LocalizationUpdate`, MAP/ODOM
composition, health transitions, a measured jump term) and must NOT rely on
the covariance until a calibrated provider (FAST-LIO2/Point-LIO on real bags)
replaces the ICP proxy. SR loss across the drift ladder is entirely refusals
— a localizer that publishes honest health costs missions, not safety.
