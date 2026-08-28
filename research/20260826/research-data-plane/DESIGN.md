# Off-robot research data plane

Date: 2026-08-26
Status: proposed architecture plus local mechanism probe; not a production deployment

## Decision in one sentence

Build a separate, summary-first research plane: keep crash-recoverable MCAP and owner/companion memory local by default, admit only typed pseudonymous summaries into a dedicated SQLite spool, upload deterministic encrypted bundles through a fail-closed byte governor, and let offline learning consume versioned datasets through lineage and promotion gates—not through the live robot's memory or motion path.

The local probe shows that the core spool/bundle/replay mechanism is feasible. It does not establish privacy compliance, physical-robot throughput, Starlink reliability, cloud/KMS correctness, or learning quality.

## Boundaries and terminology

These are different stores with different purposes. Treating them as one “memory” would create both a privacy failure and an unsafe learning path.

| Plane | Purpose | Typical data | Default location | May affect live behavior? |
|---|---|---|---|---|
| Companion memory | Serve this owner during ordinary interaction | consented owner facts, conversation turns/summaries, preferences, route/place state | robot/local owner store | Yes, through existing guarded product APIs |
| Operational evidence | Diagnose one run and support safety/evaluation claims | mission/safety events, counters, clocks, capture sidecars | robot/local session folder | No direct control; read by evaluators |
| Research memory | Compare runs, build datasets, label failures, train/evaluate candidates | pseudonymous typed summaries; separately consented raw windows | dedicated research spool and off-robot object store | Never directly; only an evaluated, signed promotion may enter product code/models |

Hard invariants:

1. The research exporter must never open or migrate the owner SQLite database. It consumes an explicit event interface or copied, purpose-approved artifact.
2. Owner facts, raw transcripts, voice/face embeddings, secrets, exact addresses, and exact coordinates are not research summaries.
3. “Learning feedback” is an observation about a candidate, not authority to change navigation, memory, or motion.
4. Failure of logging, upload, catalog, or cloud service cannot block a stop or insert network I/O into a control loop.
5. Raw capture and research export require distinct controls. Enabling a local diagnostic recording is not consent to upload it.

## Existing Parcel substrate: keep, adapt, or exclude

This design follows the existing strong seams rather than replacing them.

### Keep and reuse

- The sim bag contract already declares hardware-shaped topics, separate source/receive clocks, frame and calibration identifiers, expiry, and recursive rejection of privileged oracle fields (`src/parcel_robot/bags/schema.py:13-31`, `:88-100`, `:129-180`, `:195-215`). Those provenance fields should map into research events.
- The deterministic sim replayer validates record counts and computes a canonical SHA-256 digest (`src/parcel_robot/bags/replayer.py:19-100`). The research replay contract extends that pattern across content-addressed bundles.
- The physical capture path correctly explains why the JSONL sim recorder is not suitable for binary physical sessions: it rewrites the manifest per message, lacks append/resume durability, and has one global sequence (`scripts/parcel_capture/record.py:6-23`). Its append-only MCAP plus recovery-built sidecar is the right raw substrate (`scripts/parcel_capture/record.py:25-64`).
- The physical budget code already follows the right epistemic rule: overestimate or refuse, measure real framing, and never call an unmeasured destination adequate (`scripts/parcel_capture/budget.py:9-41`). Apply the same rule to network byte budgets.
- ROS 2 capture tests demand selected topics, MCAP, write-split and message-loss events, and sidecar hashes (`tests/test_rosbag2_sidecar.py`). Preserve those artifacts and their evidence semantics.
- The session evidence log correctly separates a short ring (“what is happening”) from an append-only session history (“what happened”), names byte-cap closure, and never blocks/raises into producers (`src/parcel_robot/realtime/evidence_log.py:11-72`, `:107-121`). The exporter should consume closed evidence logs asynchronously.
- The arbitration log already canonicalizes candidate/commit records and binds them with SHA-256 so a selector can be replayed (`src/parcel_robot/counterfactual/arbitration_log.py:183-216`, `:232-267`). These are high-value learning-feedback inputs after pseudonymization.

### Keep local unless separately admitted

