#!/usr/bin/env python
"""Enroll the owner's appearance — the second owner action that turns P1-C on.

    # the ten-second live capture (OWNER-GATED: needs a camera on this host)
    tools/enroll_owner_appearance.py --camera 0 --seconds 10 --negative-camera-pass

    # from frames already on disk (a phone video exported to PNGs, a bag dump)
    tools/enroll_owner_appearance.py --frames owner/*.png --negative-frames housemate/*.png

    # from the P1-C synthetic clip, which is how CI exercises this file
    tools/enroll_owner_appearance.py --clip tests/data/p1c_two_person_clip.json \
        --clip-person owner --clip-frames 0-5 --clip-negative other --out /tmp/g.json

    tools/enroll_owner_appearance.py --verify        # re-check what is on disk
    tools/enroll_owner_appearance.py --show          # where is it, is it sane

WHAT IT WRITES, AND WHERE IT DOES NOT
-------------------------------------
One JSON file, mode 0600, **outside the repository**, beside the realtime config
— exactly where ``tools/enroll_owner_voice.py`` puts the voice profile, and for
the same reasons. It holds L2-normalized crop embeddings, the name of the
encoder that produced them, and the operating point this enrollment measured. It
holds no pixels, it is never committed, and ``--out`` refuses a path inside the
repo so it cannot become one by a slip of the shell.

It does **not** touch ``parcel_memory.sqlite3``. Card R27's isolation rule says
the owner's store is never opened read-write by a harness, and an enrollment is
precisely the sort of thing that would want to write a row there.

WHY IT ASKS FOR SOMEBODY WHO IS *NOT* YOU
------------------------------------------
This is the part worth reading before you run it. SigLIP-2 is an image↔text
encoder, not a person-verification network. Measured on the P1-C fixture with
the real fp16 weights: the owner's own crops agree with each other at 0.9903,
and a **different person in the same room scores 0.9280 against them**. The gap
is real but it is 0.06 wide, and it sits at an absolute value no constant in
this repository could have guessed.

So an enrollment that has only ever seen the owner cannot know where the
boundary goes. It falls back to "the owner's agreement minus a declared slack",
which lands at 0.9103 — and that floor was **measured admitting the stranger on
every frame where the owner was occluded**. Showing the enroller one non-owner
puts the threshold in the middle of a measured gap (0.9591) instead, and the
same clip then produces zero false claims.

(All four numbers are from one measured run — P1C_STATUS.md §3. They wander by
about 2e-4 run to run because fp16 CUDA is not deterministic, which is also why
re-enrolling the same crops does not reproduce the same file byte for byte.)

Hence: negatives are requested by default, refused-without is an explicit
``--allow-uncalibrated``, and the resulting gallery carries ``calibrated:
false`` so every consumer can see which kind it is.

WHAT COUNTS AS ENOUGH
---------------------
:data:`~parcel_robot.owner_tracking.gallery.MIN_CROPS` crops of the owner, from
frames that are not all the same instant, plus at least one non-owner crop for
the calibration. The enroller refuses an enrollment whose own crops do not agree
with each other, and refuses one whose owner does not out-score the negative —
both with the numbers printed, because a refusal without its numbers is
indistinguishable from a bug.

RE-ENROLLMENT
-------------
Overwrites cleanly and atomically. There is no merge, on purpose: averaging
today's jacket into a gallery recorded in a different room is how an operating
point drifts without anybody choosing to move it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - script entry
    sys.path.insert(0, str(REPO_ROOT / "src"))

from parcel_robot.owner_tracking.embedder import (
    PROVIDER_ENV,
    SIGLIP2_ENABLE_ENV,
    resolve_embed_fn,
    vision_model_sha256,
)
from parcel_robot.owner_tracking.gallery import (
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

#: Exit codes. 0 success, 2 refusal-with-numbers, 3 nothing to do.
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_ABSENT = 3


class EnrollmentRefusal(RuntimeError):
    """A refusal the owner is meant to read, with the numbers already in it."""


# ----------------------------------------------------------------- crop sources
def _load_image(path: Path) -> Any:
    """One image file → an ``(H, W, 3)`` uint8 array. PNG/JPEG via imageio or PIL."""

    import numpy as np

    for loader in ("imageio.v3", "PIL.Image"):
        try:
            if loader == "imageio.v3":
                import imageio.v3 as iio

                return np.asarray(iio.imread(path))[:, :, :3]
            from PIL import Image

            with Image.open(path) as handle:
                return np.asarray(handle.convert("RGB"))
        except ImportError:
            continue
    raise EnrollmentRefusal(
        f"cannot read {path}: neither imageio nor Pillow is installed in this "
        "interpreter. Install one, or enroll from --clip."
    )


def _parse_range(text: str) -> list[int]:
    """``"0-5"`` or ``"0,2,4"`` → a list of frame indices."""

    out: list[int] = []
    for chunk in str(text).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(chunk))
    return out


def crops_from_frames(paths: list[Path], *, box: tuple[int, int, int, int] | None) -> list[Any]:
    """Whole frames, or a fixed box out of each. No detector involved."""

    crops = []
    for path in paths:
        image = _load_image(path)
        if box is not None:
            u0, v0, u1, v1 = box
            image = image[v0:v1, u0:u1]
        if getattr(image, "size", 0) == 0:
            raise EnrollmentRefusal(f"{path} produced an empty crop with box {box}")
        crops.append(image)
    return crops


def crops_from_clip(clip: Path, person: str, indices: list[int]) -> list[Any]:
    """The P1-C synthetic clip. This is the path CI takes; there is no camera here."""

    from parcel_robot.owner_tracking.synthetic_clip import ClipScript, crop_for

    script = ClipScript.load(clip)
    crops = []
    for index in indices:
        crop = crop_for(script, index, person)
        if crop is None:
            raise EnrollmentRefusal(
                f"clip frame {index} has no visible crop for {person!r} — pick frames "
                "where the person is actually in shot"
            )
        crops.append(crop)
    return crops


def crops_from_camera(device: str, seconds: float, rate_hz: float) -> list[Any]:
    """OWNER-GATED. Ten seconds of frames off a UVC device.

    This host has no camera attached, so this path has never been executed. It
    is written, it is reachable, and it refuses with the reason rather than
    pretending — which is the honest state to leave an owner-gated path in.
    """

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as error:
        raise EnrollmentRefusal(
            f"live capture needs opencv-python ({error}). Either install it, or "
            "export frames and use --frames."
        ) from None
    capture = cv2.VideoCapture(int(device) if str(device).isdigit() else device)
    if not capture.isOpened():
        raise EnrollmentRefusal(
            f"no camera at {device!r}. This host had none attached when P1-C was "
            "written; plug in the D455 or any UVC webcam and re-run."
        )
    import time

    crops: list[Any] = []
    period = 1.0 / max(0.5, rate_hz)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            ok, frame = capture.read()
            if ok and frame is not None:
                crops.append(frame[:, :, ::-1])  # BGR -> RGB
            time.sleep(period)
    finally:
        capture.release()
    if not crops:
        raise EnrollmentRefusal(f"camera {device!r} opened but delivered no frames")
    return crops


# --------------------------------------------------------------------- enroll
def enroll(
    owner_crops: list[Any],
    negative_crops: list[Any],
    *,
    owner_id: str,
    allow_uncalibrated: bool,
    embed_fn: Any = None,
    model: str = "",
    provider: str = "",
    model_sha256: str = "",
) -> tuple[AppearanceGallery, dict[str, Any]]:
    """Embed, check the crops agree, check the owner beats the negative, build.

    Returns the gallery and a report dict of every number that went into the
    decision, so the caller can print them whether it accepted or refused.
    """

    if len(owner_crops) < MIN_CROPS:
        raise EnrollmentRefusal(
            f"{len(owner_crops)} owner crops is not an enrollment: "
            f"{MIN_CROPS} is the minimum, because with fewer than that one bad "
            "sample is a fifth of the identity"
        )
    if embed_fn is None:
        resolution = resolve_embed_fn()
        if not resolution.available:
            raise EnrollmentRefusal(
                f"no image encoder available ({resolution.reason}). Set "
                f"{SIGLIP2_ENABLE_ENV}=1, fetch the weights with "
                f"scripts/fetch_siglip2.sh, and optionally pin {PROVIDER_ENV}=cuda_fp16."
            )
        embed_fn = resolution.embed_fn
        model = model or resolution.model
        provider = provider or resolution.provider
        model_sha256 = model_sha256 or vision_model_sha256()
    if not model:
        raise EnrollmentRefusal(
            "refusing to write a gallery that does not name its encoder: a cosine "
            "threshold is only meaningful inside one embedding space"
        )
    owner_vectors = [tuple(float(v) for v in embed_fn(crop)) for crop in owner_crops]
    negative_vectors = [tuple(float(v) for v in embed_fn(crop)) for crop in negative_crops]
    consistency = self_consistency(owner_vectors)
    report: dict[str, Any] = {
        "owner_crops": len(owner_vectors),
        "negative_crops": len(negative_vectors),
        "model": model,
        "provider": provider,
        "leave_one_out_min": round(consistency, 6),
        "per_crop_leave_one_out": [
            round(
                max(cosine(vec, other) for j, other in enumerate(owner_vectors) if j != i),
                6,
            )
            for i, vec in enumerate(owner_vectors)
        ],
    }
    outliers = [
        index
        for index, score in enumerate(report["per_crop_leave_one_out"])
        if score < consistency + 1e-12 and score < 0.5
    ]
    if len(outliers) >= 2:
        raise EnrollmentRefusal(
            f"these crops are not all the same person: leave-one-out scores "
            f"{report['per_crop_leave_one_out']}. Re-record; an enrollment that "
            "disagrees with itself produces verdicts that are quietly wrong."
        )
    if negative_vectors:
        report["negative_reference"] = round(
            max(max(cosine(n, v) for v in owner_vectors) for n in negative_vectors), 6
        )
    elif not allow_uncalibrated:
        raise EnrollmentRefusal(
            "no negative crops were supplied. Without one this enrollment cannot "
            "measure where the boundary between you and somebody else goes; it can "
            "only guess, and the guess was measured admitting a stranger. Pass "
            "--negative-frames / --clip-negative, or --allow-uncalibrated if you "
            "have read why that is worse."
        )
    gallery = build_gallery(
        owner_vectors,
        owner_id=owner_id,
        model=model,
        provider=provider,
        model_sha256=model_sha256,
        negatives=negative_vectors or None,
    )
    report["threshold"] = round(gallery.threshold, 6)
    report["calibrated"] = gallery.calibrated
    report["dim"] = gallery.dim
    return gallery, report


def refuse_repo_path(path: Path) -> None:
    """``--out`` may not point inside the checkout. The voice enroller's rule."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return
    raise EnrollmentRefusal(
        f"refusing to write the gallery to {resolved}: that is inside the "
        f"repository ({REPO_ROOT}). It describes a person's appearance and it "
        "must not become a commit."
    )


