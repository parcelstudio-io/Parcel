"""The allowlisted, versioned action catalog.

HLD §8.8 requires "an allowlisted, versioned posture/gesture capability
catalog with bounded parameters/duration, base-stationary preconditions,
cancellation, and completion feedback", and — three paragraphs later — that
"until that action path and each capability profile are implemented and
physically commissioned, physical pose, trajectory, gesture, and decorative
expression remain unsupported even if their simulator versions exist."

Both sentences are implemented here, and the second one is the reason this
file is short: the V1 catalog admits **one** action, bounded base velocity,
and every posture/gesture/trajectory/expression name is on an explicit refusal
list with the reason.  The list is not decoration — an allowlist whose refusal
side is empty has never been shown to refuse anything, so
``tests/test_m1_0_gateway.py`` drives every name in it through
:meth:`ActionCatalogV1.admit` and pins :data:`CATALOG_DIGEST_V1`, which changes
the moment a new action is added.

``GatewayActionV1`` does not exist in the frozen V1 wire contract, so no client
can *ask* for a catalog action today; the catalog is the gateway-side gate that
will still be here when the message is added, and the refusal list is what
keeps "not implemented" from quietly meaning "not checked".
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .limits import GovernorLimitsV1

CATALOG_VERSION_V1 = 1

#: The one action any V1 client can cause: a bounded base velocity setpoint,
#: valid for at most one command TTL.
BASE_VELOCITY_ACTION = "base_velocity"


class ActionNotAdmittedError(ValueError):
    """Raised when an action name is not in the versioned allowlist."""


@dataclass(frozen=True)
class ActionParameterBoundV1:
    name: str
    unit: str
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        for name in ("minimum", "maximum"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"parameter bound {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"parameter bound {name} must be finite")
        if self.minimum > self.maximum:
            raise ValueError("parameter bound minimum exceeds maximum")

    def clamp(self, value: float) -> float:
        return min(self.maximum, max(self.minimum, value))


@dataclass(frozen=True)
class ActionSpecV1:
    name: str
    requires_base_stationary: bool
    excludes_base_motion: bool
    max_duration_s: float
    parameters: tuple[ActionParameterBoundV1, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("an action spec needs a name")
        if isinstance(self.max_duration_s, bool) or not isinstance(
            self.max_duration_s, (int, float)
        ):
            raise TypeError("max_duration_s must be numeric")
        if not math.isfinite(float(self.max_duration_s)) or self.max_duration_s <= 0.0:
            raise ValueError("max_duration_s must be finite and positive")
        if len({bound.name for bound in self.parameters}) != len(self.parameters):
            raise ValueError("action parameter names must be unique")

    def structure(self) -> dict[str, object]:
        """The version-bearing shape, without the regime's numbers in it.

        The digest is over structure only so that commissioning a *slower*
        regime does not read as "the capability set changed" — the numbers are
        pinned separately against ``bridge/timing.py`` by the suite.
        """

        return {
            "name": self.name,
            "requires_base_stationary": self.requires_base_stationary,
            "excludes_base_motion": self.excludes_base_motion,
            "parameters": [bound.name for bound in self.parameters],
        }


#: Names that exist as concepts (in the HLD, in the simulator, or in the
#: vendor's own high-level API) and are refused here until each one has been
#: implemented behind ``GatewayActionV1`` and physically commissioned.
UNSUPPORTED_ACTIONS_V1: tuple[tuple[str, str], ...] = (
    ("posture", "HLD 8.8: physical pose unsupported until commissioned"),
    ("pose", "HLD 8.8: physical pose unsupported until commissioned"),
    ("gesture", "HLD 8.8: gesture unsupported until commissioned"),
    ("trajectory", "HLD 8.8: trajectory unsupported until commissioned"),
    ("expression", "HLD 8.8: decorative expression unsupported until commissioned"),
    ("joint_command", "HLD 8.8 / FABLE_VERDICT X12: low-level joint control is out of scope"),
    ("stand_up", "vendor high-level name; needs a commissioned capability profile"),
    ("sit", "vendor high-level name; needs a commissioned capability profile"),
    ("hello", "vendor high-level name; needs a commissioned capability profile"),
    ("dance", "vendor high-level name; needs a commissioned capability profile"),
    ("front_flip", "vendor high-level name; refused permanently inside the first ODD"),
    ("jump", "vendor high-level name; refused permanently inside the first ODD"),
)


class ActionCatalogV1:
    """The versioned allowlist. Anything not in it is refused, by name."""

    def __init__(self, limits: GovernorLimitsV1) -> None:
        speed = limits.regime.max_linear_mps
        yaw = limits.regime.max_yaw_rad_s
        self._specs: dict[str, ActionSpecV1] = {
            BASE_VELOCITY_ACTION: ActionSpecV1(
                name=BASE_VELOCITY_ACTION,
                requires_base_stationary=False,
                excludes_base_motion=False,
                max_duration_s=limits.max_local_ttl_s,
                parameters=(
                    ActionParameterBoundV1("vx_mps", "m/s", -speed, speed),
                    ActionParameterBoundV1("vy_mps", "m/s", -speed, speed),
                    ActionParameterBoundV1("vyaw_rad_s", "rad/s", -yaw, yaw),
                ),
            )
        }
        self._refusals = dict(UNSUPPORTED_ACTIONS_V1)

    @property
    def version(self) -> int:
        return CATALOG_VERSION_V1

    @property
    def admitted_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def admit(self, name: str) -> ActionSpecV1:
        spec = self._specs.get(name)
        if spec is not None:
            return spec
        reason = self._refusals.get(name, "not in the versioned gateway action catalog")
        raise ActionNotAdmittedError(f"action {name!r} refused: {reason}")

    def digest(self) -> str:
        payload = {
            "catalog_version": CATALOG_VERSION_V1,
            "admitted": [self._specs[name].structure() for name in sorted(self._specs)],
            "refused": [name for name, _reason in UNSUPPORTED_ACTIONS_V1],
        }
        rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


#: The pinned digest of the V1 catalog structure.  Adding, renaming or
#: un-refusing an action changes it, and the suite fails until the change is
#: deliberate.
CATALOG_DIGEST_V1 = "6de8ae1d840b5e51c57c92a6913feb715c45477069c6184ca93d6e07c037c53b"
