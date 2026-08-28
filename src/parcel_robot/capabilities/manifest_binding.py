"""Leaf helpers for exact commissioning-to-manifest bindings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace


def binding_payload(manifest, authenticated) -> bytes:
    record = json.dumps(
        authenticated.commissioning.as_dict(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return json.dumps(
        {
            "domain": "parcel-capability-manifest-binding-v1",
            "manifest_digest": manifest.manifest_digest,
            "commissioning_payload_digest": hashlib.sha256(record).hexdigest(),
            "commissioning_auth_tag": authenticated.auth_tag,
            "commissioning_authority_id": authenticated.authenticator_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def manifest_entries_by_kind(manifest):
    return tuple(
        (kind, entry)
        for kind, entries in (
            ("tool", manifest.tools),
            ("gesture", manifest.gestures),
            ("pose", manifest.poses),
            ("navigation_mode", manifest.navigation_modes),
        )
        for entry in entries
    )


def commissioning_matches_manifest(manifest, authenticated) -> bool:
    record = authenticated.commissioning
    if (
        record.deployment_target != manifest.deployment_target
        or record.commissioning_authority_id != manifest.commissioning_authority_id
        or record.evidence_digest != manifest.commissioning_evidence_digest
        or record.lifecycle != manifest.commissioning_lifecycle
    ):
        return False
    artifacts = {(item.kind, item.name): item for item in record.artifacts}
    return all(
        entry.commissioned == ((kind, entry.name) in artifacts)
        and (
            not entry.commissioned
            or artifacts[(kind, entry.name)].artifact_digest == entry.artifact_digest
        )
        for kind, entry in manifest_entries_by_kind(manifest)
    )


def select_entries(*, kind, selected_names, declarations, commissioned, error_type):
    declared = {entry.name: entry for entry in declarations}
    unknown = sorted(set(selected_names) - set(declared))
    if unknown:
        raise error_type(
            f"effective profile selects unknown {kind} capability names: {unknown}"
        )
    result = []
    for name in selected_names:
        entry = declared[name]
        record = commissioned.get((kind, name))
        if record is not None and record.artifact_digest != entry.artifact_digest:
            raise error_type(
                f"commissioning digest mismatch for {kind} {name!r}: "
                f"record={record.artifact_digest}, effective={entry.artifact_digest}"
            )
        result.append(replace(entry))
    return tuple(result)
