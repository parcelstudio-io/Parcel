"""Speaker identity for command arming — the owner's voice (card F1-SI, task_12).

THE DEFECT THIS MODULE EXISTS TO PREVENT
----------------------------------------
On 2026-08-20 a television commanded the robot. Twice, across two owner
sessions: a Korean broadcast was transcribed, attributed to the owner, and
barged in on the conversation the owner was actually having. The transcript
layer catches THAT instance and only that instance — ``evals/assertions``'
``script_anomaly_provenance`` check is deterministic for a cross-language
broadcast in an English session and blind to an English one. A same-language TV
defeats every transcript-level layer there is.

Acoustic echo cancellation is not a defence either, and this is measured rather
than assumed: AEC cancels the robot's OWN loudspeaker against its OWN reference
signal. A television is an independent source in the room; it arrives at the
microphone array as ordinary speech. (``bench_doa.md`` §"Ranked recommendation"
item 3, and the live ``aec.constructed: false`` on the owner's own stack.)

So the defence has to be acoustic and it has to be about WHO IS SPEAKING.

THE SAFETY ASYMMETRY — BINDING, AND THE FIRST THING TO READ
-----------------------------------------------------------
**The emergency latch is NEVER identity-gated.** Anyone in the room may stop
the dog: a visitor, a child, a stranger, a voice this module has never heard.
Identity gates *arming* — turning a sentence into motion — and nothing else.

``SYNTHESIS_EVAL.md`` speech-identity decision 2 states it as the fail-closed
direction that actually matters: *an unverified voice cannot start motion; it
can always stop it.* :func:`gates_kind` is the executable statement of that
sentence, it reads its emergency class from ``realtime/ingress.py`` rather than
holding a copy of one, and
``test_a_strangers_stop_still_latches_while_their_command_does_not_arm`` is the
seed that proves both directions at once.

Nothing in this module is reachable from the latch path. It cannot delay a
stop, it cannot refuse a stop, and it is not consulted on the way to one.

WHAT IT DOES, AND WHAT IT COSTS
-------------------------------
One speaker embedding per owner turn, post-VAD, in-process, compared by cosine
against an enrolled owner profile. Measured on THIS host (``bench_doa.md``
Bench B, 378 pairs over 5 speakers): titanet_small separates same-speaker
(mean +0.802, min +0.640) from cross-speaker (mean +0.033, max +0.431) with
**zero overlap** and 0/378 pair errors, at **27 ms median / 126 ms p95** added
latency and a 115 ms one-time model load. The default threshold 0.55 is the
midpoint of that measured worst-case gap (0.431 … 0.640), which is where
decision 1 puts it.

The verify runs synchronously on the socket reader thread, at most TWICE per
turn — not once per frame. One provisional embedding as soon as the turn holds
:data:`DEFAULT_MIN_UTTERANCE_S` of speech, so a verdict is on the shelf before
the transcript arrives; one final embedding over the WHOLE turn when the turn
ends, which replaces it. See :data:`MAX_VERIFIES_PER_TURN` — and the FAR/FRR
measurement in :data:`DEFAULT_MIN_UTTERANCE_S`, which is why the second one
exists at all.

THE FOUR FAIL-CLOSED RULES
--------------------------
1. **No profile ⇒ verify DISABLED ⇒ motion remains disarmed**, said out
   loud in the snapshot and in a boot event. Owner authority is evidence, not
   a configuration fallback; an absent verifier cannot turn any nearby voice
   into the owner. The emergency latch remains available to everyone.
2. **A profile that exists and cannot be trusted is a REFUSAL, never a silent
   downgrade to (1).** A truncated file, a different embedding model, a wrong
   dimension: an operator gets an exception naming the file, because a corrupt
   profile silently reading as "no profile" would turn a security feature off
   at exactly the moment it looked on.
3. **With a profile loaded, anything short of a passing score refuses to arm** —
   a low score, a verify that raised, an utterance too short to verify, a turn
   whose verdict has not been computed yet. Refusal is the default and arming
   is the exception that has to be earned.
4. **The refusal is never silent.** Every rejection increments
   ``voice_rejected`` and writes a panel/evidence event; the first one per
   minute is also offered to the whisperer as an always-band fact, so the owner
   HEARS "someone who isn't you asked me to…" rather than watching a robot
   ignore the room for reasons known only to a counter.

THE PREFILTER (card work item 4)
--------------------------------
The XVF3800's vendor control interface reports ``DOA_VALUE`` — ``[angle, vad]``
— in a single EP0 control read that cannot disturb the audio stream, because it
is a different USB interface from the two UAC ones (``bench_doa.md`` Bench A:
IF3 vendor-specific, no kernel driver bound; SC-A3 non-disruption PASS). A
configured rejected sector (the television's azimuth) refuses a turn **unless
the embedding verify passes** — belt and suspenders, in that order: the
embedding is the authority and the sector is the cheap early no.

An unreadable DoA contributes NOTHING rather than refusing everything. That is
not laziness: at the time of writing the read path is blocked by a udev
permission only the owner can grant, and a prefilter that failed closed on its
own absence would have turned an unshipped hardware feature into a robot that
takes no commands at all.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .ingress import KIND_EMERGENCY

# ---------------------------------------------------------------- the profile
#: Schema id on the enrolled profile. Versioned for the same reason the capture
#: index is: the enroller writes it, the loader reads it, and a silently changed
#: shape would be a silently wrong verdict about who is in the room.
VOICE_PROFILE_SCHEMA = "parcel.owner_voice_profile.v1"

#: File name the enroller writes and the loader looks for, beside the realtime
#: config. Never inside the repo: this is biometric material about one person.
VOICE_PROFILE_NAME = "owner_voice_profile.json"

#: Where the profile lives when nothing says otherwise. Mirrors the credential's
#: own home (``~/.config/parcel/realtime.env``, mode 600) because it deserves
#: exactly the same handling.
VOICE_PROFILE_FALLBACK_DIR = Path("~/.config/parcel")

#: The mode the enroller sets and the loader complains about. 0600 = owner-only.
VOICE_PROFILE_MODE = 0o600

#: The vendored embedding model, repo-relative. Vendored under ``models/`` with
#: a provenance lock exactly like the judge (``models/judge/models.lock.json``);
#: the ``.onnx`` itself is gitignored and the LOCK is the committed artifact.
DEFAULT_MODEL_RELATIVE = ("models", "speaker_id", "nemo_en_titanet_small.onnx")


class VoiceIdentityError(RuntimeError):
    """A voice profile or embedder that cannot be trusted. Never downgraded."""


# ------------------------------------------------------------------- defaults
#: Decision 1's threshold: the midpoint of the measured worst-case gap on this
#: host (max impostor pair 0.431, min genuine pair 0.640).
DEFAULT_THRESHOLD = 0.55

#: Silence between owner frames that ends a turn. The SAME rule and the same
#: default as the R17 capture tee's ``owner_gap_s``, so a segment in
#: ``index.json`` and a turn in this module are the same span of audio and an
#: investigation never has to reconcile two segmentations.
DEFAULT_TURN_GAP_S = 0.75

#: Buffered audio that triggers the PROVISIONAL verify. See
#: :data:`MAX_VERIFIES_PER_TURN` for why there is a second one.
#:
#: **Measured, and raised from 0.6 s because of it.** The first version of this
#: module verified once, eagerly, at 0.6 s — and the FAR/FRR run over the bench's
#: own gold set through this exact code path returned **FRR 5/13 = 38.5 %** at
#: FAR 0/112. Every false reject was a genuine speaker judged on the first
#: fragment of a long utterance. 0.6 s is enough audio to have an opinion and not
#: enough to be right; the bench's own zero-overlap numbers were measured on
#: WHOLE utterances (10 ms @ 1.1 s, 28 ms @ 2.7 s). The fix is both halves: more
#: audio before the first opinion, and a second look once the turn is over.
DEFAULT_MIN_UTTERANCE_S = 1.2

#: Two embeddings per turn, maximum, and they answer different questions.
#:
#: The PROVISIONAL one exists for timeliness: a verdict has to be on the shelf
#: before the hosted transcript arrives, or a fail-closed gate refuses the owner
#: for the crime of speaking quickly. The FINAL one exists for accuracy: when the
#: turn is over and turned out to be much longer than the fragment we judged it
#: on, the whole turn is embedded again and **the later verdict replaces the
#: earlier one unconditionally** — later means more audio, and more audio is a
#: better estimate whichever way it moves the score. Deliberately NOT "take the
#: higher of the two": that would be a gate that quietly lowers its own threshold
#: by sampling twice.
MAX_VERIFIES_PER_TURN = 2

#: How much the turn must have grown since the provisional verify before the
#: final one is worth its ~27 ms. Below this the second embedding would be over
#: substantially the same audio and would return substantially the same number.
REVERIFY_GROWTH_FACTOR = 1.5

#: Absolute floor. Below this a turn is NOT verified and therefore does not arm
#: — an embedding over 200 ms of audio is noise with a cosine attached.
DEFAULT_FLOOR_UTTERANCE_S = 0.35

#: Hard bound on the audio one turn may buffer. The FIRST seconds are kept
#: (a command lives at the start of a sentence) and the rest is not stored.
DEFAULT_MAX_UTTERANCE_S = 8.0

#: The card's latency budget, in milliseconds. Not enforced as a timeout — a
#: half-finished embedding is worse than a slow one — but measured, counted when
#: exceeded, and reported in the snapshot.
DEFAULT_BUDGET_MS = 50.0

#: How often a rejection may become a SPOKEN sentence. The counter and the panel
#: event fire on every rejection; this only rate-limits the narration, because a
#: television talking to the robot for ten minutes must not become ten minutes
#: of the robot talking about it.
DEFAULT_NARRATION_INTERVAL_S = 60.0

#: Maximum age of a passing acoustic verdict at authority consumption. A
#: transcript normally follows end-of-turn VAD within a fraction of a second;
#: anything older is context, not authorization for a later command.
DEFAULT_VERDICT_TTL_S = 2.0

# ------------------------------------------------------------- verdict codes
CODE_ARMED = "armed"
CODE_NOT_OWNER = "not_owner"
CODE_TOO_SHORT = "too_short"
CODE_PENDING = "pending"
CODE_VERIFY_ERROR = "verify_error"
CODE_DISABLED = "verify_disabled"
CODE_REJECTED_SECTOR = "rejected_sector"
CODE_SAFETY_NEVER_GATED = "safety_never_gated"

#: Every code this module can produce. A code outside this set is a programming
#: error, and :func:`gate_decision` asserts on it rather than arming.
VERDICT_CODES: frozenset[str] = frozenset(
    {
        CODE_ARMED,
        CODE_NOT_OWNER,
        CODE_TOO_SHORT,
        CODE_PENDING,
        CODE_VERIFY_ERROR,
        CODE_DISABLED,
        CODE_REJECTED_SECTOR,
        CODE_SAFETY_NEVER_GATED,
    }
)

#: PCM shape the gateway hands us. One number, stated, because the embedder is
#: told the rate rather than guessing it.
PCM_SAMPLE_WIDTH_BYTES = 2


# ============================================================== the asymmetry
def gates_kind(kind: str) -> bool:
    """Does speaker identity have ANY say over this ingress class?

    ``False`` for the emergency class and ``True`` for everything else. This is
    the binding safety asymmetry of the card, in one function, and it reads
    :data:`~parcel_robot.realtime.ingress.KIND_EMERGENCY` from the ingress
    module rather than holding a copy of the string — U33 cost a stop that
    stopped nothing because a grammar had three copies of itself, and the same
    mistake here would cost a stop that never ran.

    Deliberately keyed on the CLASS and not on the score: there is no threshold,
    no configuration and no profile state that can make this return ``True`` for
    an emergency. A stranger stops the dog.
    """

    return str(kind) != KIND_EMERGENCY


# ================================================================= the vector
def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two same-length vectors. ``0.0`` on a zero vector.

    Returning zero rather than raising on a degenerate vector is deliberate and
    it is the fail-closed direction: zero is below every admissible threshold,
    so a broken embedding refuses to arm instead of exploding inside the socket
    reader thread.
    """

    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_sq += a * a
        right_sq += b * b
    if left_sq <= 0.0 or right_sq <= 0.0:
        return 0.0
    value = dot / math.sqrt(left_sq * right_sq)
    if not math.isfinite(value):
        return 0.0
    return max(-1.0, min(1.0, value))