- `ConversationMemory` is a local conversation/owner store with no raw audio, an owner-fact table carrying provenance/consent/edit/delete data, and an enforced read-only SQLite mode (`src/parcel_robot/memory/conversation.py:49-116`, `:348-427`). Research code must not reuse this database as a spool.
- The tiered conversation and route-memory stores are product cognition. Route keyframes can contain map poses, embeddings, frame IDs, metadata, and labels (`src/parcel_robot/route_memory/memory.py:30-114`). Export only a derived relative trajectory/aggregate under a research contract; never bulk-copy the store.
- Duplex transcripts explicitly stay local and rotate at about 2 MB (`src/parcel_robot/duplex/session_log.py:12-68`). That is not a long-term dataset or an upload grant.
- Session audio capture writes owner and robot WAV files but is bounded and owner-opt-in; its default is off (`src/parcel_robot/realtime/audio_gateway.py:591-666`, `src/parcel_robot/realtime/config.py:704-710`). Default research export is an acoustic summary, not either WAV.
- The local ear gate demonstrates the needed ordering: admission and identity happen before upload because post-upload identity is too late for cost and privacy (`src/parcel_robot/realtime/ear_gate.py:1-28`). Research export needs an equivalent pre-spool gate.

### Gap to fill

Parcel has a hosted-call spend governor, not an off-robot byte/retention governor. `HostedCallGovernor` protects the application’s $160 hosted-call envelope and fails closed for unknown routine-call accounting (`src/parcel_robot/realtime/hosted_budget.py:1-52`, `:62-85`). There is no unified research consent ledger, pseudonymous event schema, long-lived upload spool, resumable content-addressed sync, deletion cascade, or off-robot dataset catalog.

## Proposed architecture

```text
sensor/runtime producers                  companion product path
        |                                      |
        +--> selected-topic MCAP + sidecar     +--> owner SQLite / tiered / route memory
        |    (local, raw, opt-in)                    (local, owner-controlled)
        |
        +--> typed summary adapters -- pre-spool admission ----------------------+
                                      | allow-list / purpose / consent / expiry  |
                                      v                                          |
                              dedicated SQLite WAL spool                         |
                                      |                                          |
                              deterministic bundles                              |
                           gzip NDJSON + SHA-256 manifest                         |
                                      |                                          |
                      client envelope encryption (AES-256-GCM)                    |
                                      |                                          |
                       priority + daily/monthly byte governor                     |
                                      | resumable/content addressed               |
                                      v                                          |
                        object store + small metadata catalog                     |
                                      |                                          |
                      offline redaction checks / transforms / labels              |
                                      v                                          |
                         versioned dataset + lineage + replay                     |
                                      |                                          |
                             evaluation and human review                          |
                                      | signed promotion only                     |
                                      +------------------------------------------>+
```

No arrow returns directly from research storage to a live control topic, owner-memory row, or motion command.

### 1. Raw robotics evidence

