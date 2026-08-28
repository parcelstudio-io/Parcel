# SOCIAL-PROGRESS-1 shadow implementation

**Implemented:** 2026-08-26
**Disposition:** simulator/product-path instrumentation is ready; physical social
motion remains **NO-GO**.

## What shipped in this slice

The first product seam now observes social-navigation stalls without gaining
motion authority:

1. `DirectiveNavigator.snapshot()` publishes typed route/liveness facts
   (`route_status`, `body_is_still`, `steps_gate_blocked`, and
   `progress_demand`). It does not expose or parse free-form command notes.
2. The runtime samples the pre-dispatch arbiter winner.
3. The existing digest-pinned `_dispatch_active()` executes unchanged, including
   the final reactive collision brake and sole control-manager write.
4. Immediately afterward, a bounded in-memory observer records the requested,
   final accepted, and achieved velocities with source, sequence, age, and
   freshness.
5. The observer joins those facts to the stamped `NavigationSnapshotV2`, its
   existing `DynamicTrackV2` rows, and LiDAR/traversability provenance. It emits
   typed states and planning proposals only. Every decision carries
   `authorizes_motion=false` and `requires_downstream_safety_gate=true`.

There is no actuator method, velocity output, disk writer, ROS command,
crosswalk authority, elevator authority, or learned-model promotion path in the
observer.

## Evidence rules

- A current dynamic track becomes `VISIBLE` only when a fresh LiDAR obstacle or
  range mark corroborates it geometrically. A matching obstacle ID without
  angular and radial agreement is insufficient. Otherwise the track is
  `OCCLUDED`, `OUT_OF_FOV`, or `STALE` rather than silently trusted as visible.
- A missing track is retained as uncertain for a bounded interval. Its absence
  never certifies clearance.
- `EXPLICIT_FREE` requires a fresh, healthy, translation-allowed snapshot, a
  complete effectively 360-degree ray sweep with bounded angular gaps, an
  explicit footprint conversion for base-centre ranges, and ray-by-ray
  clearance beyond every boundary of the full swept rectangle. A front-only or
  gapped scan refuses the certificate.
- The transitional carrier's planar scan is base-centre range while its
  analytic nearest/obstacle channels are already body-surface clearance. The
  adapter now declares those source conventions independently and normalizes
  every finite subchannel, including scan bounds, before publishing one honest
  body-surface `TraversabilityV1`; NaN and infinity sentinels are preserved.
- Fresh contradictory `person_proximity` evidence suppresses clearance. An
  unknown bearing is conservative; a known person outside the swept rectangle
  does not mask otherwise valid LiDAR evidence.
- Source age, measured/effective transport delay, capture/assembly ordering,
  health reasons, and clock-map uncertainty are checked against consumer
  thresholds. Effective transport is retained in the visibility timestamps.
- The free certificate is keyed by a SHA-256 digest of immutable source ID,
  process epoch, sequence, capture time, and calibration lineage—not the opaque
  evidence label. Relabelling one scan cannot manufacture the distinct clear
  streak required for a probe proposal.
- New contradictory, stale, incomplete, or unhealthy evidence revokes or blocks
  release eligibility.
- Dynamic tracks, obstacle rows, planar rays, track/obstacle identifiers, and
  track covariance are bounded before sorting, covariance iteration, derivation,
  lock acquisition, or history mutation. Covariance is capped at the 36 entries
  required by a dense 6x6 constant-acceleration state; oversized snapshots fail
  visibly instead of adding unbounded work to the control loop.
- Internal evidence history is capped at 128 samples. `/api/state` never
  materializes that full ring: it publishes one covariance-free detailed latest
  row plus at most 16 fixed-size summaries. Actor-related track, class, group,
  and blocker identifiers are hashed; bounded sensor evidence and source IDs
  remain readable for audit lineage. A fully populated 128 x 64-track
  adversarial ring with maximum Unicode identifiers and uint64 values encodes
  to 82,354 bytes in UTF-8 and 87,474 bytes in default escaped JSON, versus
  14.7 MiB before this bound, and exposes truncation/counts.
- Every integer reachable from that projection is capped at uint64 before
  hashing, derivation, or retention. Maximum+1 and 5,000-digit inputs fail
  before history mutation, so Python's integer-string limit cannot break the
  state endpoint.
- Navigation generation changes clear history, retained tracks, recovery budget,
  and liveness state.
- Sidewalk, crosswalk, and elevator outcomes remain typed proposal states.
  Crosswalk entry requires independent authority and owner commitment;
  elevator entry requires door, egress, capacity, and owner-order evidence.

## Configuration boundary

The digest-pinned base/physical configuration contains no `social_progress`
section. Absence is the strict disabled default: no observer is constructed, no
sampling or observation hook runs, no social metric or snapshot key is added,
and no file is created. Existing `MotionDispatch` timing still begins immediately
before the unchanged dispatch call.

The simulator prototype overlay opts into the sole accepted operating mode:

```yaml
social_progress:
  enabled: true
  mode: shadow
```

Unknown keys, non-boolean enablement, and any mode other than `shadow` fail at
runtime construction. The runtime overwrites research distance knobs with the
commissioned deployment person envelope and robot footprint before constructing
the observer.

## Verification performed

All commands ran through the repository process guard with the repository
environment:

