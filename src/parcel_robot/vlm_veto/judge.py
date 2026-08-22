"""The correctness judge — an independent seat that vocabulary must pass (NM-1).

Why k-consistency is not a correctness filter
---------------------------------------------
C-2 promotes a proposed name after **k = 3 independent visits agree**. The
research that sized that gate assumed naming is right about 82-87 % of the time,
so a wrong name would rarely survive three separate approaches. P1-D measured the
real rate on this world: **45.0 % (18/40)** — and, worse, measured *why* the
residue is dangerous. The wrong answers are not random hallucinations, they are
descriptions of geometry:

    bollard        -> "yellow cylinder"  (x4)
    traffic light  -> "pole"             (x3)
    bicycle        -> "black rectangle"

A model that is wrong for a *structural* reason is wrong the same way every
time, from every angle. On P1-D's full-resolution arm three independent visits
agreed on ``pole`` for a traffic light and on ``yellow cylinder`` for a bollard,
and **both were promoted into** ``known_places()``: 2 promotions, 2 false
(``scrum/20260822/task_9/evidence/row5_kgate_fullres.json``). The k-gate is a
*consistency* filter, and a systematically wrong model is systematically
consistent. The shipping 64-px path scored 0 false only because nothing reaches
k at that size — safe because blind.

So NM-1 adds a second condition that a consistency filter cannot supply: an
**independent judge**.

What makes this judge independent
---------------------------------
It is the open-vocabulary DETECTOR the product already ships — OWLv2-B16 through
:mod:`parcel_robot.detection_adapter.owlv2_onnx`. Different architecture,
different training data, no shared decoder with the VLM, and it is asked a
different question: not "what is this?" but "**where is a `<name>` in this
picture?**". The VLM cannot collude with it, because the VLM's answer is not an
input to it — only the *string* is. When the VLM says "yellow cylinder" and the
detector cannot find a yellow cylinder anywhere in the crop, the disagreement is
information; when both agree the name has survived two unrelated ways of being
wrong.

The rule, and the floor
-----------------------
A proposed name becomes vocabulary only when

1. k independent visits agree (unchanged — C-2 still owns that), **and**
2. this judge fires on the proposed name over the entry's best view with a label
   strength at or above :data:`JUDGE_MIN_SCORE`.

:data:`JUDGE_MIN_SCORE` is **adopted, not fitted**: it is OWLv2's own shipped
``DEFAULT_OWLV2_THRESHOLD``, the score below which this detector's boxes are not
called detections anywhere else in this codebase. Fitting a floor on the same
crops the gate is then judged on is the mistake PG-3's module docstring is
about, and this card did not make it. It is pre-registered in
``scrum/20260822/task_18/NM1_PREREGISTRATION.md`` §2 before the first crop ran.

Unavailable is a HOLD, never a rejection
----------------------------------------
The prototype rule is ask-over-refuse and **no new fail-closed defaults**. So:

* no judge configured  -> the naming pass behaves exactly as it did before this
  card. Flag-off identity, tested.
* a judge that cannot answer (no weights, no execution provider, no crop, the
  env switch off) -> :data:`JUDGE_UNAVAILABLE`, and the name **holds** at
  ``vlm_proposed``. It is not refused, it is not admitted, and the next pass
  tries again. A hypothesis that could not be checked stays a hypothesis.
* the judge answers and disagrees -> :data:`JUDGE_REJECT`, and the name stays
  ``vlm_proposed`` for as long as that stays true. It never enters
  ``known_places()``, which is the sentence the card is made of.

No new config surface
---------------------
The judge is on exactly when the real detector is on: it honours
``PARCEL_OWLV2_ONNX`` and ``PARCEL_OWLV2_DIR`` through
``detection_adapter.owlv2_onnx``'s own resolution, and adds no key of its own.

The one variable this module does own is :data:`JUDGE_FLOOR_ENV`
(``PARCEL_NM1_JUDGE_FLOOR``), and it exists for **one** purpose: reproducing
NM-1's floor sweep (``NM1_STATUS.md`` §3.2), which is a *negative* result — no
floor separates on the dev fixture. It is unset everywhere in this repo, in
every config and in every launcher, and the shipped floor is
:data:`JUDGE_MIN_SCORE` and nothing else; ``tests/test_nm1_*`` pins both facts.
Read the warning in :func:`configured_floor` before using it: a floor chosen by
sweeping the same crops the gate is then judged on is a fitted threshold, which
is the mistake PG-3's module docstring is about and the one this card did not
make.
That is deliberate — the two blocks that could have carried a naming key
(``perception.online_map`` in the runtime, ``perception.abstention`` in
``AbstentionPolicy``) both belong to other cards and both hard-error on unknown
keys.

NEVER ON THE CONTROL THREAD
---------------------------
Same rule as the VLM seat and for the same measured reason: OWLv2 is 43-85 ms
per call on this host and it holds a mission lease for person-shaped phrases.
:meth:`OwlV2NamingJudge.judge` refuses to run on a thread that has declared
itself the 10 Hz loop (:func:`~parcel_robot.perception_abstention.in_control_thread`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from parcel_robot.perception_abstention import (
    ControlLoopViolation,
    in_control_thread,
)

logger = logging.getLogger(__name__)

__all__ = [
    "JUDGE_ACCEPT",
    "JUDGE_MIN_SCORE",
    "JUDGE_REJECT",
    "JUDGE_UNAVAILABLE",
    "JudgeVerdict",
    "NamingJudge",
    "NullNamingJudge",
    "OwlV2NamingJudge",
    "active_naming_judge",
    "default_naming_judge",
    "use_naming_judge",
]

#: The judge fired on the proposed name at or above the floor. The ONLY answer
#: that lets a k-agreed name become vocabulary.
JUDGE_ACCEPT = "accept"
#: The judge looked and did not find the proposed name. The name stays a
#: hypothesis — ``vlm_proposed`` — and never reaches ``known_places()``.
JUDGE_REJECT = "reject"
#: The judge could not be consulted. **Not a rejection**: the name HOLDS at
#: ``vlm_proposed`` and the next pass asks again. See the module docstring.
JUDGE_UNAVAILABLE = "unavailable"

#: PRE-REGISTERED FLOOR (``NM1_PREREGISTRATION.md`` §2), **adopted, not fitted**:
#: it is ``detection_adapter.owlv2_onnx.DEFAULT_OWLV2_THRESHOLD``. It is written
#: as a literal rather than imported so that importing this module costs no
#: detector import, and ``test_nm1_*`` pins the two together so they cannot
#: drift. Below this score OWLv2's boxes are not called detections anywhere else
#: in this codebase, and a name the detector cannot see is not a name the robot
#: may say out loud.
JUDGE_MIN_SCORE: float = 0.10

#: Env override for the floor, for a sweep. Absent means :data:`JUDGE_MIN_SCORE`.
JUDGE_FLOOR_ENV = "PARCEL_NM1_JUDGE_FLOOR"


def configured_floor(default: float = JUDGE_MIN_SCORE) -> float:
    """The floor in force, honouring :data:`JUDGE_FLOOR_ENV`.

    A malformed value keeps the pre-registered floor and says so, rather than
    guessing — a gate running at an unintended threshold is exactly the failure
    a "provisional" number invites.
    """

    raw = os.environ.get(JUDGE_FLOOR_ENV, "").strip()
    if not raw:
        return float(default)
    logger.warning(
        "%s=%r overrides the pre-registered floor %s. NM-1 measured a full sweep "
        "(NM1_STATUS.md 3.2) and found NO floor that separates on the dev "
        "fixture: at every value the detector accepts the VLM's wrong names more "
        "often than the true class names. A floor fitted on the crops the gate is "
        "judged by is a fitted threshold. Use this for a sweep, not for shipping.",
        JUDGE_FLOOR_ENV,
        raw,
        default,
    )
    try:
        value = float(raw)
    except ValueError:
        logger.warning("bad %s=%r; keeping the floor at %s", JUDGE_FLOOR_ENV, raw, default)
        return float(default)
    if not 0.0 <= value <= 1.0:
        logger.warning("%s=%r is not a score; keeping %s", JUDGE_FLOOR_ENV, raw, default)
        return float(default)
    return value


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """One judgement, immutable, with everything needed to argue about it later.

    ``strength`` is the detector's own label score for the proposed name over
    this crop, or ``None`` when the judge could not answer — never ``0.0``,
    because "the detector looked and saw nothing" and "the detector was never
    asked" are different facts and only one of them is evidence. Same rule
    :class:`~parcel_robot.vlm_veto.verifier.VetoAnswer` keeps for ``p_yes``.
    """

    outcome: str
    name: str
    entry_id: str = ""
    strength: float | None = None
    floor: float = JUDGE_MIN_SCORE
    model: str = ""
    detail: str = ""
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.outcome not in (JUDGE_ACCEPT, JUDGE_REJECT, JUDGE_UNAVAILABLE):
            raise ValueError(f"unknown judge outcome {self.outcome!r}")
        if self.strength is not None:
            value = float(self.strength)
            if not 0.0 <= value <= 1.0:
                raise ValueError("JudgeVerdict.strength must be a score or None")
            object.__setattr__(self, "strength", value)
        if self.outcome == JUDGE_ACCEPT and self.strength is None:
            raise ValueError("an accepting judge must report the strength it accepted on")

    @property
    def accepted(self) -> bool:
        """May this name be promoted? The one question the naming pass asks."""

        return self.outcome == JUDGE_ACCEPT

    @property
    def rejected(self) -> bool:
        return self.outcome == JUDGE_REJECT

    @property
    def unavailable(self) -> bool:
        return self.outcome == JUDGE_UNAVAILABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "name": self.name,
            "entry_id": self.entry_id,
            "strength": self.strength,
            "floor": self.floor,
            "model": self.model,
            "detail": self.detail,
            "latency_ms": round(float(self.latency_ms), 3),
        }


class NamingJudge(Protocol):
    """The judge's shape. One question, one answer, no retrieval."""

    name: str

    def judge(
        self, name: str, crop_png: bytes | None, *, entry_id: str = ""
    ) -> JudgeVerdict:
        """Does ``crop_png`` contain a ``name``?"""