# ----------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enroll_owner_appearance.py",
        description="Enroll the owner's appearance for pixel re-identification (card P1-C).",
    )
    source = parser.add_argument_group("where the owner's crops come from")
    source.add_argument("--frames", nargs="+", type=Path, help="image files of the owner")
    source.add_argument("--camera", help="UVC device index or path (OWNER-GATED: needs a camera)")
    source.add_argument("--seconds", type=float, default=10.0, help="live capture length")
    source.add_argument("--rate-hz", type=float, default=2.0, help="live capture rate")
    source.add_argument("--clip", type=Path, help="a P1-C clip script to enroll from")
    source.add_argument("--clip-person", default="owner", help="which person in the clip")
    source.add_argument("--clip-frames", default="0-5", help="frame indices, e.g. 0-5 or 0,2,4")
    source.add_argument(
        "--box", help="fixed crop box u0,v0,u1,v1 applied to every --frames image"
    )
    negatives = parser.add_argument_group("somebody who is NOT the owner (read the docstring)")
    negatives.add_argument("--negative-frames", nargs="*", type=Path, default=[])
    negatives.add_argument("--clip-negative", help="which person in the clip is the negative")
    negatives.add_argument("--clip-negative-frames", default="0-5")
    negatives.add_argument(
        "--allow-uncalibrated",
        action="store_true",
        help="write a gallery whose boundary is derived, not measured. Worse; see --help.",
    )
    parser.add_argument("--owner-id", default="owner-1")
    parser.add_argument("--out", type=Path, help="gallery path (default: beside the realtime config)")
    parser.add_argument("--config", help="realtime config path, to site the gallery beside it")
    parser.add_argument("--verify", action="store_true", help="re-check the gallery on disk")
    parser.add_argument("--show", action="store_true", help="print where it is and what it says")
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return parser