def normalize(vector: Sequence[float]) -> tuple[float, ...]:
    """Unit-length copy. A zero vector stays zero rather than dividing by it."""

    total = math.sqrt(sum(float(value) * float(value) for value in vector))
    if total <= 0.0 or not math.isfinite(total):
        return tuple(0.0 for _ in vector)
    return tuple(float(value) / total for value in vector)


def average_embedding(embeddings: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """The enrolled profile: unit-normalize each utterance, then average, then
    normalize again.

    Normalizing BEFORE the mean is what stops one loud or one long enrollment
    utterance from dominating the profile — the average would otherwise be a
    weighted vote where the weights are recording levels.
    """

    if not embeddings:
        raise VoiceIdentityError("cannot average an empty set of embeddings")
    width = len(embeddings[0])
    if width == 0 or any(len(item) != width for item in embeddings):
        raise VoiceIdentityError("enrollment embeddings have inconsistent dimensions")
    summed = [0.0] * width
    for item in embeddings:
        for index, value in enumerate(normalize(item)):
            summed[index] += value
    return normalize(summed)


# ================================================================ the profile
@dataclass(frozen=True)
class OwnerVoiceProfile:
    """The enrolled owner, as stored beside the realtime config.

    Carries the MODEL it was computed with, and the loader refuses a profile
    whose model is not the one the runtime is about to use. A cosine of 0.61
    means "the owner" only in the geometry of the network that produced both
    vectors; comparing a titanet embedding to an eres2net threshold is a
    number-shaped opinion about nothing.
    """

    embedding: tuple[float, ...]
    model: str
    utterances: int
    created_at: str = ""
    sample_rate_hz: int = 0
    source: str = ""
    #: sha256 of the model file at enrollment time, when the enroller could
    #: compute one. Recorded, and compared when both sides know it.
    model_sha256: str = ""

    @property
    def dim(self) -> int:
        return len(self.embedding)

    def score(self, embedding: Sequence[float]) -> float:
        return cosine(self.embedding, embedding)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VOICE_PROFILE_SCHEMA,
            "model": self.model,
            "model_sha256": self.model_sha256,
            "dim": self.dim,
            "utterances": self.utterances,
            "created_at": self.created_at,
            "sample_rate_hz": self.sample_rate_hz,
            "embedding": list(self.embedding),
        }

    def describe(self) -> dict[str, Any]:
        """What the SNAPSHOT may see. Deliberately NOT the embedding.

        The vector is biometric material about one person; a panel that renders
        ``/api/state`` in a browser tab has no business holding it, and an
        artifact that gets pasted into a status document even less. The counts
        and the model are what an operator needs in order to know the feature is
        configured, and they are all that leaves this object.
        """

        return {
            "model": self.model,
            "dim": self.dim,
            "utterances": self.utterances,
            "created_at": self.created_at,
            "source": self.source,
        }


def default_profile_path(config_path: str | Path | None = None) -> Path:
    """Where the profile lives: BESIDE the realtime config, else in ~/.config/parcel.

    Beside the config because that is the directory the owner already keeps
    outside the repository for exactly this class of file (the credential lives
    there, mode 600), and because an operator running two profiles gets two
    directories rather than one file with two meanings.
    """

    if config_path:
        candidate = Path(config_path).expanduser()
        parent = candidate.parent if candidate.suffix else candidate
        return parent / VOICE_PROFILE_NAME
    return VOICE_PROFILE_FALLBACK_DIR.expanduser() / VOICE_PROFILE_NAME


