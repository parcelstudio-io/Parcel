# Research data-plane probe results

Date: 2026-08-26
Result artifact: `results.json`
Prototype: `prototype.py`
Schema: `schemas/research_event_v1.schema.json`

## Outcome

All six falsifiable hypotheses passed in the local synthetic probe. The result establishes that a small, isolated SQLite → canonical bundle → byte-capped sync → verified replay pipeline is mechanically feasible on this development host. It does not establish production privacy, cryptography, physical-robot performance, cloud correctness, or Starlink performance.

## Commands run

From the repository root:

```bash
python3 -m py_compile research/20260826/research-data-plane/prototype.py
python3 -m json.tool research/20260826/research-data-plane/schemas/research_event_v1.schema.json >/dev/null
python3 -m json.tool research/20260826/research-data-plane/source_manifest.json >/dev/null
python3 research/20260826/research-data-plane/prototype.py
python3 research/20260826/research-data-plane/prototype.py \
  --output research/20260826/research-data-plane/results.repeat.json
```

The repeat artifact was compared programmatically and then removed. Both runs had the same retained counts, event-set digest, bundle-manifest digest, and 6/6 hypothesis verdict. `results.json` is the retained run.

Environment recorded in the result:

- Python 3.14.4
- SQLite 3.46.1
- Linux 7.0.0-30-generic x86-64, glibc 2.43
- standard library only; no GPU and no network service

The benchmark’s code SHA-256 was `f8184afe976b3724885f94fb1e54e5df3f9bdbc4761895869751bf2f2ff917cd`; config SHA-256 was `7983e243f72b963d623a8323da6e5a41c4bcd4115464825ab435724df20ad119`.

## Workload

One deterministic synthetic hour modeled five typed summary streams:

| Stream | Rate | Retained events |
|---|---:|---:|
| Navigation summary | 2 Hz | 7,200 |
| Acoustic summary | 1 Hz | 3,600 |
| Perception summary | 1 Hz | 3,600 |
| Conversation outcome | one per 30 s | 120 |
| Learning feedback | one per 5 min | 12 |
| Total | — | 14,532 |

There were 14,535 candidates: 14,532 valid summary events plus three negative controls (companion-only data, a raw payload, and consent-required data without consent). All three controls were rejected before persistence.

Synthetic values included deterministic random hashes and varied numeric/categorical content so compression was not measured on identical rows. The workload still is not a model of real physical entropy or event cadence.

## Observations

### Admission and privacy seed test

- Scanned 68 artifacts while the scratch workspace existed: one SQLite spool, one manifest, and 66 compressed bundles.
- Ten known leak markers produced zero hits.
- Replayed events contained zero forbidden keys.
- The filter removed eight instances each of exact latitude, longitude, and address; five each of raw audio, transcript, voice embedding, raw image, and face embedding; and eight unknown navigation fields.
- It redacted eight email occurrences, eight phone occurrences, and four credential occurrences from explicitly allowed note fields.
- Companion-only, raw-payload, and missing-consent controls were each rejected once.

This is a seeded negative-control test. It does not prove de-identification, recognize indirect identity/location inference, or make arbitrary free text safe. A production design should avoid free text, use narrow per-event schemas, quarantine anomalies, and add privacy threat-model and human review gates.

### Spool and idempotency

- SQLite used WAL and `synchronous=FULL` in a scratch database separate from product memory.
- Spool file after checkpoint: 28,880,896 bytes.
- 100 duplicate event inserts produced zero new rows due to event-ID and run/stream/sequence uniqueness.
- Ingestion plus validation took about 0.765 s in this run.

No sudden-power-loss or filesystem-full fault was injected, so the configuration is not a crash-durability result.

### Bundling and replay

