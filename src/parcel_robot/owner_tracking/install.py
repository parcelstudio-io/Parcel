"""The product installer for the owner tracker — card A8 FOLLOW-COMPOSE.

``RobotRuntime.install_owner_tracker`` was written as a composition root and
then had **no product caller**: the M1 plan's own finding
(``scrum/20260824/task_2/CLAUDE_RESPONSE.md`` addendum A3 — "grep: only a
docstring mention and a comment") and the reason the box-day Follow identity
gate was not runnable at all.  Card A8 gives it one, and this module is the
half that does not belong in ``runtime.py``: read a knob, resolve an encoder,
load a gallery, decide whether anything may be installed.

Three rules, and each is a measured one rather than a preference.

1.  **``off`` builds nothing.**  Not a disabled tracker, not an inert object —
    the runtime's ``_ot2_*`` region is already written so that a ``None``
    tracker makes every seam return its argument as the SAME OBJECT, so an
    ``off`` build is byte-identical to a runtime that never had this card.

2.  **A refusal is loud and additive.**  A malformed knob, a missing gallery,
    an encoder that did not resolve: each returns a :class:`OwnerTrackerBuild`
    with ``tracker=None`` and a reason a human can read.  Nothing else in the
    runtime becomes less safe — the panel STOP, the reactive gate and the
    follow controller are exactly what they were, and the owner keeps a
    PERSON's clearance because ``_ot2_apply_owner_identity`` was written to
    overwrite identity and never presence.

3.  **An uncalibrated gallery may not be installed by default.**  P1-C
    measured the cost: against an uncalibrated boundary the stranger scored
    0.9295 on the owner's own gallery, which is above the 0.65 floor the
    reactive gate reads.  ``require_calibrated`` therefore defaults True, and
    turning it off is an operator writing it down.

WHERE THE KNOB LIVES, AND WHY IT LIVES THERE
--------------------------------------------
``owner_follow.tracker``.  It is nested inside a section the SHA-locked base
already defines and is popped and validated at the read site, which is the
shape ``owner_follow.prediction`` and ``owner_follow.yield_aside`` already
have in that same section.  ``config.py`` sits exactly on the DEC-0 1,000-line
ceiling and may not grow, so no entry was added to
``config.OVERLAY_INTRODUCIBLE_KEYS``; the consequence is stated rather than
hidden — see ``scrum/20260824/task_2/A8_STATUS.md`` §"The knob".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from parcel_robot.owner_tracking.embedder import resolve_embed_fn
from parcel_robot.owner_tracking.gallery import (
    AppearanceGallery,
    AppearanceGalleryError,
    default_gallery_path,
    load_gallery,
)
from parcel_robot.owner_tracking.tracker import OwnerTracker

#: Build nothing.  The shipped default, because Follow's ENABLE is gated on the
#: box-day identity study and no camera identity evidence exists on this host.
TRACKER_MODE_OFF = "off"
#: Install ``OwnerTracker`` over an enrolled appearance gallery.
TRACKER_MODE_GALLERY = "gallery"

TRACKER_MODES: frozenset[str] = frozenset({TRACKER_MODE_OFF, TRACKER_MODE_GALLERY})

_KNOWN_KEYS: frozenset[str] = frozenset({"mode", "gallery_path", "require_calibrated"})


@dataclass(frozen=True, slots=True)
class OwnerTrackerSettings:
    """The validated ``owner_follow.tracker`` block.  Absent == ``off``."""

    mode: str = TRACKER_MODE_OFF
    #: Empty means :func:`owner_tracking.gallery.default_gallery_path`, which is
    #: where ``tools/enroll_owner_appearance.py`` writes.  One spelling of
    #: "where the enrollment went", not two.
    gallery_path: str = ""
    require_calibrated: bool = True

    def __post_init__(self) -> None:
        if self.mode not in TRACKER_MODES:
            raise ValueError(
                f"owner_follow.tracker.mode must be one of {', '.join(sorted(TRACKER_MODES))}, "
                f"got {self.mode!r}"
            )
        if not isinstance(self.gallery_path, str):
            raise TypeError("owner_follow.tracker.gallery_path must be a string")
        if not isinstance(self.require_calibrated, bool):
            raise TypeError("owner_follow.tracker.require_calibrated must be a boolean")

    @classmethod
    def from_mapping(cls, raw: object) -> OwnerTrackerSettings:
        """Parse the block, refusing an unknown key BY NAME.

        The typo guard lives here because ``config.check_overlay_keys`` stops
        descending at a section it admits: a spelling check that is not at the
        read site is the inert kind this repo has already been bitten by twice
        (``minimum_confidenc``, ROAM-1 finding 6).
        """

        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise TypeError("owner_follow.tracker must be a mapping")
        unknown = sorted(set(raw) - _KNOWN_KEYS)
        if unknown:
            raise ValueError(
                f"unknown owner_follow.tracker settings: {unknown}; "
                f"known keys are {sorted(_KNOWN_KEYS)}"
            )
        values: dict[str, Any] = {}
        if "mode" in raw:
            mode = raw["mode"]
            # YAML 1.1, which `yaml.safe_load` implements, resolves a bare
            # ``off`` to the BOOLEAN False — so the most natural spelling of
            # this knob (``mode: off``) never reaches this method as a string.
            # Refusing it would be a fail-closed trap that reads as a bug, so
            # False is accepted as the mode it obviously means. True is not:
            # there is no "on" mode, and guessing WHICH tracker an operator
            # meant is exactly the guess this module exists to refuse.
            if mode is False:
                mode = TRACKER_MODE_OFF
            if not isinstance(mode, str):
                raise TypeError(
                    "owner_follow.tracker.mode must be one of "
                    f"{', '.join(sorted(TRACKER_MODES))} (quote it: YAML reads a bare "
                    "'off'/'on'/'no' as a boolean)"
                )
            values["mode"] = mode.strip().lower()
        if "gallery_path" in raw:
            values["gallery_path"] = raw["gallery_path"]
        if "require_calibrated" in raw:
            values["require_calibrated"] = raw["require_calibrated"]
        return cls(**values)


@dataclass(frozen=True, slots=True)
class OwnerTrackerBuild:
    """What the installer resolved, and — when nothing — why not."""

    tracker: OwnerTracker | None
    detail: str
    gallery_threshold: float = 0.0
    #: True when the knob asked for a tracker and none could be built.  The
    #: caller emits at ``error`` for this and at ``info`` otherwise, so an
    #: operator who turned the knob on learns that it did not take.
    refused: bool = False

    @property
    def installed(self) -> bool:
        return self.tracker is not None


def _resolve_gallery(settings: OwnerTrackerSettings) -> tuple[AppearanceGallery | None, str]:
    path = settings.gallery_path.strip() or str(default_gallery_path())
    try:
        gallery = load_gallery(path)
    except (AppearanceGalleryError, OSError, ValueError) as error:
        return None, f"gallery at {path} is unreadable: {error}"
    if gallery is None:
        return None, f"no enrolled gallery at {path} (run tools/enroll_owner_appearance.py)"
    if settings.require_calibrated and not gallery.calibrated:
        return None, (
            f"gallery at {path} is UNCALIBRATED and require_calibrated is on — P1-C measured "
            "the stranger at 0.9295 against an uncalibrated boundary, above the gate's floor"
        )
    return gallery, path


def build_owner_tracker(
    settings: OwnerTrackerSettings,
    *,
    ingress: Any = None,
    embed_fn: Any = None,
) -> OwnerTrackerBuild:
    """Resolve ``settings`` into a tracker, or into the reason there is none.

    Never raises.  Every failure is a build with ``tracker=None`` and a
    sentence: an installer that throws into ``RobotRuntime.__init__`` would
    make a mis-typed gallery path the difference between a robot that boots
    without an identity and a robot that does not boot.
    """

    if settings.mode == TRACKER_MODE_OFF:
        return OwnerTrackerBuild(None, "off (owner_follow.tracker.mode=off)")
    encoder = resolve_embed_fn(ingress=ingress, embed_fn=embed_fn)
    if not encoder.available:
        return OwnerTrackerBuild(
            None,
            f"unavailable: no encoder resolved ({encoder.source}: {encoder.reason})",
            refused=True,
        )
    gallery, detail = _resolve_gallery(settings)
    if gallery is None:
        return OwnerTrackerBuild(None, f"unavailable: {detail}", refused=True)
    if encoder.model and gallery.model and encoder.model != gallery.model:
        return OwnerTrackerBuild(
            None,
            (
                f"unavailable: gallery was enrolled on {gallery.model!r} and this venue's "
                f"encoder is {encoder.model!r} — a cosine across two encoders is not a cosine"
            ),
            refused=True,
        )
    tracker = OwnerTracker(gallery=gallery, embed_fn=encoder.embed_fn)
    return OwnerTrackerBuild(
        tracker,
        (
            f"gallery ({detail}, model={gallery.model!r}, crops={gallery.crops}, "
            f"threshold={gallery.threshold:.4f}, calibrated={gallery.calibrated}, "
            f"encoder={encoder.source})"
        ),
        gallery_threshold=float(gallery.threshold),
    )


__all__ = [
    "TRACKER_MODES",
    "TRACKER_MODE_GALLERY",
    "TRACKER_MODE_OFF",
    "OwnerTrackerBuild",
    "OwnerTrackerSettings",
    "build_owner_tracker",
]