def load_owner_profile(path: str | Path) -> OwnerVoiceProfile | None:
    """Read an enrolled profile. ABSENT ⇒ ``None``; PRESENT-AND-BROKEN ⇒ raise.

    The two outcomes are deliberately different, and the difference is the whole
    fail-closed story of the card:

    * an absent file is a household that has not enrolled, and the answer is a
      disabled verdict that cannot arm motion, stated out loud (rule 1);
    * a file that exists and does not parse, or carries the wrong schema, the
      wrong model or a degenerate vector, is an operator error that must be
      READ, not absorbed (rule 2). Silently treating it as "no profile" would
      turn the feature off while every surface still said it was configured.
    """

    target = Path(path).expanduser()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VoiceIdentityError(
            f"owner voice profile {target} exists and cannot be read: {error}. "
            "Refusing to treat an unreadable profile as an absent one — "
            f"re-run tools/enroll_owner_voice.py or delete {target}."
        ) from None
    if not isinstance(raw, Mapping):
        raise VoiceIdentityError(f"owner voice profile {target} is not a JSON object")
    schema = raw.get("schema")
    if schema != VOICE_PROFILE_SCHEMA:
        raise VoiceIdentityError(
            f"owner voice profile {target} declares schema {schema!r}, expected "
            f"{VOICE_PROFILE_SCHEMA!r}"
        )
    embedding = raw.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise VoiceIdentityError(f"owner voice profile {target} carries no embedding")
    values: list[float] = []
    for item in embedding:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise VoiceIdentityError(
                f"owner voice profile {target} has a non-numeric embedding value {item!r}"
            )
        number = float(item)
        if not math.isfinite(number):
            raise VoiceIdentityError(
                f"owner voice profile {target} has a non-finite embedding value"
            )
        values.append(number)
    unit = normalize(values)
    if not any(unit):
        raise VoiceIdentityError(
            f"owner voice profile {target} is a zero vector: it would score 0.0 "
            "against every voice on earth, which is not an enrollment"
        )
    model = str(raw.get("model", "")).strip()
    if not model:
        raise VoiceIdentityError(
            f"owner voice profile {target} does not name the model it was computed "
            "with; a cosine threshold is only meaningful within one embedding space"
        )
    utterances = raw.get("utterances", 0)
    if isinstance(utterances, bool) or not isinstance(utterances, int) or utterances < 1:
        raise VoiceIdentityError(
            f"owner voice profile {target} claims {utterances!r} enrollment utterances"
        )
    return OwnerVoiceProfile(
        embedding=unit,
        model=model,
        utterances=int(utterances),
        created_at=str(raw.get("created_at", "")),
        sample_rate_hz=int(raw.get("sample_rate_hz", 0) or 0),
        model_sha256=str(raw.get("model_sha256", "")),
        source=str(target),
    )


def save_owner_profile(profile: OwnerVoiceProfile, path: str | Path) -> Path:
    """Write a profile at mode 0600, atomically. Re-enrollment OVERWRITES.

    Atomic because a half-written profile is precisely the "present and broken"
    case :func:`load_owner_profile` refuses on, and an interrupted enrollment
    must not be able to brick the microphone. 0600 is set on the TEMPORARY file
    before the rename, so the bytes are never briefly world-readable.
    """

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    payload = dict(profile.as_dict())
    handle = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, VOICE_PROFILE_MODE)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.chmod(temporary, VOICE_PROFILE_MODE)
    os.replace(temporary, target)
    return target


# =============================================================== the embedder
class SpeakerEmbedder(Protocol):
    """One utterance of PCM16 in, one embedding out. Synchronous, CPU, no state."""

    name: str

    def embed(self, pcm16: bytes, sample_rate_hz: int) -> tuple[float, ...]:
        """Embed one utterance. May raise; the gate turns that into a refusal."""


def pcm16_to_floats(payload: bytes) -> list[float]:
    """Little-endian PCM16 bytes to floats in [-1, 1). Odd trailing byte dropped."""

    usable = len(payload) - (len(payload) % PCM_SAMPLE_WIDTH_BYTES)
    if usable <= 0:
        return []
    return [
        int.from_bytes(payload[index : index + 2], "little", signed=True) / 32768.0
        for index in range(0, usable, PCM_SAMPLE_WIDTH_BYTES)
    ]


def _fake_vector(tag: int, dim: int) -> tuple[float, ...]:
    """A unit vector whose ANGLE is ``tag``. See :class:`FakeSpeakerEmbedder`."""

    theta = (int(tag) % 2001) * (math.pi / 2.0) / 1000.0
    values = [0.0] * max(2, dim)
    values[0] = math.cos(theta)
    values[1] = math.sin(theta)
    return tuple(values)


class FakeSpeakerEmbedder:
    """The test double, and the reason every seed in this card is deterministic.

    The FIRST PCM16 sample of the utterance names the speaker: it is read as an
    angle in thousandths of a right angle, so two utterances tagged ``t1`` and
    ``t2`` score ``cos((t1 - t2) · π/2000)`` against each other. Tag 0 vs 0 is
    1.000, tag 0 vs 1000 is 0.000, tag 0 vs 500 is 0.707 — a continuous knob a
    threshold test can turn, with no model, no ONNX runtime and no 40 MB file.

    It is not a stand-in for the measured separation and never claims to be; it
    is a stand-in for "the embedder returned a number", which is the only part
    of the embedder this module's policy actually depends on.
    """

    name = "fake"

    def __init__(self, *, dim: int = 8, latency_s: float = 0.0) -> None:
        self.dim = max(2, int(dim))
        self.latency_s = max(0.0, float(latency_s))
        self.calls = 0

    def embed(self, pcm16: bytes, sample_rate_hz: int) -> tuple[float, ...]:
        self.calls += 1
        if self.latency_s:
            time.sleep(self.latency_s)
        if len(pcm16) < PCM_SAMPLE_WIDTH_BYTES:
            raise VoiceIdentityError("fake embedder was handed no audio")
        tag = int.from_bytes(pcm16[:2], "little", signed=True)
        return _fake_vector(tag, self.dim)


class SherpaSpeakerEmbedder:
    """titanet_small on CPU via sherpa-onnx. The shipped embedder.

    Imported LAZILY and constructed only when a profile exists, for two
    reasons: ``sherpa_onnx`` is an optional dependency this build does not
    require, and the model is a 40 MB file that the gitignore keeps out of the
    repository. A build without either still boots, still records, still stops
    on command — it simply reports ``verify_disabled`` and says why.
    """

    name = "sherpa"

    def __init__(self, model_path: str | Path, *, num_threads: int = 2) -> None:
        self.model_path = Path(model_path).expanduser()
        if not self.model_path.is_file():
            raise VoiceIdentityError(
                f"speaker embedding model {self.model_path} is not present. "
                "Fetch it with models/speaker_id/pin_lock.py --verify after "
                "downloading the URL the lock names."
            )
        try:
            import sherpa_onnx  # local import: optional dependency, lazy on purpose
        except ImportError as error:  # pragma: no cover - depends on the build
            raise VoiceIdentityError(
                "voice identity verify needs the optional 'sherpa_onnx' package "
                f"and this build does not have it ({error})"
            ) from None
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(self.model_path), num_threads=max(1, int(num_threads))
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.dim = int(getattr(self._extractor, "dim", 0) or 0)

    def embed(self, pcm16: bytes, sample_rate_hz: int) -> tuple[float, ...]:
        samples = pcm16_to_floats(pcm16)
        if not samples:
            raise VoiceIdentityError("speaker embedder was handed no audio")
        try:
            import numpy  # local import: kept beside its only use

            waveform = numpy.asarray(samples, dtype="float32")
        except ImportError:  # pragma: no cover - numpy is a project dependency
            waveform = samples
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=int(sample_rate_hz), waveform=waveform)
        stream.input_finished()
        return normalize([float(value) for value in self._extractor.compute(stream)])


# ==================================================================== the DoA
@dataclass(frozen=True)
class DoaSample:
    """One ``DOA_VALUE`` read: an azimuth in degrees and the hardware VAD flag."""

    angle_deg: int
    vad: bool
    read_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"angle_deg": self.angle_deg, "vad": self.vad, "read_ms": round(self.read_ms, 3)}


#: USB identity of the reSpeaker XVF3800 on this host (``lsusb``: 2886:001a).
XVF3800_VENDOR_ID = 0x2886
XVF3800_PRODUCT_ID = 0x001A

#: ``DOA_VALUE`` on the vendor control interface, from the Seeed XVF3800 python
#: SDK and confirmed against the XMOS host-application guide: resource 20,
#: command 18, two little-endian uint16 — ``[angle_deg 0..359, vad 0|1]``. Some
#: firmware prepends a one-byte status, so the reader asks for one extra byte
#: and tolerates both layouts, exactly as the staged bench tool does.
DOA_RESOURCE_ID = 20
DOA_COMMAND_ID = 18
DOA_PAYLOAD_BYTES = 4

#: ``bmRequestType`` for a vendor IN control transfer on EP0.
_CTRL_IN = 0xC0


class DoaReader(Protocol):
    """Anything that can answer 'where is the sound coming from right now'."""

    def read(self) -> DoaSample | None:
        """One sample, or ``None`` when the device cannot be read."""


