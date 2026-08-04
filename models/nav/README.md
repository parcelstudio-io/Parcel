# Navigation model cache

Download immutable, checksummed artifacts with:

```bash
.parcel/bin/python models/nav/fetch_models.py citywalker_2000hr
```

`models.lock.json` records the release URL, byte count, digest, release-tag
commit, repository-review commit, and license scope. The CityWalker repository
code is Apache-2.0, but the exact original GitHub v1.0 checkpoint has no
artifact-specific notice and is recorded as `NOASSERTION`. A later official
ai4ce Hugging Face conversion is Apache-2.0; that is evidence for the converted
artifact, not automatic licensing of the byte-distinct original checkpoint.
Checkpoints are intentionally ignored by Git.

Downloaded does not mean active. CityWalker requires an isolated Python 3.11 /
PyTorch environment and timestamped RGB plus trajectory history. Parcel does
not yet provide pixels through `NavObservation`, so `citywalker_v1` remains an
explicit research checkpoint and the active navigator stays `stub_v0`.

Never route a learned trajectory directly to joints. A future adapter must
convert it into bounded local waypoints, then pass them through LiDAR collision
checking, the runtime command arbiter, and the closed-loop locomotion backend.
