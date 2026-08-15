# Parallel engineering cards

These cards improve the path from captured evidence to a governed robot. They
must not delay MR-A, and none authorizes physical motion today.

## PE-D — replay-first physical sensor contract

- **Owner:** Sol
- **Priority:** P1
- **Depends on:** MR-A truth-table freeze

**Today-sized slice:** contract, fixtures and one replay adapter; not a full
SLAM/fusion implementation.

### Build

Define a simulator-neutral `SensorFrameV2`/`SensorSource` boundary carrying:

- raw image encoding/shape/stride and `CameraInfo`;
- raw `PointCloud2` fields without collapsing unknown vendor fields;
- IMU samples;
- source time, host monotonic receipt, clock-domain/boot epoch and uncertainty;
- frame ID, TF/calibration epoch and artifact digests;
- typed provenance, sequence, health and freshness;
- no semantic object IDs, true pose or collision truth on the agent side.

Implement the first deterministic rosbag2-MCAP replay source through that
boundary. Live ROS and simulators will later implement the same source; do not
import Isaac or ROS types into navigation.

### Tests

- Live-shaped fixture and normalized replay are equivalent.
- Drop, duplicate, reorder, clock step, missing TF, bad calibration, NaN point
  and unknown-field fixtures fail or degrade exactly as specified.
- A stale LiDAR frame never becomes free space; stale camera blocks semantic
  authority.
- Scorer-only oracle fields are rejected from agent input.
- V1 bags remain readable or receive an explicit migration refusal.

### Exit

`PE_D_STATUS.md` plus focused tests. The status must not claim localization,
fusion or navigation improvement.

## SG-E — bounded W0-C/W0-F safety slice

- **Owner:** Sol
- **Priority:** P1, required before future Parcel-driven physical motion

**Hardware required:** no

### Today-sized slice

1. Publish the required TTL/latency derivation table before freezing a gateway
   protocol constant.
2. Define versioned gateway DTOs for boot epoch, sequence, local TTL, frame,
   capability/config/calibration/firmware hashes, command acknowledgement,
   state and stop confirmation.
3. Implement or extend a fake high-level Sport service capable of delayed or
   no-reply `Move`, late completion, stale/out-of-order state, lease loss,
   writer conflict, process loss and `StopMove` failure.
4. Add the first process-level proof: client death after a nonzero proposal
   causes a local stop, never auto-resumes, and restart is disarmed.
5. Start the product `authority-invariants` CI manifest/gate. Do not claim the
   full W0-C/F cards are complete unless their accepted plan gates all pass.

### Safety decisions to record, not silently make

- B5 arrival reserve under localization error;
- B6 directional/closing relevance in the collision brake;
- B7 whether a latched input-health stop permits any yaw;
- B8 no-provider pose fallback health/covariance.

Product changes to B5/B6 remain behind their owner 2×2 decisions. SG-E may add
fixtures and specifications without changing frozen behavior.

### Exit

`SG_E_STATUS.md` identifies which subset landed and lists the uncompleted W0-C
and W0-F gates. A partial slice is not called a gateway.

## IS-F — Isaac RTX sensor-contract smoke

- **Owner:** Sol
- **Priority:** P2/stretch
- **Depends on:** PE-D schema

**Host constraint:** this Ubuntu 26.04 desktop is outside Isaac Sim's supported
host matrix; Docker/ROS/Isaac are absent at task opening.

### Work

1. Pin an Ubuntu 24.04-compatible Isaac Sim release/image by digest and record
   driver/GPU requirements.
2. Prepare a single-GPU headless compatibility check; do not modify the host
   into an untracked environment.
3. Define an Isaac producer that emits the same RGB, depth, `CameraInfo`, RTX
   LiDAR `PointCloud2`, IMU, TF and clock contract as PE-D.
4. Start with a stationary calibration rig and known geometry; moving people,
   stairs and weather come only after static reprojection/time gates pass.
5. Keep true pose, semantic IDs and collision truth on scorer-only channels.

### Minimum useful exit today

- pinned environment/setup manifest;
- contract mapping and launch skeleton;
- a deterministic fixture or skipped smoke with a precise missing-dependency
  reason;
- no claim that RTX simulation proves physical sensing.

Do not train RL or wire CityWalker in this card.

## DOC-G — status and backlog consolidation

- **Owner:** Sol
- **Priority:** P1

**Hardware required:** no

### Work

1. Update `docs/CURRENT_STATUS.md` from its 2026-08-04 snapshot to the current
   landed state without overstating hardware evidence.
2. Add durable backlog entries for residuals currently hidden only in
   PS-I/PS-N/PS-P status documents:

   - sync fit not wired into real sidecar;
   - missing camera plausibility samples;
   - wrong `VENDOR_VIDEO` dependency;
   - Stage-0 recorder/driver command rows;
   - Humble/QoS/L2/driver topic and Orin throughput verification;
   - CameraInfo/TF/calibration capture completeness;
   - primary rosbag interior-loss attribution limitation.

3. Add a terminal-status pointer from today's board to every completed or
   carried-forward card. Do not rewrite yesterday's historical task.

### Exit

No `UNVERIFIED` or `NOT RUN` result exists only inside a historical Scrum file;
every one has a durable owner and concrete unblock action.