- Canonical NDJSON: 16,696,858 bytes.
- Deterministic gzip bundles: 1,514,594 bytes across 66 priority-separated chunks.
- Compression ratio: 0.0907 (9.07%).
- Bundle throughput: 117.9 MB/s on this host.
- Replay throughput: 32.3 MB/s on this host.
- Both replays recovered exactly 14,532 unique events and contiguous per-stream sequences.
- Both event sets had SHA-256 `15e4fdcb4ec6702739037a3e3c5c3b63f6b417575521ba0c3069b63262bf8e03`.
- The bundle manifest digest was stable across the repeated process run: `93d3cf5590d8dc1adec3b0e247e46643af40273eeea257d8bb5a78b9d5631784`.
- Flipping one byte changed the bundle SHA-256 and was detected before decompression.

The throughput is a single warm local run, not a distribution and not an Orin result. gzip/JSONL was tested as edge interchange, not as an analytical lakehouse format.

### Resumable byte-budget simulation

- The first deliberately partial round transferred 34 of 66 content-addressed bundles and 753,940 bytes.
- A second round transferred the remaining 32 bundles and 760,654 bytes under a 50 MiB cap.
- A third retry transferred zero bytes because every content hash was already present.
- All priority 0–2 bundles were present at the end.

This simulated whole-object resume and idempotency locally. It did not exercise TLS, authentication, multipart state, remote checksum semantics, packet loss, Starlink, or a cloud object store.

### Traffic and cost sensitivity

Extrapolating the measured synthetic summary output to 8 h/day for 30 days:

| Quantity | Projection |
|---|---:|
| Compressed summaries per hour | 1.514 MB |
| Summary ingress per month | 0.363 GB |
| 90-day retained summaries | 1.090 GB |
| Fraction of a conservative 40 GB priority bucket | 0.91% |
| R2 Standard 90-day summary storage at $0.015/GB-month | $0.016/month |
| Bundle puts per month | 15,840 |
| Gross R2 Class A put estimate | $0.071/month |
| Put estimate after cited 1M/month free tier | $0/month |

The raw scenario was deliberately explicit:

- PCM16 mono 16 kHz: 32,000 B/s, derived from sample rate and width;
- JPEG camera: 5 fps × 150,000 B/frame = 750,000 B/s, an assumption to measure;
- serialized lidar: 100,000 B/s, an assumption to measure.

Together that is 882,000 B/s, or 762.048 GB/month at the same duty cycle—19.05 times a 40 GB bucket. One month retained at the cited R2 Standard rate is about $11.43/month. That excludes compute, catalog operations, retrieval, taxes, Starlink plan/overage, support, and labor. Camera/lidar rates are not physical measurements and must not be used for procurement.

## Hypothesis matrix

| ID | Threshold | Observation | Result |
|---|---|---|---|
| H1 privacy boundary | zero seeded marker/key hits; three negative controls rejected | zero hits; all three rejected | PASS |
| H2 deterministic replay | exact count/digest twice; idempotent duplicate; mutation detected | 14,532 twice; stable digest; 0/100 duplicate inserts; mutation detected | PASS |
| H3 compact/fast bundles | ratio ≤0.30; throughput ≥10 MB/s | 0.0907; 117.9 MB/s | PASS |
| H4 budgeted sync | ≤5 GB/month; all priority 0–2 within 50 MiB/day | 0.363 GB/month; all synced | PASS |
| H5 summary-first required | raw >40 GB/month; summary <40 GB/month | 762.048 GB; 0.363 GB | PASS (scenario-sensitive) |
| H6 summary storage cost | 90-day summary storage <$1/month | about $0.016/month | PASS (price-sensitive) |

## What the probe did not test

- physical sensor rate, MCAP reference-reader interoperability, Orin CPU/disk/power/thermal behavior;
- sudden power loss, disk exhaustion, SQLite recovery, retention sweeper, or deletion cascade;
- arbitrary PII inference or privacy/legal compliance;
- AES-GCM, KMS/HSM, key rotation, cryptoshred, TLS, IAM, or restore;
- object-store and multipart APIs, network interruption, Starlink variability, or metered billing;
- Parquet/Iceberg conversion, transactional catalog commits, concurrent writers, analytical query cost;
- dataset-label quality, learned-model improvement, safety/regression gates, or physical behavior.

Those are production/pilot gates, not evidence that can be inferred from this passing local result.
