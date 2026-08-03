# Rolling-grid update microbenchmark

`RollingOccupancyGrid.update` has an assertion-free microbenchmark at
`scripts/benchmark_grid_update.py`. It integrates a stationary, 720-ray,
270-degree open-space scan into Parcel's production-size 161-by-161 rolling
grid with a 12 m range cap. Run it from the repository root:

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
