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
]
