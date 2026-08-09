"""Re-export of the embodiment authority triple at its planned import path.

The plan (``docs/STRATA_GENERALIZATION_PLAN.md``, strata 4+5) places the
authority triple at ``parcel_robot.core.authority``. The implementation
actually lives one level up, in :mod:`parcel_robot.authority`, for one
mechanical reason: importing *anything* under ``parcel_robot.core`` executes
``parcel_robot/core/__init__.py``, which imports
``parcel_robot.navigation.velocity_shaping`` and therefore the whole
``parcel_robot.navigation`` package (``navigation/__init__`` -> ``envs`` ->
``pipeline``). The authority's own consumers — ``instructnav/scoring.py``,
``navigation/collision.py``, ``navigation/approach.py`` — are *below* the
pipeline in that graph, so importing them through ``parcel_robot.core`` is a
circular import (measured: ``ImportError: cannot import name 'NEXT_TO_BAND_M'
from partially initialized module 'parcel_robot.instructnav.scoring'``).

The authority has to sit low in the import graph, which is the whole point of
"one authority, low in the import graph". So:

* **Low-level consumers import** :mod:`parcel_robot.authority`.
* Anything that already lives inside or above ``parcel_robot.core`` may import
  this module instead; it is the same objects, not copies.

Collapsing the two back into one file is a one-line change once
``parcel_robot/core/__init__.py`` stops eagerly importing the navigation
package — recorded as a handoff note in
``scrum/20260806/task_3/LANE_A_STATUS.md`` (that file is owned by another lane
right now).
"""

from __future__ import annotations

from parcel_robot.authority import (
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_SPEED_REGIME,
    DEFAULT_STAND_OFF_ENVELOPE,
    GRAVITY_MPS2,
    HUMAN_BUCKET,
    PERSON_SOCIAL_ZONE_M,
    REGIME_NAMES,
    SCALING_BUCKETS,
    FieldMeta,
    RegimeLimits,
    SafetyEnvelope,
    SpeedRegime,
    StandOffEnvelope,
    arbitrate_limits,
)

__all__ = [
    "DEFAULT_SAFETY_ENVELOPE",
    "DEFAULT_SPEED_REGIME",
    "DEFAULT_STAND_OFF_ENVELOPE",
    "GRAVITY_MPS2",
    "HUMAN_BUCKET",
    "PERSON_SOCIAL_ZONE_M",
    "REGIME_NAMES",
    "SCALING_BUCKETS",
    "FieldMeta",
    "RegimeLimits",
    "SafetyEnvelope",
    "SpeedRegime",
    "StandOffEnvelope",
    "arbitrate_limits",
]
