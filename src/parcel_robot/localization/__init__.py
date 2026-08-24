"""Delegated MAP-role localization — the estimator that fills ``PoseProvider``.

``pose.py`` is the localization SEAM and says outright that it is never a
localizer: "A real localizer slots into the ``MAP`` role behind
:class:`PoseProvider` with zero consumer changes."  This package is the first
thing that tries to.  Nothing in the product imports it; it is reached only by
``research/20260823/localization-delegation-bench/`` and by
``tests/test_h7_localization_contract.py``, so the STRATA anti-goal "no
SLAM/EKF in sim (seam only)" is untouched by construction — installing this
package changes no runtime behaviour at all.

Leaves, in dependency order:

``contract.py``
    ``ScanFrame`` in, ``LocalizationUpdate`` out, ``LocalizerProvider`` between
    them.  The update carries ``T_map_odom`` (REP-105's correction transform),
    a 3x3 covariance over ``(x, y, yaw)``, a :class:`~parcel_robot.pose.PoseHealth`,
    and ``jump_m`` — the term ``bridge/timing.py`` has carried as UNMEASURED
    since HW-6.

``gicp_provider.py``
    A scan-to-map matcher delegated to ``small-gicp`` (see the module docstring
    for why it is not ``kiss-icp``).

``global_match.py``
    Card A3 / NAV-CORE fix 4.  The whole-map second-best margin: coarse grid,
    two-finalist refinement, exact yaw sweep by circular shift.  The number
    addendum A4's re-arm path (a) is expressed in, which existed nowhere in the
    product before this card.

``discontinuity.py``
    Card A3.  Addendum A10's six signals, the latch they set, and addendum A4's
    two re-arm paths — the whole-map margin and the ONE-SHOT operator
    pose-reset transaction.  Latched motion is a motion authority, never a
    health level: ``HEALTHY`` + covariance re-arms nothing.

``jump_journal.py``
    Card A3.  ``localization_jump_m`` written down at last, in the exact entry
    shape ``bridge/timing.load_stopping_envelope_record`` consumes.

``pose_adapter.py``
    Composes a ``LocalizerProvider`` (MAP) with ``pose.DriftingOdomProvider``
    (ODOM) into one object that satisfies ``pose.PoseProvider``.  Optionally
    feeds the latch and the jump journal; with neither supplied its behaviour
    is unchanged by A3.
"""
