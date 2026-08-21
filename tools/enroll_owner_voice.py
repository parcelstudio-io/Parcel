#!/usr/bin/env python
"""Enroll the owner's voice — the one owner action that turns card F1-SI on.

    tools/enroll_owner_voice.py --wav a.wav b.wav c.wav d.wav e.wav
    tools/enroll_owner_voice.py --session recordings/2026...Z   # an R17 capture
    tools/enroll_owner_voice.py --verify                        # re-check on disk
    tools/enroll_owner_voice.py --show                          # where is it, is it sane

WHAT IT WRITES, AND WHERE IT DOES NOT
-------------------------------------
One JSON file, mode 0600, **outside the repository** — beside the realtime
config, which is where this household already keeps the credential. It holds an
averaged speaker embedding and the name of the model that produced it. It does
not hold audio, it is never committed, and ``--out`` refuses a path inside the
repo so it cannot become one by a slip of the shell.

WHY THE MODEL NAME IS IN THE FILE
---------------------------------
A cosine of 0.61 means "the owner" only inside the geometry of the network that
produced both vectors. A profile that did not name its model could be scored,
with a perfectly straight face, against a threshold measured on a different
one — and the number would look exactly as convincing as a real one. The loader
refuses a profile whose model is not the one the runtime is about to use.

WHAT COUNTS AS ENOUGH VOICE
---------------------------
Five to ten utterances (decision 4). The enroller refuses fewer than
:data:`MIN_UTTERANCES`, refuses an utterance shorter than
:data:`MIN_UTTERANCE_S`, and — the check that actually matters — refuses an
enrollment whose own utterances do not agree with each other. If two of the
recordings score below the operating threshold against their own average, the
"owner" this file describes is not one person, and every verdict it ever
produces would be quietly wrong. That is a refusal with the numbers printed,
not a warning.

RE-ENROLLMENT
-------------
Overwrites cleanly: the write is atomic (temp file at 0600, then rename), so an
interrupted re-enrollment leaves the previous profile intact rather than a
half-written one. There is no merge, on purpose — averaging today's voice into a
profile recorded in a different room is how a threshold drifts without anybody
choosing to move it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - script entry
    sys.path.insert(0, str(REPO_ROOT / "src"))

# Imported after the sys.path line above; the script runs from a checkout.
from parcel_robot.realtime.voice_identity import (
    DEFAULT_MODEL_RELATIVE,
    DEFAULT_THRESHOLD,
    OwnerVoiceProfile,
    SherpaSpeakerEmbedder,
    VoiceIdentityError,
    average_embedding,
    cosine,
    default_profile_path,
    iso_now,
    load_owner_profile,
    normalize,
    save_owner_profile,
)

#: Decision 4's lower bound. Fewer than five utterances is a profile whose
#: average is dominated by one recording's room, mood and microphone distance.
MIN_UTTERANCES = 5

#: Shortest utterance that may enter an enrollment. Well above the runtime's own
#: verify floor: enrollment is the one time we can insist on good material.
MIN_UTTERANCE_S = 1.0

#: Self-consistency floor. Every enrollment utterance must score at least this
#: against the averaged profile, or the recordings are not one speaker.
SELF_CONSISTENCY_MIN = DEFAULT_THRESHOLD


class EnrollmentRefusal(RuntimeError):
    """A refusal the operator has to read. Printed to stderr, exit code 2.

    Deliberately NOT a ``SystemExit`` subclass: a refusal is a value this
    module's own tests assert the WORDS of, and ``SystemExit``'s ``str()`` is
    its exit code, so every message would have been invisible to the suite that
    is supposed to keep them useful.
    """

    @property
    def message(self) -> str:
        return str(self)


def read_wav(path: Path) -> tuple[bytes, int, float]:
    """Mono PCM16 bytes, its rate and its duration. Anything else refuses.

    Deliberately strict rather than helpfully converting: a stereo or 8-bit
    recording that this script silently reshaped would produce an embedding of
    audio the runtime will never see, and the profile would be subtly wrong in a
    way no error message ever mentions.
    """

    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as error:
        raise EnrollmentRefusal(f"{path}: not a readable WAV ({error})") from None
    if width != 2:
        raise EnrollmentRefusal(f"{path}: {width * 8}-bit audio; enrollment needs PCM16")
    if channels != 1:
        raise EnrollmentRefusal(
            f"{path}: {channels} channels; enrollment needs mono (the gateway is mono)"
        )
    seconds = len(frames) / float(rate * 2)
    return frames, int(rate), seconds


def utterances_from_session(session: Path) -> list[Path]:
    """Owner-turn WAV slices from an R17 capture folder. Refuses a bad index.

    An R17 session folder is ``owner.wav`` + ``robot.wav`` + ``index.json``, and
    the index tiles ``owner.wav`` into owner turns by byte range. This reads the
    index rather than the file, so an enrollment cut from a session is cut on
    exactly the turn boundaries the runtime itself drew.
    """

    index_path = session / "index.json"
    if not index_path.is_file():
        raise EnrollmentRefusal(f"{session}: no index.json — not an R17 capture folder")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    owner = index.get("streams", {}).get("owner", {})
    wav_path = session / str(owner.get("path", "owner.wav"))
    if not wav_path.is_file():
        raise EnrollmentRefusal(f"{session}: {wav_path.name} is missing")
    return [wav_path]


def slice_session(session: Path, *, minimum_s: float) -> list[tuple[str, bytes, int]]:
    """Cut ``owner.wav`` into its indexed turns. Short turns are skipped, loudly."""

    index = json.loads((session / "index.json").read_text(encoding="utf-8"))
    rate = int(index.get("sample_rate_hz", 24_000))
    owner = index.get("streams", {}).get("owner", {})
    payload, wav_rate, _ = read_wav(session / str(owner.get("path", "owner.wav")))
    if wav_rate != rate:
        rate = wav_rate
    cuts: list[tuple[str, bytes, int]] = []
    skipped = 0
    for segment in owner.get("segments", []):
        start = int(segment.get("start_byte", 0))
        end = int(segment.get("end_byte", start))
        chunk = payload[start:end]
        if len(chunk) / float(rate * 2) < minimum_s:
            skipped += 1
            continue
        cuts.append((f"{session.name}#segment{segment.get('index')}", chunk, rate))
    if skipped:
        print(f"  (skipped {skipped} owner turn(s) shorter than {minimum_s:.1f}s)")
    return cuts


def resolve_model(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    return REPO_ROOT.joinpath(*DEFAULT_MODEL_RELATIVE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def refuse_repo_path(target: Path) -> None:
    """A voice profile inside the repository is a voice profile in a commit."""

    resolved = target.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise EnrollmentRefusal(
            f"refusing to write an owner voice profile inside the repository "
            f"({resolved}). It is biometric material about one person; it belongs "
            f"beside the credential, outside the tree. Default: "
            f"{default_profile_path()}"
        )


def enroll(
    sources: list[tuple[str, bytes, int]],
    *,
    model_path: Path,
    threshold: float,
) -> tuple[OwnerVoiceProfile, list[tuple[str, float]]]:
    """Embed every utterance, average, then prove the average describes ONE voice."""

    if len(sources) < MIN_UTTERANCES:
        raise EnrollmentRefusal(
            f"{len(sources)} usable utterance(s); enrollment needs at least "
            f"{MIN_UTTERANCES} (decision 4 asks for 5–10). A profile averaged over "
            "fewer is a profile of one recording's room."
        )
    try:
        embedder = SherpaSpeakerEmbedder(model_path)
    except VoiceIdentityError as error:
        raise EnrollmentRefusal(str(error)) from None
    embeddings: list[tuple[float, ...]] = []
    rates: set[int] = set()
    for name, payload, rate in sources:
        try:
            embeddings.append(normalize(embedder.embed(payload, rate)))
        except VoiceIdentityError as error:
            raise EnrollmentRefusal(f"{name}: {error}") from None
        rates.add(rate)
    average = average_embedding(embeddings)
    scores = [
        (name, cosine(average, embedding))
        for (name, _, _), embedding in zip(sources, embeddings)
    ]
    weak = [(name, score) for name, score in scores if score < threshold]
    if weak:
        detail = "; ".join(f"{name} = {score:.3f}" for name, score in weak)
        raise EnrollmentRefusal(
            f"{len(weak)} enrollment utterance(s) score below {threshold:.2f} "
            f"against their own average ({detail}). These recordings are not one "
            "voice — re-record them in one sitting, one speaker, same room. "
            "Writing this profile would put a wrong answer behind a real number."
        )
    profile = OwnerVoiceProfile(
        embedding=average,
        model=model_path.name,
        utterances=len(sources),
        created_at=iso_now(),
        sample_rate_hz=min(rates) if rates else 0,
        model_sha256=sha256_file(model_path) if model_path.is_file() else "",
    )
    return profile, scores


def collect(args: argparse.Namespace) -> list[tuple[str, bytes, int]]:
    sources: list[tuple[str, bytes, int]] = []
    for raw in args.wav or []:
        path = Path(raw).expanduser()
        payload, rate, seconds = read_wav(path)
        if seconds < MIN_UTTERANCE_S:
            raise EnrollmentRefusal(
                f"{path}: {seconds:.2f}s is shorter than the {MIN_UTTERANCE_S:.1f}s "
                "enrollment minimum"
            )
        sources.append((path.name, payload, rate))
    if args.session:
        session = Path(args.session).expanduser()
        utterances_from_session(session)
        sources.extend(slice_session(session, minimum_s=MIN_UTTERANCE_S))
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wav", nargs="*", help="enrollment WAVs (mono PCM16, ≥1s each)")
    parser.add_argument("--session", help="an R17 capture folder to cut owner turns from")
    parser.add_argument("--out", help=f"profile path (default {default_profile_path()})")
    parser.add_argument("--model", help="embedding model .onnx (default models/speaker_id/)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"self-consistency floor for enrollment (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--verify", action="store_true", help="re-read the profile on disk")
    parser.add_argument("--show", action="store_true", help="print where the profile is")
    args = parser.parse_args(argv)

    target = Path(args.out).expanduser() if args.out else default_profile_path()

    if args.show or args.verify:
        print(f"profile path : {target}")
        try:
            profile = load_owner_profile(target)
        except VoiceIdentityError as error:
            print(f"profile      : UNREADABLE — {error}", file=sys.stderr)
            return 2
        if profile is None:
            print(
                "profile      : ABSENT — speaker verification is OFF and any voice "
                "can arm a command. This is the pre-card behaviour."
            )
            return 1
        print(f"model        : {profile.model}")
        print(f"dimensions   : {profile.dim}")
        print(f"utterances   : {profile.utterances}")
        print(f"created_at   : {profile.created_at}")
        mode = target.stat().st_mode & 0o777
        print(f"mode         : {mode:04o}{'' if mode == 0o600 else '  <-- expected 0600'}")
        return 0

    refuse_repo_path(target)
    sources = collect(args)
    model_path = resolve_model(args.model)
    profile, scores = enroll(sources, model_path=model_path, threshold=args.threshold)
    written = save_owner_profile(profile, target)
    print(f"enrolled {profile.utterances} utterance(s) with {profile.model}")
    for name, score in scores:
        print(f"  {score:+.3f}  {name}")
    print(f"wrote {written} (mode {written.stat().st_mode & 0o777:04o})")
    print(
        "speaker verification will arm on the next lane construction; the "
        "emergency latch is NOT identity-gated and never will be."
    )
    return 0


def _entry() -> int:  # pragma: no cover - script entry
    try:
        return main()
    except EnrollmentRefusal as refusal:
        print(f"refused: {refusal.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(_entry())


__all__ = [
    "MIN_UTTERANCES",
    "MIN_UTTERANCE_S",
    "SELF_CONSISTENCY_MIN",
    "EnrollmentRefusal",
    "collect",
    "enroll",
    "main",
    "read_wav",
    "refuse_repo_path",
    "resolve_model",
    "slice_session",
]