class NullNamingJudge:
    """No judge on this host. Every answer is :data:`JUDGE_UNAVAILABLE`.

    Which is a HOLD, not a rejection: a name it cannot check keeps accruing
    visits and is re-examined by the next pass. Installing this deliberately is
    how an operator says "check nothing, promote nothing" without turning the
    naming pass into a refusal machine.
    """

    name = "null"

    def judge(
        self, name: str, crop_png: bytes | None, *, entry_id: str = ""
    ) -> JudgeVerdict:
        del crop_png
        return JudgeVerdict(
            JUDGE_UNAVAILABLE,
            name=name,
            entry_id=entry_id,
            model=self.name,
            detail="no correctness judge is installed on this host",
        )


class OwlV2NamingJudge:
    """OWLv2 as the independent judge. Lazy, and honest when it cannot answer.

    The detector is built once, on the first judgement, and is deliberately
    constructed with a **zero threshold** so that this class — and not the
    detector's own default — decides what the floor is and can report the raw
    strength it decided on. A gate whose threshold is hidden inside a dependency
    is a gate nobody can sweep.
    """

    name = "owlv2"

    def __init__(
        self,
        *,
        floor: float | None = None,
        weights_dir: Any = None,
        require_env: bool = True,
        detector: Any = None,
    ) -> None:
        self._floor = configured_floor() if floor is None else float(floor)
        self._weights_dir = weights_dir
        self._require_env = bool(require_env)
        self._detector = detector
        self._attempts = 1 if detector is not None else 0
        self._lock = threading.RLock()
        self._unavailable_detail = ""

    @property
    def floor(self) -> float:
        return self._floor

    @property
    def loaded(self) -> bool:
        return self._detector is not None

    def load(self) -> bool:
        """Build the detector once. Returns whether a judge is available.

        Never raises: an unbuildable judge is :data:`JUDGE_UNAVAILABLE`, which
        holds names rather than rejecting them.
        """

        with self._lock:
            if self._detector is not None:
                return True
            # Correction pass. This used to latch on ``self._tried`` and never
            # retry, which made the module's own promise — "unavailable HOLDS
            # the name and the next pass tries again" — true of the ASK and
            # FALSE of the build: one transient failure (a GPU busy at startup,
            # weights still downloading, the env switch flipped a second later)
            # retired the judge for the life of the process, and every name
            # after that held forever while the log said "will retry".
            # ``load_owlv2_detector`` returns ``None`` cheaply when the weights
            # or the provider are absent, so retrying costs a stat and a
            # provider probe on an idle-time pass. The counter exists only so
            # the warning is logged once instead of once per entry per pass.
            self._attempts += 1
            try:
                from parcel_robot.detection_adapter.owlv2_onnx import (
                    load_owlv2_detector,
                )

                self._detector = load_owlv2_detector(
                    self._weights_dir,
                    threshold=0.0,
                    require_env=self._require_env,
                )
            except Exception as exc:  # noqa: BLE001 - an unbuildable judge holds
                self._unavailable_detail = f"judge could not be built: {exc}"
                self._log_once(self._unavailable_detail)
                return False
            if self._detector is None:
                self._unavailable_detail = (
                    "OWLv2 unavailable (weights, provider or PARCEL_OWLV2_ONNX)"
                )
                self._log_once(self._unavailable_detail)
                return False
            return True

    def _log_once(self, detail: str) -> None:
        """Warn on the first failed build, then stay quiet but keep retrying."""

        if self._attempts <= 1:
            logger.warning("nm1 judge: %s", detail)
        else:
            logger.debug("nm1 judge: %s (attempt %d)", detail, self._attempts)

    @property
    def attempts(self) -> int:
        """How many times a build has been tried. Retries are not latched."""

        return self._attempts

    def judge(
        self, name: str, crop_png: bytes | None, *, entry_id: str = ""
    ) -> JudgeVerdict:
        if in_control_thread():
            raise ControlLoopViolation(
                "the 10 Hz control thread may not run the naming judge; OWLv2 is "
                "43-85 ms per call on this host and takes a mission lease for "
                "person-shaped phrases"
            )
        text = " ".join(str(name).split())
        if not text:
            return self._unavailable(text, entry_id, "a judgement needs a name")
        if not crop_png:
            return self._unavailable(text, entry_id, "no crop to look at")
        if not self.load():
            return self._unavailable(
                text, entry_id, self._unavailable_detail or "judge unavailable"
            )
        try:
            rgb = _decode_png_rgb(crop_png)
        except Exception as exc:  # noqa: BLE001 - an undecodable crop is unavailable
            return self._unavailable(text, entry_id, f"crop could not be decoded: {exc}")
        started = time.perf_counter()
        try:
            detections = self._detector.detect(
                rgb=rgb, depth=None, seg=None, query=[text]
            )
        except Exception as exc:  # noqa: BLE001 - a broken judge holds, never rejects
            return self._unavailable(text, entry_id, f"judge raised: {exc}")
        elapsed = (time.perf_counter() - started) * 1000.0
        strength = 0.0
        for detection in detections:
            score = float(getattr(detection, "score", 0.0))
            strength = max(strength, score)
        outcome = JUDGE_ACCEPT if strength >= self._floor else JUDGE_REJECT
        return JudgeVerdict(
            outcome,
            name=text,
            entry_id=entry_id,
            strength=strength,
            floor=self._floor,
            model=self.name,
            latency_ms=elapsed,
            detail="" if outcome == JUDGE_ACCEPT else "below the pre-registered floor",
        )

    def _unavailable(self, name: str, entry_id: str, detail: str) -> JudgeVerdict:
        return JudgeVerdict(
            JUDGE_UNAVAILABLE,
            name=name,
            entry_id=entry_id,
            floor=self._floor,
            model=self.name,
            detail=detail,
        )