def _target_path(args: argparse.Namespace) -> Path:
    return Path(args.out).expanduser() if args.out else default_gallery_path(args.config)


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=1, sort_keys=True))
        return
    for key in sorted(payload):
        print(f"  {key}: {payload[key]}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = _target_path(args)

    if args.show or args.verify:
        try:
            gallery = load_gallery(target)
        except AppearanceGalleryError as error:
            print(f"REFUSED: {error}", file=sys.stderr)
            return EXIT_REFUSED
        if gallery is None:
            print(f"no appearance gallery at {target} — nobody has enrolled")
            return EXIT_ABSENT
        payload = {
            "path": str(target),
            "owner_id": gallery.owner_id,
            "model": gallery.model,
            "provider": gallery.provider,
            "crops": gallery.crops,
            "dim": gallery.dim,
            "threshold": round(gallery.threshold, 6),
            "min_margin": gallery.min_margin,
            "measured_self_consistency": round(gallery.measured_self_consistency, 6),
            "negative_reference": round(gallery.negative_reference, 6),
            "calibrated": gallery.calibrated,
            "created_at": gallery.created_at,
        }
        _emit(payload, as_json=args.json)
        if not gallery.calibrated:
            print(
                "WARNING: this gallery's threshold was DERIVED, not measured against "
                "a known non-owner. On SigLIP-2 crops that was measured admitting a "
                "stranger. Re-enroll with --negative-frames.",
                file=sys.stderr,
            )
        return EXIT_OK

    try:
        refuse_repo_path(target)
        box = None
        if args.box:
            parts = [int(v) for v in str(args.box).split(",")]
            if len(parts) != 4:
                raise EnrollmentRefusal("--box must be u0,v0,u1,v1")
            box = (parts[0], parts[1], parts[2], parts[3])
        if args.clip:
            owner_crops = crops_from_clip(args.clip, args.clip_person, _parse_range(args.clip_frames))
        elif args.frames:
            owner_crops = crops_from_frames(list(args.frames), box=box)
        elif args.camera is not None:
            owner_crops = crops_from_camera(args.camera, args.seconds, args.rate_hz)
        else:
            raise EnrollmentRefusal("pick a source: --frames, --clip or --camera")

        negative_crops: list[Any] = []
        if args.clip_negative and args.clip:
            negative_crops = crops_from_clip(
                args.clip, args.clip_negative, _parse_range(args.clip_negative_frames)
            )
        elif args.negative_frames:
            negative_crops = crops_from_frames(list(args.negative_frames), box=box)

        gallery, report = enroll(
            owner_crops,
            negative_crops,
            owner_id=args.owner_id,
            allow_uncalibrated=args.allow_uncalibrated,
        )
    except (EnrollmentRefusal, AppearanceGalleryError, ValueError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return EXIT_REFUSED

    print(f"enrolling {report['owner_crops']} crops of {args.owner_id!r}:")
    _emit(report, as_json=args.json)
    if not args.yes:
        answer = input(f"write this gallery to {target}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("not written")
            return EXIT_ABSENT
    written = save_gallery(gallery, target)
    print(f"wrote {written} (mode 0600, calibrated={gallery.calibrated})")
    if not gallery.calibrated:
        print(
            "WARNING: uncalibrated. The boundary in this file is a derivation, not "
            "a measurement, and it was measured admitting a stranger on the P1-C "
            "fixture. Re-run with a negative when you can.",
            file=sys.stderr,
        )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
