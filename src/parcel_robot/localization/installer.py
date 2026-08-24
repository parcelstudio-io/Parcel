"""Compose A3's localization pieces into one installable bundle (card A4).

A3 (``scrum/20260824/task_2/A3_STATUS.md``) shipped the discontinuity latch,
the whole-map relocalization margin, the jump journal and the operator re-arm
transaction — and deliberately shipped **no runtime installer**: nothing in the
product constructed a ``LocalizerProvider``, so every one of those pieces was
inert.  This module is that installer, and it is a pure function so the
composition can be tested without a runtime.

The default is unchanged behaviour.  A deployment that does not commission a
localizer gets :data:`NOT_COMMISSIONED` back and keeps the truth pose provider
it already had; every A3 flag keeps the default A3 shipped
(``require_relocalization_margin`` OFF, latch enabled once a localizer exists,
``LatchBounds`` untouched).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from parcel_robot.localization.discontinuity import ArmingLatch, LatchBounds
from parcel_robot.localization.gicp_provider import ScanMatchConfig, ScanMatchLocalizer
from parcel_robot.localization.global_match import WholeMapMatcher
from parcel_robot.localization.jump_journal import LocalizationJumpJournal
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider

#: Provider names this installer knows.  Anything else raises rather than
#: silently falling back — a mistyped profile must not ship truth pose.
KNOWN_PROVIDERS = frozenset({"scan_match"})

#: Values that mean "this deployment commissioned no localizer".
UNCOMMISSIONED = frozenset({"", "none", "truth", "truth_pose"})


@dataclass(frozen=True, slots=True)
class LocalizationInstallation:
    """What the runtime installs, and why it is (or is not) there."""

    provider: LocalizedPoseProvider | None = None
    latch: ArmingLatch | None = None
    journal: LocalizationJumpJournal | None = None
    matcher: WholeMapMatcher | None = None
    reason: str = "not_commissioned"

    @property
    def installed(self) -> bool:
        return self.provider is not None

    @property
    def motion_latched(self) -> bool:
        """True only when a latch exists AND has fired.  Absent latch is False."""

        return self.latch is not None and self.latch.latched


#: The shipping default: nothing commissioned, nothing installed.
NOT_COMMISSIONED = LocalizationInstallation()


def install_localization(
    config: Mapping[str, Any] | None,
    *,
    odom_provider: Any,
    template_source: Any = None,
) -> LocalizationInstallation:
    """Build the localization bundle a ``navigation.localization`` section asks for.

    ``odom_provider`` is the pose source the localizer corrects — in the
    runtime that is the provider already installed at the seam, so ODOM keeps
    receiving exactly what it received before and only MAP becomes estimated.

    ``template_source`` is the whole-map matcher's range-template source.  The
    product has no map source that can answer ``free``/``template`` yet (A3
    exercised the matcher against a harness room), so the matcher is built only
    when one is supplied; otherwise it is ``None`` and the latch keeps its
    other five triggers.  That gap is named in ``A4_STATUS.md``, not papered
    over with a stub map.
    """

    if not isinstance(config, Mapping):
        return NOT_COMMISSIONED
    name = str(config.get("provider", "") or "").strip().lower()
    if name in UNCOMMISSIONED:
        return NOT_COMMISSIONED
    if name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"unknown localization provider {name!r}; known providers: {sorted(KNOWN_PROVIDERS)}"
        )

    scan_config = ScanMatchConfig(
        require_relocalization_margin=bool(config.get("require_relocalization_margin", False)),
        relocalize_margin_min=float(config.get("relocalize_margin_min", 0.25)),
    )
    journal = LocalizationJumpJournal(host=str(config.get("host", "") or ""))
    bounds = LatchBounds(
        jump_bound_m=float(config.get("jump_bound_m", LatchBounds().jump_bound_m)),
        margin_min=float(config.get("relocalize_margin_min", LatchBounds().margin_min)),
    )
    holder: dict[str, LocalizedPoseProvider] = {}
    latch = ArmingLatch(
        bounds=bounds,
        enabled=bool(config.get("latch", True)),
        # The re-arm and the estimator move atomically: A3 requires the
        # re-anchor to land on the same provider whose latch is clearing.
        reanchor=lambda pose: holder["provider"].reanchor(pose),
    )
    provider = LocalizedPoseProvider(
        ScanMatchLocalizer(scan_config),
        odom_provider,
        map_covariance_floor_m2=float(config.get("map_covariance_floor_m2", 0.0)),
        arming_latch=latch,
        jump_journal=journal,
    )
    holder["provider"] = provider
    matcher = None
    raw_bounds = config.get("bounds")
    if template_source is not None and raw_bounds is not None:
        values = tuple(float(item) for item in raw_bounds)
        if len(values) != 4:
            raise ValueError("localization bounds must be (min_x, min_y, max_x, max_y)")
        matcher = WholeMapMatcher(template_source, bounds=values)
    return LocalizationInstallation(
        provider=provider,
        latch=latch,
        journal=journal,
        matcher=matcher,
        reason="commissioned" if matcher is not None else "commissioned_without_map_templates",
    )


__all__ = [
    "KNOWN_PROVIDERS",
    "NOT_COMMISSIONED",
    "UNCOMMISSIONED",
    "LocalizationInstallation",
    "install_localization",
]
