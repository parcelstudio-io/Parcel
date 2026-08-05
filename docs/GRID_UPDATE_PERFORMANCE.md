# Rolling-grid update microbenchmark

`RollingOccupancyGrid.update` has an assertion-free microbenchmark at
`scripts/benchmark_grid_update.py`. It integrates a stationary, 720-ray,
270-degree open-space scan into Parcel's production-size 161-by-161 rolling
grid with a 12 m range cap. The ray count is a repeatable stress case, not the
exact daily simulator input: the MuJoCo backend currently publishes 360 rays
and default `grid_v1` applies `lidar_stride: 2` before integration. Run it from
the repository root:

```bash
.parcel/bin/python scripts/benchmark_grid_update.py --iterations 40 --warmups 5
```

On 2026-08-03, on the project's AMD Ryzen Threadripper PRO 7995WX host with
Python 3.14.4 and NumPy 2.5.1, the same command measured:

| Implementation | Median | Mean | p95 | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python sets, sorted cells, scalar NumPy writes | 22.885 ms | 24.443 ms | 32.071 ms | 22.535 ms | 34.212 ms |
| Batched Bresenham masks and vector log-odds writes | 3.403 ms | 3.475 ms | 3.660 ms | 3.336 ms | 3.884 ms |

The median update is 6.7 times faster. These are local microbenchmark results,
not real-time deadlines or navigation-quality evidence. The script emits JSON
and deliberately contains no timing assertion, because scheduler load and host
power state make wall-clock thresholds flaky. Exact sensor-model equivalence is
instead enforced by unit tests against an independent scalar Bresenham oracle.

A 2026-08-04 verification run on the same host, command, Python, and NumPy
versions measured 3.679 ms median, 3.640 ms mean, 3.720 ms p95, and 3.750 ms
maximum. Variation from the 2026-08-03 row is expected; the equivalence tests,
not a particular timing sample, are the correctness gate.

## What this result does and does not cover

The benchmark times only inverse-sensor-model integration into the rolling
log-odds grid. It excludes LiDAR generation/IPC, semantic-track parsing,
dynamic-agent Gaussian cost construction, footprint inflation, A*, route
smoothing, runtime arbitration, the two collision/TTC gates, and controller
delivery. In particular, default `grid_v1` now replans every tick while its
dynamic-agent cost layer is active, so this number alone cannot establish the
10 Hz end-to-end navigation deadline. Use `ControlLoopWork`,
`NavigationController`, and `ControlLoopOverrun` runtime metrics for that
claim.
