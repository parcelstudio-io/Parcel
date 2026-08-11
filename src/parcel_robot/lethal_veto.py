"""Fail-closed lethal-cell veto predicates (leaf module — import from anywhere).

This module exists to be *safe to import from any layer*. It deliberately has
**no** ``parcel_robot`` imports at all, so pulling it in can never drag in a
package ``__init__`` and can never open an import cycle.

That is not a style preference, it is the whole point. ``waypoints_trigger_lethal_veto``
used to live in :mod:`parcel_robot.core.arbiter`; importing it from
``instructnav/arbiter.py`` ran ``parcel_robot/core/__init__.py``, which reaches
``core.motion_shaping`` -> ``navigation.velocity_shaping`` -> ``navigation/__init__``
-> ``navigation.envs`` -> ``navigation.pipeline``, whose guarded InstructNav
import then observed a half-initialized ``instructnav.arbiter`` and silently set
``_HAS_INSTRUCTNAV = False``. See ``tests/test_import_order_no_cycle.py``.

Keep this module a leaf. If a predicate here needs a project type, it belongs
somewhere else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

__all__ = ["waypoints_trigger_lethal_veto"]


def waypoints_trigger_lethal_veto(
    lethal: Callable[[float, float], bool],
    waypoints: Sequence[tuple[float, float]] | None,
) -> bool:
    """Fail-closed lethal veto for a waypoint list (P0 mixed-lethal harden).

    Empty / missing waypoints do not veto on their own (pose is checked
    separately). **Any** lethal waypoint vetoes — a mixed safe/lethal list
    must not pass (the old ``all()`` rule let mixed goals through).
    """

    if not waypoints:
        return False
    return any(lethal(float(x), float(y)) for x, y in waypoints)
