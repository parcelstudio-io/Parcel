# `deploy/orin/services/` — five owned service skeletons and their target

**Card:** A4 SPINE (`scrum/20260824/task_2/`) · **Design:**
`research/20260824/PORTABLE_LIVING_DOG_HLD.md` §3 (process/failure ownership)
and §12 Gate 2 · **Finding:** EMBODIMENT-KERNEL row K6 — *"2 firewall units
only; five owned services"*
(`research/20260824/embodiment-kernel-portability/RESULTS.md`).

## These are SKELETONS. Nothing here has been run on the target.

The installable `parcel-gateway` and stop-only `parcel-safety` console entry
points now exist in the source tree. The runtime, LIO, and audio service
executables do not, and no aarch64 artifact has been installed or exercised on
an Orin. Every unit retains an `ExecStartPre` that fails loudly when its
installed executable is absent. Source-level entry points and desktop
fake/injected tests do not make this five-service layout runnable or
hardware-qualified.

Nothing here is installed on the development desktop. There is no Orin on hand
(`CLAUDE.md`: no robot hardware), so no unit below has ever been loaded by
systemd, and `deploy/README.md`'s "No Orin flash" disclaimer still stands.

## The five, and who owns what (HLD §3)

| unit | principal | owns | must not own |
|---|---|---|---|
| `parcel-gateway.service` | `parcel-gateway` | sole vendor SDK/DDS writer, lease/epoch, TTL, clamps, stop latch, bounded audit | dialogue, navigation goals, memory, hosted calls |
| `parcel-safety.service` | `parcel-safety` | stop-only software principal, gateway-state consistency/freshness checks, latch, gateway heartbeat | positive motion, disk/network/model blocking work |
| `parcel-lio.service` | `parcel-lio` | LIO provider, MAP→ODOM, health/covariance/innovation/jump/relocalization evidence | mission-success claims |
| `parcel-audio.service` | `parcel-audio` | one capture rail, AEC/VAD/endpointing, local STOP, speaker/engagement gate | direct physical tools |
| `parcel-runtime.service` | `parcel-runtime` | world model, conversation, drives, behavior executive, memory, task compilation | vendor SDK or device handles |

**Known deviation from HLD §3, stated rather than hidden:** §3 splits
`parcel-safety` and `parcel-sensor-hub` into two processes. This card ships
five units, and `parcel-safety.service` therefore carries the sensor-hub
responsibilities (monotonic clock map, frames/extrinsics, calibration
manifest) in its TODO list. Splitting it is Gate 3 work, together with the
manifest itself — the split is cheap once there is a manifest to own, and
premature while there is not.

## Boot is disarmed, and every restart is disarmed

HLD §3: *"Boot and every restart are disarmed. A service becoming 'ready'
never rearms motion."* Two mechanisms, both present in every unit:

1. Each `ExecStart` invokes `/usr/bin/env PARCEL_ARMED=0 ...` immediately before
   its absolute executable and also supplies `--disarmed`. The command-line
   assignment wins over an accidental `PARCEL_ARMED=1` in an optional
   `EnvironmentFile`; arming is a separate operator transaction, never a side
   effect of a unit reaching `active`.
2. No service reaches a target other than the gateway's explicit
   `parcel.target` membership. `parcel.target` is now present and is installable
   from `multi-user.target`, but enabling it remains a box-day step with a human
   on the runbook, not a property of committing a file. Target activation only
   starts the five processes with `PARCEL_ARMED=0`; it never performs the
   separate operator arm transaction.

## Target and profile composition

`parcel.target` requires gateway, safety, and runtime; wants degradable LIO and
audio; and orders
`gateway -> safety -> LIO/audio -> runtime -> target`. It is an orchestration
request, **not readiness**: a core start failure fails target activation, while
a wanted LIO/audio failure does not; even five active processes say nothing
about process-internal physical sensor or motion readiness. Operators must
inspect every service and its readiness state. Today the missing
`/opt/parcel/bin/parcel-runtime`, `parcel-lio`, and
`parcel-audio` fail their own `ExecStartPre` loudly; an active target cannot be
cited as a runnable-deployment result.

The runtime uses `Requires=` to start gateway and safety and `BindsTo=` plus
`After=` to stop itself if either authority service fails or becomes inactive
unexpectedly. The target also requires those three core processes so a failed
core start is visible as a failed target job. `Requires=` does not propagate an
explicit target stop to the required units; the target's explicit
`PropagatesStopTo=` submits stop jobs for runtime, audio, LIO, and gateway; the
services' `After=` relationships, not list order, govern shutdown ordering. It
intentionally excludes safety. An explicit gateway stop can
deactivate the target and its positive/degradable rails, while safety remains
alive, observes the missing gateway, and keeps retrying until an operator
separately stops it after verifying the independent physical stop state.