class UsbDoaReader:
    """``DOA_VALUE`` over the XVF3800 vendor interface. READ-ONLY, EP0 only.

    Productionized from ``<bench>/doa_poll.py``. The non-disruption argument is
    structural rather than empirical: this class issues ``ctrl_transfer`` on
    endpoint zero and nothing else. It never calls ``set_configuration``, never
    claims an interface, never opens an ALSA device, and never touches IF1/IF2
    (the UAC streams) or IF4 (DFU). Bench A measured the consequence — the ALSA
    stream state was ``closed → closed`` across the probe and the device kept
    its bus address, so no re-enumeration and therefore no reset.

    At the time of writing every read on this host fails with ``Errno 13``,
    because ``/dev/bus/usb/003/008`` is ``root:root 0664`` and there is no udev
    rule for vendor 2886. That is the owner action in ``bench_doa.md``; until it
    lands, :meth:`read` returns ``None``, counts the failure, and the sector
    prefilter contributes nothing.
    """

    def __init__(
        self,
        *,
        vendor_id: int = XVF3800_VENDOR_ID,
        product_id: int = XVF3800_PRODUCT_ID,
        timeout_ms: int = 200,
    ) -> None:
        self.vendor_id = int(vendor_id)
        self.product_id = int(product_id)
        self.timeout_ms = max(1, int(timeout_ms))
        self.reads_ok = 0
        self.reads_failed = 0
        self.last_error = ""
        self._device: Any = None

    def _ensure_device(self) -> Any:
        if self._device is not None:
            return self._device
        try:
            import usb.core  # local import: optional dependency, lazy on purpose
        except ImportError as error:
            raise VoiceIdentityError(f"pyusb is not available in this build ({error})") from None
        device = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if device is None:
            raise VoiceIdentityError(
                f"no USB device {self.vendor_id:04x}:{self.product_id:04x} is attached"
            )
        self._device = device
        return device

    def read(self) -> DoaSample | None:
        """One ``DOA_VALUE``. ``None`` — never an exception — on any failure."""

        started = time.perf_counter()
        try:
            device = self._ensure_device()
            raw = bytes(
                device.ctrl_transfer(
                    _CTRL_IN,
                    0,
                    0x80 | DOA_COMMAND_ID,
                    DOA_RESOURCE_ID,
                    DOA_PAYLOAD_BYTES + 1,
                    timeout=self.timeout_ms,
                )
            )
        except Exception as error:  # noqa: BLE001 - a prefilter may never raise
            self.reads_failed += 1
            self.last_error = f"{type(error).__name__}: {error}"
            self._device = None
            return None
        payload = raw[1:] if len(raw) == DOA_PAYLOAD_BYTES + 1 else raw
        if len(payload) < DOA_PAYLOAD_BYTES:
            self.reads_failed += 1
            self.last_error = f"short DOA_VALUE payload: {len(payload)} bytes"
            return None
        angle = int.from_bytes(payload[0:2], "little", signed=False)
        vad = int.from_bytes(payload[2:4], "little", signed=False)
        self.reads_ok += 1
        self.last_error = ""
        return DoaSample(
            angle_deg=angle % 360,
            vad=bool(vad),
            read_ms=(time.perf_counter() - started) * 1000.0,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "kind": "usb",
            "device": f"{self.vendor_id:04x}:{self.product_id:04x}",
            "reads_ok": self.reads_ok,
            "reads_failed": self.reads_failed,
            "last_error": self.last_error,
        }


class FakeDoaReader:
    """A scripted DoA, and the audit trail of everything it was asked to do.

    ``calls`` records every read so a test can assert what the prefilter did;
    :attr:`opened_audio` stays ``False`` forever, which is the test-double half
    of the non-disruption claim (the other half is Bench A's measurement, and
    neither is a substitute for the other — see ``does_not_prove``).
    """

    def __init__(self, samples: Sequence[DoaSample | None] = ()) -> None:
        self._samples = list(samples)
        self.calls = 0
        self.opened_audio = False

    def read(self) -> DoaSample | None:
        self.calls += 1
        if not self._samples:
            return None
        if len(self._samples) == 1:
            return self._samples[0]
        return self._samples.pop(0)

    def snapshot(self) -> dict[str, Any]:
        return {"kind": "fake", "reads_ok": self.calls, "reads_failed": 0, "last_error": ""}


def sector_contains(angle_deg: float, start_deg: float, end_deg: float) -> bool:
    """Is this azimuth inside ``[start, end]`` on a circle? Wrap-aware.

    ``(350, 10)`` is the twenty degrees around due north and NOT the three
    hundred and forty degrees the other way round — a sector that silently
    inverted itself at the wrap point would reject the whole room except the
    television.
    """

    angle = float(angle_deg) % 360.0
    start = float(start_deg) % 360.0
    end = float(end_deg) % 360.0
    if start <= end:
        return start <= angle <= end
    return angle >= start or angle <= end


# =============================================================== the decision
@dataclass(frozen=True)
class VoiceVerdict:
    """What the gate believes about the CURRENT owner turn, and why."""

    code: str
    passed: bool
    score: float | None = None
    threshold: float = DEFAULT_THRESHOLD
    seconds: float = 0.0
    turn: int = 0
    verify_ms: float = 0.0
    doa_deg: int | None = None
    detail: str = ""
    issued_monotonic_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "passed": self.passed,
            "score": None if self.score is None else round(self.score, 4),
            "threshold": self.threshold,
            "seconds": round(self.seconds, 3),
            "turn": self.turn,
            "verify_ms": round(self.verify_ms, 2),
            "doa_deg": self.doa_deg,
            "detail": self.detail,
            "issued_monotonic_s": self.issued_monotonic_s,
        }


@dataclass(frozen=True)
class VoiceArmingDecision:
    """May THIS ingress class act, given THAT verdict? The asymmetry, applied."""

    armed: bool
    code: str
    reason: str
    kind: str = ""
    verdict: VoiceVerdict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "code": self.code,
            "reason": self.reason,
            "kind": self.kind,
            "verdict": None if self.verdict is None else self.verdict.as_dict(),
        }


#: The sentence the whisperer is handed, and the sentence the panel logs. Stated
#: once, here, so the spoken narration and the written event cannot drift.
def rejection_fact(kind: str, transcript: str) -> str:
    """The always-band FACT for one refused turn. Never a speech act.

    Names what was refused and what was NOT refused, because the second half is
    the part an owner needs to hear: an unverified voice can still stop the dog,
    and a robot that said only "I ignored someone" would be describing a
    stricter product than this one.
    """

    said = " ".join(str(transcript).split())[:120]
    return (
        "The robot's speaker-identity check reports it did NOT recognise the "
        f"voice that just said {said!r}, so it refused to act on it "
        f"({kind}). Its emergency stop is not identity-checked and would still "
        "have obeyed that voice."
    )


def gate_decision(kind: str, verdict: VoiceVerdict | None) -> VoiceArmingDecision:
    """THE gate. Pure, total, and the only place arming is decided.

    Order matters and is the order of the card:

    1. the emergency class is answered BEFORE the verdict is even looked at;
    2. no gate object / no profile ⇒ refused, with the code that says so;
    3. a passing verdict ⇒ armed;
    4. everything else ⇒ refused, carrying the code that explains it.
    """

    kind_text = str(kind)
    if not gates_kind(kind_text):
        return VoiceArmingDecision(
            armed=True,
            code=CODE_SAFETY_NEVER_GATED,
            reason=(
                "the emergency latch is never identity-gated: anyone in the room "
                "may stop the dog"
            ),
            kind=kind_text,
            verdict=verdict,
        )
    if verdict is None or verdict.code == CODE_DISABLED:
        return VoiceArmingDecision(
            armed=False,
            code=CODE_DISABLED,
            reason=(
                "speaker verification is unavailable (no authenticated owner "
                "verdict); non-emergency motion remains disarmed"
            ),
            kind=kind_text,
            verdict=verdict,
        )
    if verdict.passed and verdict.code == CODE_ARMED:
        return VoiceArmingDecision(
            armed=True,
            code=CODE_ARMED,
            reason=(
                f"the speaker embedding scored {verdict.score:.3f} against the "
                f"enrolled owner (threshold {verdict.threshold:.2f})"
            ),
            kind=kind_text,
            verdict=verdict,
        )
    return VoiceArmingDecision(
        armed=False,
        code=verdict.code if verdict.code in VERDICT_CODES else CODE_VERIFY_ERROR,
        reason=verdict.detail or "the voice on this turn was not verified as the owner",
        kind=kind_text,
        verdict=verdict,
    )


