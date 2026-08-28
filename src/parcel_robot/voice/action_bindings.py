"""Canonical consent and safety bindings for commissioned companion actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from parcel_robot.capabilities.manifest import CapabilityManifestV1, canonical_digest
from parcel_robot.contracts.companion_v1 import (
    ACTION_INITIATORS,
    CONSENT_SCOPES,
    _boolean,
    _enum,
    _identifier,
)

MOVEMENT_SCOPES = frozenset({"approach", "following", "owner_search", "navigation"})
PHYSICAL_SCOPES = MOVEMENT_SCOPES | {"stationary_expression"}


@dataclass(frozen=True, slots=True)
class ActionScopeBindingV1:
    """Trusted local semantics for one exact commissioned action name."""

    consent_scope: str
    allowed_initiators: tuple[str, ...]
    requires_verified_owner: bool
    requires_idle_body: bool
    requires_locomotion: bool
    requires_clear_space: bool
    repeatable: bool

    def __post_init__(self) -> None:
        _enum(self.consent_scope, CONSENT_SCOPES, "binding consent_scope")
        if not isinstance(self.allowed_initiators, tuple) or not self.allowed_initiators:
            raise ValueError("allowed_initiators must be a non-empty tuple")
        if len(set(self.allowed_initiators)) != len(self.allowed_initiators):
            raise ValueError("allowed_initiators cannot contain duplicates")
        if self.allowed_initiators != tuple(sorted(self.allowed_initiators)):
            raise ValueError("allowed_initiators must be sorted")
        for initiator in self.allowed_initiators:
            _enum(initiator, ACTION_INITIATORS, "allowed initiator")
        for name in (
            "requires_verified_owner",
            "requires_idle_body",
            "requires_locomotion",
            "requires_clear_space",
            "repeatable",
        ):
            _boolean(getattr(self, name), name)
        if self.consent_scope in MOVEMENT_SCOPES and not self.requires_locomotion:
            raise ValueError("movement consent scopes must require locomotion")
        if self.consent_scope in MOVEMENT_SCOPES and not self.requires_verified_owner:
            raise ValueError("movement consent scopes must require a verified owner")
        if self.requires_locomotion and self.consent_scope not in MOVEMENT_SCOPES:
            raise ValueError("locomotion may only be bound to a movement consent scope")

    def as_dict(self) -> dict[str, object]:
        return {
            "consent_scope": self.consent_scope,
            "allowed_initiators": list(self.allowed_initiators),
            "requires_verified_owner": self.requires_verified_owner,
            "requires_idle_body": self.requires_idle_body,
            "requires_locomotion": self.requires_locomotion,
            "requires_clear_space": self.requires_clear_space,
            "repeatable": self.repeatable,
        }


@dataclass(frozen=True, slots=True)
class ActionBindingRegistryV1:
    """Canonical immutable exact-name bindings sealed into body snapshots."""

    bindings: tuple[tuple[str, ActionScopeBindingV1], ...]
    registry_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bindings, tuple):
            raise TypeError("bindings must be a tuple")
        checked: list[tuple[str, ActionScopeBindingV1]] = []
        for name, binding in self.bindings:
            if not isinstance(binding, ActionScopeBindingV1):
                raise TypeError("registry values must be ActionScopeBindingV1")
            checked.append((_identifier(name, "binding action name"), binding))
        ordered = tuple(sorted(checked, key=lambda item: item[0]))
        if len({name for name, _ in ordered}) != len(ordered):
            raise ValueError("binding registry contains duplicate action names")
        object.__setattr__(self, "bindings", ordered)
        object.__setattr__(
            self,
            "registry_digest",
            canonical_digest(
                {
                    "format": "companion-action-binding-registry-v1",
                    "bindings": [
                        {"action_name": name, **binding.as_dict()}
                        for name, binding in ordered
                    ],
                }
            ),
        )

    def get(self, action_name: str) -> ActionScopeBindingV1 | None:
        clean = _identifier(action_name, "action_name")
        return next(
            (binding for name, binding in self.bindings if name == clean),
            None,
        )

    def assert_canonical_integrity(self) -> None:
        """Reject post-construction mutation of digest-bound action semantics."""

        current = canonical_digest(
            {
                "format": "companion-action-binding-registry-v1",
                "bindings": [
                    {"action_name": name, **binding.as_dict()}
                    for name, binding in self.bindings
                ],
            }
        )
        if current != self.registry_digest:
            raise ValueError(
                "registry_digest no longer matches canonical action bindings"
            )


def manifest_binding_reason(
    manifest: CapabilityManifestV1,
    action_name: str,
    binding: ActionScopeBindingV1,
) -> str | None:
    """Enforce coarse capability categories before exact trusted scope use."""

    navigation_names = {
        entry.name for entry in manifest.available_navigation_modes()
    }
    stationary_names = {
        entry.name
        for entry in (*manifest.available_gestures(), *manifest.available_poses())
    }
    if action_name in navigation_names and binding.consent_scope not in MOVEMENT_SCOPES:
        return "navigation_action_requires_movement_scope"
    if action_name in stationary_names and binding.consent_scope in MOVEMENT_SCOPES:
        return "stationary_action_cannot_use_movement_scope"
    return None


__all__ = [
    "MOVEMENT_SCOPES",
    "PHYSICAL_SCOPES",
    "ActionBindingRegistryV1",
    "ActionScopeBindingV1",
    "manifest_binding_reason",
]
