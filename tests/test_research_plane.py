from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parcel_robot.research_plane.admission import admit_candidate
from parcel_robot.research_plane.bundle import build_bundle, replay_bundle
from parcel_robot.research_plane.contracts import (
    EVENT_TYPES,
    PRIORITY_BY_STREAM,
    canonical_json_bytes,
    sha256_hex,
)
from parcel_robot.research_plane.governor import (
    ByteGovernor,
    EncryptedObjectV1,
    RemoteReceiptV1,
    TrustedReceiptVerifierV1,
    mark_remote_receipt,
    transfer_aad_bytes,
)
from parcel_robot.research_plane.pipeline import (
    DisabledResearchPlane,
    ResearchPlane,
    ResearchPlaneConfig,
)
from parcel_robot.research_plane.producer import (
    ResearchEventFactoryV1,
    ResearchProducerIdentityV1,
    pseudonymous_robot_id,
)
from parcel_robot.research_plane.spool import (
    SPOOL_APPLICATION_ID,
    AuthenticatedConsentV1,
    ConsentRecordV1,
    ResearchSpool,
    SpoolDecision,
    TrustedConsentVerifierV1,
)
from parcel_robot.research_plane.worker import AsyncResearchSink

NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)
ZERO_SHA = "0" * 64
ONE_SHA = "1" * 64
CONSENT_KEY = b"test-only-persisted-consent-verifier-key"


def _consent_proof(
    payload: bytes,
    authenticator_id: str,
    channel: str,
) -> str:
    bound = b"\0".join(
        (payload, authenticator_id.encode("utf-8"), channel.encode("utf-8"))
    )
    return hmac.new(CONSENT_KEY, bound, hashlib.sha256).hexdigest()


CONSENT_VERIFIER = TrustedConsentVerifierV1(
    verifier_id="test-consent-verifier-v1",
    verifier=lambda payload, supplied, authenticator, channel: hmac.compare_digest(
        supplied,
        _consent_proof(payload, authenticator, channel),
    ),
)


def test_packaged_research_schema_matches_contract_streams_and_required_shape() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "parcel_robot"
        / "research_plane"
        / "schemas"
        / "research_event_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "parcel://schemas/research_event_v1"
    assert set(schema["properties"]["stream"]["enum"]) == set(EVENT_TYPES)
    assert set(schema["properties"]["type"]["enum"]) == set(EVENT_TYPES.values())
    assert set(schema["required"]) == set(schema["properties"])


def _candidate(
    sequence: int,
    *,
    stream: str = "navigation",
    priority: int | None = None,
    consent_id: str | None = None,
    privacy_class: str = "research_pseudonymous",
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    robot = "robot_0123456789abcdef"
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"parcel-test:{stream}:{sequence}")),
        "source": f"parcel://robot/{robot}",
        "type": EVENT_TYPES[stream],
        "time": (NOW + timedelta(seconds=sequence)).isoformat().replace("+00:00", "Z"),
        "dataschema": "parcel://schemas/research_event_v1",
        "run_id": "research-test-run",
        "stream": stream,
        "sequence": sequence,
        "robot_pseudonym": robot,
        "origin": {
            "device_clock": "sim",
            "source_time_ns": sequence * 1_000_000_000,
            "receive_monotonic_ns": sequence * 1_000_000_000 + 10,
        },
        "privacy_class": privacy_class,
        "purpose": "research_evaluation",
        "consent_id": consent_id,
        "retention_class": "feedback_1y" if stream == "feedback" else "summary_90d",
        "priority": PRIORITY_BY_STREAM[stream] if priority is None else priority,
        "provenance": {
            "source_event_ids": [f"sim://event/{sequence}"],
            "code_sha256": ZERO_SHA,
            "config_sha256": ONE_SHA,
            "model_ids": [],
            "calibration_ids": ["sim-v1"],
        },
        "data": data if data is not None else {"planner_state": "tracking"},
    }


def _store(spool: ResearchSpool, candidate: dict[str, object]) -> None:
    decision = admit_candidate(candidate)
    assert decision.accepted, decision.reason
    assert spool.admit(decision, now=NOW) == (SpoolDecision.STORED, "stored")


def _authenticated(record: ConsentRecordV1) -> AuthenticatedConsentV1:
    authenticator_id = "test-owner-authenticator-v1"
    proof = _consent_proof(record.canonical_bytes(), authenticator_id, record.authority)
    return AuthenticatedConsentV1.authenticate(
        record,
        channel=record.authority,
        authenticator_id=authenticator_id,
        proof=proof,
        verifier_provider=CONSENT_VERIFIER,
    )


def test_default_plane_is_disabled_and_performs_no_io(tmp_path: Path) -> None:
    requested_root = tmp_path / "must-not-exist"
    plane = ResearchPlane.from_config(ResearchPlaneConfig(root=requested_root))
    assert isinstance(plane, DisabledResearchPlane)
    assert plane.emit(_candidate(0)) == (
        SpoolDecision.REJECTED,
        "research_plane_disabled",
    )
    assert plane.bundle_next() is None
    assert plane.maintenance() == {
        "purged_events": 0,
        "recovered_claims": 0,
        "local_deletions": 0,
        "orphans": 0,
    }
    assert not requested_root.exists()
    with pytest.raises(TypeError, match="exact boolean"):
        ResearchPlaneConfig(enabled=1)  # type: ignore[arg-type]


def test_enabled_startup_and_periodic_maintenance_enforce_retention(tmp_path: Path) -> None:
    root = tmp_path / "research"
    with ResearchSpool(root=root) as spool:
        _store(spool, _candidate(0))
        spool.connection_for_governor.execute(
            "UPDATE events SET expires_at = '2000-01-01T00:00:00Z'"
        )
        spool.connection_for_governor.commit()
    plane = ResearchPlane.from_config(ResearchPlaneConfig(enabled=True, root=root))
    assert isinstance(plane, ResearchPlane)
    try:
        assert plane.snapshot()["spool"]["event_states"] == {}
        _store(plane.spool, _candidate(1))
        result = plane.maintenance(now=NOW + timedelta(days=91))
        assert result["purged_events"] == 1
        assert plane.snapshot()["spool"]["event_states"] == {}
    finally:
        plane.close()