# =================================================== card P2-B: identity as a LABEL
#
# THE DISTINCTION THIS SECTION EXISTS TO KEEP
# -------------------------------------------
# Everything above decides whether a turn may ACT. Everything below decides only
# what a turn is CALLED. They are deliberately different functions with different
# return types, and the second one has no way to reach the first: a label is
# computed from a verdict that has already been settled, it takes no lock, it
# starts no verification, and there is no code path in this module by which a
# label can turn into a refusal.
#
# That is the whole of card P2-B's absolute constraint, stated as structure
# rather than as a comment: *identity becomes a label, not a gate*. The emergency
# class labels as :data:`LABEL_UNGATED` and arms exactly as it did before, and a
# build with no enrolled profile labels every row :data:`LABEL_UNENROLLED` while
# arming everything, exactly as it did before.

#: The enrolled owner, verified this turn.
LABEL_OWNER = "owner"
#: Somebody else: a voice that was verified and did not match the profile.
LABEL_NOT_OWNER = "not_owner"
#: The gate exists and could not say. Too short, still pending, or it failed —
#: three different codes, one label, because "we do not know" is one fact.
LABEL_UNVERIFIED = "unverified"
#: No enrolled profile at all (or no embedder to use it with). Identity is not
#: merely unknown here, it is UNKNOWABLE, and the two must never be conflated:
#: `unverified` says the check ran and abstained, `unenrolled` says there is no
#: check. Before ``tools/enroll_owner_voice.py`` is run this is every row.
LABEL_UNENROLLED = "unenrolled"
#: The emergency class. Identity had no say and was not consulted; the row is
#: labelled so an auditor can SEE the exemption in the record rather than infer
#: it from an absence.
LABEL_UNGATED = "ungated"

SPEAKER_LABELS: frozenset[str] = frozenset(
    {
        LABEL_OWNER,
        LABEL_NOT_OWNER,
        LABEL_UNVERIFIED,
        LABEL_UNENROLLED,
        LABEL_UNGATED,
    }
)

#: The class a row with no ingress class of its own is labelled under — a robot
#: turn, a system note, a panel line. Deliberately NOT
#: :data:`~parcel_robot.realtime.ingress.KIND_EMERGENCY`, so ``gates_kind``
#: returns True for it and no bookkeeping row can borrow the latch's exemption
#: by accident (the same reasoning ``runtime.VOICE_KIND_TOOL`` is written down
#: with, and for the same reason).
VOICE_LABEL_KIND = "turn"

#: Verdict code ⇒ label, for the codes that map one-to-one. Codes outside this
#: table fall through to :data:`LABEL_UNVERIFIED`, which is the honest answer for
#: any state this table has not been taught about.
_CODE_LABELS: Mapping[str, str] = {
    CODE_ARMED: LABEL_OWNER,
    CODE_NOT_OWNER: LABEL_NOT_OWNER,
    CODE_REJECTED_SECTOR: LABEL_NOT_OWNER,
    CODE_TOO_SHORT: LABEL_UNVERIFIED,
    CODE_PENDING: LABEL_UNVERIFIED,
    CODE_VERIFY_ERROR: LABEL_UNVERIFIED,
    CODE_DISABLED: LABEL_UNENROLLED,
    CODE_SAFETY_NEVER_GATED: LABEL_UNGATED,
}


@dataclass(frozen=True)
class SpeakerLabel:
    """WHOSE VOICE a row is attributed to. Carries no authority of any kind.

    ``blocking`` is on the record and is always ``False``. It is not a knob and
    nothing reads it to decide anything — it exists so that "did this build ever
    let a label gate something" is a question an artifact can answer, instead of
    a property a reader has to re-derive from the source every time.
    """

    label: str
    code: str
    #: Did identity have any say over this class at all? ``False`` only for the
    #: emergency class, and it is the same predicate :func:`gates_kind` answers —
    #: read from it, never re-expressed.
    gated: bool
    #: Is there an enrolled profile behind this label?
    enrolled: bool
    score: float | None = None
    threshold: float = DEFAULT_THRESHOLD
    turn: int = 0
    kind: str = ""
    #: Structurally always False. See the class docstring.
    blocking: bool = False

    def __post_init__(self) -> None:
        if self.label not in SPEAKER_LABELS:
            raise VoiceIdentityError(f"unknown speaker label {self.label!r}")
        if self.blocking:
            raise VoiceIdentityError(
                "a speaker label may never be blocking: card P2-B makes identity a "
                "label and not a gate, and arming is decided by gate_decision alone"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "code": self.code,
            "gated": self.gated,
            "enrolled": self.enrolled,
            "score": None if self.score is None else round(float(self.score), 4),
            "threshold": round(float(self.threshold), 4),
            "turn": int(self.turn),
            "kind": self.kind,
            "blocking": False,
        }

    def describe(self) -> str:
        """One machine-readable clause for a ledger row or a panel event."""

        score = "none" if self.score is None else f"{self.score:.4f}"
        return (
            f"speaker={self.label} code={self.code} score={score} "
            f"enrolled={'yes' if self.enrolled else 'no'} "
            f"gated={'yes' if self.gated else 'no'}"
        )


def speaker_label(
    kind: str,
    verdict: VoiceVerdict | None,
    *,
    enrolled: bool,
) -> SpeakerLabel:
    """Name the speaker of one turn. Pure, total, and never an authority.

    Mirrors :func:`gate_decision`'s ORDER so the two can never disagree about
    what happened, while disagreeing completely about what it means:

    1. the emergency class is :data:`LABEL_UNGATED` before the verdict is read;
    2. no verdict, or the disabled verdict, is :data:`LABEL_UNENROLLED`;
    3. otherwise the verdict's own code names the label.

    ``enrolled`` is passed rather than inferred because the caller is the only
    one that knows whether a profile exists at all: a gate that has not seen
    audio yet reports ``pending``, and "pending with a profile" and "pending
    because there is no profile" are the same code and different facts.
    """

    kind_text = str(kind)
    gated = gates_kind(kind_text)
    if not gated:
        return SpeakerLabel(
            label=LABEL_UNGATED,
            code=CODE_SAFETY_NEVER_GATED,
            gated=False,
            enrolled=bool(enrolled),
            score=None if verdict is None else verdict.score,
            threshold=DEFAULT_THRESHOLD if verdict is None else verdict.threshold,
            turn=0 if verdict is None else verdict.turn,
            kind=kind_text,
        )
    if verdict is None or verdict.code == CODE_DISABLED or not enrolled:
        return SpeakerLabel(
            label=LABEL_UNENROLLED,
            code=CODE_DISABLED if verdict is None else verdict.code,
            gated=True,
            enrolled=bool(enrolled),
            score=None if verdict is None else verdict.score,
            threshold=DEFAULT_THRESHOLD if verdict is None else verdict.threshold,
            turn=0 if verdict is None else verdict.turn,
            kind=kind_text,
        )
    label = _CODE_LABELS.get(verdict.code, LABEL_UNVERIFIED)
    if label == LABEL_OWNER and not verdict.passed:
        # Belt and braces: ``armed`` is only ever set on a passing verdict, and a
        # hand-built verdict that says otherwise is named for what it proves.
        label = LABEL_UNVERIFIED
    return SpeakerLabel(
        label=label,
        code=verdict.code,
        gated=True,
        enrolled=True,
        score=verdict.score,
        threshold=verdict.threshold,
        turn=verdict.turn,
        kind=kind_text,
    )


#: The label a build with no identity stack at all stamps on its rows. A
#: ``mode: text`` session has no gate object; its rows are still labelled, and
#: they are labelled with the truth.
def unenrolled_label(kind: str = "") -> SpeakerLabel:
    return speaker_label(kind, None, enrolled=False)


# ==================================================================== the gate
@dataclass
class _Turn:
    """One owner turn's buffer and its settled verdict. Gate-internal."""

    index: int
    buffer: bytearray = field(default_factory=bytearray)
    seconds: float = 0.0
    last_wall: float = 0.0
    #: How many embeddings this turn has cost. At most
    #: :data:`MAX_VERIFIES_PER_TURN`: one provisional, one final.
    verifies: int = 0
    #: Bytes the last verify actually embedded, so the settle step can tell
    #: "the turn barely grew" from "the turn was ten times longer than the
    #: fragment we judged it on".
    verified_bytes: int = 0
    truncated: bool = False

    @property
    def verified(self) -> bool:
        return self.verifies > 0


