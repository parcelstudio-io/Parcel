"""Which person is you — person pixels to a measured owner identity.

Card P1-C. Four pieces, in the order the data moves:

``gallery``       the owner's enrolled crops on disk, with the operating point
                  the enrollment measured, mode 0600, outside the repository.
``embedder``      where the ``embed_fn`` comes from: P1-B's ingress seam first,
                  ``instructnav.siglip2_onnx`` second, ``None`` third.
``tracker``       C-1 detection frames → per-person appearance tracks → an owner
                  claim whose confidence is a cosine and not 1.0.
``synthetic_clip`` a two-person clip with a crossing and an occlusion, rendered
                  from a readable script, because this host has no camera.

The output crosses into the rest of the stack through
``uwb.fusion.OwnerFusionStub``: :meth:`~.tracker.PixelOwnerTrack.as_fusion_input`
carries the identity, :meth:`~.tracker.PixelOwnerTrack.as_detection_msg` carries
the pose-bearing observation. Nothing in this package writes to the owner's
memory store, and nothing in it opens a camera.
"""

from __future__ import annotations

from parcel_robot.owner_tracking.embedder import (
    EmbedderResolution,
    default_weights_dir,
    resolve_embed_fn,
    vision_model_sha256,
)
from parcel_robot.owner_tracking.gallery import (
    GALLERY_NAME,
    GALLERY_SCHEMA,
    MIN_CROPS,
    AppearanceGallery,
    AppearanceGalleryError,
    build_gallery,
    cosine,
    default_gallery_path,
    load_gallery,
    save_gallery,
    self_consistency,
)
from parcel_robot.owner_tracking.tracker import (
    STATE_AMBIGUOUS,
    STATE_CONFIRMED,
    STATE_LOST,
    STATE_SEARCHING,
    OwnerTracker,
    OwnerTrackerConfig,
    OwnerTrackerUpdate,
    PersonObservation,
    PixelOwnerTrack,
    is_person_label,
)

#: What this package does NOT establish, kept next to the code that could be
#: mistaken for establishing it (the house convention, cf. ``uwb.fusion``).
DOES_NOT_PROVE = (
    "Measured on a SYNTHESIZED clip: recall and separation on real people are unmeasured.",
    (
        "The gallery threshold is derived from the enrollment's own agreement "
        "unless the enroller was shown a negative; see gallery.calibrated."
    ),
    (
        "SigLIP-2 is an image-text encoder, not a person-verification network; "
        "its absolute cosines are not a re-ID operating point until measured "
        "on a camera."
    ),
    "Nothing here is wired into runtime.py — the runtime seam is a P1-C handoff.",
)

__all__ = [
    "DOES_NOT_PROVE",
    "GALLERY_NAME",
    "GALLERY_SCHEMA",
    "MIN_CROPS",
    "STATE_AMBIGUOUS",
    "STATE_CONFIRMED",
    "STATE_LOST",
    "STATE_SEARCHING",
    "AppearanceGallery",
    "AppearanceGalleryError",
    "EmbedderResolution",
    "OwnerTracker",
    "OwnerTrackerConfig",
    "OwnerTrackerUpdate",
    "PersonObservation",
    "PixelOwnerTrack",
    "build_gallery",
    "cosine",
    "default_gallery_path",
    "default_weights_dir",
    "is_person_label",
    "load_gallery",
    "resolve_embed_fn",
    "save_gallery",
    "self_consistency",
    "vision_model_sha256",
]