| Check | Result |
|---|---:|
| Contract, adversarial observer, and product-wiring tests | 104 passed |
| Navigation/dynamic/yield/liveness/config regressions | 371 passed |
| Runtime, packaged-assets, and release-parity regressions | 70 passed |
| Import-order/cycle regressions | 10 passed |
| Total focused and regression tests | 555 passed |
| Frozen research replay | 475/475 rows, byte-identical |
| Research episode digest | `932167875fd16bbd67256f60ef8b555b074bfb23fb2eb4b3695aa5051578c1ad` |
| Ruff lint on the implementation surface | passed |

The regression set includes the AST digest that freezes `_dispatch_active()`.
It also verifies the exact simulator observation spine, the dynamic layer,
traffic-aware navigation, yield policy, nominal stop wiring, lock discipline,
profile admission, runtime assets, and release parity.

## Independent review and repair

A fresh Sol model at Ultra reasoning independently rejected the initial pass and
then rejected the first repaired pass. Its reproductions found a
wedge/rectangle mismatch that could mint false clear evidence at a near-field
side obstacle, omission of `person_proximity`, lossy transport and clock
provenance, opaque-label clear-streak identity, incomplete exception isolation,
mixed final-target attribution, unlocked navigator reads, unbounded input
traversal, mixed source-range conventions, unbounded nested covariance, and work
leaking into the disabled path. A further public-state audit reproduced a
14.7 MiB default history response, and the range audit showed that bools and
numeric strings could be coerced into apparently valid rays. Final adversarial
passes also found unbounded Python integers in public counters and an
all-infinity raw-sensor scan bypassing unsupported conversion provenance.

Each reproduction is now a regression test. The implementation uses full
ray-to-rectangle exits, joins positive person evidence, hashes immutable sample
lineage, evaluates time authority in integer nanoseconds, records one coherent
controller target snapshot, locks planner reads, normalizes mixed geometry,
caps nested inputs before iteration, and catches every ordinary diagnostic
exception while still dispatching and continuing repeated control ticks.
The normalizer now rejects malformed scalars and invalid footprint radii before
scan iteration, and validates the convention pair before preserving any
NaN/infinity sentinel; the public state uses the capped compact projection and
uint64 boundary above.
`BaseException` remains uncaught. The disabled path is inert. The unchanged
dispatch digest and downstream collision/safety authority were reverified after
the fixes.

## Readiness verdict

This slice is ready to collect simulator shadow traces and to evaluate whether
stalls are caused by stale sensing, localization, planner failure, a live person,
a retained uncertain track, or a costmap ghost. It is not a resume controller
and therefore cannot yet make the dog continue walking.

The current shadow classifier also has deliberate limitations: its full proof
assumes Mid-360-style planar coverage; `PersonProximityV1` inherits snapshot
freshness because it has no independent header; simulator dynamic tracks are
truth-like rather than qualified camera/LiDAR associations; venue phase facts
are not yet produced by runtime perception; and corridor direction comes from a
nonzero requested/final velocity rather than a typed route tangent. A planner
that already outputs zero can be diagnosed as stalled, but cannot yet earn a
free-corridor proposal until that intended-direction contract exists.

Mounting the full autonomous companion stack around pedestrians remains
**NO-GO**. The physical source still lacks qualified camera/LiDAR association,
owner identity, venue semantics, braking calibration, achieved-feedback
sequence lineage, AGX timing evidence, and real-bag replay. Crosswalk, elevator,
stairs, physical Follow, and proactive evasion remain disabled.

### Adversarial clock-domain closure

A later integration review reproduced a boundary defect that manually
restamped fixtures hid: `HeadlessCityWorld` starts its simulator clock at zero,
while the runtime observer judges freshness on host monotonic time. Direct
native headless observations therefore looked permanently stale. The runtime's
synchronous in-process carrier source now declares an `ingress_monotonic` clock
domain and stamps the snapshot at receipt; simulation origin and fixture
provenance remain unchanged. Other carrier users retain the source-clock
default, so this does not turn genuinely old replay/source evidence fresh.

A regression constructed a real `HeadlessCityWorld`, published its time-zero
observation without manual restamping, observed a non-`stale_sensor` decision,
then advanced 251 ms and observed `stale_sensor`. The targeted node passed 1/1;
the final cross-surface focused suite containing all social-progress contract,
observer, and runtime tests passed 269 tests. This repairs simulator shadow
diagnostics only and grants no motion authority.

## Next qualification tranche

1. Feed natural camera/LiDAR association and calibrated existence/covariance
   into the same sidecar contract; never treat simulator truth tracks as
   physical perception evidence.
2. Add a stamped intended route tangent so planner-side zero-output stalls can
   evaluate the correct swept corridor without retaining an implicit heading.
3. Record frozen simulator/bag episodes and score truth-clear, evidence-ready,
   proposal, dispatch, and achieved-motion timestamps separately.
4. Implement safe-staging and evasion **candidate generation** in simulation,
   then compare CV/CA, IMM, ORCA/Social Force, and chance-constrained lattice or
   MPPI behind the unchanged hard monitor.
5. Add responsive and adversarial pedestrians, association faults, ray-level
   occlusion, control delay, and Go2 braking/dynamics to the 1,200 nominal + 240
   stress qualification matrix.
6. Profile the observer and candidate planner on the intended AGX workload;
   require local-stack p99 at or below 50 ms with no 100 ms misses.
7. Only after frozen simulation and real-bag shadow gates pass, implement a
   separately reviewed bounded creep/probe consumer. It must still pass through
   the existing arbiter, TTL, collision gate, and sole actuator writer.