def test_admission_redacts_only_explicit_note_and_rejects_contract_widening() -> None:
    note = _candidate(
        0,
        stream="conversation",
        priority=1,
        privacy_class="consent_required",
        consent_id="consent-note",
        data={
            "outcome_code": "clarified",
            "redacted_note": "email me at owner@example.com or +1 (212) 555-0199",
        },
    )
    note["retention_class"] = "consented_text_30d"
    accepted = admit_candidate(note)
    assert accepted.accepted
    assert accepted.event is not None
    assert accepted.event.data["redacted_note"] == (
        "email me at [REDACTED_EMAIL] or [REDACTED_PHONE]"
    )
    assert accepted.redactions == ("email", "phone")

    unknown = _candidate(1, data={"planner_state": "tracking", "owner_hint": "private"})
    assert admit_candidate(unknown).reason == "unknown_data_fields:owner_hint"
    raw = _candidate(2, data={"planner_state": "tracking", "raw_audio": "RIFF"})
    assert admit_candidate(raw).reason == "forbidden_fields:raw_audio"
    smuggled = _candidate(3, data={"planner_state": "owner@example.com"})
    assert "planner_state is not an allowed value" in admit_candidate(smuggled).reason
    companion = _candidate(3)
    companion["privacy_class"] = "companion_only"
    assert admit_candidate(companion).reason == "companion_only"


def test_admitted_event_freezes_its_hashed_payload_against_caller_mutation() -> None:
    data: dict[str, object] = {"planner_state": "tracking"}
    accepted = admit_candidate(_candidate(0, data=data))
    assert accepted.event is not None
    before_bytes = accepted.event.canonical_bytes()
    before_digest = accepted.event.sha256

    data["planner_state"] = "tampered"
    exposed = accepted.event.as_dict()
    exposed["data"]["planner_state"] = "also-tampered"

    assert accepted.event.canonical_bytes() == before_bytes
    assert accepted.event.sha256 == before_digest
    assert accepted.event.as_dict()["data"] == {"planner_state": "tracking"}


def test_spool_is_separate_bounded_idempotent_and_collision_detecting(tmp_path: Path) -> None:
    root = tmp_path / "research"
    with pytest.raises(ValueError, match="owner memory"):
        ResearchSpool(root=root, owner_memory_paths=[root / "owner.sqlite3"])

    with ResearchSpool(root=root, max_payload_bytes=2048) as spool:
        first = admit_candidate(_candidate(0))
        assert spool.admit(first, now=NOW) == (SpoolDecision.STORED, "stored")
        assert spool.admit(first, now=NOW) == (
            SpoolDecision.DUPLICATE,
            "duplicate_event_id",
        )
        collision = _candidate(0, data={"planner_state": "paused"})
        with pytest.raises(ValueError, match="event_id collision"):
            spool.admit(admit_candidate(collision), now=NOW)

        result = None
        for sequence in range(1, 20):
            result = spool.admit(admit_candidate(_candidate(sequence)), now=NOW)
            if result[1] == "spool_payload_cap":
                break
        assert result == (SpoolDecision.REJECTED, "spool_payload_cap")
        snapshot = spool.snapshot()
        assert snapshot["payload_bytes"] <= snapshot["max_payload_bytes"]
        assert root / "research_spool.sqlite3" == spool.database_path


def test_spool_refuses_an_existing_foreign_sqlite_database(tmp_path: Path) -> None:
    root = tmp_path / "foreign"
    root.mkdir()
    path = root / "research_spool.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE owner_facts(secret TEXT)")
    connection.execute("INSERT INTO owner_facts VALUES ('must-not-touch')")
    connection.commit()
    connection.close()
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="not a Parcel research spool"):
        ResearchSpool(root=root)
    assert path.read_bytes() == before


def test_spool_refuses_destination_rebinding(tmp_path: Path) -> None:
    root = tmp_path / "destination"
    ResearchSpool(root=root, destination="study-a").close()
    with pytest.raises(RuntimeError, match="destination is immutable"):
        ResearchSpool(root=root, destination="study-b")


def test_spool_refuses_genuine_v6_database_after_schema_bump(tmp_path: Path) -> None:
    root = tmp_path / "v6"
    root.mkdir()
    path = root / "research_spool.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA application_id={SPOOL_APPLICATION_ID}")
    connection.execute("PRAGMA user_version=6")
    connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO metadata VALUES('schema_version', '6')")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="not a Parcel research spool"):
        ResearchSpool(root=root)


def test_spool_refuses_schema_shape_tampering(tmp_path: Path) -> None:
    root = tmp_path / "shape"
    spool = ResearchSpool(root=root)
    path = spool.database_path
    spool.close()
    connection = sqlite3.connect(path)
    connection.execute("ALTER TABLE bundles ADD COLUMN unexpected TEXT")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="table shape mismatch"):
        ResearchSpool(root=root)


def test_consent_is_immutable_scoped_and_revocation_invalidates_bundle(tmp_path: Path) -> None:
    consent = ConsentRecordV1(
        consent_id="consent-1",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        candidate = _candidate(
            0,
            stream="conversation",
            priority=1,
            consent_id=consent.consent_id,
            privacy_class="consent_required",
            data={"outcome_code": "completed"},
        )
        admitted = admit_candidate(candidate)
        assert spool.admit(admitted, now=NOW) == (
            SpoolDecision.REJECTED,
            "unknown_consent",
        )
        authenticated = _authenticated(consent)
        assert spool.record_consent(authenticated)
        assert not spool.record_consent(authenticated)
        assert spool.admit(admitted, now=NOW) == (SpoolDecision.STORED, "stored")
        artifact = build_bundle(spool, now=NOW)
        assert artifact is not None
        assert spool.bundle_uploadable(artifact.bundle_sha256)

        revoked = spool.revoke_consent(
            consent.consent_id,
            reason_code="owner_revoked",
            revoked_at=NOW + timedelta(minutes=1),
        )
        assert revoked["affected_events"] == 1
        assert revoked["invalidated_bundles"] == 1
        assert not spool.bundle_uploadable(artifact.bundle_sha256)
        assert not artifact.bundle_path.exists()
        assert not artifact.manifest_path.exists()
        snapshot = spool.snapshot()
        assert snapshot["invalidated_bundles"] == 0


def test_persisted_consent_mutation_cannot_widen_scope_or_retention(tmp_path: Path) -> None:
    consent = ConsentRecordV1(
        consent_id="consent-db-binding",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        spool.record_consent(_authenticated(consent))
        _store(
            spool,
            _candidate(
                0,
                stream="conversation",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"outcome_code": "completed"},
            ),
        )
        artifact = build_bundle(spool, now=NOW)
        assert artifact is not None
        widened_expiry = NOW + timedelta(days=300)
        widened_record = ConsentRecordV1(
            consent_id=consent.consent_id,
            subject_pseudonym=consent.subject_pseudonym,
            streams=("conversation", "audio"),
            destination=consent.destination,
            granted_at=consent.granted_at,
            expires_at=widened_expiry.isoformat(),
            authority=consent.authority,
        )
        spool.connection_for_governor.execute(
            """UPDATE consents SET streams_json = ?, expires_at = ?, record_sha256 = ?
               WHERE consent_id = ?""",
            (
                canonical_json_bytes(["conversation", "audio"]),
                widened_expiry.isoformat(),
                sha256_hex(widened_record.canonical_bytes()),
                consent.consent_id,
            ),
        )
        spool.connection_for_governor.commit()

        with pytest.raises(ValueError, match="authentication binding"):
            spool.record_consent(_authenticated(consent))

        widened = admit_candidate(
            _candidate(
                1,
                stream="audio",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"snr_db": 12.0},
            )
        )
        assert spool.admit(widened, now=NOW) == (
            SpoolDecision.REJECTED,
            "consent_record_binding_invalid",
        )
        with pytest.raises(ValueError, match="source_retention_or_consent_invalid"):
            spool.validate_bundle_for_transfer(artifact.bundle_sha256, now=NOW)
        revoked = spool.revoke_consent(
            consent.consent_id,
            reason_code="corrupt_consent_revoked",
            revoked_at=NOW,
        )
        assert revoked["deleted_events"] == 1
        assert spool.snapshot()["event_states"] == {}


