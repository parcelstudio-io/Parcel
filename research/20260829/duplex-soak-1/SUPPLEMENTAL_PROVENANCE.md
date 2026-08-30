# DSOAK-1 supplemental provenance

This record was captured **after** the run, during final synthesis on
2026-08-30. It describes the surviving host environment and checkout; it is
not a preregistered or independently timestamped launch manifest and cannot
prove that every value was unchanged during the soak.

| Field | Observed value |
| --- | --- |
| Checkout HEAD | `c96ac345358ec2786748fc3a885c35d32710c5e2` |
| HEAD commit time | `2026-08-30T01:19:41-04:00` |
| Python | 3.14.4, GCC 15.2.0 |
| Interpreter | `/home/jaewoo-jang/.cache/parcel-0e/venv/bin/python` |
| Interpreter SHA-256 | `b8d8288faefdd300201f43fcf00f6f539a27218eeed3a3dff5ab10b9c4c99700` |
| Torch | `2.13.0+cu130` |
| NumPy | `2.5.2` |
| Kernel / libc | Linux 7.0.0-30-generic x86_64 / glibc 2.43 |
| CPU | AMD Ryzen Threadripper PRO 7995WX, 96 cores / 192 logical CPUs |

The frozen runner itself recorded one Torch thread, process ID 164974, source
and model hashes at start and finish, timestamps, monotonic elapsed time, and
bounded RSS samples in [`results.json`](results.json). The strict verifier
confirmed the serialized start/finish source/model hashes match. That proves
internal byte consistency for the paths the runner hashed, not Git
preregistration, package closure, kernel identity, or external custody.
