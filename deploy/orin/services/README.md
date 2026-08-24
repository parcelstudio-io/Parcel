# `deploy/orin/services/` — the five owned service skeletons

**Card:** A4 SPINE (`scrum/20260824/task_2/`) · **Design:**
`research/20260824/PORTABLE_LIVING_DOG_HLD.md` §3 (process/failure ownership)
and §12 Gate 2 · **Finding:** EMBODIMENT-KERNEL row K6 — *"2 firewall units
only; five owned services"*
(`research/20260824/embodiment-kernel-portability/RESULTS.md`).

## These are SKELETONS. Nothing here has been run.

Every unit in this directory names an `ExecStart` that **does not exist yet**
and carries an `ExecStartPre` that fails loudly when it is absent. That is
deliberate: a unit that starts something plausible would report `active
(running)` for a service that has never existed, and the audit that found this
gap would then read green against nothing. Each file's header lists exactly
what is missing and which gate lands it.

Nothing here is installed on the development desktop. There is no Orin on hand
(`CLAUDE.md`: no robot hardware), so no unit below has ever been loaded by
systemd, and `deploy/README.md`'s "No Orin flash" disclaimer still stands.

## The five, and who owns what (HLD §3)

| unit | principal | owns | must not own |
|---|---|---|---|
| `parcel-gateway.service` | `parcel-gateway` | sole vendor SDK/DDS writer, lease/epoch, TTL, clamps, stop latch, bounded audit | dialogue, navigation goals, memory, hosted calls |
| `parcel-safety.service` | `parcel-safety` | independent STOP inputs, observation-health gate, final local motion envelope, gateway heartbeat | disk/network/model blocking work |
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

1. `Environment=PARCEL_ARMED=0` — the process starts with no motion authority.
   Arming is an explicit operator transaction, never a side effect of a unit
   reaching `active`.
2. No `[Install] WantedBy=` on any unit except the gateway's explicit
   `parcel.target` membership. `systemctl enable` is a box-day step with a
   human on the runbook, not a property of committing a file.

The gateway additionally declares `Restart=on-failure` with a rate limit: a
crash-looping sole writer that re-acquires its lease every 200 ms is a second
writer in all but name.

## What must exist before any of these can be enabled

- a pinned aarch64 artifact (`deploy/README.md` disclaims one today);
- the `parcel-*` system users and their data/log directories;
- `MotionGatewayClient` and the gateway process itself (card A1 M1-0 GATEWAY);
- a real LIO provider (Gate 5) — `parcel_robot/localization/` has the latch,
  the jump journal and the whole-map matcher, and card A4 installed them, but
  the estimator behind them is still the scan-match stub;
- the sensor hub's clock map and extrinsics manifest (Gate 3).
