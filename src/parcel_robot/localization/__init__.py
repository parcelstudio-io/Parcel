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

``pose_adapter.py``
    Composes a ``LocalizerProvider`` (MAP) with ``pose.DriftingOdomProvider``
    (ODOM) into one object that satisfies ``pose.PoseProvider``.
"""