Use the existing selected-topic `ros2 bag record -s mcap` path for physical capture. MCAP supports schemas/channels/messages, chunks, compression, CRCs, indexes, and summaries in one robotics-oriented container ([MCAP specification](https://mcap.dev/spec)). The official rosbag2 MCAP plugin exposes storage profiles and warns that `fastwrite` lacks message indexing and is not a recommended long-term form; an indexed compressed form such as `zstd_fast` is suitable after capture ([rosbag2 MCAP plugin](https://github.com/ros2/rosbag2/blob/rolling/rosbag2_storage_mcap/README.md)).

Recommended two-object flow:

1. Record the existing crash-recoverable local profile and build/verify its sidecar.
2. Preserve the original object hash.
3. If conversion is desired, create a second indexed/compressed MCAP, validate it with the reference reader, and record `derived_from` plus code/config hashes. Never overwrite the source.
4. Upload raw MCAP only for a named protocol or targeted failure window with a valid consent/scope record and a short expiry.

The JSONL `BagRecorder` remains appropriate for sim fixtures, not physical binary data (`src/parcel_robot/bags/recorder.py:23-56`, `:70-117`).

### 2. Research event contract

`schemas/research_event_v1.schema.json` is CloudEvents-inspired. CloudEvents requires `id`, `source`, `specversion`, and `type`, with `source` plus `id` acting as a unique event identity ([CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)). Parcel extensions make research policy and replay explicit:

- `run_id`, `stream`, per-stream `sequence`;
- pseudonymous robot ID, separate source and receive clocks;
- `privacy_class`, `purpose`, `consent_id`, `retention_class`, `priority`;
- source event IDs and code/config/model/calibration digests;
- typed stream data.

Streams are navigation summary, conversation outcome, acoustic summary, perception summary, and learning feedback. Data keys are allow-listed per stream before the local spool. The JSON Schema uses the stable Draft 2020-12 dialect ([JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)).

Unknown fields fail or are quarantined; they do not silently widen the research contract. Free text should be exceptional. Regex redaction is a backstop for seeded mistakes, not an anonymity claim.

### 3. Edge spool and bundles

The prototype uses a distinct SQLite database with WAL, `synchronous=FULL`, primary-key event IDs, unique `(run_id, stream, sequence)`, expiry, and sync state. Production should also have:

- bounded bytes and age; stop summaries with a named reason before consuming reserved disk;
- a reserved control quota for consent revocations/tombstones;
- crash-start integrity check and recovery metric;
- queue/drop/gap counters carried into the next successful manifest;
- transactional bundle claiming so an uploader crash cannot lose or double-delete rows;
- a filesystem guard that resolves every spool/bundle path under the configured research root.

Canonical NDJSON bundles are grouped by priority, compressed, and named by SHA-256. The manifest binds bundle hash, sizes, counts, event-ID digest, schema, and lineage. This is a simple edge interchange format; it is not the proposed analytical table format.

### 4. Object store and analytical table

Start with portable object storage and immutable manifests:

```text
control/tombstones/date=YYYY-MM-DD/...
raw/mcap/protocol=<id>/date=.../run=<id>/original.mcap
raw/mcap/protocol=<id>/date=.../run=<id>/sidecar.json
bundles/schema=v1/date=.../priority=<n>/<sha256>.jsonl.gz.enc
datasets/<dataset_id>/metadata.json
datasets/<dataset_id>/manifests/<snapshot>.json
derived/<transform_id>/<input_digest>/<output_digest>.*
```

Do not deploy a lakehouse merely for the label. Compact summary events to Parquet/Iceberg when scan cost, table size, concurrent writers, or schema evolution makes manifest-only access painful. Iceberg’s immutable data files, snapshots, and explicit metadata commits are a good eventual fit ([Iceberg specification](https://iceberg.apache.org/spec/)). Dataset releases can publish Croissant 1.1 JSON-LD metadata for files/records/fields ([Croissant 1.1](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html)).

Cloudflare R2 is a plausible cost-conscious object backend, but its managed Iceberg Data Catalog is public beta as checked on 2026-08-26 ([R2 Data Catalog](https://developers.cloudflare.com/r2-data-catalog/)). Keep catalog interfaces portable and do not make that beta service the only recoverable metadata pointer.

### 5. Lineage, datasets, replay, and promotion

Use an OpenLineage-compatible shape—job, run, input datasets, output datasets, and versioned facets—without requiring an OpenLineage service in the first prototype ([OpenLineage model](https://openlineage.io/docs/), [dataset lineage facet](https://openlineage.io/docs/next/spec/facets/dataset-facets/lineage/)). The minimum release manifest binds:

- immutable input object hashes;
- consent/purpose/retention policy version;
- schema versions;
- adapter, redactor, transform, labeler, and evaluator code/config/model hashes;
- excluded/quarantined counts and reasons;
- output hashes and row counts;
- evaluation suite version and promotion decision.

Replay procedure:

1. Resolve a dataset snapshot, never “latest.”
2. Verify manifest signature and every object hash before decoding.
3. Decrypt in an access-controlled workspace; verify authenticated-encryption tags.
4. Validate schema, event uniqueness, per-stream sequence/gap records, clocks, and retention/consent status.
5. Re-run the pinned transform/evaluator and compare canonical output digests plus metric tolerances.
6. Emit a new lineage record; never mutate the historical snapshot.

Research feedback may train or tune a candidate offline. It reaches the robot only through a signed promotion manifest after navigation, conversation, safety, privacy, and regression gates. Promotion is reversible and version-pinned. A feedback label can never write an owner fact or authorize motion.

## Privacy, consent, retention, and deletion

The engineering objectives follow purpose limitation, minimization, storage limitation, integrity/confidentiality, affirmative consent, and erasure concepts in the official GDPR text ([Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng)). This is risk-control guidance, not a legal conclusion. NIST explicitly treats de-identification as risk management rather than a perfect transformation ([NISTIR 8053](https://nvlpubs.nist.gov/nistpubs/ir/2015/nist.ir.8053.pdf)).

### Admission policy

- Use a project-scoped HMAC pseudonym, not serial number, account ID, owner name, or a stable cross-purpose identifier. Rotate it when a research purpose ends.
- Emit relative navigation deltas and place-class aggregates. Exact GNSS and home/place addresses are a separately consented raw class.
- Emit conversation outcome codes, counts, and latency—not transcript text. A redacted excerpt requires explicit per-study consent and quarantine review.
- Emit VAD/SNR/acoustic-class summaries—not WAV or voice embeddings. Face/voice embeddings stay companion-local.
- Reject credentials/secrets and unknown keys before persistence. Quarantine anomalous events locally with a short TTL; never “upload and clean later.”
- Bind consent to subject, purpose, data classes, destinations, grant time, expiry, policy version, and revocation time. The model cannot manufacture consent.

### Recommended initial retention

| Data class | Default off-robot retention | Notes |
|---|---:|---|
| Consent/tombstone control records | Minimal non-content audit for the required legal/operational period | Keep hashes, scope, time, action; no deleted content |
| Operational-health nonpersonal summaries | 90 days hot; aggregate up to 1 year | Remove robot/site linkability where possible |
| Relative navigation and perception summaries | 90 days; aggregate up to 1 year | Exact GNSS is excluded |
| Exact GNSS/location | Off by default; at most 30 days when study-consented | Treat home inference as sensitive |
| Conversation metrics with no text | 90 days | No owner fact values or transcript |
| Redacted conversation excerpt | Off by default; at most 30 days when study-consented | Human/DLP quarantine check before release |
| Raw owner/robot audio | Off by default; 7 days, extendable to at most 30 days for a named review | Existing local opt-in is not upload consent |
| Raw images/video/MCAP | Off by default; 7–30 days for a named protocol/incident | Preserve source and sidecar hashes |
| Face/voice embeddings | Never in the research plane by default | Companion-local biometric control |
| Pseudonymous feedback labels | Up to 1 year | Delete or recompute when a source is erased |
| Nonpersonal schema/model/eval lineage | Multi-year | Tombstone missing/deleted inputs; do not retain personal payloads inside manifests |

Retention must be computed at admission and enforced in the spool, object lifecycle policy, catalog, cache, derived datasets, and backups. Expiry in a manifest alone does not delete bytes.

Revocation/deletion flow:

1. Write a high-priority tombstone/control record and immediately deny new exports for its scope.
2. Locate raw and derived objects through source-event lineage.
3. Delete objects and catalog rows unless another lawful scope independently permits them; otherwise recompute derived datasets without the subject.
4. Verify deletion and record only non-content receipts/hashes.
5. Invalidate dataset releases and models whose removal semantics require retraining; the policy must name whether exact unlearning is promised.

Avoid long WORM Object Lock on personal raw data because an immutable retention period can conflict with erasure. WORM may be appropriate for nonpersonal signed manifests under a separately reviewed policy ([S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)).

## Encryption and access control

Recommended production envelope:

- Client-side AES-256-GCM with a fresh random data-encryption key and nonce discipline per bundle/object; NIST specifies GCM as authenticated encryption ([SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final)).
- Wrap each data key with a purpose/environment-scoped KMS/HSM key. Store only wrapped key material and key ID with the object. Separate consent domains can then be cryptographically erased without rotating every dataset.
- TLS 1.3 in transit; object-store service-side encryption as defense in depth. R2 documents server-side encryption and TLS ([R2 data security](https://developers.cloudflare.com/r2/reference/data-security/)).
- Least-privilege uploader can create content-addressed bundles and control records but cannot list/decrypt all research data. Analysts receive temporary, audited access to specific dataset snapshots.
- Encrypt or minimize metadata too: object names expose only pseudonymous run/date/priority, never owner name, place, transcript fragment, or task text.
- Rotate keys, test restore and cryptoshred, and keep keys outside robot/object storage. Losing a customer-provided key can make data unrecoverable ([R2 SSE-C example](https://developers.cloudflare.com/r2/examples/ssec/)).

The local prototype tests hashes but not encryption. A production pilot is blocked until authenticated encryption, KMS policy, restore, and deletion are exercised end to end.

## Byte governor and Starlink sync

Starlink advertises typical—not guaranteed—upload ranges and variable latency ([Starlink specifications](https://starlink.com/legal/documents/DOC-1470-99699-90)). Its Fair Use Policy describes priority-data buckets, standard-data fallback, network management, usage visibility, and optional extra data ([Starlink Fair Use Policy](https://starlink.com/legal/documents/DOC-1726-51199-77)). Plan/country/account details are configuration, not constants.

Initial conservative policy:

| Priority | Contents | Behavior |
|---:|---|---|
| 0 | consent revocation/tombstone, deletion receipt, tiny dataset-control manifest | reserved quota; retry first |
| 1 | human-labeled failures and compact run manifest | upload after control records |
| 2 | navigation/conversation/audio/perception summaries | upload within daily and monthly caps |
| 3 | explicitly consented raw windows | local/unmetered by default; requires remaining raw allowance |

- Start with 50 MiB/day for priority 0–2 and a 5 GB/month research-summary hard ceiling. Both are operator-configurable and fail closed when usage state is unknown.
- Reserve at least 1 MiB/day outside the normal cap for consent/tombstone control traffic.
- Use 256 KiB–4 MiB encrypted content-addressed chunks, depending on measured link overhead. Upload one object atomically or use multipart with checksums and a durable part ledger.
- Retry with bounded exponential backoff and jitter. Never hold an active robot control resource while uploading.
- Confirm remote checksum/ETag semantics before marking local data synced. Keep the local object until the manifest commit is acknowledged and retention permits deletion.
- Pause priority 2–3 during poor power, thermal, disk, metered-link, or safety state. Link headlines never override byte accounting.
- Raw capture is physically removable-storage first. Schedule raw sync on a trusted unmetered link or operator-approved window.

The benchmark projects about 0.363 GB/month for its synthetic summaries at 8 h/day, while its explicitly hypothetical raw audio/camera/lidar scenario is 762 GB/month. This is why summary-first is a structural rule, not a compression tweak. Physical sensor and Starlink measurements must replace the raw scenario before setting production limits.

## Cost model

As checked 2026-08-26, R2 Standard storage is listed at $0.015/GB-month, Class A operations at $4.50/million, Class B at $0.36/million, with a free tier and no R2 egress fee ([R2 pricing](https://developers.cloudflare.com/r2/pricing/)). The benchmark’s projection is:

- 0.363 GB/month summary ingress;
- 1.090 GB retained with a simple 90-day window;
- about $0.016/month for that storage at the cited rate;
- 15,840 bundle puts/month, about $0.071 gross Class A cost and $0 after the cited 1M-operation free tier;
- 762 GB/month in the raw scenario and about $11.43/month for one retained month of raw bytes, before compute, catalog, retrieval, network plan, tax, or labor.

These figures are sensitivity estimates, not a quote. Object count, query compute, privacy operations, support, and Starlink service can dominate summary storage cost. Recheck `source_manifest.json` before procurement.

## Falsifiable hypotheses

The prototype encodes these before reporting its result:

| ID | Hypothesis | Threshold |
|---|---|---|
| H1 | Typed pre-spool admission removes every seeded secret/PII/raw field | zero marker/key hits; three negative controls rejected |
| H2 | Bundles replay completely and deterministically and detect corruption | exact count/digest twice; no duplicate insertion; one-byte mutation detected |
| H3 | Summary bundles are compact and locally cheap to form | compressed size ≤30%; bundling ≥10 MB/s on this host |
| H4 | Summary sync is compatible with an initial narrow cap | ≤5 GB/month; all priority 0–2 bundles fit 50 MiB/day |
| H5 | Raw auto-sync is infeasible under a conservative priority bucket | named raw scenario >40 GB/month; summary <40 GB/month |
| H6 | Summary object storage is not the primary cost risk | 90-day summary storage < $1/month at cited R2 Standard rate |

See `RESULTS.md` and `results.json` for observations and limitations.

## Production gates

Before an off-robot pilot:

1. Implement the research spool/exporter in product code as a separate process and path, with byte/age caps, disk-reserve protection, drop/gap evidence, and no owner-DB access.
2. Specify per-stream data schemas more narrowly than the prototype’s generic `data` object; add property-based privacy and malformed-event tests.
3. Implement consent scope/revocation/tombstone cascade and demonstrate deletion across spool, objects, catalog, cache, and a derived dataset.
4. Implement AES-256-GCM envelope encryption with KMS, TLS, least privilege, key rotation, restore, and cryptoshred tests.
5. Exercise real resumable/multipart object upload under packet loss, interruption, duplicate retries, stale credentials, cap exhaustion, and checksum mismatch.
6. Measure physical MCAP rates, storage throughput, CPU/power/thermal cost, on-robot summary generation, and the actual Starlink plan over representative routes and weather.
7. Replay a physical bag through the pinned navigation/conversation/perception evaluator and reproduce dataset hashes and metrics from an empty workspace.
8. Run a privacy threat model and legal review for jurisdictions, research purpose, biometric/location/audio handling, subjects other than the owner, and retention.
9. Add dataset/model cards, signed promotion manifests, rollback, and independent safety/navigation/conversation regression gates.

Iceberg/catalog deployment can follow after the pilot demonstrates enough data/query concurrency to justify it. Raw automatic upload, direct feedback-to-model updates, and merging research with companion memory should remain explicitly prohibited.