The runtime selects `go2_edu_plus` once, on its `ExecStart` command line. That
is the reviewed loadable overlay at `configs/robot.go2_edu_plus.yaml` and takes
precedence over any stray `PARCEL_PROFILE` value in `runtime.env`. The former
`physical` selector named no profile in this repository. Selecting the correct
overlay still does not inject the missing commissioned physical observation
source or create the missing runtime executable.

### Fixed environment wins over optional environment files

Systemd's `EnvironmentFile=` values override `Environment=` values regardless
of textual order. The previous units therefore allowed a box-day file to
replace fixed disarm, role, vendor-body, topic, queue-depth, socket, mode, or
client-principal values. The units no longer express those invariants with
`Environment=`. Instead, each retains its optional root-owned environment file
for credentials, commissioning evidence, calibration and measured tuning, then
uses `/usr/bin/env KEY=fixed ... /opt/parcel/bin/...` in `ExecStart`. Those
later per-process assignments win even if a file mistakenly repeats a fixed
key. Runtime's `--profile go2_edu_plus` likewise outranks a stray
`PARCEL_PROFILE` value.

This protects only the named launch invariants. The environment files are still
trusted root-controlled configuration and can influence every non-fixed option;
their ownership, permissions, schema and exact allowed settings remain image
build/box-day gates. No secret is committed in these units.

The gateway additionally declares `Restart=on-failure` with a rate limit: a
crash-looping sole writer that re-acquires its lease every 200 ms is a second
writer in all but name.

The motion and stop processes use distinct UIDs. The gateway creates
`/run/parcel-gateway/gateway.sock` as `0660`, owned by the gateway user and the
dedicated `parcel-motion` group. Runtime and safety join only that shared IPC
group. The gateway authenticates each kernel-reported peer UID: only
`parcel-runtime` may acquire or refresh a positive-motion lease, while the
distinct `parcel-safety` UID may observe state and issue an unconditional
latched STOP. Group membership is therefore filesystem reachability rather
than lease authority. Desktop/fake launches retain the private `0600`,
same-UID default.

The source-level `parcel-safety` process is deliberately narrow. It has no
acquire, velocity, or vendor API; uses only the local Unix socket; earns
systemd readiness/watchdog notifications; stops and latches on stale or
inconsistent gateway state; and maps `SIGUSR1`, `SIGINT`, and `SIGTERM` to a
latched STOP. Desktop evidence covers UID separation, command refusal, stop
dominance, reconnect/lifecycle behavior, and gateway-watchdog failure. It has
not run on the Orin or Go2, has no GPIO/serial remote input, and cannot stop the
body if the sole-writer gateway, Orin, shared power, or vendor controller is
itself unavailable. A physically independent robot remote/E-stop remains
mandatory.

### One physical SDK writer, including commissioning maintenance

Autonomous operation and armed commissioning share the fixed
`/run/parcel-gateway/unitree-writer.lock`. Both real SDK constructors require a
held lock before they initialize a channel or lease, and the lock becomes
process-lifetime after SDK activation because the public Unitree lease client
has no shutdown API. The old in-process runtime `unitree_sport` factory is
unregistered and always refuses; `parcel-runtime` can reach the body only
through `motion_gateway_commissioned` and the gateway socket.

Armed `parcel-unitree-control run` is therefore a **mutually exclusive
maintenance mode**, not a sixth service and not a fallback writer:

1. stop `parcel-runtime.service`, then stop `parcel-gateway.service` and verify
   both processes exited;
2. invoke the commissioning command as the same dedicated
   **`parcel-gateway` UID** that owns the persistent `0600` lock inode—never
   widen the file mode or run it as `parcel-runtime`;
3. keep that process alive through stop confirmation and record persistence;
   after activation, only process exit releases its SDK authority; and
4. restart the gateway only after the commissioning process has exited. The
   gateway restarts disarmed and requires a new explicit runtime arm.

The read-only `observe` subcommand constructs no controller, claims no lease,
and does not take writer authority. For a clean Stage-0 “zero `Move`” record,
the runbook still stops runtime and gateway before observing.

The current skeleton has no packaged commissioning-maintenance unit or wrapper.
Stopping `parcel-gateway.service` may remove its systemd `RuntimeDirectory`, so
the eventual signed maintenance procedure must create or retain
`/run/parcel-gateway` with exact `parcel-gateway:parcel-gateway` ownership before
dropping to that UID. Operators must not improvise by deleting a lock inode or
making it group/world writable. This procedural gap is another reason the
files are not ready to enable.

The vendor gateway also requires fresh `rt/sportmodestate` and `rt/lowstate`
before it can acquire or refresh motion authority. Its additive V2 state
preserves pose/tilt, vendor mode/error and device time, plus battery SOC,
power and raw thermal/motor/force health. Raw temperature bytes, motor `lost`
counters and foot-force counts are observability only: the software does not
label them °C/newtons, infer contact, or estimate slip before commissioning
establishes those meanings and thresholds.

