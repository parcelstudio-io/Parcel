# Sol Ultra final read-only audit

**Audit date:** 2026-08-30
**Mode:** fresh `gpt-5.6-sol`, ultra reasoning, read-only
**Autonomous physical motion:** **NO-GO**
**Observe-only / motors-disabled:** conditional

The reviewer made no edits, ran no tests, and did not touch the live owner
socket, ports, or default database. This file preserves its controlling findings
and the disposition applied after review.

The review findings below are preserved as found. Their bounded software
dispositions and guarded regression evidence are tracked separately in
[`POST_ULTRA_REMEDIATION.md`](POST_ULTRA_REMEDIATION.md); fixing those defects
does not change the physical NO-GO.

## Blockers

1. **Navigation remains hard red.** All six pose-drift arms miss their frozen
   floors, and the post-remediation slow marker still retains the 0.875-vs-0.90
   person-cell assertion. Do not enable motion until the commissioned frozen
   matrix is green. See [`POSE_DRIFT_NIGHTLY_AUDIT.md`](POSE_DRIFT_NIGHTLY_AUDIT.md)
   and [`NIGHTLY_REMEDIATION_AUDIT.md`](NIGHTLY_REMEDIATION_AUDIT.md).
2. **There is no physically independent stop chain.** The software stop
   principal cannot disable the body after gateway, Orin, shared-power, or
   vendor-controller failure. A normally closed independently powered
   actuator-disable/E-stop path and the Unitree remote require fault injection.
3. **[Source-fixed after audit; target evidence open] The runtime service
   selected a nonexistent profile.** It requested
   `physical`, but only the reviewed `go2_edu_plus` overlay exists. This is an
   unambiguous source defect selected for immediate remediation.
4. **[Target file added after audit; deployment still open] The five-service
   deployment is a target skeleton.** Runtime/LIO/audio
   artifacts, principals, paths, physical observation, clocks, extrinsics, and
   LIO are absent; `parcel.target` was also missing.
5. **The assumed and encoded BOMs disagree.** Research targets likely AGX Orin
   64 GB while the hardware overlay describes factory Orin NX 16 GB plus an
   external D455. The actual BOM, power, cooling, payload/CoM, serial identities,
   mounts, extrinsics, and timing must be frozen and measured.
6. **DSOAK-1 lacks strict temporal provenance.** The final arithmetic and
   retained hashes are internally consistent, but its checkpoint is overwritten,
   monitoring started late, the monitor is unsigned/unchained, process identity
   and final-file handoff are not bound, and verifiers were produced after the
   run. Its claim is now explicitly “self-reported and partially corroborated,”
   with machine scope in
   [`duplex-soak-1/INTERPRETATION.json`](duplex-soak-1/INTERPRETATION.json).

## High findings

- Physical LiDAR health can pass with one populated angular bin while NaN bins
  are skipped. Translation needs fresh contiguous travel-sector coverage,
  packet-loss/age limits, CRC/sequence validation, synchronized device time,
  and measured height/extrinsics.
- Commissioning hashes establish assertion agreement, not the observed robot's
  identity or a secure DDS boundary. A signed artifact must bind robot/sensor
  serials, firmware, calibration, topology, and hashes.
- Executive revision mutation precedes fallible publication/journal sinks;
  sink failure can expose partial state. This was selected for immediate
  transactional failure-injection remediation.
- Latent `ScanBehavior` / `SearchEntity` navigation failures can map to terminal
  success. This was selected for immediate failure-mapping tests and repair.
- A hung vendor `StopMove` call is not meaningfully retried: later attempts wait
  on the same in-flight generation. Fail-closed latching is useful but does not
  replace an independent hardware stop or killable vendor helper.
- Gateway audit export drains before write; disk failure can lose records while
  motion continues. It needs a durable/requeued spool and sticky evidence-health
  arming policy that never delays STOP.
- The commit-gate report did not bind a content identity for the materially dirty
  checkout. Worktree-manifest provenance was selected for immediate remediation.
- DSOAK source drift is not sticky-latched, its monitor does not bind the full
  dependency closure, and its verifier checks aggregate consistency rather than
  independently regenerating episodes/outcomes.

## Medium findings

- Compact Model-B frames omitted important authority lineage and were not
  revalidated at drain time. The process-local frame and drain defect was
  repaired after this read-only audit; commit-time, persistence, live-session,
  provider, and audio authority remain blockers.
- Terminal-pose retry retains original committed geometry while refreshing a
  candidate. The unchanged K0 region is fail-closed, but future work must either
  prove geometry identity or recompute all derived geometry atomically.
- Conversation/research storage is plaintext without complete message-level
  consent, retention, deletion, encryption, or deletion verification. Collection
  remains default-off and must not be enabled for owner data.
- Frozen DSOAK machine fields use misleading names such as `promotion_pass` and
  keep refuted narration gates green. Frozen bytes were preserved; a controlling
  interpretation sidecar now declares promotion and semantic truth non-evaluable.
- `product-evals/summary.json` was stale. It was upgraded to v2 with corrected
  acoustic, durability scope, and commit/nightly results.

## Positive findings

- Top-level documentation consistently denies physical deployment authority.
- Model A remains proposal-only; no learned artifact promotion or actuator
  bypass was found.
- Gateway boot is disarmed and enforces peer, epoch, sequence, TTL, freshness,
  stop confirmation, compensation for late move completion, and fail-closed
  latching.
- The physical observation source refuses to fabricate simulator provenance.
- The person-cell threshold was not weakened post hoc, and collision braking
  remains authoritative.
- The lamppost recovery passed two narrow live-simulator repetitions without
  changing safety or arrival thresholds.
- Prompt assets and current OpenAI Realtime protocol/pricing assumptions were
  consistent with official documentation; no OpenAI-specific blocker was found.

## Required physical ladder

After code-level remediation, the minimum next rung is permanently disarmed
target install/boot and motors-disabled HIL on the exact frozen BOM. Powered
testing still requires synchronized mounted perception/localization, contiguous
LiDAR coverage health, calibrated D455/audio/AEC, signed device-bound
commissioning, concurrent Orin thermal/power/timing measurements, a physically
independent E-stop, and measured braking envelopes. Sidewalk, crosswalk,
elevator, stair, and autonomous people-adjacent operation remain **NO-GO**.
