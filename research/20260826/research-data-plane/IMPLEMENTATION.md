# Research data-plane implementation addendum

Date: 2026-08-26
Code: `src/parcel_robot/research_plane/`
Focused tests: `tests/test_research_plane.py`
Default: **disabled**

## Relationship to the original experiment

`prototype.py`, `results.json`, `RESULTS.md`, and the original verdict preserve
the synthetic 14,532-event mechanism experiment. The product package added
after that experiment is a separate local P0 implementation. It carries the
design into strict interfaces, but it does not turn the original local probe
into evidence for cloud storage, Starlink, production encryption, privacy
compliance, or autonomous learning.

## Implemented locally

- `ResearchPlaneConfig(enabled=False)` returns a no-I/O implementation. An
  enabled plane requires an explicit research root; the package initializer is
  import-free.
- The v1 event boundary admits bounded typed navigation, conversation, audio,
  perception, and feedback summaries. Raw media, transcripts, exact locations,
  embeddings, credentials, unknown keys, and widened schemas are not accepted.
- Research identity is pseudonymous and scoped. Consented events require the
  consent subject to match the event robot pseudonym, and a consent destination
  must exactly match the immutable spool destination. Consent is accepted only
  through a process-local authenticated wrapper. Schema v7 persists the bounded
  detached proof plus its channel, authenticator identity, and immutable trusted
  verifier identity, and re-verifies that complete binding on every persisted
  authorization, duplicate, retention, transfer, and revocation read. Recomputing
  the public canonical-record digest cannot widen scope or expiry.
- The schema-v7 dedicated SQLite spool is distinct from owner memory, uses
  bounded/root-resolved paths, detects a foreign or wrong-version database,
  provides idempotent event admission, and creates deterministic
  content-addressed priority-isolated bundles with exact manifests and immutable
  event-replay/lineage checks. Bundle publication records an owner-scoped intent
  and bounded lease before staging/final publication; startup reconciliation
  rolls back expired intents without deleting another live owner's artifacts.
- Expiry or consent revocation removes affected local event rows, plaintext
  bundle/manifest files, and registered ciphertext files. If a mixed bundle
  contains still-retained events, those events are requeued for rebundling.
  Committed local-deletion journals bind managed direct-child paths to expected
  content identity/generation, refuse symlink or replacement deletion, retry
  without head-of-line starvation, and surface quarantined pending entries.
  The spool also records content-free pending remote-deletion obligations; it
  does not claim that a remote system was contacted or deleted.
- `EncryptedObjectV1` accepts only an AES-256-GCM-labelled envelope whose
  canonical AAD binds source bundle, priority, and destination. Construction
  has no permissive default: an injected provider must positively verify the
  authentication tag/AAD. The package does not implement AES or hold a key.
- The governor validates the current source bundle before attempt idempotence,
  keeps an immutable source-to-ciphertext mapping, prevents ciphertext reuse
  across sources, separates control and ordinary quotas, and charges every
  distinct transfer-attempt ID. Only an exact replay of the same attempt ID and
  metadata is already-accounted rather than charged again.
- A bundle becomes `synced` only after an injected receipt verifier accepts a
  typed receipt bound to the accounted attempt, source, ciphertext,
  destination, and remote checksum. No verifier means denial.
- An asynchronous local sink bounds its producer queue and moves storage and
  bundle work off the producer call. It has no network client and no control
  connection.

## Trust-provider boundary

Consent-proof, AEAD, and remote-receipt verification are process-local
dependency-injection seams for future trusted providers. There is no default
provider. Persisting a consent proof makes later re-verification possible, but
does not make the callback, its key custody, or its external authority durable;
the same trusted verifier identity and implementation must be supplied after a
restart. Test providers demonstrate fail-closed call ordering and exact context
binding; they do **not** demonstrate production consent-channel authentication,
AES correctness, key custody, KMS wrapping, TLS/IAM, object-store durability,
or remote identity. Those claims require named provider implementations and
their own end-to-end evidence.

Likewise, a local pending deletion obligation is an honest statement that a
remote deletion may be required. There is no remote deleter, catalog/cache
cascade, backup expiry witness, cryptoshred implementation, or deletion
receipt verifier in this tranche.

## Verification status

The focused suite covers default-off/no-I/O behavior, strict admission,
persistence/isolation/collision checks, consent scope, deterministic bundles,
corruption, byte accounting, canonical AAD, mandatory AEAD verification,
source revalidation, attempt charging, authenticated receipt binding,
consent recomputed-digest refusal, missing-verifier denial with safe revocation,
publication-intent recovery, quarantined deletion retry, revocation,
mixed-bundle requeue, expiry, producer identity, and asynchronous drain behavior.

Merged-tree final result: **RED**. The guarded non-slow run completed with
10,811 passed, 111 failed, 23 skipped, 83 deselected, and 5 xfailed in
549.20 seconds. Focused research-plane/P0 verification is green; the dominant
merged failures are legacy motion fixtures disarmed because they do not inject
the new required commissioned capability manifest, plus two commissioning
architecture ratchets that preserve the older seam rule.

## Pilot gate remains closed

Before any physical or off-robot pilot, supply and test all of the following as
one bounded, operator-consented protocol:

1. a real client-side AES-256-GCM implementation with fresh nonce/DEK handling,
   managed key wrapping, rotation, restore, and cryptoshred evidence;
2. an authenticated object-store transport with TLS/IAM, interrupted-upload
   accounting, provider checksum semantics, and signed receipt verification;
3. actual deletion from the object store, catalog/cache, a derived dataset,
   and the applicable backup lifecycle, followed by non-content receipts;
4. measured Orin CPU, disk, temperature, power, event-drop, sensor-rate, and
   network-byte effects with the control plane isolated; and
5. replay of the surviving snapshot from an empty workspace with exact lineage
   and evaluation reproduction.

Until those gates pass, the appropriate operating state is local-only,
summary-only, explicitly enabled for development, and disconnected from
robot control and model activation.