### Gateway vendor flags are box-day evidence, not image defaults

`parcel-gateway.service` fixes the two DDS topics and the direct-callback queue
depth (`PARCEL_UNITREE_SUBSCRIBER_QUEUE_DEPTH=0`). It deliberately does **not**
set any hardware acknowledgement. After a tethered commissioning run, the
operator-owned `/etc/parcel/gateway.env` must provide all of the following or
the vendor entrypoint refuses to create the SDK2 port:

- `PARCEL_UNITREE_INTERFACE` and `PARCEL_UNITREE_DOMAIN_ID`;
- `PARCEL_UNITREE_ALLOWED_MODES` and
  `PARCEL_UNITREE_ALLOWED_ERROR_CODES`, each as a measured comma-separated
  allowlist;
- `PARCEL_UNITREE_STATE_VELOCITY_FRAME`, `PARCEL_UNITREE_LATERAL_SIGN`, and
  `PARCEL_UNITREE_YAW_SIGN`;
- `PARCEL_UNITREE_AXES_COMMISSIONED=1` and
  `PARCEL_UNITREE_STATE_FRAME_COMMISSIONED=1`, only after the frame/sign test;
- `PARCEL_UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED=1`, only after
  repeated samples and a robot reboot have established that the
  `SportModeState.stamp` contract advances monotonically;
- `PARCEL_UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED=1` and
  `PARCEL_UNITREE_MINIMUM_BATTERY_SOC_PERCENT`, only after the raw `soc` field
  has been shown to be a trustworthy percentage and the operating floor has
  been approved;
- `PARCEL_UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED=1`, only after repeated
  samples, wraparound behavior and a robot reboot have established the tick
  contract; and
- the four `PARCEL_GATEWAY_*_SHA256` launch-supplied configuration/artifact
  compatibility hashes. Runtime/stop client identities, socket path/mode,
  vendor body, state topics and subscriber queue depth are fixed by the unit
  after this file is read and are not commissioning-file options.

The four hashes are a local launch-attestation fence: they make the gateway
and runtime agree on the selected configuration, capability manifest,
calibration artifact and firmware claim. They are **not** read from, challenged
against, or otherwise bound to the robot actually observed on DDS. They do not
authenticate or encrypt DDS traffic and must not be described as physical
robot identity. The firewall/process boundary remains the only deployed
network containment represented by this skeleton.

These `...COMMISSIONED=1` commissioning acknowledgements are assertions backed by
the box-day record, not feature toggles. They remain absent from the shipped
unit so an untested image fails closed.

The service manager also enforces finite lifecycle bounds. `TimeoutStartSec=15`
covers the port's maximum 10-second SDK evidence wait, the 1-second boot stop,
the 1.5-second readiness probe and the notifier's 0.5-second send, leaving 2
seconds of scheduling margin; an SDK constructor that hangs before that wait
is still terminated. `TimeoutStopSec=10` exceeds the 8.1-second sum of
configured shipped shutdown wait budgets by 1.9 seconds. It therefore lets
bounded cleanup finish without inheriting systemd's host default, while still
terminating an unbounded SDK or filesystem stall.

Physical qualification remains blocked. It requires a tethered Unitree run
that records the commissioning evidence above and a mechanism that binds the
observed robot/firmware identity to the launch (or authenticates the DDS peer).
Until then, these files describe a fail-closed desktop-tested integration, not
an authenticated or hardware-qualified robot deployment.

## What must exist before any of these can be enabled

- a pinned aarch64 artifact (`deploy/README.md` disclaims one today);
- the `parcel-*` system users and their data/log directories;
- target installation and Orin/systemd qualification of the source-level
  `parcel-gateway` and `parcel-safety` entry points, including the dedicated
  `parcel-motion` group and two distinct kernel UIDs;
- a signed, mutually exclusive commissioning-maintenance wrapper that preserves
  the fixed writer-lock directory/ownership and runs the armed CLI as the
  `parcel-gateway` UID;
- a recorded tethered Unitree qualification run and an observed-robot identity
  or authenticated-DDS binding; launch-provided hashes alone do not satisfy
  this gate;
- a physical observation source injected into `RobotRuntime` that consumes the
  commissioned gateway/sensor-hub state without reopening Unitree or Livox in
  the runtime process, plus the normal runtime launcher/config composition
  that selects that source;
- a real LIO provider (Gate 5) — `parcel_robot/localization/` has the latch,
  the jump journal and the whole-map matcher, and card A4 installed them, but
  the estimator behind them is still the scan-match stub;
- the sensor hub's clock map and extrinsics manifest (Gate 3).
