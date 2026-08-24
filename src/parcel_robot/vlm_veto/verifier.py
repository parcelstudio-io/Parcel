"""The Qwen3-VL-2B verification seat (card P1-D, work item 1).

What this is for
----------------
PG-3's abstention gate is built from signals that have an absolute scale. Every
one of them is a statement about *evidence* — how loudly the label head answered,
how many frames saw it, how much of it is at standing height. None of them looks
at the picture and asks the question a person would ask: **is that actually a
bench?**

The 2026-08-21 cutover research answered which model gets that seat
(``scrum/20260821/cutover_research/SYNTHESIS.md`` decision 4): **Qwen3-VL-2B**,
a statistical quality tie with the 8B at n=40 across QA / naming /
verification, at 4.4 GB resident instead of 17 GB and 89 ms per answer instead
of 214 ms. ``bench_retrieval.md`` §2 fixed the operating point: the verifier is
asked about the **top candidate's best-view crop** and the query noun, and
``p_yes >= 0.5`` is present.

Subtractive, always
-------------------
The veto can only ever **remove** an admission. It is not a retrieval signal, it
does not rank, and it never promotes a place that the evidence gates refused.
That asymmetry is deliberate and it is why a 2B model is allowed near the
mission path at all: a wrong veto costs a *refusal* of a place the robot could
have reached, which is recoverable by asking again; it can never cause the robot
to set off for the wrong place. A **missing** veto is cheaper still — see
:data:`VETO_UNAVAILABLE` and the abstention module's "unavailable is an ASK"
rule — it costs a question.

The cost is real and it was measured. On P1-D's textured dev-scene fixture the
seat kept 30/40 true crops and vetoed 30/40 decoys; on the seven-place map row 1
it wrongly vetoed 2 of 7 present places. So roughly a quarter of correct
admissions are refused by this signal today. That is the price of 0/8 on the
absent set, and it is the direction to be wrong in.

NEVER IN THE 10 Hz LOOP
-----------------------
Every VLM size measured breaches the 100 ms detector bound *while generating*
(``bench_vlm.md``). This module is therefore never called from the control
loop; :mod:`parcel_robot.vlm_veto.runner` owns that contract and
``tests/test_p1d_vlm_veto.py`` AST-asserts it the way C-1 asserts the camera
producer is out of the loop.

Optional dependency, by construction
------------------------------------
``torch``/``transformers`` are **not** in the shipping ``.parcel`` environment
and this package does not put them there. The import is lazy and lives inside
:meth:`Qwen3VLVerifier.load`; importing :mod:`parcel_robot.vlm_veto` costs
nothing and pulls in no tensor library. A host without the weights gets
:class:`NullVerifier`, which answers :data:`VETO_UNAVAILABLE` — a question, not
a refusal and not a silent pass.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from parcel_robot.perception.abstention import (
    VETO_ABSENT,
    VETO_PRESENT,
    VETO_UNAVAILABLE,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_CROP_PX",
    "MODEL_REPO",
    "NAME_PROMPT",
    "NAME_PROMPT_CLASS_ANCHORED",
    "VERIFY_PROMPT_TEMPLATE",
    "VETO_ABSENT",
    "VETO_PRESENT",
    "VETO_P_YES_PRESENT",
    "VETO_UNAVAILABLE",
    "NameAnswer",
    "NullVerifier",
    "Qwen3VLVerifier",
    "Verifier",
    "VetoAnswer",
    "VetoRequest",
    "active_verifier",
    "parse_yes_no",
    "resolve_weights",
    "use_verifier",
    "warm_up_png",
]

#: The seat, named once. SYNTHESIS decision 4.
MODEL_REPO = "Qwen/Qwen3-VL-2B-Instruct"

#: ``bench_retrieval.md`` §2's operating point, INHERITED not re-derived: the
#: crop is "present" when the yes-token mass is at least this. It is a
#: probability over two single tokens, not a calibrated confidence, and the
#: bench's own ECE numbers are the only calibration evidence that exists.
VETO_P_YES_PRESENT: float = 0.5

#: Verbatim from the 2026-08-21 bench (``bench-vlm/code/common.py::q_verify``).
#: Kept character-identical on purpose: the 89 ms / n=40 quality numbers this
#: seat was chosen on were measured with THIS sentence, and a reworded prompt is
#: an unmeasured model.
VERIFY_PROMPT_TEMPLATE = (
    "Is the main object in this image a {noun}? "
    "Answer with exactly one word: yes or no."
)

#: Likewise verbatim (``common.py::Q_NAME``) — the naming-accuracy figure the
#: k-gate is sized against was measured with this sentence.
NAME_PROMPT = "What is the main object in this image? Answer with one to three words."

# ---- CARD NM-1 (task_18) — the prompt arm -----------------------------------
#
# P1-D measured 45.0 % naming accuracy against the research's 82-87 % and read
# the residue correctly: the wrong answers are not hallucinations, they are
# DESCRIPTIONS OF GEOMETRY ("yellow cylinder" for a bollard, "black rectangle"
# for a bicycle, "pole" for a traffic light). :data:`NAME_PROMPT` asks what the
# object *is* and accepts a description as an answer, so a model looking at a
# textured MuJoCo primitive gives the honest one.
#
# This prompt asks the same question with the description arm closed. It is an
# ARM, not a replacement: :data:`NAME_PROMPT` stays the default everywhere,
# because the 82-87 % / 89 ms numbers the seat was chosen on were measured with
# that sentence and a reworded prompt is an unmeasured model. NM-1's status doc
# reports both on the same 40 crops.
NAME_PROMPT_CLASS_ANCHORED = (
    "What kind of object is the main object in this image? Answer with the "
    "common noun for the object, one to three words. Do not describe its "
    "colour or shape."
)
# ---- END CARD NM-1 (task_18) — the prompt arm -------------------------------

#: Longest edge a crop is resized to before it reaches the model. A best-view
#: crop of a lamppost can be 1000+ px tall and the vision tower will happily
#: tokenize all of it; the bench ran at native crop size and measured 89 ms, so
#: this is a ceiling that protects the latency budget, not a quality choice.
DEFAULT_MAX_CROP_PX = 896


@dataclass(frozen=True, slots=True)
class VetoRequest:
    """One question for the verifier: this crop, that noun.

    ``crop_png`` is the **best-view** crop's encoded bytes. Best-view and not an
    average: ``bench_retrieval.md`` measured that averaging views degrades, and
    C-2 already keeps exactly one bounded thumbnail per entry
    (``MapEntry.thumbnail``) for this reason.
    """

    noun: str
    crop_png: bytes | None = None
    place_id: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        text = " ".join(str(self.noun).strip().split())
        if not text:
            raise ValueError("a veto request must name a noun")
        object.__setattr__(self, "noun", text[:160])
        object.__setattr__(self, "place_id", str(self.place_id)[:128])
        object.__setattr__(self, "label", str(self.label)[:160])
        if self.crop_png is not None and not isinstance(self.crop_png, (bytes, bytearray)):
            raise TypeError("VetoRequest.crop_png must be bytes")

    @property
    def prompt(self) -> str:
        return VERIFY_PROMPT_TEMPLATE.format(noun=self.noun)


@dataclass(frozen=True, slots=True)
class VetoAnswer:
    """What the verifier said, and how sure it was.

    ``verdict`` is one of :data:`VETO_PRESENT`, :data:`VETO_ABSENT`,
    :data:`VETO_UNAVAILABLE`. ``p_yes`` is ``None`` whenever the verdict is
    unavailable or the model could not be scored — never ``0.0``, because a
    missing probability and a confident "no" are different facts and only one of
    them is evidence.
    """

    verdict: str
    p_yes: float | None = None
    latency_ms: float = 0.0
    model: str = ""
    answer_text: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in (VETO_PRESENT, VETO_ABSENT, VETO_UNAVAILABLE):
            raise ValueError(f"unknown veto verdict {self.verdict!r}")
        if self.p_yes is not None:
            value = float(self.p_yes)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("VetoAnswer.p_yes must be a probability or None")
            object.__setattr__(self, "p_yes", value)
        if not math.isfinite(float(self.latency_ms)) or float(self.latency_ms) < 0.0:
            raise ValueError("VetoAnswer.latency_ms must be a non-negative number")

    @property
    def vetoes(self) -> bool:
        """Does this answer REMOVE an admission? Only an explicit absent does."""

        return self.verdict == VETO_ABSENT

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "p_yes": self.p_yes,
            "latency_ms": round(float(self.latency_ms), 3),
            "model": self.model,
            "answer_text": self.answer_text,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class NameAnswer:
    """A vocabulary-free name proposal for an unnamed place. Never authority.

    This is the ~82-87 %-accurate output of ``SYNTHESIS.md`` decision 5, which is
    to say roughly one in seven of these is wrong. It becomes vocabulary only
    through :mod:`parcel_robot.online_map.naming`'s k-gate.
    """

    text: str
    latency_ms: float = 0.0
    model: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", " ".join(str(self.text).strip().split())[:96])


class Verifier(Protocol):
    """The seat's shape. Two questions, one model, no retrieval."""

    name: str

    def verify(self, request: VetoRequest) -> VetoAnswer:
        """Is the crop's main object a ``request.noun``?"""

    def describe(self, crop_png: bytes | None, *, prompt: str | None = None) -> NameAnswer:
        """What is the crop's main object called? Idle-time batch use only.

        ``prompt`` (card NM-1) overrides :data:`NAME_PROMPT` for a measurement
        arm. Keyword-only and defaulting to ``None`` so every existing caller —
        ``online_map.naming.run_naming_pass``, ``VetoRunner.run_batch`` — asks
        exactly the sentence the seat's accuracy was measured with.
        """


