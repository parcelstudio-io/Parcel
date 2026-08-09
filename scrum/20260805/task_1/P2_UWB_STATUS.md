# P2 Status — UWB noise model + owner-fusion seam (Sol pure)

**Phase:** 2 (sim) · **Owner lane:** Sol (pure) · **Date:** 2026-08-05 ·
**State:** DONE (pure modules + CI; no real UWB / DDS; no hardware claims)

Binding: [ADJUDICATION.md](ADJUDICATION.md) D3 + Owner amendment P2
(“UWB noise model … so the owner-fusion code path exists and is tested
before characterization”). Ledger: [hardware-readiness.md](hardware-readiness.md)
**HR-2**.

## Delivered

| Artifact | Path |
|---|---|
| UWB package | `src/parcel_robot/uwb/` |
| Noise config + multipath schedule | `…/uwb/noise.py` |
| `UwbSample` (EvidenceEnvelopeV1) | `…/uwb/sample.py` |
| Observation model | `…/uwb/model.py` |
| Sim injector → extras / bag payload | `…/uwb/injector.py` |
| Fusion seam stub (vision ↔ UWB primary) | `…/uwb/fusion.py` |
| CI tests | `tests/test_p2_uwb_noise.py` |
| Hardware-readiness HR-2 update | [hardware-readiness.md](hardware-readiness.md) |

## Checklist

- [x] Pure **UWB observation model**: configurable bearing/range Gaussian noise,
  quality roll-off, range cutoff
- [x] **Multipath dropout schedule**: forced windows, periodic bursts, optional
  Bernoulli `p_dropout`
- [x] Envelope / freshness via `EvidenceEnvelopeV1` on `UwbSample` (DetectionMsg-
  compatible discipline; K1 `OwnerTrackV1` / `DetectionMsg` unchanged)
- [x] Sim **injector** attaches noisy UWB (or dropout marker) to headless/owner
  extras under `extras["uwb"]`; bag-shaped `uwb/state` payload helper
- [x] **Fusion seam stub**: `OwnerFusionConfig.primary ∈ {uwb, vision}` switches
  which channel drives pose into `OwnerTrackV1` **without contract change**
- [x] Fail-closed on missing / stale / multipath-suspect primary
- [x] Explicit `DOES_NOT_PROVE` strings (HR-2 honesty)

## Fusion switch surface (no contract change)

Consumers keep reading `OwnerTrackV1`. Primary is a **config** on the stub:

```text
OwnerFusionConfig.primary: "uwb" | "vision"
OwnerFusionStub.with_primary("vision")  # invert after P5 data
```

- Primary channel must be fresh and above `min_primary_quality`.
- Secondary channel may corroborate identity / appearance refs only.
- Pose always comes from the primary sample’s bearing/range.

P5 characterization (HR-2) decides which default to ship; flipping primary
does not require a DTO revision.

## Explicit non-claims

- **No real UWB / `rt/uwbstate`.** Noise params are sim placeholders, not
  fitted Unitree statistics.
- Passing CI is **sim evidence only** — see HR-2 P5 re-run gate.
- Stub fusion is not Kalman/IMM association or ReID confirmation.
- Injector may use privileged GT poses *internally*; agent path sees only
  `UwbSample` / `extras["uwb"]`.

## Test command

```bash
pytest tests/test_p2_uwb_noise.py -q
```