def test_missing_persisted_consent_verifier_fails_closed_but_revocation_proceeds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research"
    consent = ConsentRecordV1(
        consent_id="consent-missing-read-verifier",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(root=root, consent_verifier=CONSENT_VERIFIER) as spool:
        spool.record_consent(_authenticated(consent))
        _store(
            spool,
            _candidate(
                0,
                stream="conversation",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"outcome_code": "completed"},
            ),
        )

    with ResearchSpool(root=root) as spool:
        rejected = admit_candidate(
            _candidate(
                1,
                stream="conversation",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"outcome_code": "completed"},
            )
        )
        assert spool.admit(rejected, now=NOW) == (
            SpoolDecision.REJECTED,
            "consent_record_binding_invalid",
        )
        revoked = spool.revoke_consent(
            consent.consent_id,
            reason_code="owner_revoked_without_verifier",
            revoked_at=NOW,
        )
        assert revoked["deleted_events"] == 1
        assert spool.snapshot()["event_states"] == {}


def test_bundles_are_deterministic_priority_isolated_and_corruption_detected(
    tmp_path: Path,
) -> None:
    artifacts = []
    for index in range(2):
        with ResearchSpool(root=tmp_path / f"run-{index}") as spool:
            _store(
                spool,
                _candidate(
                    0,
                    stream="conversation",
                    priority=1,
                    data={"outcome_code": "completed"},
                ),
            )
            _store(spool, _candidate(1, priority=2))
            first = build_bundle(spool)
            second = build_bundle(spool)
            assert first is not None and second is not None
            assert first.priority == 1
            assert second.priority == 2
            assert [event.sequence for event in replay_bundle(first)] == [0]
            assert [event.sequence for event in replay_bundle(second)] == [1]
            artifacts.append((first.bundle_sha256, first.manifest_sha256))
    assert artifacts[0] == artifacts[1]

    assert admit_candidate(_candidate(9, priority=0)).reason == "reserved_control_priority"
    assert "priority does not match stream" in admit_candidate(
        _candidate(
            10,
            stream="conversation",
            priority=2,
            data={"outcome_code": "completed"},
        )
    ).reason
    assert admit_candidate(
        _candidate(
            11,
            stream="feedback",
            priority=0,
            data={"label": "success", "task": "navigate"},
        )
    ).reason == "reserved_control_priority"

    with ResearchSpool(root=tmp_path / "corrupt") as spool:
        _store(spool, _candidate(4))
        artifact = build_bundle(spool)
        assert artifact is not None
        payload = bytearray(artifact.bundle_path.read_bytes())
        payload[len(payload) // 2] ^= 1
        artifact.bundle_path.write_bytes(payload)
        with pytest.raises(ValueError, match="bundle checksum mismatch"):
            replay_bundle(artifact)


def test_startup_rolls_back_publication_intent_and_removes_plaintext_orphans(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research"
    with ResearchSpool(root=root) as spool:
        _store(spool, _candidate(0))
        claim = spool.claim_queued(now=NOW)
        assert claim is not None
        final_bundle = spool.bundle_root / f"p2-{ZERO_SHA}.jsonl.gz"
        final_manifest = spool.bundle_root / f"{ZERO_SHA}.manifest.json"
        stage_bundle = spool.bundle_root / f".stage-{claim.claim_token}.bundle"
        stage_manifest = spool.bundle_root / f".stage-{claim.claim_token}.manifest"
        spool.record_bundle_publication_intent(
            claim_token=claim.claim_token,
            bundle_sha256=ZERO_SHA,
            bundle_path=final_bundle,
            manifest_path=final_manifest,
            bundle_stage_path=stage_bundle,
            manifest_stage_path=stage_manifest,
            now=NOW - timedelta(days=1),
        )
        for path in (final_bundle, final_manifest, stage_bundle, stage_manifest):
            path.write_bytes(b"orphaned research plaintext")
    with ResearchSpool(root=root) as reopened:
        assert reopened.snapshot()["event_states"] == {"queued": 1}
        assert not any(
            path.exists()
            for path in (final_bundle, final_manifest, stage_bundle, stage_manifest)
        )


def test_reconciliation_preserves_live_foreign_publication_until_lease_expiry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research"
    lease_start = datetime.now(timezone.utc)
    with ResearchSpool(root=root) as builder:
        _store(builder, _candidate(0))
        claim = builder.claim_queued(now=lease_start)
        assert claim is not None
        paths = (
            builder.bundle_root / f"p2-{ZERO_SHA}.jsonl.gz",
            builder.bundle_root / f"{ZERO_SHA}.manifest.json",
            builder.bundle_root / f".stage-{claim.claim_token}.bundle",
            builder.bundle_root / f".stage-{claim.claim_token}.manifest",
        )
        builder.record_bundle_publication_intent(
            claim_token=claim.claim_token,
            bundle_sha256=ZERO_SHA,
            bundle_path=paths[0],
            manifest_path=paths[1],
            bundle_stage_path=paths[2],
            manifest_stage_path=paths[3],
            now=lease_start,
        )
        for path in paths:
            path.write_bytes(b"live publication")

        with ResearchSpool(root=root) as maintenance:
            assert all(path.exists() for path in paths)
            assert builder.snapshot()["event_states"] == {"claimed": 1}
            assert maintenance.reconcile_bundle_artifacts(now=lease_start) == 0
            assert all(path.exists() for path in paths)
            assert maintenance.reconcile_bundle_artifacts(
                now=lease_start + timedelta(minutes=16)
            ) == 4
            assert maintenance.snapshot()["event_states"] == {"queued": 1}
            assert not any(path.exists() for path in paths)


def test_persisted_manifest_is_exact_and_reconstructed_from_event_replay(
    tmp_path: Path,
) -> None:
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        persisted = spool.connection_for_governor.execute(
            """SELECT manifest_file_sha256, manifest_content_sha256,
                      event_id_digest, lineage_sha256, first_event_id, last_event_id
               FROM bundles WHERE bundle_sha256 = ?""",
            (artifact.bundle_sha256,),
        ).fetchone()
        assert persisted == (
            artifact.manifest_file_sha256,
            artifact.manifest_sha256,
            artifact.event_id_digest,
            artifact.lineage_sha256,
            replay_bundle(artifact)[0].event_id,
            replay_bundle(artifact)[-1].event_id,
        )
        assert spool.validate_bundle_for_transfer(artifact.bundle_sha256)

        manifest = json.loads(artifact.manifest_path.read_bytes())
        manifest.pop("manifest_sha256_without_self")
        manifest["run_ids"] = ["substituted-run"]
        content_sha = sha256_hex(canonical_json_bytes(manifest))
        tampered = canonical_json_bytes(
            {**manifest, "manifest_sha256_without_self": content_sha}
        ) + b"\n"
        artifact.manifest_path.write_bytes(tampered)
        spool.connection_for_governor.execute(
            """UPDATE bundles
               SET manifest_file_sha256 = ?, manifest_content_sha256 = ?
               WHERE bundle_sha256 = ?""",
            (sha256_hex(tampered), content_sha, artifact.bundle_sha256),
        )
        spool.connection_for_governor.commit()
        with pytest.raises(ValueError, match="run IDs|exact replay-derived"):
            spool.validate_bundle_for_transfer(artifact.bundle_sha256)


def _ciphertext(
    spool: ResearchSpool,
    artifact_sha: str,
    *,
    priority: int,
    marker: bytes,
) -> EncryptedObjectV1:
    path = spool.encrypted_root / f"{artifact_sha[:8]}-{marker.hex()}.enc"
    # Accounting tests exercise the ciphertext contract and caps. The product
    # module intentionally contains no test/local key pretending to be KMS.
    path.write_bytes(marker * 32 + b"0" * 16)
    return EncryptedObjectV1.from_file(
        source_bundle_sha256=artifact_sha,
        ciphertext_path=path,
        priority=priority,
        destination=spool.destination,
        nonce_hex="ab" * 12,
        wrapped_key_id="kms:test-key:v1",
        aad_sha256=sha256_hex(
            transfer_aad_bytes(artifact_sha, priority, spool.destination)
        ),
        # Accounting is isolated from cryptography. Production must pass an
        # AES-GCM/KMS provider that verifies the authentication tag and AAD;
        # this test witness asserts only that the governor calls that seam.
        aead_verifier=lambda path, nonce, key, aad, algorithm: bool(
            path.is_file() and nonce and key and aad and algorithm == "AES-256-GCM"
        ),
    )


def _receipt_provider(
    verifier: object | None = None,
) -> TrustedReceiptVerifierV1:
    callback = verifier if callable(verifier) else lambda payload, signature: bool(
        payload and signature
    )
    return TrustedReceiptVerifierV1("receipt-key-v1", callback)


def test_governor_is_persistent_idempotent_separates_control_and_fails_closed(
    tmp_path: Path,
) -> None:
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        _store(spool, _candidate(0, priority=2))
        _store(spool, _candidate(1, priority=2))
        first = build_bundle(spool, target_uncompressed_bytes=1)
        second = build_bundle(spool, target_uncompressed_bytes=1)
        assert first is not None and second is not None
        encrypted_one = _ciphertext(spool, first.bundle_sha256, priority=2, marker=b"a")
        encrypted_two = _ciphertext(spool, second.bundle_sha256, priority=2, marker=b"b")
        governor = ByteGovernor(
            spool,
            daily_ordinary_bytes=encrypted_one.byte_count,
            monthly_ordinary_bytes=encrypted_one.byte_count,
            daily_control_bytes=1024,
            monthly_control_bytes=1024,
        )
        charged = governor.charge(encrypted_one, transfer_attempt_id="attempt-1", now=NOW)
        assert charged.allowed and charged.reason == "charged"
        duplicate = governor.charge(encrypted_one, transfer_attempt_id="attempt-1", now=NOW)
        assert duplicate.allowed and duplicate.already_accounted
        denied = governor.charge(encrypted_two, transfer_attempt_id="attempt-2", now=NOW)
        assert not denied.allowed and denied.reason == "daily_cap"

        spool.connection_for_governor.execute("DROP TABLE transfer_attempts")
        spool.connection_for_governor.commit()
        unavailable = governor.charge(
            encrypted_two, transfer_attempt_id="attempt-3", now=NOW
        )
        assert not unavailable.allowed
        assert unavailable.reason == "accounting_unavailable"


def test_byte_cap_constructors_reject_float_coercion(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ResearchSpool(root=tmp_path / "bad-spool", max_payload_bytes=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive integers"):
        ResearchPlaneConfig(daily_summary_bytes=1.5)  # type: ignore[arg-type]
    with (
        ResearchSpool(root=tmp_path / "research") as spool,
        pytest.raises(ValueError, match="positive integers"),
    ):
        ByteGovernor(spool, daily_ordinary_bytes=1.5)  # type: ignore[arg-type]


def test_plaintext_bundle_cannot_be_presented_as_ciphertext(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        with pytest.raises(ValueError, match="byte-identical"):
            EncryptedObjectV1.from_file(
                source_bundle_sha256=artifact.bundle_sha256,
                ciphertext_path=artifact.bundle_path,
                priority=artifact.priority,
                destination=spool.destination,
                nonce_hex="ab" * 12,
                wrapped_key_id="kms:test-key:v1",
                aad_sha256=sha256_hex(
                    transfer_aad_bytes(
                        artifact.bundle_sha256, artifact.priority, spool.destination
                    )
                ),
                aead_verifier=lambda *_args: True,
            )


def test_ciphertext_requires_positive_aead_provider_verification(tmp_path: Path) -> None:
    path = tmp_path / "unverified.enc"
    path.write_bytes(b"ciphertext" + b"0" * 16)

    with pytest.raises(ValueError, match="did not verify"):
        EncryptedObjectV1.from_file(
            source_bundle_sha256=ZERO_SHA,
            ciphertext_path=path,
            priority=2,
            destination="research-local",
            nonce_hex="ab" * 12,
            wrapped_key_id="kms:test-key:v1",
            aad_sha256=sha256_hex(transfer_aad_bytes(ZERO_SHA, 2, "research-local")),
            aead_verifier=lambda *_args: False,
        )


def test_aead_has_no_default_and_aad_is_exactly_context_bound(tmp_path: Path) -> None:
    path = tmp_path / "cipher.enc"
    path.write_bytes(b"ciphertext" + b"0" * 16)
    correct = sha256_hex(transfer_aad_bytes(ZERO_SHA, 2, "research-local"))
    with pytest.raises(ValueError, match="trusted AEAD verifier"):
        EncryptedObjectV1.from_file(
            source_bundle_sha256=ZERO_SHA,
            ciphertext_path=path,
            priority=2,
            destination="research-local",
            nonce_hex="ab" * 12,
            wrapped_key_id="kms:key:v1",
            aad_sha256=correct,
        )
    with pytest.raises(ValueError, match="AAD digest"):
        EncryptedObjectV1.from_file(
            source_bundle_sha256=ZERO_SHA,
            ciphertext_path=path,
            priority=2,
            destination="different-destination",
            nonce_hex="ab" * 12,
            wrapped_key_id="kms:key:v1",
            aad_sha256=correct,
            aead_verifier=lambda *_args: True,
        )


def test_source_is_revalidated_before_exact_attempt_idempotence(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"v")
        governor = ByteGovernor(spool)
        assert governor.charge(
            encrypted, transfer_attempt_id="attempt-revalidate", now=NOW
        ).allowed
        artifact.bundle_path.write_bytes(artifact.bundle_path.read_bytes() + b"tamper")
        retried = governor.charge(
            encrypted, transfer_attempt_id="attempt-revalidate", now=NOW
        )
        assert not retried.allowed
        assert retried.reason == "bundle checksum or byte count mismatch"


def test_ciphertext_mapping_is_immutable_and_cross_source_unique(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        _store(spool, _candidate(1))
        first = build_bundle(spool, target_uncompressed_bytes=1)
        second = build_bundle(spool, target_uncompressed_bytes=1)
        assert first is not None and second is not None
        encrypted_one = _ciphertext(spool, first.bundle_sha256, priority=2, marker=b"s")
        governor = ByteGovernor(spool)
        assert governor.charge(
            encrypted_one, transfer_attempt_id="mapping-1", now=NOW
        ).allowed

        alternate = _ciphertext(spool, first.bundle_sha256, priority=2, marker=b"t")
        collision = governor.charge(alternate, transfer_attempt_id="mapping-2", now=NOW)
        assert not collision.allowed
        assert collision.reason == "source_ciphertext_metadata_collision"

        reused = _ciphertext(spool, second.bundle_sha256, priority=2, marker=b"s")
        reuse = governor.charge(reused, transfer_attempt_id="mapping-3", now=NOW)
        assert not reuse.allowed
        assert reuse.reason == "cross_source_ciphertext_reuse"

        unique_second = _ciphertext(spool, second.bundle_sha256, priority=2, marker=b"w")
        attempt_collision = governor.charge(
            unique_second, transfer_attempt_id="mapping-1", now=NOW
        )
        assert not attempt_collision.allowed
        assert attempt_collision.reason == "transfer_attempt_id_collision"


def test_each_distinct_wire_attempt_is_charged_but_exact_retry_is_not(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"r")
        governor = ByteGovernor(
            spool,
            daily_ordinary_bytes=encrypted.byte_count * 2,
            monthly_ordinary_bytes=encrypted.byte_count * 2,
        )
        first = governor.charge(encrypted, transfer_attempt_id="retry-1", now=NOW)
        exact = governor.charge(encrypted, transfer_attempt_id="retry-1", now=NOW)
        second = governor.charge(encrypted, transfer_attempt_id="retry-2", now=NOW)
        third = governor.charge(encrypted, transfer_attempt_id="retry-3", now=NOW)
        assert first.charged_bytes == encrypted.byte_count
        assert exact.already_accounted and exact.charged_bytes == 0
        assert second.charged_bytes == encrypted.byte_count
        assert not third.allowed and third.reason == "daily_cap"


def test_remote_sync_requires_strict_bound_and_authentic_receipt(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"u")
        governor = ByteGovernor(spool)
        assert governor.charge(
            encrypted, transfer_attempt_id="receipt-attempt", now=NOW
        ).allowed
        receipt = RemoteReceiptV1(
            receipt_id="receipt-1",
            transfer_attempt_id="receipt-attempt",
            source_bundle_sha256=artifact.bundle_sha256,
            ciphertext_sha256=encrypted.ciphertext_sha256,
            destination=spool.destination,
            remote_checksum_sha256=encrypted.ciphertext_sha256,
            received_at=NOW.isoformat(),
            provider_receipt_id="provider-receipt-1",
            signature="trusted-signature-0001",
        )
        with pytest.raises(TypeError, match="trusted remote receipt verifier"):
            mark_remote_receipt(spool, receipt)
        with pytest.raises(ValueError, match="authenticity"):
            mark_remote_receipt(
                spool,
                receipt,
                verifier_provider=_receipt_provider(lambda *_args: False),
                now=NOW,
            )
        provider = _receipt_provider()
        with pytest.raises(FrozenInstanceError):
            provider.verifier_id = "substituted-key"  # type: ignore[misc]
        wrong_destination = RemoteReceiptV1(
            receipt_id="receipt-wrong-destination",
            transfer_attempt_id="receipt-attempt",
            source_bundle_sha256=artifact.bundle_sha256,
            ciphertext_sha256=encrypted.ciphertext_sha256,
            destination="other-study",
            remote_checksum_sha256=encrypted.ciphertext_sha256,
            received_at=NOW.isoformat(),
            provider_receipt_id="provider-receipt-2",
            signature="trusted-signature-0002",
        )
        with pytest.raises(ValueError, match="registered encrypted object"):
            mark_remote_receipt(
                spool,
                wrong_destination,
                verifier_provider=provider,
                now=NOW,
            )
        assert mark_remote_receipt(
            spool,
            receipt,
            verifier_provider=provider,
            now=NOW,
        )
        assert not mark_remote_receipt(
            spool,
            receipt,
            verifier_provider=provider,
            now=NOW,
        )
        audit = spool.connection_for_governor.execute(
            "SELECT signature, receipt_verifier_id FROM remote_receipts"
        ).fetchone()
        assert audit == (receipt.signature, "receipt-key-v1")
        assert spool.purge_expired(now=NOW + timedelta(days=91)) == 1
        obligation = spool.connection_for_governor.execute(
            """SELECT remote_provider_receipt_id, receipt_verifier_id,
                      receipt_proof_sha256, receipt_record_sha256
               FROM deletion_obligations"""
        ).fetchone()
        assert obligation[:2] == (receipt.provider_receipt_id, provider.verifier_id)
        assert obligation[2] == sha256_hex(receipt.signature.encode("utf-8"))
        assert obligation[3] is not None


def test_receipt_revalidates_source_after_provider_verification(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"z")
        assert ByteGovernor(spool).charge(
            encrypted,
            transfer_attempt_id="receipt-race-attempt",
            now=NOW,
        ).allowed
        receipt = RemoteReceiptV1(
            receipt_id="receipt-race",
            transfer_attempt_id="receipt-race-attempt",
            source_bundle_sha256=artifact.bundle_sha256,
            ciphertext_sha256=encrypted.ciphertext_sha256,
            destination=spool.destination,
            remote_checksum_sha256=encrypted.ciphertext_sha256,
            received_at=NOW.isoformat(),
            provider_receipt_id="provider-race-receipt",
            signature="trusted-signature-race",
        )

        def invalidate_after_verification(_payload: bytes, _signature: str) -> bool:
            spool.connection_for_governor.execute(
                "UPDATE bundles SET invalidated = 1 WHERE bundle_sha256 = ?",
                (artifact.bundle_sha256,),
            )
            spool.connection_for_governor.commit()
            return True

        with pytest.raises(ValueError, match="source_not_uploadable"):
            mark_remote_receipt(
                spool,
                receipt,
                verifier_provider=_receipt_provider(invalidate_after_verification),
                now=NOW,
            )
        assert spool.connection_for_governor.execute(
            "SELECT COUNT(*) FROM remote_receipts"
        ).fetchone() == (0,)


def test_receipt_chronology_is_bound_to_attempt_and_future_skew(tmp_path: Path) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"c")
        assert ByteGovernor(spool).charge(
            encrypted,
            transfer_attempt_id="chronology-attempt",
            now=NOW,
        ).allowed
        common = {
            "transfer_attempt_id": "chronology-attempt",
            "source_bundle_sha256": artifact.bundle_sha256,
            "ciphertext_sha256": encrypted.ciphertext_sha256,
            "destination": spool.destination,
            "remote_checksum_sha256": encrypted.ciphertext_sha256,
            "provider_receipt_id": "provider-chronology-receipt",
            "signature": "trusted-signature-chronology",
        }
        predating = RemoteReceiptV1(
            receipt_id="receipt-predating",
            received_at=(NOW - timedelta(microseconds=1)).isoformat(),
            **common,
        )
        with pytest.raises(ValueError, match="predates"):
            mark_remote_receipt(
                spool,
                predating,
                verifier_provider=_receipt_provider(),
                now=NOW,
            )
        future = RemoteReceiptV1(
            receipt_id="receipt-future",
            received_at=(NOW + timedelta(minutes=5, microseconds=1)).isoformat(),
            **common,
        )
        with pytest.raises(ValueError, match="future clock skew"):
            mark_remote_receipt(
                spool,
                future,
                verifier_provider=_receipt_provider(),
                now=NOW,
            )
        boundary = RemoteReceiptV1(
            receipt_id="receipt-future-boundary",
            received_at=(NOW + timedelta(minutes=5)).isoformat(),
            **common,
        )
        assert mark_remote_receipt(
            spool,
            boundary,
            verifier_provider=_receipt_provider(),
            now=NOW,
        )


def test_consent_binds_spool_destination_and_event_robot(tmp_path: Path) -> None:
    wrong_destination = ConsentRecordV1(
        consent_id="consent-wrong-destination",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="other-study",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    wrong_subject = ConsentRecordV1(
        consent_id="consent-wrong-subject",
        subject_pseudonym="robot_ffffffffffffffff",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        with pytest.raises(ValueError, match="destination"):
            spool.record_consent(_authenticated(wrong_destination))
        assert spool.record_consent(_authenticated(wrong_subject))
        candidate = _candidate(
            0,
            stream="conversation",
            privacy_class="consent_required",
            consent_id=wrong_subject.consent_id,
            data={"outcome_code": "completed"},
        )
        assert spool.admit(admit_candidate(candidate), now=NOW) == (
            SpoolDecision.REJECTED,
            "consent_subject_mismatch",
        )


def test_consent_authority_requires_authenticated_full_record(tmp_path: Path) -> None:
    record = ConsentRecordV1(
        consent_id="consent-auth-boundary",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(root=tmp_path / "research") as spool:
        with pytest.raises(TypeError, match="authenticated consent wrapper"):
            spool.record_consent(record)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="authenticated consent wrapper"):
            spool.record_consent({"record": record})  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="typed ConsentRecordV1"):
            AuthenticatedConsentV1(  # type: ignore[arg-type]
                {"consent_id": record.consent_id},
                "owner_ui",
                "test-owner-authenticator-v1",
                sha256_hex(record.canonical_bytes()),
            )
        direct = AuthenticatedConsentV1(
            record,
            "owner_ui",
            "test-owner-authenticator-v1",
            sha256_hex(record.canonical_bytes()),
        )
        with pytest.raises(TypeError, match="authenticated consent wrapper"):
            spool.record_consent(direct)
        with pytest.raises(ValueError, match="channel does not match"):
            AuthenticatedConsentV1.authenticate(
                record,
                channel="operator_protocol",
                authenticator_id="test-owner-authenticator-v1",
                proof=sha256_hex(record.canonical_bytes()),
                verifier_provider=CONSENT_VERIFIER,
            )
        tampered = ConsentRecordV1(
            consent_id=record.consent_id,
            subject_pseudonym=record.subject_pseudonym,
            streams=record.streams,
            destination=record.destination,
            granted_at=record.granted_at,
            expires_at=(NOW + timedelta(days=2)).isoformat(),
            authority=record.authority,
        )
        with pytest.raises(ValueError, match="authentication failed"):
            AuthenticatedConsentV1.authenticate(
                tampered,
                channel="owner_ui",
                authenticator_id="test-owner-authenticator-v1",
                proof=sha256_hex(record.canonical_bytes()),
                verifier_provider=CONSENT_VERIFIER,
            )
        with (
            pytest.raises(TypeError, match="trusted persisted consent verifier"),
            ResearchSpool(root=tmp_path / "missing-verifier") as unverified_spool,
        ):
            unverified_spool.record_consent(_authenticated(record))


def test_consent_lifetime_is_bounded_to_exactly_365_days() -> None:
    common = {
        "subject_pseudonym": "robot_0123456789abcdef",
        "streams": ("conversation",),
        "destination": "research-local",
        "granted_at": NOW.isoformat(),
        "authority": "owner_ui",
    }
    accepted = ConsentRecordV1(
        consent_id="consent-365-days",
        expires_at=(NOW + timedelta(days=365)).isoformat(),
        **common,
    )
    assert accepted.expires_at == "2027-08-26T18:00:00Z"
    with pytest.raises(ValueError, match="must not exceed 365 days"):
        ConsentRecordV1(
            consent_id="consent-too-long",
            expires_at=(NOW + timedelta(days=365, seconds=1)).isoformat(),
            **common,
        )


def test_consent_normalizes_time_and_rejects_mutable_or_substituted_scope(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        ConsentRecordV1(
            consent_id="mutable-streams",
            subject_pseudonym="robot_0123456789abcdef",
            streams=["conversation"],  # type: ignore[arg-type]
            destination="research-local",
            granted_at="2026-08-26T14:00:00-04:00",
            expires_at="2026-08-27T14:00:00-04:00",
            authority="owner_ui",
        )
    record = ConsentRecordV1(
        consent_id="canonical-time",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at="2026-08-26T14:00:00-04:00",
        expires_at="2026-08-27T14:00:00-04:00",
        authority="owner_ui",
    )
    assert record.granted_at == "2026-08-26T18:00:00Z"
    authenticated = _authenticated(record)
    original = authenticated.canonical_record
    widened = ConsentRecordV1(
        consent_id=record.consent_id,
        subject_pseudonym=record.subject_pseudonym,
        streams=("conversation", "audio"),
        destination=record.destination,
        granted_at=record.granted_at,
        expires_at=record.expires_at,
        authority=record.authority,
    )
    object.__setattr__(authenticated, "record", widened)
    assert not authenticated.authenticated
    assert original != widened.canonical_bytes()
    with (
        ResearchSpool(root=tmp_path / "research") as spool,
        pytest.raises(TypeError, match="authenticated consent wrapper"),
    ):
        spool.record_consent(authenticated)


def test_revocation_deletes_mixed_bundle_and_requeues_retained_events(tmp_path: Path) -> None:
    consent = ConsentRecordV1(
        consent_id="consent-mixed",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        spool.record_consent(_authenticated(consent))
        _store(
            spool,
            _candidate(
                0,
                stream="conversation",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"outcome_code": "completed"},
            ),
        )
        _store(
            spool,
            _candidate(
                1,
                stream="feedback",
                data={"label": "success", "task": "navigate"},
            ),
        )
        artifact = build_bundle(spool, now=NOW)
        assert artifact is not None and artifact.event_count == 2
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=1, marker=b"d")
        assert ByteGovernor(spool).charge(
            encrypted, transfer_attempt_id="deletion-attempt", now=NOW
        ).allowed

        result = spool.revoke_consent(
            consent.consent_id, reason_code="owner_revoked", revoked_at=NOW
        )
        assert result == {
            "affected_events": 1,
            "deleted_events": 1,
            "invalidated_bundles": 1,
            "requeued_events": 1,
        }
        assert not artifact.bundle_path.exists()
        assert not artifact.manifest_path.exists()
        assert not encrypted.ciphertext_path.exists()
        rejected_retry = ByteGovernor(spool).charge(
            encrypted, transfer_attempt_id="deletion-retry", now=NOW
        )
        assert not rejected_retry.allowed
        assert rejected_retry.reason == "unknown_source_bundle"
        snapshot = spool.snapshot()
        assert snapshot["event_states"] == {"queued": 1}
        assert snapshot["pending_remote_deletion_obligations"] == 1
        rebuilt = build_bundle(spool)
        assert rebuilt is not None
        assert [event.sequence for event in replay_bundle(rebuilt)] == [1]


def test_expiry_cascades_mixed_bundle_and_preserves_longer_retention(tmp_path: Path) -> None:
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        _store(
            spool,
            _candidate(
                0,
                stream="conversation",
                data={"outcome_code": "completed"},
            ),
        )
        _store(
            spool,
            _candidate(
                1,
                stream="feedback",
                data={"label": "success", "task": "navigate"},
            ),
        )
        artifact = build_bundle(spool)
        assert artifact is not None and artifact.event_count == 2
        deleted = spool.purge_expired(now=NOW + timedelta(days=91))
        assert deleted == 1
        assert not artifact.bundle_path.exists()
        assert not artifact.manifest_path.exists()
        assert spool.snapshot()["event_states"] == {"queued": 1}


def test_mass_expiry_uses_bounded_sqlite_batches_beyond_parameter_limit(
    tmp_path: Path,
) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        for sequence in range(1_100):
            candidate = _candidate(sequence)
            candidate["time"] = NOW.isoformat().replace("+00:00", "Z")
            _store(spool, candidate)
        assert spool.purge_expired(now=NOW + timedelta(days=91)) == 1_100
        assert spool.snapshot()["event_states"] == {}


def test_deletion_journal_rejects_symlink_replacement_and_path_generation_reuse(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research"

    def fail_unlink(_path: Path) -> None:
        raise OSError("injected unlink failure")

    with ResearchSpool(root=root, deletion_unlinker=fail_unlink) as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"s")
        assert ByteGovernor(spool).charge(
            encrypted,
            transfer_attempt_id="symlink-journal-attempt",
            now=NOW,
        ).allowed
        assert spool.purge_expired(now=NOW + timedelta(days=91)) == 1

    encrypted.ciphertext_path.unlink()
    external = tmp_path / "must-survive.enc"
    external.write_bytes(b"not a managed research object")
    encrypted.ciphertext_path.symlink_to(external)
    with ResearchSpool(root=root) as reopened:
        assert external.read_bytes() == b"not a managed research object"
        assert encrypted.ciphertext_path.is_symlink()
        assert reopened.snapshot()["pending_local_deletions"] == 1

        reused = reopened.encrypted_root / "generation-reuse.enc"
        reused.write_bytes(b"generation-one")
        reused_sha = sha256_hex(reused.read_bytes())
        reopened._journal_local_path(
            "encrypted", reused.name, reused_sha, "generation-one", NOW.isoformat(), "test"
        )
        with pytest.raises(ValueError, match="path reuse"):
            reopened._journal_local_path(
                "encrypted",
                reused.name,
                reused_sha,
                "generation-two",
                NOW.isoformat(),
                "test",
            )


def test_tampered_artifact_is_quarantined_without_blocking_consent_revocation(
    tmp_path: Path,
) -> None:
    consent = ConsentRecordV1(
        consent_id="consent-tampered-artifact",
        subject_pseudonym="robot_0123456789abcdef",
        streams=("conversation",),
        destination="research-local",
        granted_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        authority="owner_ui",
    )
    with ResearchSpool(
        root=tmp_path / "research", consent_verifier=CONSENT_VERIFIER
    ) as spool:
        spool.record_consent(_authenticated(consent))
        _store(
            spool,
            _candidate(
                0,
                stream="conversation",
                privacy_class="consent_required",
                consent_id=consent.consent_id,
                data={"outcome_code": "completed"},
            ),
        )
        artifact = build_bundle(spool, now=NOW)
        assert artifact is not None
        artifact.bundle_path.write_bytes(b"unverified replacement")

        revoked = spool.revoke_consent(
            consent.consent_id,
            reason_code="owner_revoked",
            revoked_at=NOW,
        )
        assert revoked["deleted_events"] == 1
        assert revoked["invalidated_bundles"] == 1
        assert artifact.bundle_path.read_bytes() == b"unverified replacement"
        assert not artifact.manifest_path.exists()
        snapshot = spool.snapshot()
        assert snapshot["event_states"] == {}
        assert snapshot["pending_local_deletions"] == 1


def test_deletion_journal_scans_beyond_failed_oldest_rows_under_bounded_work(
    tmp_path: Path,
) -> None:
    with ResearchSpool(root=tmp_path / "research") as spool:
        rows = []
        for index in range(300):
            name = f"blocked-{index}.enc"
            device = inode = None
            if index < 260:
                target = spool.encrypted_root / name
                target.symlink_to(tmp_path / f"external-{index}")
                device = inode = 1
            rows.append(
                (
                    f"journal-{index}",
                    "encrypted",
                    name,
                    ZERO_SHA,
                    f"generation-{index}",
                    device,
                    inode,
                    NOW.isoformat(),
                    "test_failure",
                )
            )
        spool.connection_for_governor.executemany(
            """INSERT INTO local_deletion_journal(
                   entry_id, managed_kind, relative_path, content_sha256,
                   generation_id, device_id, inode, created_at, reason_code
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        spool.connection_for_governor.commit()
        assert spool.drain_local_deletions(max_entries=256) == 40
        assert spool.snapshot()["pending_local_deletions"] == 260


def test_committed_local_deletion_intent_recovers_after_unlink_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research"

    def fail_unlink(_path: Path) -> None:
        raise OSError("injected unlink failure")

    with ResearchSpool(root=root, deletion_unlinker=fail_unlink) as spool:
        _store(spool, _candidate(0))
        artifact = build_bundle(spool)
        assert artifact is not None
        encrypted = _ciphertext(spool, artifact.bundle_sha256, priority=2, marker=b"j")
        assert ByteGovernor(spool).charge(
            encrypted,
            transfer_attempt_id="journal-attempt",
            now=NOW,
        ).allowed
        assert spool.purge_expired(now=NOW + timedelta(days=91)) == 1
        assert artifact.bundle_path.exists()
        assert artifact.manifest_path.exists()
        assert encrypted.ciphertext_path.exists()
        snapshot = spool.snapshot()
        assert snapshot["event_states"] == {}
        assert snapshot["pending_local_deletions"] == 3
        assert snapshot["pending_remote_deletion_obligations"] == 1

    with ResearchSpool(root=root) as reopened:
        assert reopened.snapshot()["pending_local_deletions"] == 0
        assert reopened.snapshot()["pending_remote_deletion_obligations"] == 1
        assert not artifact.bundle_path.exists()
        assert not artifact.manifest_path.exists()
        assert not encrypted.ciphertext_path.exists()


def test_producer_factory_has_scoped_identity_and_per_stream_sequences() -> None:
    secret = b"p" * 32
    pseudonym = pseudonymous_robot_id(secret, "local-unitree-serial-never-exported")
    assert pseudonym == pseudonymous_robot_id(
        secret, "local-unitree-serial-never-exported"
    )
    assert pseudonym != pseudonymous_robot_id(b"q" * 32, "local-unitree-serial-never-exported")
    identity = ResearchProducerIdentityV1(
        run_id="sim-campaign-1",
        robot_pseudonym=pseudonym,
        code_sha256=ZERO_SHA,
        config_sha256=ONE_SHA,
        calibration_ids=("sim-v1",),
        device_clock="sim",
    )
    factory = ResearchEventFactoryV1(
        identity,
        wall_clock=lambda: NOW,
        monotonic_ns=lambda: 123,
    )
    nav0 = factory.candidate("navigation", {"planner_state": "tracking"}, source_time_ns=1)
    nav1 = factory.candidate("navigation", {"planner_state": "paused"}, source_time_ns=2)
    audio0 = factory.candidate("audio", {"snr_db": 12.0}, source_time_ns=3)

    assert (nav0["sequence"], nav1["sequence"], audio0["sequence"]) == (0, 1, 0)
    assert nav0["priority"] == 2
    assert nav0["robot_pseudonym"] == pseudonym
    assert admit_candidate(nav0).accepted
    assert admit_candidate(audio0).accepted
    consented_note = factory.candidate(
        "conversation",
        {"outcome_code": "clarified", "redacted_note": "approved excerpt"},
        source_time_ns=4,
        privacy_class="consent_required",
        consent_id="study-consent-1",
    )
    assert consented_note["retention_class"] == "consented_text_30d"
    assert admit_candidate(consented_note).accepted
    with pytest.raises(ValueError, match="explicit consent"):
        factory.candidate(
            "conversation",
            {"redacted_note": "not approved"},
            source_time_ns=5,
        )
    with pytest.raises(ValueError, match="non-negative integer"):
        factory.candidate("navigation", {}, source_time_ns=1.5)


def test_async_sink_keeps_storage_off_producer_and_drains_to_bundles(tmp_path: Path) -> None:
    root = tmp_path / "research"
    plane = ResearchPlane.from_config(
        ResearchPlaneConfig(enabled=True, root=root, target_bundle_bytes=1024)
    )
    assert isinstance(plane, ResearchPlane)
    sink = AsyncResearchSink(plane, max_queue_events=8, bundle_every_events=2)
    identity = ResearchProducerIdentityV1(
        run_id="async-run",
        robot_pseudonym="robot_0123456789abcdef",
        code_sha256=ZERO_SHA,
        config_sha256=ONE_SHA,
        device_clock="sim",
    )
    factory = ResearchEventFactoryV1(identity)
    try:
        assert sink.start()
        assert sink.offer(
            factory.candidate("navigation", {"planner_state": "tracking"}, source_time_ns=0)
        )
        assert sink.offer(factory.candidate("audio", {"snr_db": 8.0}, source_time_ns=1))
        assert not sink.offer(
            factory.candidate(
                "navigation",
                {"planner_state": "tracking", "raw_audio": "private"},
                source_time_ns=2,
            )
        )
        sink.close()

        snapshot = sink.snapshot()
        assert snapshot["running"] is False
        assert snapshot["queue_depth"] == 0
        assert snapshot["counters"]["queued"] == 2
        assert snapshot["counters"]["rejected:forbidden_fields:raw_audio"] == 1
        spool = plane.snapshot()["spool"]
        assert spool["event_states"] == {"bundled": 2}
        assert list((root / "bundles").glob("*.jsonl.gz"))
    finally:
        sink.close()
        plane.close()
