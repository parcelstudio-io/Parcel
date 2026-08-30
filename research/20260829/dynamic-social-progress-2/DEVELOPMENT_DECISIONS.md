# DSP-2 development decisions (pre-test)

The test split was not rolled out or inspected while making these decisions.
Every change below was prompted by the 10-family development split. Test actor
trajectories and sensor seeds remained behind the frozen-run guard.

## Development sequence

| Run | Normalized episode digest | Observation and bounded change |
|---|---|---|
| `development-result.json` | `18aa5ea8a68c154d1d3668e4229acc58acb8ec52b9e432b1e93272723a2cb258` | Initial implementation revealed that generic escape scoring pre-empted the authored elevator pocket and that goal scoring incorrectly required returning to the centerline. |
| `development-result-2.json` | `5ec756226fbc0e73302eaf41860c042bbc06d40983d5b66d4eee09f354b97ea3` | Prioritized the context pocket, classified escape separately from release, and used the prior study's longitudinal goal contract. |
| `development-result-3.json` | `53dd32455ff34fb10ab4ac0194cb83823dbff722d25ba5f65905b274fbe4a9ca` | Identified that re-solving an already admitted escape caused a stop halfway through the tube. Added an explicit escape target and continuation audit. |
| `development-result-4.json` | `d4a2020b463e5c150e562515a84b6cbf505cd0572cc59252e7e3e2da9e78971d` | Elevator contact was removed; a late mid-crossing intrusion remained. |
| `development-verifier-input.json` | `af4953909afba2734fff5db1c6cfbefa40c0cc8ff13ead9ee79a00f044b10a43` | Final development implementation: 0 S2/S3 contacts, actor-into-stationary contacts, hard admissions, hard-floor ticks, and semantic violations. Independent verifier and all three tamper tests passed. |

## Frozen parameter decisions

- The elevator stage center moved from `y=-0.62 m` to `y=-0.88 m` because
  `-0.62 m` leaves only `0.02 m` nominal surface separation for the authored
  `0.32 m + 0.28 m` radii when an exiting actor is centered. This is a simulator
  geometry parameter, not a physical clearance recommendation.
- Robust arms use `0.62 m/s` in a crosswalk. This retained time-to-clear in the
  authored 22-second episode while increasing reaction time for a late lateral
  intrusion. S0 remains the prior A3 parameterization at `0.8 m/s`.
- Sidewalk episodes allow 26 seconds rather than 22 so completion is not
  censored solely by the authored multi-second yield. Crosswalk and elevator
  episodes remain 22 seconds.
- A reachable lateral escape selected against the full two-second tube carries
  an explicit target. Each continuation tick still passes the common semantic
  boundary, corridor, one-step current hard-floor, and non-worsening-clearance
  checks. An intervention resets S3 to `BRAKE`.
- Missing detections cannot trigger release. S3 release needs fresh input,
  an explicit free certificate, three low-risk frames, and four creep ticks.
- Latency results report eligible, observed, and censored event counts for each
  leg. Difficult episodes are retained as censored observations rather than
  silently removed from denominators.

## Final development audit (30 episodes per arm)

S2 had 0 contacts, 3 near-contact episodes, minimum surface clearance
`0.163490 m`, 100% task completion, `98.4 s` false-block time, and 142
stop/start transitions. S3 had 0 contacts, 0 near-contact episodes, minimum
surface clearance `0.211945 m`, 90% completion, `120.8 s` false-block time, and
158 transitions. Therefore H1 was supported on development, while H2, H3, and
H4 were refuted. In particular, S3's liveness mechanism increased false-block
time and transitions on development; this negative result was frozen rather
than tuned against test.

Task completion and safety remain separate fields. `task_success` may be true
when a contact occurred; `safety_gate_pass` is computed independently, and
`safe_task_successes` is reported only as a derived intersection. Every safety
hypothesis retains its own conjunctive hard gate.

