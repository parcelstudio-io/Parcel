"""Process-local lifecycle checks for authenticated commissioning records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

MAX_COMMISSIONING_TTL_NS = 86_400_000_000_000


class CommissioningLifecycleError(ValueError):
    pass


def _int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommissioningLifecycleError(f"{field} must be an integer")
    if value < minimum:
        raise CommissioningLifecycleError(f"{field} must be at least {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise CommissioningLifecycleError(f"{field} must be a string")
    clean = value.strip()
    if not clean or len(clean) > 128:
        raise CommissioningLifecycleError(f"{field} must contain 1-128 characters")
    return clean


@dataclass(frozen=True)
class CommissioningLifecycleV1:
    epoch: int
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    nonce: str
    revocation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch", _int(self.epoch, "epoch", minimum=1))
        object.__setattr__(
            self,
            "issued_monotonic_ns",
            _int(self.issued_monotonic_ns, "issued_monotonic_ns", minimum=1),
        )
        object.__setattr__(
            self,
            "expires_monotonic_ns",
            _int(self.expires_monotonic_ns, "expires_monotonic_ns", minimum=1),
        )
        object.__setattr__(self, "nonce", _token(self.nonce, "nonce"))
        object.__setattr__(
            self,
            "revocation_id",
            _token(self.revocation_id, "revocation_id"),
        )
        ttl = self.expires_monotonic_ns - self.issued_monotonic_ns
        if ttl <= 0 or ttl > MAX_COMMISSIONING_TTL_NS:
            raise CommissioningLifecycleError(
                "commissioning expiry must follow issue time within 24 hours"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "epoch": self.epoch,
            "issued_monotonic_ns": self.issued_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "nonce": self.nonce,
            "revocation_id": self.revocation_id,
        }

    @classmethod
    def from_mapping(cls, value: object) -> CommissioningLifecycleV1:
        if not isinstance(value, dict) or set(value) != set(cls.__annotations__):
            raise CommissioningLifecycleError("commissioning lifecycle fields are not exact")
        return cls(**value)


@dataclass(frozen=True)
class CommissioningCurrentStateV1:
    epoch: int
    active_nonce: str
    revoked_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch", _int(self.epoch, "current epoch", minimum=1))
        object.__setattr__(self, "active_nonce", _token(self.active_nonce, "active_nonce"))
        if isinstance(self.revoked_ids, (str, bytes)) or not isinstance(
            self.revoked_ids, Iterable
        ):
            raise CommissioningLifecycleError("revoked_ids must be an iterable")
        object.__setattr__(
            self,
            "revoked_ids",
            frozenset(_token(item, "revoked_id") for item in self.revoked_ids),
        )


CommissioningStateProviderV1 = Callable[
    [CommissioningLifecycleV1], CommissioningCurrentStateV1
]


def validate_commissioning_lifecycle(
    lifecycle: CommissioningLifecycleV1,
    *,
    state_provider: CommissioningStateProviderV1,
    now_monotonic_ns: int,
) -> None:
    if not isinstance(lifecycle, CommissioningLifecycleV1):
        raise CommissioningLifecycleError("commissioning lifecycle is missing")
    if not callable(state_provider):
        raise CommissioningLifecycleError("trusted commissioning state provider is missing")
    now = _int(now_monotonic_ns, "now_monotonic_ns", minimum=1)
    if now < lifecycle.issued_monotonic_ns or now >= lifecycle.expires_monotonic_ns:
        raise CommissioningLifecycleError("commissioning lifecycle is not currently valid")
    try:
        current = state_provider(lifecycle)
    except Exception as error:  # noqa: BLE001 - provider failure must fail closed
        raise CommissioningLifecycleError(
            f"trusted commissioning state lookup failed: {error}"
        ) from None
    if not isinstance(current, CommissioningCurrentStateV1):
        raise CommissioningLifecycleError("trusted commissioning state lookup returned no state")
    if lifecycle.epoch != current.epoch:
        raise CommissioningLifecycleError("commissioning epoch is not current")
    if lifecycle.nonce != current.active_nonce:
        raise CommissioningLifecycleError("commissioning nonce is not active")
    if lifecycle.revocation_id in current.revoked_ids:
        raise CommissioningLifecycleError("commissioning record is revoked")


__all__ = [
    "MAX_COMMISSIONING_TTL_NS",
    "CommissioningCurrentStateV1",
    "CommissioningLifecycleError",
    "CommissioningLifecycleV1",
    "CommissioningStateProviderV1",
    "validate_commissioning_lifecycle",
]
