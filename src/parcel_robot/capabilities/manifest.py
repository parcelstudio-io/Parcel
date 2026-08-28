"""Canonical declarations, profiles, and authenticated commissioning.

Only :func:`generate_effective_manifest` joins those facts; names never imply
semantic tags, and missing, stale, or mismatched evidence is unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypeVar

from .commissioning_lifecycle import (
    CommissioningLifecycleV1,
    CommissioningStateProviderV1,
    validate_commissioning_lifecycle,
)
from .manifest_binding import binding_payload as _manifest_binding_payload
from .manifest_binding import (
    commissioning_matches_manifest as _commissioning_matches_manifest,
)
from .manifest_binding import select_entries as _select_entries
from .manifest_parsing import (
    manifest_rows as _manifest_rows,
)
from .manifest_parsing import (
    parse_gesture_rows as _parse_gesture_rows,
)
from .manifest_parsing import (
    parse_navigation_rows as _parse_navigation_rows,
)
from .manifest_parsing import (
    parse_pose_rows as _parse_pose_rows,
)
from .manifest_parsing import (
    parse_tool_rows as _parse_tool_rows,
)

CAPABILITY_MANIFEST_VERSION = "capability-manifest-v1"
CapabilityKind = Literal["tool", "gesture", "pose", "navigation_mode"]
DeploymentEnvironment = Literal["simulation", "staging", "physical"]

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_TAG = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityManifestError(ValueError):
    """A declaration or commissioning record is malformed or contradictory."""
class CapabilityProfileError(CapabilityManifestError):
    """An effective profile cannot be resolved exactly against declarations."""
def _exact_fields(row: Mapping[str, Any], names: set[str], label: str) -> None:
    if set(row) != names:
        raise CapabilityManifestError(
            f"{label} fields must be exactly {sorted(names)}, got {sorted(row)}"
        )
def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CapabilityManifestError(f"capability data is not canonical JSON: {error}") from error
def canonical_digest(value: object) -> str:
    """Return the SHA-256 of canonical JSON for ``value``."""
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _name(value: object, field_name: str = "name") -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise CapabilityManifestError(
            f"{field_name} must match {_NAME.pattern!r}, got {value!r}"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CapabilityManifestError(
            f"{field_name} must be a lowercase 64-character SHA-256 digest"
        )
    return value


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise CapabilityManifestError(f"{field_name} must be a boolean")
    return value


def _strings(
    values: Sequence[object] | tuple[str, ...],
    field_name: str,
    *,
    validator,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CapabilityManifestError(f"{field_name} must be a sequence of strings")
    cleaned = tuple(validator(value, field_name) for value in values)
    if len(set(cleaned)) != len(cleaned):
        raise CapabilityManifestError(f"{field_name} contains duplicate values")
    return tuple(sorted(cleaned))


def _tag(value: object, field_name: str = "tag") -> str:
    if not isinstance(value, str) or not _TAG.fullmatch(value):
        raise CapabilityManifestError(
            f"{field_name} must match {_TAG.pattern!r}, got {value!r}"
        )
    return value


def _tags(values: Sequence[object] | tuple[str, ...]) -> tuple[str, ...]:
    return _strings(values, "tags", validator=_tag)


@dataclass(frozen=True)
class DeploymentTargetV1:
    """Exact deployment and adapter identity to which evidence applies."""

    deployment_id: str
    environment: DeploymentEnvironment
    adapter_id: str
    adapter_identity_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "deployment_id", _name(self.deployment_id, "deployment_id"))
        if self.environment not in {"simulation", "staging", "physical"}:
            raise CapabilityManifestError(
                "environment must be simulation, staging, or physical"
            )
        object.__setattr__(self, "adapter_id", _name(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "adapter_identity_digest",
            _digest(self.adapter_identity_digest, "adapter_identity_digest"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "deployment_id": self.deployment_id,
            "environment": self.environment,
            "adapter_id": self.adapter_id,
            "adapter_identity_digest": self.adapter_identity_digest,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DeploymentTargetV1:
        if not isinstance(value, Mapping):
            raise CapabilityManifestError("deployment target must be a mapping")
        fields = {
            "deployment_id",
            "environment",
            "adapter_id",
            "adapter_identity_digest",
        }
        _exact_fields(value, fields, "deployment target")
        return cls(
            deployment_id=value["deployment_id"],
            environment=value["environment"],
            adapter_id=value["adapter_id"],
            adapter_identity_digest=value["adapter_identity_digest"],
        )


@dataclass(frozen=True)
class ToolCapabilityV1:
    name: str
    schema_digest: str
    tags: tuple[str, ...] = ()
    commissioned: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(self, "schema_digest", _digest(self.schema_digest, "schema_digest"))
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(self, "commissioned", _bool(self.commissioned, "commissioned"))

    @property
    def artifact_digest(self) -> str:
        return self.schema_digest

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "schema_digest": self.schema_digest,
            "tags": list(self.tags),
            "commissioned": self.commissioned,
        }


@dataclass(frozen=True)
class GestureCapabilityV1:
    name: str
    tags: tuple[str, ...]
    trajectory_digest: str
    commissioned: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(
            self,
            "trajectory_digest",
            _digest(self.trajectory_digest, "trajectory_digest"),
        )
        object.__setattr__(self, "commissioned", _bool(self.commissioned, "commissioned"))

    @property
    def artifact_digest(self) -> str:
        return self.trajectory_digest

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tags": list(self.tags),
            "trajectory_digest": self.trajectory_digest,
            "commissioned": self.commissioned,
        }


@dataclass(frozen=True)
class PoseCapabilityV1:
    name: str
    tags: tuple[str, ...]
    trajectory_digest: str
    commissioned: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(
            self,
            "trajectory_digest",
            _digest(self.trajectory_digest, "trajectory_digest"),
        )
        object.__setattr__(self, "commissioned", _bool(self.commissioned, "commissioned"))

    @property
    def artifact_digest(self) -> str:
        return self.trajectory_digest

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tags": list(self.tags),
            "trajectory_digest": self.trajectory_digest,
            "commissioned": self.commissioned,
        }


@dataclass(frozen=True)
class NavigationModeCapabilityV1:
    name: str
    tags: tuple[str, ...]
    required_evidence: tuple[str, ...]
    commissioned: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(self, "tags", _tags(self.tags))
        object.__setattr__(
            self,
            "required_evidence",
            _strings(self.required_evidence, "required_evidence", validator=_tag),
        )
        if not self.required_evidence:
            raise CapabilityManifestError(
                f"navigation mode {self.name!r} requires at least one evidence type"
            )
        object.__setattr__(self, "commissioned", _bool(self.commissioned, "commissioned"))

    @property
    def artifact_digest(self) -> str:
        """Digest of the typed navigation contract used for commissioning."""

        return canonical_digest(
            {
                "format": "navigation-mode-capability-v1",
                "name": self.name,
                "tags": list(self.tags),
                "required_evidence": list(self.required_evidence),
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tags": list(self.tags),
            "required_evidence": list(self.required_evidence),
            "commissioned": self.commissioned,
        }


CapabilityEntryV1 = (
    ToolCapabilityV1
    | GestureCapabilityV1
    | PoseCapabilityV1
    | NavigationModeCapabilityV1
)
_EntryT = TypeVar("_EntryT", bound=CapabilityEntryV1)


def _entries(
    values: Sequence[_EntryT] | tuple[_EntryT, ...],
    expected_type: type[_EntryT],
    field_name: str,
) -> tuple[_EntryT, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CapabilityManifestError(f"{field_name} must be a sequence")
    if not all(isinstance(value, expected_type) for value in values):
        raise CapabilityManifestError(
            f"{field_name} must contain only {expected_type.__name__} entries"
        )
    ordered = tuple(sorted(values, key=lambda value: value.name))
    names = [value.name for value in ordered]
    if len(set(names)) != len(names):
        raise CapabilityManifestError(f"{field_name} contains duplicate names")
    return ordered


@dataclass(frozen=True)
class CapabilityManifestV1:
    """Canonical typed capabilities for one effective deployment profile."""

    profile_id: str
    deployment_target: DeploymentTargetV1
    commissioning_authority_id: str
    commissioning_evidence_digest: str
    commissioning_lifecycle: CommissioningLifecycleV1
    tools: tuple[ToolCapabilityV1, ...] = ()
    gestures: tuple[GestureCapabilityV1, ...] = ()
    poses: tuple[PoseCapabilityV1, ...] = ()
    navigation_modes: tuple[NavigationModeCapabilityV1, ...] = ()
    version: str = CAPABILITY_MANIFEST_VERSION
    manifest_digest: str = field(init=False)
    _authenticated_commissioning: AuthenticatedCapabilityCommissioningV1 | None = field(
        init=False, default=None, repr=False, compare=False
    )
    _manifest_binding_tag: str = field(init=False, default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _name(self.profile_id, "profile_id"))
        if not isinstance(self.deployment_target, DeploymentTargetV1):
            raise CapabilityManifestError("deployment_target must be DeploymentTargetV1")
        object.__setattr__(
            self,
            "commissioning_authority_id",
            _name(self.commissioning_authority_id, "commissioning_authority_id"),
        )
        object.__setattr__(
            self,
            "commissioning_evidence_digest",
            _digest(
                self.commissioning_evidence_digest,
                "commissioning_evidence_digest",
            ),
        )
        if not isinstance(self.commissioning_lifecycle, CommissioningLifecycleV1):
            raise CapabilityManifestError("commissioning_lifecycle is required")
        if self.version != CAPABILITY_MANIFEST_VERSION:
            raise CapabilityManifestError(
                f"unsupported capability manifest version: {self.version!r}"
            )
        object.__setattr__(self, "tools", _entries(self.tools, ToolCapabilityV1, "tools"))
        object.__setattr__(
            self,
            "gestures",
            _entries(self.gestures, GestureCapabilityV1, "gestures"),
        )
        object.__setattr__(self, "poses", _entries(self.poses, PoseCapabilityV1, "poses"))
        object.__setattr__(
            self,
            "navigation_modes",
            _entries(
                self.navigation_modes,
                NavigationModeCapabilityV1,
                "navigation_modes",
            ),
        )
        action_names = [
            entry.name
            for entry in (*self.gestures, *self.poses, *self.navigation_modes)
        ]
        if len(set(action_names)) != len(action_names):
            raise CapabilityManifestError(
                "an action name cannot span gesture, pose, and navigation categories"
            )
        commissioned = any(
            entry.commissioned
            for entry in (*self.tools, *self.gestures, *self.poses, *self.navigation_modes)
        )
        if commissioned:
            raise CapabilityManifestError(
                "commissioned availability requires authenticated manifest generation"
            )
        object.__setattr__(self, "manifest_digest", canonical_digest(self._digest_payload()))

    def _digest_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "profile_id": self.profile_id,
            "deployment_target": self.deployment_target.as_dict(),
            "commissioning_authority_id": self.commissioning_authority_id,
            "commissioning_evidence_digest": self.commissioning_evidence_digest,
            "commissioning_lifecycle": self.commissioning_lifecycle.as_dict(),
            "tools": [entry.as_dict() for entry in self.tools],
            "gestures": [entry.as_dict() for entry in self.gestures],
            "poses": [entry.as_dict() for entry in self.poses],
            "navigation_modes": [entry.as_dict() for entry in self.navigation_modes],
        }

    def as_dict(self) -> dict[str, object]:
        return {"manifest_digest": self.manifest_digest, **self._digest_payload()}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CapabilityManifestV1:
        """Parse and verify a serialized manifest without accepting extra fields."""

        if not isinstance(value, Mapping):
            raise CapabilityManifestError("capability manifest must be a mapping")
        allowed = {
            "manifest_digest",
            "version",
            "profile_id",
            "deployment_target",
            "commissioning_authority_id",
            "commissioning_evidence_digest",
            "commissioning_lifecycle",
            "tools",
            "gestures",
            "poses",
            "navigation_modes",
        }
        unknown = set(value) - allowed
        if unknown:
            raise CapabilityManifestError(
                f"unsupported capability manifest fields: {sorted(unknown)}"
            )
        missing = allowed - set(value)
        if missing:
            raise CapabilityManifestError(
                f"capability manifest is missing fields: {sorted(missing)}"
            )

        manifest = cls(
            profile_id=value["profile_id"],
            deployment_target=DeploymentTargetV1.from_mapping(
                value["deployment_target"]
            ),
            commissioning_authority_id=value["commissioning_authority_id"],
            commissioning_evidence_digest=value["commissioning_evidence_digest"],
            commissioning_lifecycle=CommissioningLifecycleV1.from_mapping(
                value["commissioning_lifecycle"]
            ),
            version=value["version"],
            tools=_parse_tool_rows(
                _manifest_rows(value, "tools", CapabilityManifestError),
                ToolCapabilityV1,
                CapabilityManifestError,
            ),
            gestures=_parse_gesture_rows(
                _manifest_rows(value, "gestures", CapabilityManifestError),
                GestureCapabilityV1,
                CapabilityManifestError,
            ),
            poses=_parse_pose_rows(
                _manifest_rows(value, "poses", CapabilityManifestError),
                PoseCapabilityV1,
                CapabilityManifestError,
            ),
            navigation_modes=_parse_navigation_rows(
                _manifest_rows(value, "navigation_modes", CapabilityManifestError),
                NavigationModeCapabilityV1,
                CapabilityManifestError,
            ),
        )
        supplied_digest = _digest(value["manifest_digest"], "manifest_digest")
        if supplied_digest != manifest.manifest_digest:
            raise CapabilityManifestError(
                "manifest_digest does not match the canonical capability payload"
            )
        return manifest

    def prompt_context(self) -> dict[str, object]:
        """Return the complete manifest; consumers must still check commissioning."""

        self.assert_canonical_integrity()
        return self.as_dict()

    def assert_canonical_integrity(self) -> None:
        """Reject post-construction mutation of the digest-bound manifest payload."""

        current = canonical_digest(self._digest_payload())
        if not hmac.compare_digest(self.manifest_digest, current):
            raise CapabilityManifestError(
                "manifest_digest no longer matches the canonical capability payload"
            )

    def assert_authenticated_commissioning(
        self, authenticator: TrustedCommissioningAuthenticatorV1
    ) -> None:
        self.assert_canonical_integrity()
        if not isinstance(authenticator, TrustedCommissioningAuthenticatorV1):
            raise CapabilityManifestError("trusted commissioning authenticator is missing")
        if not authenticator.verify_manifest(self):
            raise CapabilityManifestError(
                "manifest commissioning provenance authentication failed"
            )

    def _available(
        self,
        entries: Sequence[_EntryT],
        required_tags: Sequence[str] = (),
    ) -> tuple[_EntryT, ...]:
        self.assert_canonical_integrity()
        tags = frozenset(_tags(tuple(required_tags)))
        return tuple(
            entry
            for entry in entries
            if entry.commissioned and tags.issubset(entry.tags)
        )

    def available_tools(self, *, required_tags: Sequence[str] = ()) -> tuple[ToolCapabilityV1, ...]:
        return self._available(self.tools, required_tags)

    def available_gestures(
        self, *, required_tags: Sequence[str] = ()
    ) -> tuple[GestureCapabilityV1, ...]:
        return self._available(self.gestures, required_tags)

    def available_poses(self, *, required_tags: Sequence[str] = ()) -> tuple[PoseCapabilityV1, ...]:
        return self._available(self.poses, required_tags)

    def available_navigation_modes(
        self, *, required_tags: Sequence[str] = ()
    ) -> tuple[NavigationModeCapabilityV1, ...]:
        return self._available(self.navigation_modes, required_tags)

    def navigation_mode_available(
        self,
        name: str,
        *,
        required_tags: Sequence[str] = (),
    ) -> bool:
        """Return whether one exact navigation mode is commissioned."""

        clean = _name(name)
        return any(
            entry.name == clean
            for entry in self.available_navigation_modes(required_tags=required_tags)
        )

    def available_embodied_names(self, *, required_tags: Sequence[str] = ()) -> tuple[str, ...]:
        """Exact commissioned gesture/pose names carrying every requested tag."""

        entries = (
            *self.available_gestures(required_tags=required_tags),
            *self.available_poses(required_tags=required_tags),
        )
        return tuple(sorted(entry.name for entry in entries))

    def commissioned_action_names(self) -> tuple[str, ...]:
        """Exact non-tool actions admitted at the conversation bridge."""

        entries = (
            *self.available_gestures(),
            *self.available_poses(),
            *self.available_navigation_modes(),
        )
        return tuple(sorted(entry.name for entry in entries))

    def gesture_available(self, name: str, *, required_tags: Sequence[str] = ()) -> bool:
        clean = _name(name)
        return any(
            entry.name == clean
            for entry in self.available_gestures(required_tags=required_tags)
        )

    def pose_available(self, name: str, *, required_tags: Sequence[str] = ()) -> bool:
        clean = _name(name)
        return any(
            entry.name == clean
            for entry in self.available_poses(required_tags=required_tags)
        )


@dataclass(frozen=True)
class EffectiveCapabilityProfileV1:
    """Exact names selected by a fully merged/effective robot profile."""

    profile_id: str
    deployment_target: DeploymentTargetV1
    tools: tuple[str, ...] = ()
    gestures: tuple[str, ...] = ()
    poses: tuple[str, ...] = ()
    navigation_modes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _name(self.profile_id, "profile_id"))
        if not isinstance(self.deployment_target, DeploymentTargetV1):
            raise CapabilityProfileError("deployment_target must be DeploymentTargetV1")
        for field_name in ("tools", "gestures", "poses", "navigation_modes"):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name, validator=_name),
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EffectiveCapabilityProfileV1:
        if not isinstance(value, Mapping):
            raise CapabilityProfileError("effective capability profile must be a mapping")
        allowed = {
            "version",
            "profile_id",
            "deployment_target",
            "tools",
            "gestures",
            "poses",
            "navigation_modes",
        }
        unknown = set(value) - allowed
        if unknown:
            raise CapabilityProfileError(
                f"unsupported effective capability profile fields: {sorted(unknown)}"
            )
        version = value.get("version", CAPABILITY_MANIFEST_VERSION)
        if version != CAPABILITY_MANIFEST_VERSION:
            raise CapabilityProfileError(f"unsupported capability profile version: {version!r}")
        try:
            return cls(
                profile_id=value["profile_id"],
                deployment_target=DeploymentTargetV1.from_mapping(
                    value["deployment_target"]
                ),
                tools=tuple(value.get("tools", ())),
                gestures=tuple(value.get("gestures", ())),
                poses=tuple(value.get("poses", ())),
                navigation_modes=tuple(value.get("navigation_modes", ())),
            )
        except KeyError as error:
            raise CapabilityProfileError("effective capability profile requires profile_id") from error

    def as_dict(self) -> dict[str, object]:
        return {
            "version": CAPABILITY_MANIFEST_VERSION,
            "profile_id": self.profile_id,
            "deployment_target": self.deployment_target.as_dict(),
            "tools": list(self.tools),
            "gestures": list(self.gestures),
            "poses": list(self.poses),
            "navigation_modes": list(self.navigation_modes),
        }


@dataclass(frozen=True)
class CommissionedArtifactV1:
    kind: CapabilityKind
    name: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if self.kind not in {"tool", "gesture", "pose", "navigation_mode"}:
            raise CapabilityManifestError(f"unsupported commissioned capability kind: {self.kind!r}")
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(
            self,
            "artifact_digest",
            _digest(self.artifact_digest, "artifact_digest"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "artifact_digest": self.artifact_digest,
        }


@dataclass(frozen=True)
class CapabilityCommissioningV1:
    deployment_target: DeploymentTargetV1
    commissioning_authority_id: str
    evidence_digest: str
    lifecycle: CommissioningLifecycleV1
    artifacts: tuple[CommissionedArtifactV1, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.deployment_target, DeploymentTargetV1):
            raise CapabilityManifestError("deployment_target must be DeploymentTargetV1")
        object.__setattr__(
            self,
            "commissioning_authority_id",
            _name(self.commissioning_authority_id, "commissioning_authority_id"),
        )
        object.__setattr__(
            self,
            "evidence_digest",
            _digest(self.evidence_digest, "evidence_digest"),
        )
        if not isinstance(self.lifecycle, CommissioningLifecycleV1):
            raise CapabilityManifestError("commissioning lifecycle is required")
        if isinstance(self.artifacts, (str, bytes)) or not isinstance(self.artifacts, Sequence):
            raise CapabilityManifestError("commissioned artifacts must be a sequence")
        if not all(isinstance(item, CommissionedArtifactV1) for item in self.artifacts):
            raise CapabilityManifestError(
                "commissioned artifacts must contain CommissionedArtifactV1 entries"
            )
        ordered = tuple(sorted(self.artifacts, key=lambda item: (item.kind, item.name)))
        keys = [(item.kind, item.name) for item in ordered]
        if len(set(keys)) != len(keys):
            raise CapabilityManifestError("commissioning record contains duplicate entries")
        object.__setattr__(self, "artifacts", ordered)

    def as_dict(self) -> dict[str, object]:
        return {
            "version": CAPABILITY_MANIFEST_VERSION,
            "deployment_target": self.deployment_target.as_dict(),
            "commissioning_authority_id": self.commissioning_authority_id,
            "evidence_digest": self.evidence_digest,
            "lifecycle": self.lifecycle.as_dict(),
            "artifacts": [item.as_dict() for item in self.artifacts],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CapabilityCommissioningV1:
        if not isinstance(value, Mapping):
            raise CapabilityManifestError("capability commissioning record must be a mapping")
        allowed = {
            "version",
            "deployment_target",
            "commissioning_authority_id",
            "evidence_digest",
            "lifecycle",
            "artifacts",
        }
        if set(value) != allowed:
            raise CapabilityManifestError(
                f"commissioning fields must be exactly {sorted(allowed)}, got {sorted(value)}"
            )
        if value["version"] != CAPABILITY_MANIFEST_VERSION:
            raise CapabilityManifestError(
                f"unsupported commissioning version: {value['version']!r}"
            )
        raw = value["artifacts"]
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise CapabilityManifestError("commissioned artifacts must be a sequence")
        artifacts: list[CommissionedArtifactV1] = []
        for row in raw:
            if not isinstance(row, Mapping) or set(row) != {
                "kind",
                "name",
                "artifact_digest",
            }:
                raise CapabilityManifestError(
                    "commissioned artifact fields must be kind, name, and artifact_digest"
                )
            artifacts.append(
                CommissionedArtifactV1(
                    kind=row["kind"],
                    name=row["name"],
                    artifact_digest=row["artifact_digest"],
                )
            )
        return cls(
            deployment_target=DeploymentTargetV1.from_mapping(
                value["deployment_target"]
            ),
            commissioning_authority_id=value["commissioning_authority_id"],
            evidence_digest=value["evidence_digest"],
            lifecycle=CommissioningLifecycleV1.from_mapping(value["lifecycle"]),
            artifacts=tuple(artifacts),
        )


@dataclass(frozen=True)
class AuthenticatedCapabilityCommissioningV1:
    commissioning: CapabilityCommissioningV1
    authenticator_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.commissioning, CapabilityCommissioningV1):
            raise CapabilityManifestError(
                "commissioning must be CapabilityCommissioningV1"
            )
        object.__setattr__(
            self, "authenticator_id", _name(self.authenticator_id, "authenticator_id")
        )
        _digest(self.auth_tag, "auth_tag")

    @property
    def authorizes_actuation(self) -> bool:
        return False


class TrustedCommissioningAuthenticatorV1:
    __slots__ = ("_key", "authenticator_id")

    def __init__(self, *, authenticator_id: str, key: bytes) -> None:
        self.authenticator_id = _name(authenticator_id, "authenticator_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise CapabilityManifestError(
                "commissioning authentication key must contain at least 32 bytes"
            )
        self._key = bytes(key)

    def authenticate(
        self, commissioning: CapabilityCommissioningV1
    ) -> AuthenticatedCapabilityCommissioningV1:
        if commissioning.commissioning_authority_id != self.authenticator_id:
            raise CapabilityManifestError(
                "commissioning authority does not match authenticator"
            )
        tag = hmac.new(
            self._key,
            _canonical_json(commissioning.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return AuthenticatedCapabilityCommissioningV1(
            commissioning=commissioning,
            authenticator_id=self.authenticator_id,
            auth_tag=tag,
        )

    def verify(self, authenticated: AuthenticatedCapabilityCommissioningV1) -> bool:
        if not isinstance(authenticated, AuthenticatedCapabilityCommissioningV1):
            return False
        if authenticated.authenticator_id != self.authenticator_id:
            return False
        record = authenticated.commissioning
        if record.commissioning_authority_id != self.authenticator_id:
            return False
        expected = hmac.new(
            self._key,
            _canonical_json(record.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(authenticated.auth_tag, expected)

    def commission_manifest(
        self,
        manifest: CapabilityManifestV1,
        authenticated: AuthenticatedCapabilityCommissioningV1,
    ) -> CapabilityManifestV1:
        if not isinstance(manifest, CapabilityManifestV1) or not self.verify(authenticated):
            raise CapabilityManifestError("commissioning authentication failed")
        record = authenticated.commissioning
        if (
            record.deployment_target != manifest.deployment_target
            or record.commissioning_authority_id != manifest.commissioning_authority_id
            or record.evidence_digest != manifest.commissioning_evidence_digest
            or record.lifecycle != manifest.commissioning_lifecycle
        ):
            raise CapabilityManifestError("commissioning record does not match manifest")
        artifacts = {(item.kind, item.name): item for item in record.artifacts}
        for field_name, kind in (
            ("tools", "tool"),
            ("gestures", "gesture"),
            ("poses", "pose"),
            ("navigation_modes", "navigation_mode"),
        ):
            selected = []
            for entry in getattr(manifest, field_name):
                item = replace(entry)
                record_entry = artifacts.get((kind, item.name))
                if record_entry is not None:
                    if record_entry.artifact_digest != item.artifact_digest:
                        raise CapabilityManifestError(
                            f"commissioning digest mismatch for {kind} {item.name!r}"
                        )
                    object.__setattr__(item, "commissioned", True)
                selected.append(item)
            object.__setattr__(manifest, field_name, tuple(selected))
        object.__setattr__(manifest, "manifest_digest", canonical_digest(manifest._digest_payload()))
        object.__setattr__(manifest, "_authenticated_commissioning", authenticated)
        binding = hmac.new(
            self._key,
            _manifest_binding_payload(manifest, authenticated),
            hashlib.sha256,
        ).hexdigest()
        object.__setattr__(manifest, "_manifest_binding_tag", binding)
        return manifest

    def verify_manifest(self, manifest: CapabilityManifestV1) -> bool:
        if not isinstance(manifest, CapabilityManifestV1):
            return False
        authenticated = manifest._authenticated_commissioning
        if not self.verify(authenticated) or not _commissioning_matches_manifest(
            manifest, authenticated
        ):
            return False
        expected = hmac.new(
            self._key,
            _manifest_binding_payload(manifest, authenticated),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(manifest._manifest_binding_tag, expected)


def generate_effective_manifest(
    *,
    profile: EffectiveCapabilityProfileV1,
    commissioning: AuthenticatedCapabilityCommissioningV1,
    commissioning_authenticator: TrustedCommissioningAuthenticatorV1,
    commissioning_state_provider: CommissioningStateProviderV1,
    now_monotonic_ns: int,
    tools: Sequence[ToolCapabilityV1] = (),
    gestures: Sequence[GestureCapabilityV1] = (),
    poses: Sequence[PoseCapabilityV1] = (),
    navigation_modes: Sequence[NavigationModeCapabilityV1] = (),
) -> CapabilityManifestV1:
    if not isinstance(
        commissioning_authenticator, TrustedCommissioningAuthenticatorV1
    ):
        raise CapabilityProfileError(
            "commissioning_authenticator must be TrustedCommissioningAuthenticatorV1"
        )
    if not commissioning_authenticator.verify(commissioning):
        raise CapabilityProfileError("commissioning authentication failed")
    record = commissioning.commissioning
    validate_commissioning_lifecycle(
        record.lifecycle,
        state_provider=commissioning_state_provider,
        now_monotonic_ns=now_monotonic_ns,
    )
    if profile.deployment_target != record.deployment_target:
        raise CapabilityProfileError(
            "commissioning deployment/environment/adapter identity does not match profile"
        )
    checked_tools = _entries(tools, ToolCapabilityV1, "tools")
    checked_gestures = _entries(gestures, GestureCapabilityV1, "gestures")
    checked_poses = _entries(poses, PoseCapabilityV1, "poses")
    checked_navigation_modes = _entries(
        navigation_modes,
        NavigationModeCapabilityV1,
        "navigation_modes",
    )
    declared_by_kind: dict[CapabilityKind, dict[str, CapabilityEntryV1]] = {
        "tool": {entry.name: entry for entry in checked_tools},
        "gesture": {entry.name: entry for entry in checked_gestures},
        "pose": {entry.name: entry for entry in checked_poses},
        "navigation_mode": {entry.name: entry for entry in checked_navigation_modes},
    }
    records = {(item.kind, item.name): item for item in record.artifacts}
    unknown_records = sorted(
        f"{kind}:{name}"
        for (kind, name) in records
        if name not in declared_by_kind[kind]
    )
    if unknown_records:
        raise CapabilityProfileError(
            f"commissioning record names undeclared capabilities: {unknown_records}"
        )
    manifest = CapabilityManifestV1(
        profile_id=profile.profile_id,
        deployment_target=profile.deployment_target,
        commissioning_authority_id=record.commissioning_authority_id,
        commissioning_evidence_digest=record.evidence_digest,
        commissioning_lifecycle=record.lifecycle,
        tools=_select_entries(
            kind="tool",
            selected_names=profile.tools,
            declarations=checked_tools,
            commissioned=records,
            error_type=CapabilityProfileError,
        ),
        gestures=_select_entries(
            kind="gesture",
            selected_names=profile.gestures,
            declarations=checked_gestures,
            commissioned=records,
            error_type=CapabilityProfileError,
        ),
        poses=_select_entries(
            kind="pose",
            selected_names=profile.poses,
            declarations=checked_poses,
            commissioned=records,
            error_type=CapabilityProfileError,
        ),
        navigation_modes=_select_entries(
            kind="navigation_mode",
            selected_names=profile.navigation_modes,
            declarations=checked_navigation_modes,
            commissioned=records,
            error_type=CapabilityProfileError,
        ),
    )
    return commissioning_authenticator.commission_manifest(manifest, commissioning)
