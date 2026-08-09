"""Deprecated shim for the two embodiment constants this module used to own.

Both constants moved to :class:`parcel_robot.robot_profile.RobotProfile` on
2026-08-07 (Lane A, strata 4+5). They kept their exact values; what changed is
that they are now *fields of a profile* rather than module literals, so an
injected profile can reach them and a half-size robot gets a half-size body.

Reading either name here still works and still returns the Go2 value, but emits
a :class:`DeprecationWarning` naming the replacement. Neither is hard-errored:
both are still imported by modules other lanes own right now (see
``scrum/20260806/task_3/LANE_A_STATUS.md`` for the live importer list). The
hard error lands when that list empties.

Replacements::

    from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
    DEFAULT_ROBOT_PROFILE.footprint_radius_m       # ROBOT_FOOTPRINT_RADIUS_M
    DEFAULT_ROBOT_PROFILE.obstacle_clearance_height_m  # ROBOT_OBSTACLE_HEIGHT_M

...or, better, accept a ``RobotProfile`` and read the field off that.
"""

from __future__ import annotations

import warnings
from typing import Any

#: ``retired name -> (RobotProfile field, migration hint, hard_error)``.
#:
#: ``hard_error`` is the ratchet. A name flips to ``True`` the moment no module
#: outside this file imports it any more; from then on a *new* import is a red
#: build rather than a warning nobody reads. Importer census taken 2026-08-07:
#:
#: * ``ROBOT_FOOTPRINT_RADIUS_M`` — still imported by
#:   ``navigation/pipeline.py``, ``navigation/grid_planner.py`` and
#:   ``navigation/models/__init__.py``, all owned by other lanes right now.
#:   Stays a warning.
#: * ``ROBOT_OBSTACLE_HEIGHT_M`` — zero importers left after Lane A migrated
#:   ``mujoco_lidar``, ``headless_city``, ``sim`` and
#:   ``tests/test_city_orbit_clearance``. Hard error.
RETIRED_CONSTANTS: dict[str, tuple[str, str, bool]] = {
    "ROBOT_FOOTPRINT_RADIUS_M": (
        "footprint_radius_m",
        "read RobotProfile.footprint_radius_m (or SafetyEnvelope.footprint_radius_m)",
        False,
    ),
    "ROBOT_OBSTACLE_HEIGHT_M": (
        "obstacle_clearance_height_m",
        "read RobotProfile.obstacle_clearance_height_m",
        True,
    ),
}

# The two retired names resolve through ``__getattr__`` (PEP 562), so they are
# deliberately absent from the module globals — F822 is expected here.
__all__ = [  # noqa: F822
    "RETIRED_CONSTANTS",
    "ROBOT_FOOTPRINT_RADIUS_M",
    "ROBOT_OBSTACLE_HEIGHT_M",
    "retired_constant_value",
]


def __getattr__(name: str) -> Any:
    """PEP 562 poison: retired constants warn (or hard-error); rest fails."""

    try:
        field_name, hint, hard_error = RETIRED_CONSTANTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    if hard_error:
        raise AttributeError(
            f"parcel_robot.geometry.{name} was removed on 2026-08-07 because no "
            f"module imported it any more; {hint}."
        )
    warnings.warn(
        f"parcel_robot.geometry.{name} is retired; {hint}. "
        "It still returns the Go2 value and will be removed once no lane "
        "imports it (see scrum/20260806/task_3/LANE_A_STATUS.md).",
        DeprecationWarning,
        stacklevel=2,
    )
    from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

    return getattr(DEFAULT_ROBOT_PROFILE, field_name)


def retired_constant_value(name: str) -> Any:
    """Escape hatch for the migration tests: read a retired value, no warning."""

    field_name = RETIRED_CONSTANTS[name][0]
    from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

    return getattr(DEFAULT_ROBOT_PROFILE, field_name)


def __dir__() -> list[str]:
    return sorted({*globals(), *RETIRED_CONSTANTS})
