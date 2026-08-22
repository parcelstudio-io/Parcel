# Blocked work

**Opened:** 2026-08-04 · **Refreshed:** 2026-08-22 from the
[conversational-autonomy HLD](../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
· Conventions in [README.md](README.md).

Promotion, decision, and evidence work that needs something outside the repository.
Some cards also name repository prerequisites; start the physical/decision work only
when both the internal predecessors and the explicit external unblock are satisfied.
Each card names the unblock so nobody has to re-derive it.

Historical B1 (optional system packages) and B2 (ONNX endpointing install) are
closed; their evidence remains in the dated scrum/status records. They are not
blockers. Active external work begins below.

---

## B3 — ReSpeaker XVF3800 physical stream · *attached, not commissioned* · **robot through-air/AEC blocker**

> **2026-08-22 delta:** USB enumeration now reports Seeed `2886:001a`, so
> procurement/attachment is closed. It does **not** prove a UAC product stream,
> DoA control access, AEC, speaker wiring, or through-air latency. The remaining
> external unblock is the udev/usbfs access plus operator-supervised capture,
> playback, echo and double-talk runbook.

> **2026-08-07:** with B1 demoted and B2 landed, a transducer is the single
> hardware item gating the robot Tier-2 through-air rig, the
> whole AEC ladder (ERLE cannot be measured where there is no echo path), the
> double-talk operating curve, and the first sound Parcel ever makes in a
> room. **Any** analog mic + speaker in the HD-Audio jacks unblocks Tier 2;
> the XVF3800 additionally unblocks hardware AEC. Owner runbook:
> [../docs/ACOUSTIC_BRINGUP_PLAN.md](../docs/ACOUSTIC_BRINGUP_PLAN.md) §5.
> B15 policy, N37 software integration, B18 command/privacy policy, and B21's
> human corpus remain separate voice/audio gates.


Ordered 2026-08-04 with a CQRobot 4 Ω 3 W JST-PH2.0 enclosed speaker. Full
arrival checklist, wiring constraint, and the speaker-specific cautions are in
[../scrum/20260804/task_1/B-audio-io.md](../scrum/20260804/task_1/B-audio-io.md) card B3.

The one thing worth repeating here: **the speaker must be wired to the array's
own JST amp output**. The AEC reference is the array's DAC path; a separate
USB speaker defeats echo cancellation entirely. And do not drive a 3 W driver
near clipping — a clipped speaker breaks AEC (the modelled echo is linear),
which shows up as barge-in false triggers rather than merely bad sound.

**Unblocks:** deleting the `echo_guard_scale` stopgap, real barge-in during
playback, and DoA-driven head orientation.

---

## B4 — Operator file deletion · *classifier-blocked for agents*

The 2026 redesign severed all code paths to the removed research trees, but
the files themselves are still on disk. Presence is not a production claim
([../docs/REDESIGN_2026_ASSESSMENT.md](../docs/REDESIGN_2026_ASSESSMENT.md) §6).

**Refreshed 2026-08-04 (task_4 O1):** candidate list staged at
[`scrum/20260804/task_4/freeze/b4_delete_list.txt`](../scrum/20260804/task_4/freeze/b4_delete_list.txt)
(8 roots: `src/parcel_robot/rl`, BARN development v4–v8 trees, experiments
v9–v10). `navigation/pipeline.py` now lazy-imports the v8 shield so importing
the navigator no longer pulls `experimental_all_ray_shield` into the default
grep/import surface O2 is refactoring.

**Operator command (run locally; agents must not):**

```bash
# From repo root, after reviewing the staged list:
LIST=scrum/20260804/task_4/freeze/b4_delete_list.txt
# Optional: archive first
mkdir -p deleted-archive && tar -czf "deleted-archive/b4-$(date -u +%Y%m%dT%H%M%SZ).tgz" -T "$LIST"
xargs -a "$LIST" git rm -r --ignore-unmatch
# Any still-untracked trees:
xargs -a "$LIST" rm -rf
.parcel/bin/python -m pytest -q
```

Low urgency: do it when convenient; nothing production-critical depends on it.
Keep `experimental_all_ray_shield.py` until BARN v8 tests are retired — only
the eager import was removed.

---

## B5 — Arrival honesty under a drifting MAP: the predicate has no pose-error reserve · **owner decision needed (2×2)**

**Opened:** 2026-08-12 (Wave 2 of
[../scrum/20260811/task_2/SLAM_M_PLAN.md](../scrum/20260811/task_2/SLAM_M_PLAN.md),
card DR-2; full record in
[../scrum/20260811/task_2/DR2_STATUS.md](../scrum/20260811/task_2/DR2_STATUS.md) §5/§5b
and [../scrum/20260811/task_2/AUDIT_WAVE2_FABLE.md](../scrum/20260811/task_2/AUDIT_WAVE2_FABLE.md)).

- **The defect, measured and 4-0 audit-confirmed (bit-for-bit reproduction):**
  the arrival predicate consumes 100 % of the K0 band with no reserve for pose
  error. On the `calibrated_go2_reanchoring` eval arm — the only arm where MAP
  drift can reach the predicate — the controller stops 0.002–0.040 m inside the
  2.5 m outer band edge *in its own MAP frame*, while claim-tick MAP error runs
  0.007–0.239 m. Result: 3 of 7 arrivals stopped TRUE-outside the band
  (−0.153 m / −0.043 m / −0.024 m); one exceeded the scorer's 0.05 m epsilon
  and is the standing `false_arrival=1` red on the nightly
  `pose-drift-arms:safety` hard gate. The honest rate is 3/61, not 1/61 — two
  were absorbed as `tolerated_boundary`.
- **Why no card could fix it:** neither existing guard can catch it — the
  provider reports `HEALTHY` at the claim tick, and its covariance is 3.6×
  optimistic by documented design (systematic biases excluded from `_var_xy`,
  DR1_STATUS §9). The fix lives in the arrival predicate
  (`pipeline.py` / K0 seam), and making arrival stricter moves EVERY frozen
  eval row — frozen-row movement = STOP + 2×2 by global rule 2.
- **Unblock action (owner):** decide the mechanism and authorize the re-freeze.
  Candidate mechanisms recorded in DR2_STATUS §9 handoff 1 (e.g. an arrival
  margin derived from distance-since-last-reanchor × the calibrated drift band,
  or an owner-set fixed reserve), with the enumerated non-fixes (DEGRADED
  gating, covariance gating, epsilon widening) and why each fails.
- **Then execute:** implement the selected reserve at the current single arrival-
  predicate seam, consume timestamp-compatible pose health/covariance, and apply it
  uniformly to the currently supported finite point/region/relation claims. Freeze a
  typed witness fixture now; N34 later migrates the exact selected semantics into
  `TerminalWitnessV2` without re-deciding them. Re-run the approved 2×2 and all
  affected frozen rows without loosening scorer truth.
- **Exit evidence:** the standing 0.239 m-error fixture cannot report arrival; all
  three TRUE-outside claims become `NOT_ARRIVED`/`UNCERTAIN`; independent evidence,
  settled feedback, and the selected reserve are present on every success witness;
  mutation of any reserve input makes the hard gate red.
- **Does not prove:** localization accuracy, semantic grounding, or physical stopping.
- **Until then:** the nightly red is the record. Do not tune the band, the
  scorer epsilon, or the arm to green it.
- **Relations:** sharper, drift-induced sibling of the U32 false-success class
  (that one was a 3.2 m verification disagreement; this one is frame trust);
  U34's "MAP is a perfect reference" assumption is exactly what the
  re-anchoring profile withdraws.

---

## B6 — The collision brake hard-stops on perpendicular obstacles at the stop radius · **owner decision needed (2×2)**

**Opened:** 2026-08-12 (Wave 3 of
[../scrum/20260811/task_2/SLAM_M_PLAN.md](../scrum/20260811/task_2/SLAM_M_PLAN.md),
card RM-3; corrected localization in
[../scrum/20260811/task_2/AUDIT_WAVE3_FABLE.md](../scrum/20260811/task_2/AUDIT_WAVE3_FABLE.md) —
the RM3_STATUS §7.1 first draft blamed the grid controller; the audit proved
by instrumentation, 8/8 refuter-confirmed, that the brake is the module).

- **The defect, executed and reproduced bit-for-bit:** `apply_collision_brake`
  under the SHIPPING config (`safety.stop_distance_m: 0.8` →
  `CollisionPolicy(obstacle_stop_m=0.8, predictive_mode='projected_speed_cap')`)
  zeroes any command whenever `nearest_obstacle_m ≤ 0.8` and the bearing has
  ANY positive closing fraction — `cos(−1.53 rad) = 0.041 > 1e-9` passes the
  relevance gate (`collision.py:135/152-155`). A static crate at exactly the
  stop radius, **87.7° off the travel axis**, stops the robot dead for as long
  as it stands there (measured: 63 brake calls zeroing 0.09–0.85 m/s requests
  on one episode; 40 of 42 route-memory-armed eval cells failed wedge-like).
  Reachable **flag-OFF** (executed) — a pre-existing product defect, not
  route memory's; it is why RM-3's pre-registered McNemar gate nulled
  (net flips 0, p = 1.0): memory supplies an aim point; an aim point cannot
  restore a velocity the brake keeps zeroing.
- **Why it needs the owner:** the fix changes hard-safety semantics (when may
  a near-perpendicular, non-closing obstacle inside the stop radius NOT stop
  the robot?) — "no safety weakening" territory — and any change moves every
  frozen eval row: STOP + 2×2 by global rule 2. Candidate directions for the
  2×2: bearing-scaled stop radius vs a closing-fraction floor above 1e-9 vs
  lateral-clearance carve-out; each must re-prove the frozen collision=0 rows.
- **Unblock action (owner):** select one directional swept-footprint/closing-
  relevance rule and authorize the preregistered baseline/candidate 2×2 plus frozen
  collision and route-memory re-freeze.
- **Then execute:** implement the rule once in the current final collision-constraint
  path and freeze its evidence-attributed input/output fixture; preserve exact stop
  for intersecting/closing footprints. N43/N41 later consume the same rule/fixture and
  carry its geometry/envelope revision into `SafetyDispositionV1` rather than
  reinterpreting it.
- **Exit evidence:** perpendicular non-intersecting clutter no longer wedges the
  selected cases, every prior zero-collision hard gate remains zero, swept-footprint
  and closing-object adversarial cases still stop, and mutants that erase bearing,
  footprint, or uncertainty are killed.
- **Does not prove:** physical obstacle sensing, stopping distance, or performance in
  unseen geometry; B27 owns bounded robot evidence.
- **Until then:** route memory cannot convert the bottleneck it was built for
  (RM-3's honest null is the record), and `v4r`-class scenarios with wall-line
  clutter will keep failing on both arms.
- **Relations:** found because B5's sibling wave put the first
  flag-ON eval pressure on cluttered long-travel cells; the RM-2 wiring
  itself is audited sound (chains arm, win arbitration, and drive — 4,892
  chain ticks — the legs just cannot move through a braked tick).

## B7 — Rotation policy for degraded/recoverable input classes · **owner decision needed (2×2)**

**Opened:** 2026-08-13 · **Corrected:** 2026-08-16 by the HLD code audit.

- **Correction to the original diagnosis:** the intermediate input-health branch
  can preserve yaw while suppressing translation, but a **latched** input-health
  fault is routed through emergency finalization and becomes exact `(0,0,0)` at the
  actuator boundary. `tests/test_e2_safety_wiring.py` and the hard-stop evidence pin
  that behavior. The old title incorrectly treated the intermediate command as the
  vendor output.
- **The real open decision:** recoverable HOLD/proximity/missing-scan states and
  scan/search behaviors may preserve or request rotation. Grid scan validity is
  stricter than reactive “scan present,” so malformed calibration can currently
  fall into a point-goal navigator while a simpler downstream check still accepts
  motion. Before physical admission, every input/fault class needs an explicit axis
  matrix: exact HOLD, bounded rotation, or latched stop.
- **HLD default recommendation:** `HOLD` is exact zero. If looking around is safe for
  a particular fresh observed sector, admit a separate, bounded sensing-rotation
  intent with its own source, sector evidence, rate, TTL, task/revision, and final
  safety evaluation. Never hide inspection motion inside HOLD and never permit blind
  reverse.
- **Unblock action (owner):** approve the per-input-class matrix and whether the
  separate sensing intent is in first-ODD scope. Authorize the frozen-row 2×2 for
  scan/search rotation versus exact HOLD.
- **Then execute:** encode the matrix in the current input-health/finalizer path and
  freeze it as a porting contract for N43; any sensing rotation is a separately typed,
  TTL-bound intent now rather than hidden inside HOLD.
- **Exit evidence after decision:** property/mutation cases for missing, stale,
  malformed, wrong-frame, future, uncalibrated, and latched evidence pin every output
  axis and lifecycle disposition; the final post-shaper command is never more
  permissive than the matrix.
- **Not blocking recording:** this blocks positive-motion arming/promotion, not raw
  capture or software-only replay work.

## B8 — The no-provider pose fallback fabricates confidence · **owner decision needed (2×2)**

**Opened:** 2026-08-13 (same research pass; spot-confirmed at source).

- **The defect, read at source:** `pose.py:945-954`. When no `PoseProvider` is
  attached, `observation_pose` synthesises a `PoseEstimate` from
  `observation.position` and stamps it `health=PoseHealth.HEALTHY`,
  `covariance=ZERO_COVARIANCE`, `stamp_monotonic_s=0.0`. The fallback for
  "we have no localizer" is therefore **maximal claimed confidence with a zero
  timestamp** — fail-open by construction.
- **Correction to scope:** an attached provider that returns an invalid estimate
  raises; it does not silently take this fallback. Normal `RobotRuntime` simulator/
  eval construction also attaches an explicit `TruthPoseProvider`. The defect is the
  *absence* of a provider, not any half-wired provider, and the affected no-provider
  rows must be identified rather than attributed to truth-provider rows.
- **Why it matters and why it needs the owner:** zero covariance is not a neutral
  placeholder; it asserts perfect knowledge and defeats covariance/arrival-health
  gates. The HLD default is explicit sim/eval truth adapters plus fail-closed
  unavailable/unknown physical no-provider behavior. Adopting it changes existing
  no-provider behavior and may move frozen rows, so the repository's value-change
  policy still requires an owner-authorized comparison/re-freeze.
- **Unblock action (owner):** approve the explicit-adapter/fail-closed contract and
  the exact affected-row census. Authorize a paired old-fallback/new-fallback run;
  no unrelated truth-provider row may be re-frozen merely because it is nearby.
- **Then execute:** remove the current synthesized fallback in `pose.py` immediately,
  retain byte-equivalent simulator truth only through an explicit provider, and
  freeze the provider-absence contract. N31 later carries that contract into
  timestamped localization; N43 propagates its expiry to gateway TTL without
  reopening the semantic decision.
- **Exit evidence:** no-provider, provider-error, provider-loss, stale/future stamp,
  covariance growth, and recovery cases have typed health; no-provider cannot ground,
  move, or claim arrival; explicit simulator truth retains its pinned behavior.
- **Relations:** compounds B5 — B5 is the arrival predicate having no
  pose-error reserve; B8 is the pose layer beneath it claiming there is no
  pose error to reserve for. Fixing B5 without B8 leaves the reserve computed
  from a fabricated zero.
- **Not blocking the first physical session:** the session records sensors and
  runs no localizer. This blocks the Wave-1 physical pose provider, which must
  not be built until the fallback fails closed.

---

## B9 — Orin identity unread (H-1) · **operator · blocks S-2 finalize + H-2**

**Opened:** 2026-08-14 (DOC-G / AU-F prep from
[`scrum/20260814/task_1/REVISED_BOARD.md`](../scrum/20260814/task_1/REVISED_BOARD.md)).

- **Claim someone might assume:** the Orin is JetPack 6 / Ubuntu 22.04 / Humble
  and yesterday's recorder argv is safe to copy.
- **Reality:** H-1 has not run. Distro, JetPack, `/opt/ros`, free disk and
  Python are **UNREAD**. S-2 templates exist for Humble *and* Jazzy but
  **FINALIZE is BLOCKED** (`STAGE0_COMMAND_ADDENDUM.md` header).
- **Unblock (operator, first 30 min on the Orin, bench LAN — not robot LAN):**

  ```bash
  cat /etc/nv_tegra_release; lsb_release -a; uname -r
  ls /opt/ros; python3 --version; lsblk; df -h
  ```

  Record the exact output in the run header of
  `scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md`. JetPack 6.x / 22.04 /
  Humble → continue TONIGHT_CHECKLIST N1→N7. Anything else → **STOP**; report
  exact output; do not flash the single dock.
- **What it unblocks:** H-2 rehearsal; S-2 argv finalize from
  `Rosbag2Plan(distro=<observed>)` after `--verify-help`.

## B10 — No-dog Orin rehearsal NOT RUN (H-2) · **operator + Sol · after B9**

**Opened:** 2026-08-14.

- **Claim:** drivers, topics, recorder and preflight are session-ready.
- **Reality:** `NOT RUN` on the actual Orin. Desktop fixtures and Jazzy-sandbox
  bags are not Orin evidence (working agreement / Fable brief Q8).
- **Unblock:** after B9's distro answer — launch RealSense + L2 drivers;
  `ros2 topic list -t` + `ros2 topic hz`; render argv via
  `Rosbag2Plan(distro=<observed>)` with `--verify-help`; 10-minute D455 bag on
  the real record target; measure sustained write; run preflight end-to-end
  including `reconcile_support_topics`. Exit: measured evidence in
  `MRB_STATUS.md` / H-2 status, or a named blocker.
- **What it unblocks:** any `READY_FOR_STATIONARY_STAGE0` claim; next-session
  MR-C staffing decision.

## B11 — Mount + measure the rig on the dog (H-3) · **operator · today, software-independent**

**Opened:** 2026-08-14.

- **Claim:** mount geometry and FOV overlap are known.
- **Reality:** not executed. Independent of H-1/H-2/S-1/S-2.
- **Unblock:** follow REVISED_BOARD H-3 — SAFETY_BRIEF pre-reads; mount
  bracket/Orin/D455/L2 with strain relief; pre-torque geometric FOV gate;
  fill `MOUNT_GEOMETRY_SHEET.md` completely (tape + uncertainty, never
  calibrated TF); photograph per `PHOTO_LIST.md`. No stand without two people;
  no robot LAN before firmware pin.
- **What it unblocks:** deliberate `DEGRADE_MMP_ONLY` evidence path; geometry
  input for later extrinsic work. Durable even if every software card fails.

## B12 — S-2 Stage-0 command addendum FINALIZE · **blocked on B9 (H-1)**

**Opened:** 2026-08-14.

- **Claim:** T7–T10 are the commands of record for tomorrow's session.
- **Reality:** both-distro templates are drafted under
  `scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md` (Sol-owned renderer).
  Header correctly says **FINALIZE BLOCKED ON H-1**. Picking one argv before
  `/opt/ros/<distro>` is read would re-introduce the Humble
  `--disable-keyboard-controls` class of defect.
- **Unblock:** complete B9; then regenerate/finalize from
  `Rosbag2Plan(distro=<observed>)` after `--verify-help` against the installed
  recorder help. Do not hand-copy historical 20260813 sheets.
- **Owner:** Sol / S-2 lane (argv renderer). Do not edit-war with capture S-1.

## B13 — Isaac RTX sensor lane (IS-F) · **blocked on supported host/container**

**Opened:** 2026-08-14 (deferred from REVISED_BOARD; was P2 stretch).

- **Claim:** Isaac can smoke the PE-D sensor contract on this workstation.
- **Reality:** this desktop is **Ubuntu 26.04**, outside Isaac Sim's supported
  host matrix. Docker/ROS/Isaac are absent; `.parcel` must not gain vendor SDKs.
- **Unblock:** provision an Ubuntu **22.04 or 24.04** host or container; pin an
  Isaac Sim release/image **by digest**; run a single-GPU headless
  compatibility check without mutating the unsupported host into an untracked
  environment. Then implement an Isaac producer behind the PE-D
  `SensorFrameV2` contract (scorer-only oracle fields).
- **What it unblocks:** IS-F smoke only — never physical sensing claims.

## B14 — Operator/UI release, pause, cancel, and mission-authority semantics · **owner decision needed (2×2)**

**Opened:** 2026-08-15 (the "go to the sidewalk" incident investigation;
verdict record in the 20260815 debug session — 4 investigators, cross-examined,
link PROVEN).

- **The behaviour, proven at source:** the panel UI's `clearMotionInputs()`
  (`src/parcel_robot/ui/index.html:1609-1613`) queues a `{0,0,0}` **manual**
  motion, and it is wired to **window blur**, `visibilitychange`, Stop and
  Space (`:1667-1675`). A manual zero acquires the base
  (`manual_motion` → `_interrupt_brain("manual", ...)`,
  `runtime.py:2587-2593`) and preempts the navigation channel
  (`stop_motion` → `preempt("manual", targets=("spatial",))`,
  `runtime.py:2622-2625`), writing `navigation_disabled`. In the incident,
  BOTH admitted "go to the sidewalk" NavigateTo missions died exactly this way
  ("manual stop acquired the base") — the owner switching windows stopped the
  robot, and the UI gives no indication why.
- **Why it needs the owner:** blur-as-deadman may be *intentional* for
  held-key manual driving (release-on-focus-loss is a real safety property).
  The 2×2: does a blur-originated zero cancel an **autonomous admitted
  mission** it did not start, or only release **manual** authority? Candidate
  mechanisms: only queue zeros on blur when a manual input was actually held;
  or tag blur-originated zeros so `manual_motion` releases manual authority
  without preempting spatial. Any change moves a stop pathway = STOP + 2×2 by
  global rule 2.
- **Decision required beyond blur:** define, for browser blur/tab hide, release of a
  held manual key, Space, Stop, PAUSE, manual zero, disconnect, and operator takeover,
  which authority is released and whether an admitted task continues, pauses with a
  checkpoint, or is cancelled. Emergency STOP remains independent and dominant.
- **Unblock/exit:** owner approves the event-by-event authority matrix and frozen-row
  2×2. Encode the chosen blur/manual-release/cancel behavior in the current runtime/UI
  now and freeze typed-origin fixtures; prove delayed/duplicate focus events cannot
  cancel or resume the wrong task and display the resulting disposition/owner. N32/
  N33 later consume those fixtures through the unified authority/task contracts
  without changing the selected behavior.
- **Until then (operator workaround):** keep the panel window focused while a
  navigation mission runs.

## B15 — Echo/junk-transcript defense for real-mic rigs · **owner decision needed (2×2 stack)**

**Opened:** 2026-08-15 (same investigation). The self-talk storm exposed that
the voice input path has **no post-STT sanity layer**: whisper's
`[BLANK_AUDIO]` marker is submitted as a command verbatim; fragments of the
robot's own TTS ("Just", "him.", "Give") become commands; nothing compares
incoming transcripts against the words the robot is currently speaking
(`_finish_utterance`, `voice_audio.py:754-769`, submits every non-empty
transcript unconditionally); and "Hang/Hold on"-class mishearings parse as
`ClosedIntent.PAUSE` (`voice/closed_intents.py:29`) — the robot's own voice
can pause its navigation.

- **Candidate mechanisms (each needs the owner because each touches frozen
  surfaces):** self-echo transcript rejection against the robot's recent TTS
  words (emergency phrases exempt); a minimum-utterance-duration gate for
  speech that began during playback; whisper-marker filtering; a
  playback-aware confidence floor. All sit on the N16/N17 barge-in surface
  ("unprovable on the null-sink rig") and interact with the B2-frozen ep50
  endpointing eval — moving them re-opens those freezes = 2×2.
- **Hardware dependency:** honest tuning requires the real echo path — the
  XVF3800 (B3, still the standing blocker) wired per its own amp-output
  constraint. Until then any constants are guesses; the FIX-A arming gate
  (landed separately) prevents the *digital* self-loop, which is what made
  this catastrophic on the desktop.
- **Relations:** B3 (the transducer), N16/N17 (barge-in freezes), B14 (the
  other half of the incident).

---

## B16 — Gateway HIL and first bounded physical effect · **hardware/operator + N28**

**Opened:** 2026-08-16 from HLD Phase 0.

- **Blocked on:** N28's complete software gateway/fault exit, N29's schema/signature
  verifier, access to the intended robot/network, a supported vendor SDK in the
  native gateway environment (not `.parcel`), read-only observation of current vendor
  mode/state, an explicit arming token/acknowledgements, and an independent operator
  stop. Start from a reviewed provisional frame/axis sign and conservative speed/time
  band; this card measures and commissions them rather than assuming them. A
  gateway-only, single-axis HIL does **not** wait for B5/B6/B14 when autonomous
  navigation and UI/task authority are absent from the capability manifest. Any
  capability touched by unresolved B5–B8/B14 semantics stays disabled.
- **Unblock action:** the operator provides the robot, isolated network credential,
  supported gateway host/runtime, independent stop, arming token, vendor/manual
  references, and approval of the provisional single-axis envelope. No final
  capability signature is required before measuring the facts that will populate it.
- **Then execute:** fake-service parity, gateway boot-disarmed/arm/disarm, exact-zero
  stop, one explicitly armed axis at low speed, command age/ack/feedback, client
  kill/SIGSTOP, lease loss, restart, writer conflict, and stationary witness. Any
  posture/gesture remains unsupported unless its `GatewayActionV1` profile was
  separately admitted and bounded.
- **Exit evidence:** validated axis signs/frame/modes, repeated measured command-to-
  feedback and stop latency/distance, no auto-resume, prior-epoch rejection,
  independent-stop proof, and a locally signed capability/calibration/stopping-
  envelope manifest plus command/action/fault trace. B30 reruns the chain with N43's
  product client before B31; B27 reruns it again after N41 before P3 promotion.
- **Does not prove:** autonomous navigation, perception, localization, balance for
  uncommissioned actions, or first-ODD readiness. It is the bounded physical
  authority proof that can begin before advanced navigation.

## B17 — Physical localizer selection and `T_map_odom` commissioning · **real bags/host/operator**

**Opened:** 2026-08-16 from HLD Phase 1; physical half of former N15/N31.

- **Bake-off prerequisites:** N23/N30/N31 software contracts; B9/B10 Orin/topic
  evidence; B11 measured mount geometry; B12 finalized recorder invocation; B25's
  executed Stage-0 bag, clock map, TF/extrinsic/calibration digests and ground-truth
  reference; and an installed candidate localizer on a supported host.
- **Physical-profile exit additionally requires:** B8's implemented/re-frozen
  fail-closed no-provider behavior and N43's integrated authority-expiry/refusal path.
- **Unblock action:** owner selects the first-ODD sensor/localizer candidates and
  supplies representative real bags/ground-truth reference. Run the preregistered
  GLIM/KISS-ICP/Point-LIO (or accepted alternatives) bake-off without changing the
  snapshot/health contract to suit a winner.
- **Then execute:** first run the offline candidate bake-off, then—only after the exit
  prerequisites above—run time-aligned `map -> odom -> base_link`, covariance calibration,
  provider loss, relocalization/jump, loop closure, drift, restart, and stale-TF
  tests. Replay through `NavigationSnapshotV2` and a fake/record-only N43 gateway
  path; no replay may authorize a real robot. Any later low-speed transform test needs
  its own separately admitted B31 or B27 scenario.
- **Exit evidence:** selected/pinned implementation and image digest, calibrated
  covariance/health bands, no discontinuous command on transform epoch change, and
  physical-profile refusal when localization evidence expires.
- **Does not prove:** semantic perception, owner identity, route success, or public
  outdoor localization.

## B18 — Owner identity, voice authority, and memory/privacy policy · **owner decision**

**Opened:** 2026-08-16 from HLD Phases 2–3.

- **Decision required:** enrollment/re-enrollment and revocation; who may authorize
  positive motion; whether voice alone is sufficient and in which ODD; behavior on
  identity ambiguity/occlusion; profile/audio/image retention; consent, export, and
  deletion; remote-model data egress; and whether proactive motion may originate
  outside an already authorized mission.
- **Conservative software default while blocked:** test principal only; autonomous
  subgoals stay within an authorized task/geofence/TTL; no nearest-person fallback;
  only healthy `LOCKED` owner belief permits first-ODD follow translation; no
  predicted translation during occlusion; no remote inference or durable private
  fact without explicit consent.
- **Unblock action:** owner accepts a versioned policy/ADR and test identities,
  retention periods, revocation flow, and physical authorization matrix.
- **Blocks promotion of:** N32 physical command authority, N36 durable owner profile,
  N38 enrollment/re-ID/following, and any multi-person voice demo.
- **Exit evidence after decision:** adversarial principal/echo/replay/revocation,
  twins/stranger-nearer/occlusion, consent withdrawal, export/delete, and data-egress
  tests with human-readable operator state.

## B19 — First-ODD acceptance contract and candidate capability manifest · **owner/safety decision**

**Opened:** 2026-08-16 from HLD Phase 4.

- **Decision required:** target robot; candidate sensors/localizer/map sources and
  selection rule; compute, power, network and independent-stop requirements;
  lighting/weather/surface/slope/speed/supervision bounds; supported actions;
  geofence; privacy/security posture; and release thresholds for
  stop latency/distance, false arrival, collision/keepout/drop-off, identity swap,
  task success, intervention, conversation repair, and latency tails.
- **HLD default boundary:** flat mapped private indoor/outdoor routes, dry, adequate
  light, walking speed, trained operator, independent stop; roads/crossings, stairs,
  hills, dense crowds, and unsupervised/public use hard denied.
- **Unblock action:** owner and safety reviewer approve a versioned manifest and
  preregistered scenario/repetition/confidence-interval plan. N42 must be able to
  record every threshold and `does_not_prove` before the first acceptance run.
- **Blocks:** integrated Phase-4 commissioning and any “first ODD ready” claim.
- **Exit evidence after decision:** signed first-ODD acceptance contract, candidate
  capability manifest/selection rule, threshold table, and preregistered scenario/
  repetition/confidence plan accepted before data collection. B17 selects/pins the
  localizer; B24 freezes the final installed release manifest and owns repeated
  integrated replay/HIL/robot execution.
- **Does not prove:** that any declared capability meets its threshold, that the
  selected hardware is commissioned, or that results generalize beyond the signed
  robot/environment/version.

## B20 — Hosted GitHub Actions execution proof · **repository-admin action**

**Opened:** 2026-08-16 from the HLD evidence audit.

- **Reality:** workflow and local commit/nightly runner definitions exist, but their
  own documentation says hosted GitHub Actions is not yet wired. A green local gate
  is not proof that push/PR/scheduled jobs execute externally.
- **Unblock action:** a repository administrator enables Actions/runners and required
  permissions/secrets, then triggers one push/PR commit run and one scheduled or
  manual nightly run at a pinned commit.
- **To close:** record run URLs/IDs, runner image, commit, artifacts, hard-gate
  dispositions, expected-failure behavior, and a seeded failing control that makes
  the hosted job nonzero. Update `docs/CI.md` only from observed execution.
- **Does not prove:** physical, acoustic, HIL, or ecological validity.

## B21 — Record the human audio evaluation corpus · **owner + any real microphone**

**Moved:** 2026-08-16 from `NEXT.md` N-AUDIO-REC because it is not unblocked
repository work.

- **Blocked on:** any usable analog or USB microphone and an owner recording session.
  This need not wait for the robot XVF3800; B3 remains the real robot audio/AEC gate.
- **Unblock action:** attach/enable a capture source, follow
  `evals/companion/personal_convo_v1/human_recording/SCRIPT.md`, and record the
  consented corpus with device/room/speaker metadata and retention policy.
- **To close:** replay the corpus through the frozen evaluation path, publish the
  human-vs-synthetic delta and `does_not_prove`, and store/delete audio according to
  B18 policy.
- **Does not prove:** live audio I/O, AEC, barge-in, or command authorization.

## B22 — Semantic acceptance, affordance, and yield-deadline policy · **owner decisions + preregistered comparisons**

**Opened:** 2026-08-16 by moving the unresolved product semantics from N11/N13.

- **Decisions required:** whether a stuff-class directive such as “the sidewalk”
  means a specifically grounded polygon or any matching instance; whether `next_to`
  bands scale with object surface/robot footprint or unsupported affordances (for
  example the blocked bench) are removed; and how long an admitted navigation step
  may yield before reporting `blocked_by_person` rather than `step_timeout`.
- **Why blocked:** these choices change frozen goal/arrival rows and user-visible
  language semantics. Controller tuning cannot decide them honestly.
- **Unblock action:** owner selects each semantic and authorizes the affected re-
  freeze across grounder, typed `NavigationIntent/GroundedGoal/ExecutionGoal`,
  approach solver, terminal witness, scorer, and dialogue disposition.
- **Exit evidence after decision:** three separately preregistered comparisons: (1)
  specific polygon vs any matching instance, (2) footprint-scaled band vs explicit
  unsupported affordance, and (3) each candidate yield deadline/policy vs the current
  baseline. If interactions are claimed, run the full factorial; do not call three
  axes one 2×2. Static and traffic cases must report the selected semantics
  consistently without false arrival or a hidden timeout.
- **Does not prove:** relations, object classes, crowd dynamics, or deadlines outside
  the preregistered cases.

## B23 — Task resumption after restart, relocalization, or gateway re-arm · **owner decision**

**Opened:** 2026-08-16 from HLD open decision 8.

- **Decision required:** for each task/action class, decide whether a certified
  checkpoint may be considered after Python restart, localization epoch change,
  gateway restart/re-arm, operator takeover, or lost authority—and what fresh
  evidence, user re-authorization, resource reacquisition, and terminal policy are
  required. Gateway commands never auto-resume.
- **Conservative default while blocked:** no positive-motion task auto-resumes.
  Preserve an audit record only; require fresh snapshot/transform/capability checks
  and explicit authorization before a new transaction. Decorative expression may be
  discarded rather than restored.
- **Unblock action:** owner approves a task-class × disruption matrix and authorizes
  the affected authority/checkpoint/revision re-freeze for N28/N31/N32/N33/N34/N43.
- **Exit evidence after decision:** crash/restart, relocalization jump, re-arm, stale
  checkpoint, revoked principal, changed goal/world, and duplicated event tests prove
  no prior transaction can silently reacquire motion authority.
- **Does not prove:** process durability, localization recovery quality, or physical
  restart safety.

## B24 — Integrated first-ODD robot commissioning campaign · **hardware/operator/environment**

**Opened:** 2026-08-16 from HLD Phase 4.

- **Blocked on:** signed B19 scope/thresholds; B16/B17/B30/B31 early commissioning;
  B25–B28
  staged evidence; B18/B23 policy; applicable B5–B8/B14/B15/B22 decisions and exits;
  N32–N44 software exits required by the admitted capability manifest; applicable
  B29 human evidence; B3 through-air hardware when spoken interaction is in the
  admitted first ODD; a trained operator, independent stop, controlled site, and
  repeatable ground truth.
- **Unblock action:** safety reviewer signs the exact release/capability manifest and
  scenario order, confirms all predecessors by artifact hash, and authorizes only the
  first rung. A failed hard gate stops escalation.
- **Then execute:** repeat the earlier gateway/localizer checks, then progress through
  static obstacles, dynamic people/yield, owner identity and occlusion, conversation
  during motion, correction/pause/cancel/recovery, semantic terminal verification,
  and multi-stage missions. Record environmental/operator metadata and
  `does_not_prove` for every run; do not tune on held-out acceptance repetitions.
- **Exit evidence:** preregistered repetitions meet B19 safety, task, interaction, and
  latency thresholds with confidence intervals; independent stop succeeds; no
  unresolved hard-safety event exists; every claim is traceable through N42.
- **Does not prove:** unsupervised use, public streets, roads/crossings, stairs, hills,
  dense crowds, adverse weather/light, a different robot/release, or safety
  certification. A text-only campaign also does not prove physical audio/AEC,
  barge-in, or audible interaction.

## B25 — Execute Stage-0 sensor capture and calibration artifact · **hardware/operator**

**Opened:** 2026-08-16 from HLD Phase 1 and the S-1/S-2 capture handoff.

- **Blocked on:** N23/N25/N26 software exits; B9 observed Orin identity; B10 no-dog
  rehearsal; B11 measured mount geometry; B12 finalized recorder command; physical
  sensors/host, observable clock domains/timestamp sources plus a calibration method,
  and a controlled calibration scene.
- **Unblock action:** operator mounts the measured rig, verifies the rendered recorder
  invocation and independent disk/power budget, and selects one non-actuating branch:
  (A) sensor-only/off-robot-LAN, with dog/controller channels explicitly UNAVAILABLE;
  or (B) full read-only dog-topic capture only after Unitree firmware `>=1.1.13`
  attestation and read-only overlay verification, with no command/gateway credential.
- **Then execute:** record camera/depth/LiDAR/IMU/TF/controller/timing topics with
  per-topic loss accounting; capture calibration/clock/ground-truth references;
  exercise start/stop, backpressure, truncation and restart; replay unchanged through
  N23. No robot actuation is required. N30 later consumes the immutable artifact and
  must reproduce coherent snapshots before B17 can close.
- **Exit evidence:** immutable bag/manifests, topic/type/rate/loss table, clock map,
  TF/extrinsic/intrinsic digests, mount measurements, calibration residuals, host/
  driver image hashes, selected network branch/firmware attestation, and explicit
  unavailable/degraded channels.
- **Does not prove:** localization, perception accuracy, navigation, robot timing, or
  that the mount survives locomotion.

## B26 — Stationary physical perception and owner-identity rung · **hardware/operator + N38**

**Opened:** 2026-08-16 from HLD Phase 3 interleaved evidence.

- **Blocked on:** N38, B17/B18/B25, applicable B7 search-rotation policy, consented
  enrolled/test identities, and a controlled multi-person/occlusion setup. B16 and
  N43/B30 are additionally required if separately admitted sensing rotation is
  exercised.
- **Then execute:** keep translation disabled; test detector/tracker timing, capture
  independence, enrolled owner vs nearer stranger/twins, crossings, occlusion,
  ambiguity, reacquisition and revocation. If rotation is admitted, bound its sector,
  rate and TTL and run it through N43.
- **Exit evidence:** repeated identity belief/state/confusion metrics with no nearest-
  person switch; ambiguity/loss becomes HOLD; cached/correlated frames cannot satisfy
  evidence quorum; real latency/resource tails and model/calibration hashes recorded.
- **Does not prove:** autonomous following, moving social comfort, navigation, or
  crowd robustness.

## B27 — Low-speed local-navigation, governor, and stop rung · **hardware/operator + N39/N41/N43**

**Opened:** 2026-08-16 from HLD Phase 3 interleaved evidence.

- **Blocked on:** N39/N41/N43; B16/B17/B25/B30/B31; B6/B7/B8 decisions and
  implementation exits; B19 scenario limits; applicable B23 restart/resume policy; commissioned footprint/
  stopping envelope; independent stop; and a controlled low-speed course. Owner-
  identity/follow and every dynamic-person/yield/pass case additionally require N38
  and B26; static geometry cases do not.
- **Then execute:** re-run B16 kill/SIGSTOP/TTL/restart/writer-conflict/stopping with
  N41 in the unchanged sole-client session; inject missing/stale/malformed scans and
  ROS loss; run static/perpendicular/closing and dynamic-person obstacles, observed-
  frontier recovery, yield/pass, and bounded owner-follow formation at the lowest
  admitted speed.
- **Exit evidence:** measured stop latency/distance and clearance fit the signed
  envelope; invalid evidence and ambiguity produce exact HOLD/STOP; no stale revision,
  model/UI/logger failure, recovery target or challenger bypasses N43; no auto-resume.
- **Does not prove:** semantic arrival, geofence/drop-off enforcement, multi-stage
  missions, nominal-speed operation, or first-ODD readiness.

## B28 — Physical terminal, geofence, and negative-terrain rung · **hardware/operator + N34/N40/N41/N43**

**Opened:** 2026-08-16 from HLD Phase 3 interleaved evidence.

- **Blocked on:** N34/N40/N41/N43; B5/B6/B7/B17/B19 and applicable B22 exits; B25
  sensor evidence; B27 local stop/governor evidence; a surveyed private geofence;
  and safe, instrumented curb/drop-off/keepout fixtures with an independent stop.
- **Then execute:** point/region/relation arrivals with pose error and changed semantic
  evidence; map reanchor/loop closure; off-map and road/crossing hard denials;
  covariance touching a boundary; moved landmarks; curb/drainage/drop-off and missing
  low-viewpoint evidence; route-memory edge invalidation. N40 supplies constraints;
  N43/N41 alone enforce the final command.
- **Exit evidence:** zero false arrival, keepout/geofence crossing, or unsupported-
  terrain entry in the preregistered repetitions; every terminal claim has compatible
  independent evidence and settled feedback; missing/uncertain terrain evidence
  refuses motion.
- **Does not prove:** public-road/stair/hill capability, arbitrary terrain, long-term
  map validity, or integrated conversational missions.

## B29 — Held-out human companion-quality evaluation · **participants/reviewers/consent**

**Opened:** 2026-08-16 from the HLD product-acceptance gate.

- **Blocked on:** N42's frozen protocol/harness; the N32/N35/N36/N37 interaction
  release under test; B18 consent/privacy/retention policy; representative held-out
  participants and independent reviewers. Through-air speech cases additionally need
  B3/B15; text-only review can begin without robot audio.
- **Unblock action:** owner approves the preregistered rubric, participant/reviewer
  recruitment, consent/retention/deletion procedure, conditions, sample size, and
  analysis plan before any ratings are seen.
- **Then execute:** blinded held-out review of coherence/helpfulness, reference and
  correction accuracy, interruption/repair, explanation truth, memory correctness
  and forgetting, latency perception, and comfort. Keep safety/parser gates separate;
  do not tune on held-out participants or collapse dimensions into one flattering
  score.
- **Exit evidence:** signed protocol, anonymized condition assignments, per-dimension
  results with uncertainty/inter-rater agreement, failures and qualitative themes,
  release/config/model hashes, and explicit `does_not_prove`.
- **Does not prove:** physical authorization, acoustic robustness unless through-air
  conditions ran, navigation ability, long-term companionship, or demographic
  generalization beyond the enrolled sample.

## B30 — Sole product-client TTL/stop HIL rung · **hardware/operator + N43/B16**

**Opened:** 2026-08-16 to close the HLD Phase-1 authority-expiry chain before P2/P3.

- **Blocked on:** N43 software exit, B16 gateway/commissioning evidence, the same
  isolated robot/network/independent-stop setup, and an operator-approved conservative
  single-axis capability. N43 must have landed its test-only `HilSessionV1` fixture
  emitter/negative gates. The operator signs one short-lived session manifest and
  test invariant lease within the commissioned axis/time/speed envelope; the emitter
  remains untrusted by N43, has no gateway credential, and is refused in product
  profiles. Navigation, semantic goals, and physical actions remain disabled.
- **Then execute:** mutually disable the N28 commissioning credential and enable only
  the N43 product client. Feed only `HilSessionV1` candidates within the signed one-
  axis/time/speed manifest; repeat exact-zero, command age/ack, client kill/SIGSTOP,
  source/ROS loss, snapshot expiry, positive-refresh cessation, gateway TTL stop,
  restart-disarmed, prior-epoch and writer-conflict tests. Kill Python/model/UI/logger/
  storage independently while the deterministic admitted loop is active.
- **Exit evidence:** the physical chain `source loss -> snapshot expiry -> no positive
  refresh -> gateway TTL stop` fits the signed B16 envelope; noncritical process loss
  cannot delay it; there is never a simultaneous commissioning/product writer or
  auto-resume.
- **Does not prove:** localization, obstacle avoidance, navigation, perception,
  semantic completion, or nominal-speed operation.

## B31 — Bounded observed-space/static-obstacle HIL rung · **hardware/operator + N44/B17/B30**

**Opened:** 2026-08-16 to test the local-planning seam before conversational/social
navigation integration.

- **Blocked on:** N44 integration exit, B17 physical-localization exit, B30 product-
  client stop evidence, commissioned footprint/stopping envelope, a surveyed straight
  low-speed course, and independent stop. Exclude sensing rotation, perpendicular-
  obstacle carve-outs, semantic goals, recovery, and social behavior so unresolved
  B6/B7 capabilities cannot leak into this rung. Reuse `HilSessionV1` to stamp the
  signed metric course goal and short-lived task/revision/candidate IDs; it remains an
  untrusted N43 input, cannot reach the gateway, and is absent from product profiles.
- **Then execute:** one-axis observed-frontier motion toward a surveyed metric goal;
  head-on static obstacle; unknown-space boundary; missing/stale/malformed/wrong-frame
  scan; localization loss/jump; transform/snapshot epoch mismatch; planner unavailable;
  and recovery-bypass injection. Repeat the N43 stop/TTL chain at the lowest admitted
  speed.
- **Exit evidence:** motion occurs only inside current observed/reachable space;
  invalid or incompatible evidence becomes exact HOLD/STOP; the head-on obstacle and
  source/localizer loss stop inside the signed envelope; no point-goal or blind-
  reverse fallback reaches the gateway.
- **Does not prove:** directional B6 policy, rotation, dynamic people, owner following,
  semantic arrival, recovery, geofence/drop-off, or full first-ODD navigation.
