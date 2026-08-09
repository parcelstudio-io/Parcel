# P3 Status — City layer in sim (GNSS / OSM / Overture / crossing)

**Phase:** 3 (sim) · **Date:** 2026-08-05 · **State:** DONE (pure modules +
CI fixtures; no hardware; no Nav2 authority migration)

Binding: [ADJUDICATION.md](ADJUDICATION.md) Owner amendment P3 (“City layer,
in sim”). Ledger: [hardware-readiness.md](hardware-readiness.md) **HR-3**,
**HR-10**, **HR-11**.

## Delivered

| Artifact | Path |
|---|---|
| GNSS package | `src/parcel_robot/gnss/` |
| Noise + dropout schedule | `…/gnss/noise.py` |
| `GnssFix` (EvidenceEnvelopeV1) | `…/gnss/sample.py` |
| Observation model | `…/gnss/model.py` |
| Sim injector → extras / bag payload | `…/gnss/injector.py` |
| Maps package | `src/parcel_robot/maps/` |
| OSM footway/crossing graph | `…/maps/graph.py` |
| SE2Goal waypoint proposer | `…/maps/waypoints.py` |
| Overture tile client (offline) | `…/maps/overture.py` |
| Crossing / curb policy | `…/maps/crossing.py` |
| Neighborhood fixture | `src/parcel_robot/runtime_assets/maps/neighborhood_v1.json` |
| Overture places fixture | `src/parcel_robot/runtime_assets/maps/overture_places_v1.json` |
| CI tests | `tests/test_p3_city_layer.py` |
| Hardware-readiness HR-3/10/11 | [hardware-readiness.md](hardware-readiness.md) |

## Checklist

- [x] Pure **GNSS covariance/dropout model** (east/north jitter, cov inflation
  after dropouts, canyon schedule) → `GnssFix` / extras[`gnss`] / bag
  `gnss/fix`
- [x] **OSM footway/crossing graph** from cached neighborhood fixture;
  optional `try_osmnx_pull_to_fixture` (fail-closed if osmnx absent)
- [x] **OsmWaypointProposer** → `SE2Goal` for GoalArbiter / ProposerBus;
  crossing edges off unless policy authorizes
- [x] **Overture brand-tile client** over cached fixtures only (no network)
- [x] **Crossing mode**: curb-stop + announcement + owner voice initiation;
  hard geofence — zero autonomous road entry (tests pin this)
- [x] Fail-closed on missing path, road keepout goals, unauthorized voice
- [x] Explicit `DOES_NOT_PROVE` strings (HR-3 / HR-10 / HR-11)

## Crossing contract (sim)

```text
SIDEWALK → APPROACHING_CURB → CURB_STOPPED
  → (voice: "go" / "cross" / …) → CROSSING_AUTHORIZED
  → sidewalk after clearing curb/road
```

- Road keepout polygon is lethal to autonomous goals without authorization.
- `allow_crossing=True` on the OSM proposer is **only** legal when
  `CrossingModePolicy.allow_crossing_edges()` is true.
- Voice never releases a proximity/collision stop (callers keep that gate).

## Explicit non-claims

- **No real GNSS / ZED-F9P / NTRIP.** Noise params are sim placeholders.
- **No live osmnx or Overture download** in CI/default runtime.
- Cached fixtures are not surveyed sidewalks or CDLA field truth.
- Crossing policy does not prove field curb detection or leashed-course
  minutes-per-intervention.
- No Nav2 / ROS 2 authority migration (D1 stands).

## Test command

```bash
pytest tests/test_p3_city_layer.py -q
```
