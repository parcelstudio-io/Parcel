# K2′ status — sim-bag harness + hardware-readiness

**Date:** 2026-08-05 · **Owner lane:** Opus (stand-in) · **Binding:** Owner
amendment in [ADJUDICATION.md](ADJUDICATION.md) (hardware last).

## Delivered

| Item | Path | Notes |
|---|---|---|
| Versioned bag schema `parcel.bag.v1` | `src/parcel_robot/bags/schema.py` | Clocks, frames, envelopes, non-empty `does_not_prove`; agent path rejects privileged oracle fields |
| Recorder / replayer MVP | `src/parcel_robot/bags/recorder.py`, `replayer.py` | Directory bag: `manifest.json` + `messages.jsonl` |
| Package export | `src/parcel_robot/bags/__init__.py` | |
| Roundtrip + oracle isolation tests | `tests/test_bags_roundtrip.py` | |
| Hardware-readiness ledger | [hardware-readiness.md](hardware-readiness.md) | HR-1…HR-9 with named P5 re-run gates |
| Golden-image ADR (draft) | [adr/0001-golden-image.md](adr/0001-golden-image.md) | Validate at P5 |
| Firmware-pin ADR (draft) | [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md) | ≥1.1.13; validate at P5 |

## Explicit non-claims

- No hardware purchased or commissioned (owner: hardware last).
- No Jetson flash, no firmware check executed.
- Sim bags do not prove physical sensing, Sport tracking, Orin latency, or audio UX.
- Scorer/oracle counterfactuals are **out of band** — not on the agent bag path.

## Next (out of K2′ MVP scope)

- Wire recorder into headless/MuJoCo run loops.
- Fault-injection overlays on replay.
- Real bag drop-in at P5 (HR-8 gate).