def _decode_png_rgb(crop_png: bytes) -> Any:
    """PNG bytes -> an HxWx3 uint8 RGB array, for the detector.

    ``cv2`` is imported HERE and nowhere near module scope: it is an optional
    dependency (P1-A's sanctioned install put it on this host) and a judge is
    already an opt-in. Without it the judge answers ``unavailable``, which HOLDS
    names rather than rejecting them.
    """

    import cv2
    import numpy as np

    buffer = np.frombuffer(bytes(crop_png), dtype=np.uint8)
    bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("cv2 could not decode the crop")
    return bgr[:, :, ::-1].copy()


# --------------------------------------------------------- process default ---
#
# The same house convention as ``active_verifier`` / ``active_abstention_policy``
# / ``active_perception_chain``: one installed judge per process, named in one
# place, so "what is checking the vocabulary" is a question with an answer.

_JUDGE_LOCK = threading.Lock()
_JUDGE: Any = None


def default_naming_judge(*, require_env: bool = True, floor: float | None = None) -> Any:
    """A judge built from what this host has, or ``None`` if it has nothing.

    ``None`` means "no judge configured", and the naming pass then behaves
    exactly as it did before card NM-1 — flag-off identity, not a new refusal.
    """

    judge = OwlV2NamingJudge(require_env=require_env, floor=floor)
    if not judge.load():
        return None
    return judge


def active_naming_judge() -> Any:
    """The installed judge, or ``None``. Nothing is built implicitly."""

    with _JUDGE_LOCK:
        return _JUDGE


def use_naming_judge(judge: Any) -> None:
    """Install (or clear, with ``None``) the process-wide correctness judge."""

    global _JUDGE
    with _JUDGE_LOCK:
        _JUDGE = judge
