# Host-side systemd unit verification

Date: 2026-08-29

Command run from the repository root:

```bash
systemd-analyze verify deploy/orin/services/*.service
```

Result:

```text
deploy/orin/services/parcel-gateway.service:100: Unknown key 'StartLimitIntervalSec' in section [Service], ignoring.
parcel-audio.service: Command /opt/parcel/bin/parcel-audio is not executable: No such file or directory
parcel-gateway.service: Failed to create parcel-gateway.service/start: Unit parcel-nftables.service not found.
parcel-gateway.service: Command /opt/parcel/bin/parcel-gateway is not executable: No such file or directory
parcel-lio.service: Command /opt/parcel/bin/parcel-lio is not executable: No such file or directory
parcel-runtime.service: Failed to create parcel-runtime.service/start: Unit parcel-nftables.service not found.
parcel-runtime.service: Command /opt/parcel/bin/parcel-runtime is not executable: No such file or directory
parcel-safety.service: Command /opt/parcel/bin/parcel-safety is not executable: No such file or directory
```

Interpretation: the parser independently confirms that the gateway crash-loop
limit is in the wrong section and will be ignored. The missing `/opt/parcel/bin`
programs and `parcel-nftables.service` are expected on this development host, but
they also mean this repository does not currently provide a host-verifiable,
complete Orin service composition. This check did not start any service or touch
hardware.

## Repair and rerun

The two start-limit directives were subsequently moved to `[Unit]`, and a
section-sensitive regression test was added. The guarded unit test file passed
15/15. A second `systemd-analyze verify` run no longer emitted the unknown-key
warning; its only remaining gateway messages on this development host were:

```text
parcel-gateway.service: Failed to create parcel-gateway.service/start: Unit parcel-nftables.service not found.
parcel-gateway.service: Command /opt/parcel/bin/parcel-gateway is not executable: No such file or directory
```

This closes review finding P1-7 at the unit-file level. It does not make the Orin
composition runnable or close any of the review's P0 motion blockers.