class VoiceIdentityGate:
    """Per-turn speaker verification for the audio gateway. Owns no socket.

    THE RELAY-PATH CONTRACT, inherited verbatim from the R17 tee: this object is
    fed from ``BrowserAudioGateway.accept_audio``, which runs on the socket
    reader's own thread. So it may not raise into its caller, ever — every
    producer entry point swallows its own exceptions, counts them and refuses to
    arm, which is the fail-closed direction. What it may do, and does, is spend
    ~27 ms ONCE per turn computing an embedding; that is the card's stated
    latency budget and the only place this object is allowed to be slow.
    """

    def __init__(
        self,
        *,
        embedder: SpeakerEmbedder | None,
        profile: OwnerVoiceProfile | None,
        threshold: float = DEFAULT_THRESHOLD,
        sample_rate_hz: int = 24_000,
        turn_gap_s: float = DEFAULT_TURN_GAP_S,
        min_utterance_s: float = DEFAULT_MIN_UTTERANCE_S,
        floor_utterance_s: float = DEFAULT_FLOOR_UTTERANCE_S,
        max_utterance_s: float = DEFAULT_MAX_UTTERANCE_S,
        budget_ms: float = DEFAULT_BUDGET_MS,
        narration_interval_s: float = DEFAULT_NARRATION_INTERVAL_S,
        verdict_ttl_s: float = DEFAULT_VERDICT_TTL_S,
        doa: DoaReader | None = None,
        rejected_sector: tuple[float, float] | None = None,
        on_event: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder = embedder
        self._profile = profile
        self.threshold = float(threshold)
        self.sample_rate_hz = int(sample_rate_hz)
        self.bytes_per_second = float(self.sample_rate_hz * PCM_SAMPLE_WIDTH_BYTES)
        self.turn_gap_s = max(0.0, float(turn_gap_s))
        self.min_utterance_s = max(0.0, float(min_utterance_s))
        self.floor_utterance_s = max(0.0, float(floor_utterance_s))
        self.max_utterance_s = max(self.min_utterance_s, float(max_utterance_s))
        self.budget_ms = max(0.0, float(budget_ms))
        self.narration_interval_s = max(0.0, float(narration_interval_s))
        self.verdict_ttl_s = max(0.0, float(verdict_ttl_s))
        self._doa = doa
        self._sector = rejected_sector
        self._on_event = on_event
        self._clock = clock

        self._lock = threading.RLock()
        self._turn: _Turn | None = None
        self._turns = 0
        self._verdict: VoiceVerdict = self._disabled_verdict()
        self._last_consumed_turn = 0
        self._last_narration_at: float | None = None

        # ------------------------------------------------------------ counters
        self.turns_seen = 0
        self.turns_verified = 0
        self.voice_accepted = 0
        self.voice_rejected = 0
        self.verify_errors = 0
        self.turns_too_short = 0
        self.sector_rejected = 0
        self.budget_exceeded = 0
        self.narrations = 0
        self.frames_seen = 0
        self._latencies: list[float] = []

    # ----------------------------------------------------------------- state
    @property
    def enabled(self) -> bool:
        """Is a verdict about identity possible at all? Profile AND embedder."""

        return self._profile is not None and self._embedder is not None

    @property
    def profile(self) -> OwnerVoiceProfile | None:
        return self._profile

    def _disabled_verdict(self) -> VoiceVerdict:
        return VoiceVerdict(
            code=CODE_DISABLED,
            passed=False,
            threshold=self.threshold,
            detail="no enrolled owner voice profile; speaker verification is off",
        )

    # -------------------------------------------------------- producer side
    def observe_frame(self, payload: bytes, wall: float | None = None) -> None:
        """One accepted microphone frame. Never raises, never blocks on I/O.

        Segments turns on the SAME silence gap the R17 tee cuts its owner
        segments on, so "turn 4" here and "owner segment 4" in ``index.json``
        are the same audio.
        """

        if not self.enabled or not payload:
            return
        try:
            self._observe(bytes(payload), self._wall(wall))
        except Exception as error:  # noqa: BLE001 - may never break the relay
            self._fail(f"voice identity observe failed: {error}")

    def _observe(self, payload: bytes, wall: float) -> None:
        with self._lock:
            self.frames_seen += 1
            turn = self._turn
            if turn is not None and self.turn_gap_s and wall - turn.last_wall > self.turn_gap_s:
                self._settle_locked(turn, wall)
                turn = None
            if turn is None:
                self._turns += 1
                self.turns_seen += 1
                turn = _Turn(index=self._turns, last_wall=wall)
                self._turn = turn
                self._verdict = VoiceVerdict(
                    code=CODE_PENDING,
                    passed=False,
                    threshold=self.threshold,
                    turn=turn.index,
                    detail="this turn has not been verified yet",
                )
            turn.last_wall = wall
            turn.seconds += len(payload) / self.bytes_per_second
            # The buffer keeps growing AFTER the provisional verify, up to the
            # cap: the final verify at settle time is the one that gets to see
            # the whole sentence, and it cannot see what was never kept.
            room = int(self.max_utterance_s * self.bytes_per_second) - len(turn.buffer)
            if room > 0:
                turn.buffer.extend(payload[:room])
            else:
                turn.truncated = True
            if turn.verifies == 0 and len(turn.buffer) >= self.min_utterance_s * self.bytes_per_second:
                self._verify_locked(turn, wall)

    def end_turn(self, wall: float | None = None) -> None:
        """The caller knows the turn is over (mic closed, session ended)."""

        if not self.enabled:
            return
        try:
            with self._lock:
                turn = self._turn
                if turn is not None:
                    self._settle_locked(turn, self._wall(wall))
        except Exception as error:  # noqa: BLE001 - may never break the relay
            self._fail(f"voice identity end_turn failed: {error}")

    # -------------------------------------------------------- consumer side
    def current(self, wall: float | None = None) -> VoiceVerdict:
        """The verdict for the turn a transcript is about to be attributed to.

        Settles an open-but-silent turn on the way out: a hosted transcript
        arrives AFTER the provider's own VAD has closed the turn, so by the time
        anyone asks this question the last frame is usually already older than
        the gap. Settling here is what makes a short utterance verifiable at all
        — without it, a 0.4 s command would sit ``pending`` forever and refuse
        for the wrong reason.
        """

        if not self.enabled:
            return self._disabled_verdict()
        try:
            now = self._wall(wall)
            with self._lock:
                turn = self._turn
                # Deliberately NOT ``and not turn.verified``: a turn that was
                # verified PROVISIONALLY still has its final look owing, and
                # gating this on "unverified" would mean the whole-turn re-verify
                # only ever ran when the NEXT turn started — i.e. never, for the
                # last thing anybody said. That is the 38.5 % FRR path.
                if (
                    turn is not None
                    and self.turn_gap_s
                    and now - turn.last_wall > self.turn_gap_s
                ):
                    self._settle_locked(turn, now)
                return self._verdict
        except Exception as error:  # noqa: BLE001 - a broken gate still refuses
            self._fail(f"voice identity current failed: {error}")
            return VoiceVerdict(
                code=CODE_VERIFY_ERROR,
                passed=False,
                threshold=self.threshold,
                detail=str(error),
            )

    def decide(self, kind: str, wall: float | None = None) -> VoiceArmingDecision:
        """Arming for one ingress class. The emergency class never reads a verdict.

        The short-circuit is not an optimisation. It is the guarantee: for
        :data:`~parcel_robot.realtime.ingress.KIND_EMERGENCY` this method does
        not compute an embedding, does not consult the profile, does not touch
        the DoA and cannot fail — so no state of this object, and no failure
        inside it, can stand between a spoken stop and the latch.
        """

        if not gates_kind(kind):
            return gate_decision(kind, None)
        now = self._wall(wall)
        verdict = self.current(now)
        with self._lock:
            if verdict.passed and verdict.code == CODE_ARMED:
                if verdict.issued_monotonic_s <= 0.0:
                    return self._unbound_verdict_decision(kind, verdict, "has no issue time")
                if now - verdict.issued_monotonic_s > self.verdict_ttl_s:
                    return self._unbound_verdict_decision(kind, verdict, "is stale")
                if verdict.turn <= self._last_consumed_turn:
                    return self._unbound_verdict_decision(kind, verdict, "was already consumed")
                self._last_consumed_turn = verdict.turn
            return gate_decision(kind, verdict)

    @staticmethod
    def _unbound_verdict_decision(
        kind: str,
        verdict: VoiceVerdict,
        failure: str,
    ) -> VoiceArmingDecision:
        return VoiceArmingDecision(
            armed=False,
            code=CODE_VERIFY_ERROR,
            reason=f"the passing speaker verdict {failure} and cannot authorize this command",
            kind=str(kind),
            verdict=verdict,
        )

    def label(self, kind: str, wall: float | None = None) -> SpeakerLabel:
        """Name the speaker of one turn of class ``kind``. Card P2-B.

        The reading half of :meth:`decide`, and deliberately a separate method:
        this one may be called on rows nobody is arming — a robot turn, a system
        note, a transcript that asked for nothing — and it must be impossible for
        such a call to change what the arming half would have said.

        Total. A gate that is mid-failure still returns a label, because a row
        with no label at all is the thing card P2-B exists to remove.
        """

        try:
            verdict = None if not gates_kind(kind) else self.current(wall)
        except Exception:  # noqa: BLE001 - a label may never break its caller
            return speaker_label(kind, None, enrolled=self.enabled)
        return speaker_label(kind, verdict, enrolled=self.enabled)

    def score_buffer(self, payload: bytes) -> float | None:
        """One-shot cosine for a WHOLE buffer, or ``None``. Card A7.

        The pre-upload ear (``realtime/ear_gate.py``) has to ask "is this the
        owner" about audio it is still holding, before any of it goes on the
        wire. That is a different shape from :meth:`observe_frame`, which is a
        streaming turn-cutter whose verdict lands BESIDE a relay that has already
        happened. Both use the same embedder and the same profile; only this one
        owns no state, so a caller cannot move this gate's counters or its
        verdict by asking it a question.

        Never raises and never mutates: a gate that cannot score returns ``None``
        and lets the ear decide what "cannot verify" means (it means push-to-talk
        admission, not a silent pass at some other threshold).
        """

        profile = self._profile
        embedder = self._embedder
        if profile is None or embedder is None or not payload:
            return None
        try:
            embedding = embedder.embed(bytes(payload), self.sample_rate_hz)
            if len(embedding) != profile.dim:
                raise VoiceIdentityError(
                    f"embedder returned {len(embedding)} dimensions and the enrolled "
                    f"profile has {profile.dim}: these are different embedding spaces"
                )
            score = float(profile.score(embedding))
        except Exception as error:  # noqa: BLE001 - an unscorable turn is not a crash
            self._note(f"voice identity: could not score a buffered turn ({error})")
            return None
        return None if math.isnan(score) else score

    def note_rejection(self, wall: float | None = None) -> bool:
        """Count one refused turn; answer whether it may also be SPOKEN.

        The count and the panel event are unconditional — rule 4, the refusal is
        never silent. Only the narration is rate-limited, and it is rate-limited
        here rather than in the whisperer because the whisperer's budget is the
        owner's cost knob and this is a security fact, not chatter.

        **Card P2-B: an unenrolled gate never buys a narration slot.** With no
        profile ``gate_decision`` refuses non-emergency authority, but the boot
        event and snapshot already explain why. This keeps an unenrolled build
        from narrating the same configuration fact on every attempted command.
        The count still moves, because a refusal that happened is a refusal.
        """

        now = self._wall(wall)
        with self._lock:
            self.voice_rejected += 1
            if not self.enabled:
                return False
            last = self._last_narration_at
            if last is not None and now - last < self.narration_interval_s:
                return False
            self._last_narration_at = now
            self.narrations += 1
            return True

    # --------------------------------------------------------- verify engine
    def _settle_locked(self, turn: _Turn, wall: float) -> None:
        """The turn is over. Give it its FINAL verdict and free its audio.

        Three cases, and the middle one is the fix the FAR/FRR measurement
        forced (see :data:`DEFAULT_MIN_UTTERANCE_S`):

        * never verified and long enough ⇒ verify now, on the whole turn;
        * verified provisionally on a fragment, and the turn then grew by
          :data:`REVERIFY_GROWTH_FACTOR` ⇒ **verify again on the whole turn and
          replace the verdict**, because the provisional one was an opinion
          about the first second of a sentence;
        * never verified and too short to embed ⇒ ``too_short``, which does not
          arm. (And still does not gate the latch — nothing here does.)
        """

        if not turn.verified:
            if len(turn.buffer) >= self.floor_utterance_s * self.bytes_per_second:
                self._verify_locked(turn, wall)
            else:
                self.turns_too_short += 1
                self._verdict = VoiceVerdict(
                    code=CODE_TOO_SHORT,
                    passed=False,
                    threshold=self.threshold,
                    seconds=turn.seconds,
                    turn=turn.index,
                    detail=(
                        f"{turn.seconds:.2f}s of audio is below the "
                        f"{self.floor_utterance_s:.2f}s floor a speaker embedding needs"
                    ),
                )
                turn.verifies = MAX_VERIFIES_PER_TURN
        elif (
            turn.verifies < MAX_VERIFIES_PER_TURN
            and turn.verified_bytes
            and len(turn.buffer) >= REVERIFY_GROWTH_FACTOR * turn.verified_bytes
        ):
            self._verify_locked(turn, wall)
        self._tally_locked(turn)
        turn.buffer = bytearray()
        self._turn = None

    def _tally_locked(self, turn: _Turn) -> None:
        """Count the turn ONCE, by its FINAL verdict. Called only from settle.

        Found by the end-to-end proof rather than by a test: counting inside
        :meth:`_verify_locked` counted EMBEDDINGS, so a three-turn session read
        ``turns_verified: 5, voice_accepted: 2`` for one accepted turn — the
        provisional and the final look at the same sentence were two votes. A
        panel number that double-counts is worse than no number, because it
        looks like evidence.
        """

        if turn.verifies == 0:  # pragma: no cover - settle always verifies or refuses
            return
        self.turns_verified += 1
        code = self._verdict.code
        if code == CODE_ARMED:
            self.voice_accepted += 1
        elif code == CODE_REJECTED_SECTOR:
            self.sector_rejected += 1

    def _verify_locked(self, turn: _Turn, wall: float) -> None:
        """Compute ONE embedding for this turn and (re)settle its verdict.

        Called with the lock held, at most :data:`MAX_VERIFIES_PER_TURN` times
        per turn. Everything that can go wrong here — a raising embedder, a NaN
        vector, a model that returns the wrong width — lands on the same answer:
        refuse to arm, count it, say why. There is no branch in this method that
        reaches ``passed=True`` without a finite score at or above the
        configured threshold.
        """

        turn.verifies += 1
        turn.verified_bytes = len(turn.buffer)
        payload = bytes(turn.buffer)
        seconds = len(payload) / self.bytes_per_second
        profile = self._profile
        embedder = self._embedder
        started = time.perf_counter()
        try:
            if profile is None or embedder is None:  # pragma: no cover - guarded by `enabled`
                raise VoiceIdentityError("verification ran with no profile or no embedder")
            embedding = embedder.embed(payload, self.sample_rate_hz)
            if len(embedding) != profile.dim:
                raise VoiceIdentityError(
                    f"embedder returned {len(embedding)} dimensions and the enrolled "
                    f"profile has {profile.dim}: these are different embedding spaces"
                )
            score = profile.score(embedding)
        except Exception as error:  # noqa: BLE001 - a failed verify is a refusal
            elapsed = (time.perf_counter() - started) * 1000.0
            self.verify_errors += 1
            self._record_latency(elapsed)
            self._verdict = VoiceVerdict(
                code=CODE_VERIFY_ERROR,
                passed=False,
                threshold=self.threshold,
                seconds=seconds,
                turn=turn.index,
                verify_ms=elapsed,
                detail=f"speaker verification failed and therefore refused to arm: {error}",
            )
            self._note(
                "voice identity: verification failed on this turn and the turn was "
                f"NOT armed ({error})"
            )
            return
        elapsed = (time.perf_counter() - started) * 1000.0
        self._record_latency(elapsed)
        doa = self._read_doa()
        passed = score >= self.threshold
        if passed:
            self._accept_locked(turn, score, seconds, elapsed, doa, wall)
            return
        # The sector prefilter only ever explains a refusal that the embedding
        # had already earned; it can never overturn a pass. Reporting it as the
        # code is what makes "the television" distinguishable from "a visitor"
        # in the counters.
        if doa is not None and self._sector is not None and sector_contains(
            doa.angle_deg, self._sector[0], self._sector[1]
        ):
            self._verdict = VoiceVerdict(
                code=CODE_REJECTED_SECTOR,
                passed=False,
                score=score,
                threshold=self.threshold,
                seconds=seconds,
                turn=turn.index,
                verify_ms=elapsed,
                doa_deg=doa.angle_deg,
                detail=(
                    f"this turn arrived from {doa.angle_deg}°, inside the rejected "
                    f"sector {self._sector[0]:.0f}°–{self._sector[1]:.0f}°, and the "
                    f"speaker embedding scored {score:.3f} < {self.threshold:.2f}"
                ),
            )
            return
        self._verdict = VoiceVerdict(
            code=CODE_NOT_OWNER,
            passed=False,
            score=score,
            threshold=self.threshold,
            seconds=seconds,
            turn=turn.index,
            verify_ms=elapsed,
            doa_deg=None if doa is None else doa.angle_deg,
            detail=(
                f"the speaker embedding scored {score:.3f}, below the "
                f"{self.threshold:.2f} threshold for the enrolled owner"
            ),
        )

    def _accept_locked(
        self,
        turn: _Turn,
        score: float,
        seconds: float,
        elapsed: float,
        doa: DoaSample | None,
        wall: float,
    ) -> None:
        self._verdict = VoiceVerdict(
            code=CODE_ARMED,
            passed=True,
            score=score,
            threshold=self.threshold,
            seconds=seconds,
            turn=turn.index,
            verify_ms=elapsed,
            doa_deg=None if doa is None else doa.angle_deg,
            detail="the enrolled owner",
            issued_monotonic_s=wall,
        )

    def _read_doa(self) -> DoaSample | None:
        reader = self._doa
        if reader is None or self._sector is None:
            return None
        try:
            return reader.read()
        except Exception as error:  # noqa: BLE001 - a prefilter may never raise
            self._note(f"voice identity: DoA read failed and was ignored ({error})")
            return None

    def _record_latency(self, elapsed_ms: float) -> None:
        self._latencies.append(elapsed_ms)
        if len(self._latencies) > 512:
            del self._latencies[0]
        if self.budget_ms and elapsed_ms > self.budget_ms:
            self.budget_exceeded += 1

    # --------------------------------------------------------------- reporting
    def latency_ms(self) -> dict[str, float]:
        with self._lock:
            values = sorted(self._latencies)
        if not values:
            return {"n": 0, "median": 0.0, "p95": 0.0, "max": 0.0}
        index = min(len(values) - 1, round(0.95 * (len(values) - 1)))
        return {
            "n": len(values),
            "median": round(values[len(values) // 2], 2),
            "p95": round(values[index], 2),
            "max": round(values[-1], 2),
        }

    def snapshot(self) -> dict[str, Any]:
        """What ``/api/state`` shows. ``enabled: false`` is a FACT, not a silence.

        The card asks for the disabled case to be "loudly noted", and the loud
        part is ``reason``: an operator reading a snapshot must be able to tell
        "verification is off because nobody enrolled" from "verification is on
        and everyone passes", which a bare ``enabled: false`` does not.
        """

        with self._lock:
            profile = self._profile
            verdict = self._verdict
            doa = self._doa
        enabled = self.enabled
        return {
            "enabled": enabled,
            "reason": (
                "an enrolled owner profile is loaded; unverified voices cannot arm "
                "a command (the emergency latch is never identity-gated)"
                if enabled
                else "NO ENROLLED OWNER VOICE PROFILE: speaker verification is OFF, "
                "so non-emergency motion is DISARMED. Emergency stop remains "
                "available to anyone. Run tools/enroll_owner_voice.py to enroll."
            ),
            "threshold": self.threshold,
            "profile": None if profile is None else profile.describe(),
            "embedder": None if self._embedder is None else getattr(self._embedder, "name", "?"),
            "turns_seen": self.turns_seen,
            "turns_verified": self.turns_verified,
            "voice_accepted": self.voice_accepted,
            "voice_rejected": self.voice_rejected,
            "turns_too_short": self.turns_too_short,
            "verify_errors": self.verify_errors,
            "sector_rejected": self.sector_rejected,
            "narrations": self.narrations,
            "budget_ms": self.budget_ms,
            "budget_exceeded": self.budget_exceeded,
            "latency_ms": self.latency_ms(),
            "rejected_sector": None if self._sector is None else list(self._sector),
            "doa": None if doa is None else _doa_snapshot(doa),
            "verdict": verdict.as_dict(),
            # Card P2-B. The LABEL beside the verdict, for the ordinary command
            # class, so a panel reader can see what this build is stamping on its
            # rows without deriving it from the code — and can see, in the same
            # blob, that it never blocks.
            "label": speaker_label(
                VOICE_LABEL_KIND, verdict, enrolled=enabled
            ).as_dict(),
        }

    # ------------------------------------------------------------- internals
    def _wall(self, wall: float | None) -> float:
        return self._clock() if wall is None else float(wall)

    def _fail(self, message: str) -> None:
        self.verify_errors += 1
        self._verdict = VoiceVerdict(
            code=CODE_VERIFY_ERROR,
            passed=False,
            threshold=self.threshold,
            detail=message,
        )
        self._note(message)

    def _note(self, message: str) -> None:
        hook = self._on_event
        if hook is None:
            return
        try:
            hook(message)
        except Exception:  # noqa: BLE001,S110 - a noisy observer is not a defect here
            pass


def _doa_snapshot(reader: Any) -> dict[str, Any]:
    getter = getattr(reader, "snapshot", None)
    if callable(getter):
        try:
            return dict(getter())
        except Exception:  # noqa: BLE001 - reporting may never raise
            return {"kind": type(reader).__name__}
    return {"kind": type(reader).__name__}


def iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CODE_ARMED",
    "CODE_DISABLED",
    "CODE_NOT_OWNER",
    "CODE_PENDING",
    "CODE_REJECTED_SECTOR",
    "CODE_SAFETY_NEVER_GATED",
    "CODE_TOO_SHORT",
    "CODE_VERIFY_ERROR",
    "DEFAULT_BUDGET_MS",
    "DEFAULT_FLOOR_UTTERANCE_S",
    "DEFAULT_MAX_UTTERANCE_S",
    "DEFAULT_MIN_UTTERANCE_S",
    "DEFAULT_MODEL_RELATIVE",
    "DEFAULT_NARRATION_INTERVAL_S",
    "DEFAULT_THRESHOLD",
    "DEFAULT_TURN_GAP_S",
    "DEFAULT_VERDICT_TTL_S",
    "DOA_COMMAND_ID",
    "DOA_RESOURCE_ID",
    "LABEL_NOT_OWNER",
    "LABEL_OWNER",
    "LABEL_UNENROLLED",
    "LABEL_UNGATED",
    "LABEL_UNVERIFIED",
    "MAX_VERIFIES_PER_TURN",
    "REVERIFY_GROWTH_FACTOR",
    "SPEAKER_LABELS",
    "VERDICT_CODES",
    "VOICE_LABEL_KIND",
    "VOICE_PROFILE_MODE",
    "VOICE_PROFILE_NAME",
    "VOICE_PROFILE_SCHEMA",
    "XVF3800_PRODUCT_ID",
    "XVF3800_VENDOR_ID",
    "DoaReader",
    "DoaSample",
    "FakeDoaReader",
    "FakeSpeakerEmbedder",
    "OwnerVoiceProfile",
    "SherpaSpeakerEmbedder",
    "SpeakerEmbedder",
    "SpeakerLabel",
    "UsbDoaReader",
    "VoiceArmingDecision",
    "VoiceIdentityError",
    "VoiceIdentityGate",
    "VoiceVerdict",
    "average_embedding",
    "cosine",
    "default_profile_path",
    "gate_decision",
    "gates_kind",
    "iso_now",
    "load_owner_profile",
    "normalize",
    "pcm16_to_floats",
    "rejection_fact",
    "save_owner_profile",
    "sector_contains",
    "speaker_label",
    "unenrolled_label",
]
