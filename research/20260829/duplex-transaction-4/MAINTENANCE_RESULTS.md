# DMC-4 post-evidence maintenance 1 results

**Verdict:** `DMC4_MAINTENANCE_EQUIVALENCE_PASS`

The maintained source resolves `ExecutiveTransitionV1`'s public type hints,
retains the resource-blocker identity when an in-place resume fails, leaves the
task suspended, returns no dispatch, and appends no accepted transition for that
rejection. Targeted Ruff/compile checks passed, and the focused executive/DMC-4
selection passed **29 tests**.

Two valid fresh maintenance runs (`E` and `F`) each retained 1,824 accepted
mutations and passed the original H1–H5-static raw-trace oracle. They reproduced
the original roots exactly:

- normalized trace:
  `4814882460c6101c202c21d6e49d5c47d4ffe14b5dbcec70b49c82109db2c45e`
- chain root:
  `a928bdaba0c5900b87648fdd0ae36f5e5bf2062d60d5bb62e2648e516b2874c2`
- verifier digest:
  `90434457a0b783733fe7f31efeae84e6717d2ae647f36c907d106eb90c7218ca`
- five maintenance tamper categories detected: 5/5.

The first attempted C invocation is deliberately non-evidentiary. It wrote a
trace, then the wrapper converted the frozen runner's successful `None` return
with `int(None)` and exited nonzero. The output remains preserved, and the
execution note plus superseding v2 manifest were frozen before E/F.

## Retained file hashes

- maintenance source manifest v2:
  `0a300dad41d1f98889cea33dc9b503bd97eb2b9f86c31c269948bf163c70569d`
- run E:
  `9cf48749a5ec446f6f6ad0a578d0437338cab9eeeca5cd00a0eac8a68a1aeac1`
- run F:
  `d047e71dad44f5da4117e9aa42d9de052469c6d3ae71baea73e0548e2b9a93a1`
- verification:
  `05402a8de7b63862dd0d40081b4869bf3030b78ac7882929e7e76a1d1c61ee2e`
- tamper results:
  `d2e8d5b27695720de797aca15eb40ecd0441505976f5f23b7ad449c9a197f459`

The original source manifest and A/B evidence are preserved as historical
evidence for their exact pre-maintenance sources. Current-source reproduction
uses `maintenance_source_manifest_v2.json`, E/F, and
`maintenance_verification.json`.

This maintenance result adds no runtime consumer, provider, audio, navigation,
hardware, or physical-readiness evidence.