class NullVerifier:
    """No model on this host. Every answer is :data:`VETO_UNAVAILABLE`.

    This is the default, and it is why enabling the ``vlm_veto`` signal forces
    ``ask_below_threshold``: with no verifier the gate degrades to *asking*, not
    to a silent admit (which would be the gate dying quietly) and not to a
    blanket refusal (which is the 0/18 this card exists to end).
    """

    name = "null"

    def verify(self, request: VetoRequest) -> VetoAnswer:
        return VetoAnswer(
            VETO_UNAVAILABLE,
            model=self.name,
            detail="no VLM verifier is installed on this host",
        )

    def describe(self, crop_png: bytes | None, *, prompt: str | None = None) -> NameAnswer:
        del prompt
        return NameAnswer("", model=self.name, detail="no VLM verifier is installed")


def warm_up_png(edge: int = 64) -> bytes:
    """A synthetic RGB PNG for the throwaway warm-up answer.

    Stdlib only (``zlib`` + ``struct`` + ``crc32``, the same twenty lines
    ``camera_channel.ingress`` uses) so that warming a seat needs no image
    library and no fixture on disk. The content is a gradient rather than a flat
    colour because a solid image can short-circuit a vision tower's patch
    encoding and warm less of it than a real crop would.
    """

    import binascii
    import struct
    import zlib

    edge = max(8, int(edge))
    rows = bytearray()
    for y in range(edge):
        rows.append(0)  # PNG filter type 0
        for x in range(edge):
            rows.extend(((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", edge, edge, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def parse_yes_no(text: str) -> str | None:
    """First word only, ``yes``/``no``, else ``None``.

    Verbatim semantics from ``bench-vlm/code/common.py::parse_yesno``: anything
    that is not a bare yes or no is *not an answer*, and a model that rambled is
    treated as having said nothing rather than being keyword-scraped for a hint.
    """

    tokens = "".join(
        ch if ch.isalnum() or ch.isspace() else " " for ch in str(text).lower()
    ).split()
    if tokens and tokens[0] in ("yes", "no"):
        return tokens[0]
    return None


def resolve_weights(
    repo: str = MODEL_REPO, *, caches: Sequence[str | os.PathLike[str]] = ()
) -> str | None:
    """Newest local snapshot of ``repo`` in any HF-style cache, or ``None``.

    Searched in order: explicit ``caches``, then ``PARCEL_VLM_WEIGHTS`` (a
    direct snapshot path), then ``HF_HOME``/``HF_HUB_CACHE``, then
    ``~/.cache/huggingface/hub``. Nothing is downloaded here — a download is a
    deliberate act by the operator or by this card's bench script, not a side
    effect of an import.
    """

    direct = os.environ.get("PARCEL_VLM_WEIGHTS", "").strip()
    if direct and Path(direct).is_dir():
        return direct
    roots: list[Path] = [Path(c) for c in caches]
    for var in ("HF_HUB_CACHE", "HF_HOME"):
        value = os.environ.get(var, "").strip()
        if value:
            root = Path(value)
            roots.append(root if root.name == "hub" else root / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    folder = "models--" + repo.replace("/", "--")
    for root in roots:
        snapshots = root / folder / "snapshots"
        if not snapshots.is_dir():
            continue
        found = sorted(p for p in snapshots.iterdir() if p.is_dir())
        if found:
            return str(found[-1])
    return None


class Qwen3VLVerifier:
    """The real seat. Lazy, GPU-first, and refusing to pretend on CPU.

    P0-C established that CUDA is a given on this host (onnxruntime-gpu 1.29
    with the provider honoured). A 2B VLM decoding on CPU is not a slower
    version of this seat, it is a different one — the 89 ms number that bought
    the seat is a GPU number — so ``device="cuda"`` is the default and a CPU
    fallback is something the caller has to ask for by name.
    """

    name = "qwen3-vl-2b"

    def __init__(
        self,
        weights: str | os.PathLike[str] | None = None,
        *,
        device: str = "cuda",
        dtype: str = "float16",
        max_crop_px: int = DEFAULT_MAX_CROP_PX,
    ) -> None:
        self._weights = str(weights) if weights is not None else None
        self._device = str(device)
        self._dtype = str(dtype)
        self._max_crop_px = max(64, int(max_crop_px))
        self._lock = threading.RLock()
        self._model: Any = None
        self._proc: Any = None
        self._yes_ids: set[int] = set()
        self._no_ids: set[int] = set()
        self._torch: Any = None
        self._image_cls: Any = None

    # -- loading ------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Import torch, resolve the weights, put the model on the GPU.

        The import is HERE and nowhere else. Nothing in ``parcel_robot`` gains a
        tensor dependency by importing this package; a host that never calls
        ``load()`` never pays for one.
        """

        with self._lock:
            if self._model is not None:
                return
            import torch
            from PIL import Image
            from transformers import (
                AutoModelForImageTextToText,
                AutoProcessor,
            )

            path = self._weights or resolve_weights()
            if not path:
                raise FileNotFoundError(
                    f"no local snapshot of {MODEL_REPO}; set PARCEL_VLM_WEIGHTS or "
                    "populate an HF cache. Nothing is downloaded implicitly."
                )
            dtype = getattr(torch, self._dtype)
            proc = AutoProcessor.from_pretrained(path)
            model = AutoModelForImageTextToText.from_pretrained(
                path, dtype=dtype, device_map=self._device
            ).eval()
            tok = getattr(proc, "tokenizer", proc)
            for word in ("yes", "Yes", "YES", " yes", " Yes"):
                ids = tok.encode(word, add_special_tokens=False)
                if len(ids) == 1:
                    self._yes_ids.add(ids[0])
            for word in ("no", "No", "NO", " no", " No"):
                ids = tok.encode(word, add_special_tokens=False)
                if len(ids) == 1:
                    self._no_ids.add(ids[0])
            # NO STREAM PRIORITY. An earlier draft of this card created a
            # "low-priority" stream here and claimed the detector would preempt
            # it. That claim was FALSE and the verifier caught it:
            # ``torch.cuda.Stream.priority_range()`` returns ``(0, -1)`` on this
            # driver — least-priority FIRST — so ``priority=low`` is 0, which is
            # exactly the default stream's priority. CUDA has no priority BELOW
            # default, so there was nothing for the detector to preempt and the
            # stream bought nothing at all.
            #
            # The premise was doubly wrong: it rested on the veto sharing a CUDA
            # context with the detector, and P1-A's out-of-process detector
            # daemon removes even that. So the veto is admitted on a MEASURED
            # latency budget instead (see ``runner.VetoRunner``), which is a
            # claim about time that can be checked rather than a claim about
            # scheduling that cannot.
            self._torch = torch
            self._image_cls = Image
            self._proc = proc
            self._model = model

    def close(self) -> None:
        with self._lock:
            self._model = None
            self._proc = None
            if self._torch is not None:
                try:
                    self._torch.cuda.empty_cache()
                except Exception as exc:  # noqa: BLE001 - teardown must not raise
                    logger.debug("vlm_veto: empty_cache on close failed (%s)", exc)

    # -- inference ----------------------------------------------------------

    def _image(self, crop_png: bytes | None) -> Any:
        import io

        if not crop_png:
            return None
        image = self._image_cls.open(io.BytesIO(bytes(crop_png))).convert("RGB")
        longest = max(image.size)
        if longest > self._max_crop_px:
            scale = self._max_crop_px / float(longest)
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            )
        return image

    def _generate(
        self, image: Any, prompt: str, *, max_new_tokens: int, want_probs: bool
    ) -> tuple[str, float, Any]:
        torch = self._torch
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self._proc.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._proc(text=[text], images=[image], return_tensors="pt")
        dtype = getattr(torch, self._dtype)
        moved = {
            key: (
                value.to(self._device, dtype)
                if torch.is_floating_point(value)
                else value.to(self._device)
            )
            for key, value in inputs.items()
        }
        n_in = moved["input_ids"].shape[1]
        if self._device.startswith("cuda"):
            torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.no_grad():
            out = self._model.generate(
                **moved,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                output_scores=want_probs,
                return_dict_in_generate=want_probs,
            )
        if self._device.startswith("cuda"):
            torch.cuda.synchronize()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        sequences = out.sequences if want_probs else out
        answer = self._proc.batch_decode(
            sequences[:, n_in:], skip_special_tokens=True
        )[0].strip()
        scores = out.scores[0] if want_probs and getattr(out, "scores", None) else None
        return answer, elapsed_ms, scores

    def verify(self, request: VetoRequest) -> VetoAnswer:
        """Ask the seat whether the crop's main object is the query noun."""

        image = None
        try:
            self.load()
            image = self._image(request.crop_png)
        except Exception as exc:  # noqa: BLE001 - an unloadable seat is unavailable
            return VetoAnswer(
                VETO_UNAVAILABLE, model=self.name, detail=f"load failed: {exc}"
            )
        if image is None:
            return VetoAnswer(
                VETO_UNAVAILABLE,
                model=self.name,
                detail="no best-view crop on this place; nothing to look at",
            )
        with self._lock:
            try:
                answer, ms, scores = self._generate(
                    image, request.prompt, max_new_tokens=4, want_probs=True
                )
            except Exception as exc:  # noqa: BLE001 - inference failure is unavailable
                return VetoAnswer(
                    VETO_UNAVAILABLE, model=self.name, detail=f"generate failed: {exc}"
                )
        p_yes: float | None = None
        if scores is not None and self._yes_ids and self._no_ids:
            probs = self._torch.softmax(scores[0].float(), dim=-1)
            mass_yes = sum(probs[i].item() for i in self._yes_ids)
            mass_no = sum(probs[i].item() for i in self._no_ids)
            if mass_yes + mass_no > 1e-9:
                p_yes = mass_yes / (mass_yes + mass_no)
        word = parse_yes_no(answer)
        # The PROBABILITY decides when we have one, because it is the quantity
        # the bench's operating point was set on. The word is the fallback, and
        # a model that answered neither yes nor no has not answered: that is
        # unavailable, not a veto. A veto has to be an affirmative "no".
        if p_yes is not None:
            verdict = VETO_PRESENT if p_yes >= VETO_P_YES_PRESENT else VETO_ABSENT
        elif word == "yes":
            verdict = VETO_PRESENT
        elif word == "no":
            verdict = VETO_ABSENT
        else:
            verdict = VETO_UNAVAILABLE
        return VetoAnswer(
            verdict,
            p_yes=p_yes,
            latency_ms=ms,
            model=self.name,
            answer_text=answer[:96],
        )

    def describe(self, crop_png: bytes | None, *, prompt: str | None = None) -> NameAnswer:
        """Name the crop's main object. **Idle-time batch only** — see runner.

        ``prompt`` is card NM-1's measurement seam: ``None`` asks
        :data:`NAME_PROMPT`, the sentence every accuracy number in this repo was
        measured with. Nothing on a product path passes it.
        """

        try:
            self.load()
            image = self._image(crop_png)
        except Exception as exc:  # noqa: BLE001
            return NameAnswer("", model=self.name, detail=f"load failed: {exc}")
        if image is None:
            return NameAnswer("", model=self.name, detail="no crop")
        with self._lock:
            try:
                answer, ms, _ = self._generate(
                    image,
                    prompt if prompt else NAME_PROMPT,
                    max_new_tokens=12,
                    want_probs=False,
                )
            except Exception as exc:  # noqa: BLE001
                return NameAnswer("", model=self.name, detail=f"generate failed: {exc}")
        return NameAnswer(answer, latency_ms=ms, model=self.name)


# --------------------------------------------------------- process default ---
#
# Same house convention as ``active_abstention_policy`` and
# ``active_perception_chain``: one installed seat per process, named in one
# place, so "what is wired" is a question with an answer.

_VERIFIER_LOCK = threading.Lock()
_VERIFIER: Any = None


def active_verifier() -> Any:
    """The installed seat. :class:`NullVerifier` until something installs one."""

    global _VERIFIER
    with _VERIFIER_LOCK:
        if _VERIFIER is None:
            _VERIFIER = NullVerifier()
        return _VERIFIER


def use_verifier(verifier: Any) -> None:
    """Install (or clear, with ``None``) the process-default seat."""

    global _VERIFIER
    with _VERIFIER_LOCK:
        _VERIFIER = verifier
