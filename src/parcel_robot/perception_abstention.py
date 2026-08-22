"""Calibrated abstention for the perception-side place check (card PG-3).

Why this module exists
----------------------
R20 made Parcel refuse unknown places honestly — but it refuses *because the
chain checks a closed label set* (``navigation.goals.admit_navigation_place``,
fed by the simulator's own scene sidecar). Delete the labeled world and that
capability disappears with it. This module is the perception-side replacement:
the same verdict, earned from what the sensors actually observed.

The measurement that forced the design
--------------------------------------
2026-08-21 mapping bench (``scrum/20260821/perception/bench_mapping.md``), and
PG-3's own extended re-run over the same 120 rendered RGB-D frames:

* SigLIP-2 text→place cosine over a real fused map spans **0.049–0.135** for
  29 present queries and **0.054–0.107** for 20 absent ones. The ranges
  overlap; **no threshold separates them.** The best single cosine threshold
  costs 3 false accepts and 9 false rejects out of 49.
* This is not a tuning problem. ``argmax`` over a similarity has **no null**:
  a ranking always returns a top element, and cosine carries no absolute scale
  against which "top" could mean "present". Retrieval is a *ranking*, not a
  *detection*, and abstention is a detection question.
* The open-vocabulary label head **is** a detection: it is asked about a term
  and may answer with nothing. Measured over the same 120 frames it answers
  with nothing for "a coffee shop" (peak 0.036), "Narnia" (0.046),
  "my office" (0.098), "a car" (0.015), "a bicycle" (0.068).

So the gate is built from signals that *have* an absolute scale — a detector
response, a count of observations, a fraction of returns — and uses the
similarity only for what it is good at: ordering candidates that already
passed.

The four gates, and what each one is for
----------------------------------------
1. ``no_detector_support``   the label head, asked about this term, never
                             answered above :data:`MIN_LABEL_PROBABILITY`.
2. ``label_disagreement``    a place exists but the detector mostly calls it
                             something else (:data:`MIN_LABEL_PURITY`).
3. ``insufficient_evidence`` too few independent observations
                             (:data:`MIN_EVIDENCE_FRAMES`).
4. ``not_navigable``         the place's returns are entirely above the band
                             the robot can stand in. A destination is somewhere
                             you can *go*; a thing 2.7 m overhead is something
                             you can only look at. This is what refuses corpus
                             row 12 — the detector genuinely, repeatedly and
                             confidently calls an untextured white lamp head
                             "the moon" (peak 0.338, 23/23 detections on one
                             fused place), so the label head does **not** abstain
                             there and no threshold on it could.

and one ranking gate, :data:`MIN_RANKING_MARGIN`, which asks whether the
similarity is *decisive* — a robust z-score against the map's own background,
because a bare top-vs-runner-up difference on this data is 0.0004–0.01 and
carries nothing.

The fifth gate, re-measured (card P0-D)
---------------------------------------
The robust z-score above was fitted on a *cosine* background, where every place
carries a non-zero score. C-2's ``OnlineSemanticMap`` does not feed it one: its
background is an evidence-weighted **label strength** that is non-zero for the
places whose label matches the query and exactly ``0.0`` for every other place
(``online_map.py`` ``_assess``). One match among zeros has a median of 0 and a
median absolute deviation of 0, so :func:`ranking_margin` returns ``0.0`` — for
every query, forever. Measured: 0/6 and 0/18 admissions, ``background_mad 0.0``,
and the whole gate reading ``ABSTAIN_INDECISIVE_RANKING`` no matter what the
robot saw. It was masked only by ``abstention.enabled: false``.

So the module now carries **two** margin estimators and the policy picks one:

* :data:`RANKING_MARGIN_ROBUST_Z` — :func:`ranking_margin`, unchanged, still the
  default, still the fitted PG-3 operating point on a cosine background.
* :data:`RANKING_MARGIN_LABEL_STRENGTH` — :func:`label_strength_margin`, a
  top-vs-second **label-strength ratio among matching candidates**. The
  2026-08-21 retrieval bench (``scrum/20260821/cutover_research/
  bench_retrieval.md``) found label-primary the only *separable* arm of five:
  corroborated entries score 2.8–8.2 and stray single-detection labels 0.12,
  while cosine at two embedder sizes stayed non-separable. A single matching
  candidate is therefore scored against :data:`STRAY_LABEL_STRENGTH` rather than
  against nothing, so "the map holds exactly one lamppost" is a *strong* answer
  instead of a structurally impossible one.

Which signals are consulted at all is now configuration
-------------------------------------------------------
:attr:`AbstentionPolicy.signals` names the gates that run. The default is
:data:`DEFAULT_SIGNALS` — today's six, in today's order — so the shipping
operating point is byte-identical. A prototype profile
(``configs/navigation/prototype.yaml``) selects a subset. A threshold whose
signal is not selected is not read, which is why the "an enabled policy cannot
have a gate turned off" invariant is checked per *active* signal: dropping a
gate is now something a config says out loud, and zeroing its threshold is
still the silent death this class refuses.

Fail-closed, everywhere
-----------------------
Every missing signal is a refusal. An empty map is a refusal. A query the
detector was never asked about is a refusal. This is the **opposite** of R20's
deliberate fail-open on an empty vocabulary (R20 §9 open risk 1) and the
difference is principled: R20's vocabulary is a config sidecar, and its absence
means *the robot failed to load a file*; a perception map's emptiness means
*the robot has observed nothing*, which is a true statement about the world and
the honest answer to it is "I don't know". The cost is real and is recorded as
an open risk: a blind robot refuses every place.

OFF by default
--------------
:data:`AbstentionPolicy.enabled` is ``False``. Nothing on the mission path
consults this module until a config says so, and the numbers here are
**provisional** — they were measured in an untextured world that
``scrum/20260821/perception/SYNTHESIS.md`` §2 shows cannot support any
perception claim (0/69 person recall across three detectors against 127–145/156
on real photographs). They must be re-earned after the world work.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.camera_channel.d455 import MOUNT_HEIGHT_M
from parcel_robot.navigation.goals import (
    PLACE_OFFER_LIMIT,
    PLACE_UNKNOWN,
    PlaceAdmission,
)

__all__ = [
    "ABSTAIN_INDECISIVE_RANKING",
    "ABSTAIN_INSUFFICIENT_EVIDENCE",
    "ABSTAIN_LABEL_DISAGREEMENT",
    "ABSTAIN_NOT_NAVIGABLE",
    "ABSTAIN_NO_DETECTOR_SUPPORT",
    "ABSTAIN_NO_OBSERVATIONS",
    "DEFAULT_SIGNALS",
    "GROUNDED",
    "GROUND_BAND_M",
    "MIN_EVIDENCE_FRAMES",
    "MIN_GROUND_EVIDENCE_FRACTION",
    "MIN_LABEL_FRAMES",
    "MIN_LABEL_PROBABILITY",
    "MIN_LABEL_PURITY",
    "MIN_RANKING_MARGIN",
    "RANKING_MARGIN_LABEL_STRENGTH",
    "RANKING_MARGIN_ROBUST_Z",
    "REGISTERED_RANKING_MARGIN_MODES",
    "REGISTERED_SIGNALS",
    "SIGNAL_EVIDENCE_COUNT",
    "SIGNAL_LABEL_FRAMES",
    "SIGNAL_LABEL_PROBABILITY",
    "SIGNAL_LABEL_SUPPORT",
    "SIGNAL_NAVIGABILITY",
    "SIGNAL_RANKING_MARGIN",
    "STRAY_LABEL_STRENGTH",
    "AbstentionPolicy",
    "AbstentionVerdict",
    "DetectorSupport",
    "PlaceEvidence",
    "active_abstention_policy",
    "assess_place_query",
    "detector_prompts_for",
    "label_strength_margin",
    "ranking_margin",
    "use_abstention_policy",
]

# --------------------------------------------------------------- verdicts ---

GROUNDED = "grounded"
ABSTAIN_NO_OBSERVATIONS = "no_observations"
ABSTAIN_NO_DETECTOR_SUPPORT = "no_detector_support"
ABSTAIN_LABEL_DISAGREEMENT = "label_disagreement"
ABSTAIN_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ABSTAIN_NOT_NAVIGABLE = "not_navigable"
ABSTAIN_INDECISIVE_RANKING = "indecisive_ranking"

#: Every refusal this module can return. A caller that switches on the reason
#: can be checked against this set instead of against a comment.
ABSTENTION_REASONS: frozenset[str] = frozenset(
    {
        ABSTAIN_NO_OBSERVATIONS,
        ABSTAIN_NO_DETECTOR_SUPPORT,
        ABSTAIN_LABEL_DISAGREEMENT,
        ABSTAIN_INSUFFICIENT_EVIDENCE,
        ABSTAIN_NOT_NAVIGABLE,
        ABSTAIN_INDECISIVE_RANKING,
    }
)

# -------------------------------------------------------------- constants ---

#: Vertical band a destination's evidence must reach into, in metres above the
#: ground plane. **DERIVED, not fitted:** it is the Go2's own eye height,
#: ``camera_channel.d455.MOUNT_HEIGHT_M``, imported rather than re-typed. The
#: claim it encodes is physical — a place the robot can be sent to must present
#: surface at or below the height the robot itself occupies.
GROUND_BAND_M: float = MOUNT_HEIGHT_M

#: Peak per-prompt detector probability required before a term counts as
#: observed at all. FITTED on the PG-3 held-out FIT split (6 present classes,
#: 8 absent classes; corpus rows 10–13 were never in that split). The statistic
#: is the *per-query* column of the detector's logits, not the argmax label:
#: the argmax moves when someone edits the prompt vocabulary (measured: "a
#: person" 10→2 firing frames when 17 prompts were added) while the per-query
#: column does not (measured: max |Δ| 0.0012 over 20 shared terms × 120 frames).
MIN_LABEL_PROBABILITY: float = 0.25

#: How many frames must clear :data:`MIN_LABEL_PROBABILITY`. FITTED.
MIN_LABEL_FRAMES: int = 1

#: Fraction of a place's own detections that must carry the queried term.
#: FITTED. This is the "is this place that kind of thing" gate, and it is what
#: refuses "home" from the six mixed-label places that mention it.
MIN_LABEL_PURITY: float = 0.5

#: Independent observations (distinct frames) a place needs. FITTED.
MIN_EVIDENCE_FRAMES: int = 7

#: Fraction of a place's depth returns that must lie inside
#: :data:`GROUND_BAND_M`. FITTED (the FIT split's lowest present class sits at
#: 0.08); the *structure* — that there must be some — is the physical claim.
MIN_GROUND_EVIDENCE_FRACTION: float = 0.08

#: Robust z-score of the top similarity against the map's own background
#: (median / MAD over every place). FITTED. Not an absolute cosine and not a
#: bare top-two difference: both were measured on the FIT split and the robust
#: z was the one that separated.
MIN_RANKING_MARGIN: float = 1.0

# ---------------------------------------------------------- the signal set ---
#
# Names for the six gates, so a config can say which of them run. These are the
# strings ``perception.abstention.signals`` accepts; each one is the gate whose
# threshold constant sits directly above.

#: Peak per-prompt detector probability (:data:`MIN_LABEL_PROBABILITY`). Owns
#: the "the detector was never asked" refusal too: not asking is only evidence
#: of absence if you are willing to read the label head at all.
SIGNAL_LABEL_PROBABILITY = "label_probability"
#: How many frames cleared that probability (:data:`MIN_LABEL_FRAMES`).
SIGNAL_LABEL_FRAMES = "label_frames"
#: Share of a place's own detections carrying the term (:data:`MIN_LABEL_PURITY`).
SIGNAL_LABEL_SUPPORT = "label_support"
#: Independent observations of the place (:data:`MIN_EVIDENCE_FRAMES`).
SIGNAL_EVIDENCE_COUNT = "evidence_count"
#: Depth returns inside the ground band (:data:`MIN_GROUND_EVIDENCE_FRACTION`).
SIGNAL_NAVIGABILITY = "navigability"
#: Decisiveness of the ranking (:data:`MIN_RANKING_MARGIN`).
SIGNAL_RANKING_MARGIN = "ranking_margin"

#: The shipping signal set: all six, in the order the gate applies them. This
#: is the default, so a config that says nothing gets exactly PG-3's operating
#: point.
DEFAULT_SIGNALS: tuple[str, ...] = (
    SIGNAL_LABEL_PROBABILITY,
    SIGNAL_LABEL_FRAMES,
    SIGNAL_LABEL_SUPPORT,
    SIGNAL_EVIDENCE_COUNT,
    SIGNAL_NAVIGABILITY,
    SIGNAL_RANKING_MARGIN,
)

#: Every signal name a config may write. Anything else is a hard error, for the
#: same reason an unknown key is: a misspelled gate that reads as "the default"
#: looks exactly like a gate that never fires.
REGISTERED_SIGNALS: frozenset[str] = frozenset(DEFAULT_SIGNALS)

# ------------------------------------------------------ the ranking margin ---

#: PG-3's fitted estimator: a robust z-score against a *cosine* background.
RANKING_MARGIN_ROBUST_Z = "robust_z"
#: Top-vs-second label strength among matching candidates. See the module
#: docstring: this is the only estimator that can be non-zero on the online
#: map's own background.
RANKING_MARGIN_LABEL_STRENGTH = "label_strength"

REGISTERED_RANKING_MARGIN_MODES: frozenset[str] = frozenset(
    {RANKING_MARGIN_ROBUST_Z, RANKING_MARGIN_LABEL_STRENGTH}
)

#: Label strength a *stray* single-detection label scores under C-2's evidence
#: weighting. **PROVISIONAL**, and read off the 2026-08-21 retrieval bench
#: (``bench_retrieval.md``: "corroborated entries score 2.8-8.2 and stray
#: single-detection labels 0.12"), which ran on an untextured scene. It is the
#: denominator a lone matching candidate is scored against, so a lone stray
#: scores exactly 1.0 and a lone corroborated place scores 23-68. It has NOT
#: been re-derived on real frames.
STRAY_LABEL_STRENGTH: float = 0.12


# ------------------------------------------------------------ the evidence ---


@dataclass(frozen=True)
class DetectorSupport:
    """What the open-vocabulary label head said when asked about one term.

    ``frames_fired`` counts frames whose *per-query* peak probability cleared
    the policy's :data:`MIN_LABEL_PROBABILITY`. ``peak_probability`` is the best
    such probability over the whole observation window. A term the detector was
    never asked about is represented by ``asked=False``, which is a refusal —
    not asking is not evidence of absence, and treating it as one would be
    exactly the fail-open this card exists to prevent.
    """

    term: str
    asked: bool = False
    frames_observed: int = 0
    frames_fired: int = 0
    peak_probability: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.asked, bool):
            raise TypeError("DetectorSupport.asked must be a boolean")
        for name in ("frames_observed", "frames_fired"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"DetectorSupport.{name} must be a non-negative int")
        if self.frames_fired > self.frames_observed:
            raise ValueError("DetectorSupport cannot fire in more frames than it saw")
        if not math.isfinite(self.peak_probability) or not 0.0 <= self.peak_probability <= 1.0:
            raise ValueError("DetectorSupport.peak_probability must be in [0, 1]")


@dataclass(frozen=True)
class PlaceEvidence:
    """One fused place, and every signal the gate is allowed to look at.

    ``similarity`` is deliberately last and deliberately not called
    "confidence": it is a ranking score with no absolute scale, and the whole
    finding behind this module is that treating it as a confidence is what
    sends a robot to Narnia.
    """

    place_id: str
    label: str
    x: float
    y: float
    z: float = 0.0
    #: Detections on this place whose label is the queried term.
    label_support: int = 0
    #: All detections fused into this place, whatever they were called.
    detection_count: int = 0
    #: Distinct frames that observed it.
    evidence_frames: int = 0
    #: Fraction of its depth returns at or below :data:`GROUND_BAND_M`.
    ground_evidence_fraction: float = 0.0
    #: Text→place cosine. RANKING ONLY.
    similarity: float = 0.0

    def __post_init__(self) -> None:
        if not self.place_id or len(self.place_id) > 128:
            raise ValueError("PlaceEvidence.place_id is invalid")
        for name in ("x", "y", "z", "similarity", "ground_evidence_fraction"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"PlaceEvidence.{name} must be finite")
        for name in ("label_support", "detection_count", "evidence_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"PlaceEvidence.{name} must be a non-negative int")
        if self.label_support > self.detection_count:
            raise ValueError("PlaceEvidence.label_support exceeds detection_count")
        if not 0.0 <= self.ground_evidence_fraction <= 1.0:
            raise ValueError("PlaceEvidence.ground_evidence_fraction must be in [0, 1]")

    @property
    def label_purity(self) -> float:
        """Share of this place's detections that carried the queried term."""

        if self.detection_count <= 0:
            return 0.0
        return self.label_support / self.detection_count


# ---------------------------------------------------------------- policy ---


@dataclass(frozen=True)
class AbstentionPolicy:
    """The operating point. **Disabled by default.**

    Every threshold has a value even when disabled, so turning the flag on is a
    config change and not a code change — the card's "the cutover flips a flag
    rather than writing new safety logic under time pressure".

    ``__post_init__`` refuses a policy that is enabled with a gate turned off.
    A zeroed threshold is how an abstention mechanism dies quietly: it keeps
    reporting verdicts, keeps looking wired, and admits everything. Making that
    a construction error means it cannot happen by accident.
    """

    enabled: bool = False
    min_label_probability: float = MIN_LABEL_PROBABILITY
    min_label_frames: int = MIN_LABEL_FRAMES
    min_label_purity: float = MIN_LABEL_PURITY
    min_evidence_frames: int = MIN_EVIDENCE_FRAMES
    min_ground_evidence_fraction: float = MIN_GROUND_EVIDENCE_FRACTION
    min_ranking_margin: float = MIN_RANKING_MARGIN
    ground_band_m: float = GROUND_BAND_M
    offer_limit: int = PLACE_OFFER_LIMIT
    #: Which gates run. Card P0-D. Defaults to :data:`DEFAULT_SIGNALS`, so a
    #: policy nobody configured is PG-3's six, unchanged and in order.
    signals: tuple[str, ...] = DEFAULT_SIGNALS
    #: Which estimator :data:`SIGNAL_RANKING_MARGIN` uses. Card P0-D. Defaults
    #: to the fitted robust z-score.
    ranking_margin_mode: str = RANKING_MARGIN_ROBUST_Z

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("AbstentionPolicy.enabled must be a boolean")
        if isinstance(self.signals, str) or not isinstance(self.signals, (tuple, list)):
            raise TypeError("AbstentionPolicy.signals must be a sequence of names")
        object.__setattr__(self, "signals", tuple(str(s) for s in self.signals))
        unknown_signals = sorted(set(self.signals) - REGISTERED_SIGNALS)
        if unknown_signals:
            raise ValueError(
                "unknown abstention signal(s): " + ", ".join(unknown_signals)
            )
        if len(set(self.signals)) != len(self.signals):
            raise ValueError("AbstentionPolicy.signals must not repeat a signal")
        if self.ranking_margin_mode not in REGISTERED_RANKING_MARGIN_MODES:
            raise ValueError(
                "unknown abstention ranking_margin_mode: "
                f"{self.ranking_margin_mode!r}; expected one of "
                + ", ".join(sorted(REGISTERED_RANKING_MARGIN_MODES))
            )
        floats = (
            "min_label_probability",
            "min_label_purity",
            "min_ground_evidence_fraction",
            "min_ranking_margin",
            "ground_band_m",
        )
        for name in floats:
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"AbstentionPolicy.{name} must be finite")
        for name in ("min_label_frames", "min_evidence_frames", "offer_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"AbstentionPolicy.{name} must be an int")
        if not self.enabled:
            return
        if not self.signals:
            raise ValueError(
                "an enabled AbstentionPolicy must name at least one signal; an "
                "enabled gate with no signals admits everything, which is the "
                "silent death this class exists to refuse"
            )
        # ENABLED-ONLY invariants: a gate at zero is a gate that is not there.
        # Checked per ACTIVE signal (card P0-D): a threshold whose signal the
        # config did not select is never read, so requiring it to be non-zero
        # would only make an honest subset look like a misconfiguration.
        checks = (
            (SIGNAL_LABEL_PROBABILITY, "min_label_probability",
             self.min_label_probability > 0.0),
            (SIGNAL_LABEL_FRAMES, "min_label_frames", self.min_label_frames >= 1),
            (SIGNAL_LABEL_SUPPORT, "min_label_purity", self.min_label_purity > 0.0),
            (SIGNAL_EVIDENCE_COUNT, "min_evidence_frames", self.min_evidence_frames >= 1),
            (SIGNAL_NAVIGABILITY, "min_ground_evidence_fraction",
             self.min_ground_evidence_fraction > 0.0),
            (SIGNAL_RANKING_MARGIN, "min_ranking_margin",
             math.isfinite(self.min_ranking_margin)),
            (None, "ground_band_m", self.ground_band_m > 0.0),
            (None, "offer_limit", self.offer_limit >= 0),
        )
        active = set(self.signals)
        disabled = [
            name
            for signal, name, ok in checks
            if not ok and (signal is None or signal in active)
        ]
        if disabled:
            raise ValueError(
                "an enabled AbstentionPolicy cannot have a gate turned off: "
                + ", ".join(sorted(disabled))
            )
        if self.min_label_probability > 1.0 or self.min_label_purity > 1.0:
            raise ValueError("AbstentionPolicy probabilities must be at most 1.0")
        if not 0.0 < self.min_ground_evidence_fraction <= 1.0:
            raise ValueError("AbstentionPolicy.min_ground_evidence_fraction must be in (0, 1]")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> AbstentionPolicy:
        """Read ``perception.abstention`` from a navigation config block.

        Unknown keys fail closed — a typo in a safety flag must not read as
        "the default", because the default is OFF and a silently-ignored
        ``enabled: true`` would look identical to a working gate that never
        refused anything.
        """

        if not data:
            return cls()
        if not isinstance(data, Mapping):
            raise TypeError("perception.abstention must be a mapping")
        fields = {
            "enabled",
            "min_label_probability",
            "min_label_frames",
            "min_label_purity",
            "min_evidence_frames",
            "min_ground_evidence_fraction",
            "min_ranking_margin",
            "ground_band_m",
            "offer_limit",
            "signals",
            "ranking_margin_mode",
        }
        unknown = sorted(set(data) - fields)
        if unknown:
            raise ValueError(f"unknown perception.abstention key(s): {', '.join(unknown)}")
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key in {"min_label_frames", "min_evidence_frames", "offer_limit"}:
                kwargs[key] = int(value)
            elif key == "enabled":
                kwargs[key] = bool(value)
            elif key == "signals":
                if isinstance(value, str) or not isinstance(value, (list, tuple)):
                    raise TypeError(
                        "perception.abstention.signals must be a list of signal names"
                    )
                kwargs[key] = tuple(str(item) for item in value)
            elif key == "ranking_margin_mode":
                kwargs[key] = str(value)
            else:
                kwargs[key] = float(value)
        return cls(**kwargs)


#: The process-default policy. Mirrors ``detection_adapter.perception_chain``'s
#: ``active_perception_chain`` / ``use_perception_chain`` pattern so there is one
#: house convention for "what is installed on the mission path", not two.
_ACTIVE_POLICY = AbstentionPolicy()


def active_abstention_policy() -> AbstentionPolicy:
    return _ACTIVE_POLICY


def use_abstention_policy(policy: AbstentionPolicy | None) -> None:
    """Install (or clear, with ``None``) the process-default policy."""

    global _ACTIVE_POLICY
    if policy is not None and not isinstance(policy, AbstentionPolicy):
        raise TypeError("use_abstention_policy expects an AbstentionPolicy or None")
    _ACTIVE_POLICY = policy if policy is not None else AbstentionPolicy()


# --------------------------------------------------------------- verdict ---


@dataclass(frozen=True)
class AbstentionVerdict:
    """May this query become a goal, and what to say when it may not.

    Deliberately the same shape as ``navigation.goals.PlaceAdmission``, and its
    refusal sentences are literally that class's — ``fact()`` and ``reply()``
    delegate. The card's acceptance test is that the perception path refuses
    corpus rows 10–13 *exactly as* the closed-label path does; making the two
    paths share one sentence-writer turns that from a claim into a call.
    """

    admitted: bool
    query: str = ""
    reason: str = ""
    alternatives: tuple[str, ...] = ()
    place_id: str | None = None
    signals: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.admitted and self.reason != GROUNDED:
            raise ValueError("an admitted verdict must report the GROUNDED reason")
        if not self.admitted and self.reason not in ABSTENTION_REASONS:
            raise ValueError(f"unknown abstention reason: {self.reason!r}")

    def _as_admission(self) -> PlaceAdmission:
        return PlaceAdmission(
            admitted=self.admitted,
            query=self.query,
            reason=PLACE_UNKNOWN if not self.admitted else GROUNDED,
            alternatives=self.alternatives,
        )

    def fact(self) -> str:
        """Third person, for the hosted model to read and paraphrase (R15)."""

        return self._as_admission().fact()

    def reply(self) -> str:
        """First person, for the typed lane that speaks as itself."""

        return self._as_admission().reply()

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "query": self.query,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
            "place_id": self.place_id,
            "signals": dict(self.signals),
        }


# ---------------------------------------------------------------- helpers ---


def detector_prompts_for(query: str) -> tuple[str, ...]:
    """Open-vocabulary prompts to ask the label head about a place noun.

    A template, not a table. The whole point of an open-vocabulary head is that
    any noun can be asked; a lookup here would smuggle a closed label set back
    into the module built to replace one. The owner's own words are always the
    first prompt; a leading definite article additionally yields the indefinite
    form, because "the crosswalk" is a request for *a* crosswalk. Possessives
    ("my office") and proper nouns ("Narnia") are left verbatim — rewriting
    them would be a guess about the referent, which is the thing this module
    refuses to make.

    **NOT CALIBRATED.** PG-3 measured exactly one phrasing per term, and
    detector response is known to move with phrasing. Which of the returned
    prompts a detector answers loudest is an open question, recorded as such;
    the caller is expected to take the strongest response over the tuple.
    """

    text = " ".join(str(query).strip().split())
    if not text:
        return ()
    prompts = [text]
    lowered = text.lower()
    #: Determiners that already fix a referent. "my office" belongs to the
    #: owner, not to the scene, and "a my office" is not a thing to detect.
    possessives = ("my ", "our ", "your ", "his ", "her ", "their ", "its ")
    if lowered.startswith("the "):
        rest = text[4:]
        if rest:
            prompts.append(f"a {rest}")
    elif (
        not lowered.startswith(("a ", "an ", *possessives))
        and text[:1].islower()
    ):
        prompts.append(f"a {text}")
    seen: list[str] = []
    for prompt in prompts:
        if prompt not in seen:
            seen.append(prompt)
    return tuple(seen)


def place_evidence_from_mapping(
    item: Mapping[str, Any],
    term: str,
    *,
    place_id: str,
    label: str,
    x: float,
    y: float,
    z: float = 0.0,
    similarity: float = 0.0,
) -> PlaceEvidence:
    """Lift a candidate's perception metadata into :class:`PlaceEvidence`.

    **Every missing key defaults to the refusing value**, not to a permissive
    one. A candidate produced by a path that carries no perception evidence —
    the oracle read the mission path still uses today — therefore refuses under
    an enabled policy rather than sailing through it. That is the intended
    behaviour and it is why the policy ships OFF: the flag may only be turned on
    once the ingress actually populates these fields.
    """

    def _int(key: str) -> int:
        value = item.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return max(0, int(value))

    detections = _int("detection_count")
    support = min(_int("label_support"), detections)
    fraction = item.get("ground_evidence_fraction", 0.0)
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        fraction = 0.0
    if not math.isfinite(fraction):
        fraction = 0.0
    return PlaceEvidence(
        place_id=str(place_id)[:128] or "candidate",
        label=str(label)[:160] or str(term)[:160] or "place",
        x=float(x),
        y=float(y),
        z=float(z),
        label_support=support,
        detection_count=detections,
        evidence_frames=_int("evidence_frames"),
        ground_evidence_fraction=min(1.0, max(0.0, fraction)),
        similarity=float(similarity) if math.isfinite(float(similarity)) else 0.0,
    )


def detector_support_from_mapping(
    data: Mapping[str, Any] | None,
    prompts: Sequence[str],
) -> DetectorSupport:
    """Read the label head's answer for ``prompts`` out of an observation extra.

    ``data`` maps a prompt string to ``{"frames_observed", "frames_fired",
    "peak_probability"}``. A prompt that is absent was never asked, and not
    asking is not evidence of absence — the returned support has
    ``asked=False``, which the gate treats as a refusal.
    """

    term = prompts[0] if prompts else ""
    if not isinstance(data, Mapping) or not prompts:
        return DetectorSupport(term=term, asked=False)
    best: DetectorSupport | None = None
    for prompt in prompts:
        row = data.get(prompt)
        if not isinstance(row, Mapping):
            continue
        try:
            candidate = DetectorSupport(
                term=prompt,
                asked=True,
                frames_observed=max(0, int(row.get("frames_observed", 0))),
                frames_fired=max(0, int(row.get("frames_fired", 0))),
                peak_probability=min(1.0, max(0.0, float(row.get("peak_probability", 0.0)))),
            )
        except (TypeError, ValueError):
            continue
        if best is None or candidate.peak_probability > best.peak_probability:
            best = candidate
    return best if best is not None else DetectorSupport(term=term, asked=False)


def ranking_margin(similarities: Sequence[float]) -> float:
    """Robust z-score of the top similarity against the map's own background.

    ``(top - median) / (1.4826 * MAD)``. Per-query and therefore scale-free,
    which is the only way to use a cosine that has no absolute scale ACROSS
    queries. A degenerate map (fewer than three places, or zero spread) returns
    ``0.0`` — no separation could be established, and the gate treats that as a
    refusal rather than as a pass.
    """

    values = [float(v) for v in similarities if math.isfinite(float(v))]
    if len(values) < 3:
        return 0.0
    ordered = sorted(values)
    median = _median(ordered)
    mad = _median(sorted(abs(v - median) for v in values))
    if mad <= 0.0:
        return 0.0
    return (ordered[-1] - median) / (1.4826 * mad)


def label_strength_margin(strengths: Sequence[float]) -> float:
    """Top-vs-second **label strength** among the candidates that matched.

    The 2026-08-21 retrieval bench's finding, made into a gate: label strength
    is the separable signal (corroborated 2.8-8.2, stray 0.12) and cosine is
    not, at either embedder size. So the decisiveness question becomes "how many
    times stronger than the best alternative is the winner", where:

    * ``strengths`` is the map's background FOR THIS QUERY — a place that does
      not carry the queried label contributes ``0.0`` and is not an alternative,
      so those entries are dropped rather than counted as a tie at zero. That
      dropping is the whole fix: :func:`ranking_margin` reads the zeros as the
      background, finds MAD ``0.0``, and returns ``0.0`` for every query the
      online map can ever ask.
    * with **one** matching candidate the alternative is
      :data:`STRAY_LABEL_STRENGTH`, the strength a stray single-detection label
      scores. One lamppost in the map is then a decisive answer (ratio ~24) and
      one stray is not (ratio 1.0) — which is the distinction the bench made and
      the one a comparison against an empty set cannot make.
    * an empty match set returns ``0.0``. No candidate is not a decisive
      candidate, and the gate treats it as the refusal it is.

    Scale-free like the robust z it replaces, and for the same reason: it is a
    ratio, so it carries across queries whose absolute strengths differ.
    """

    values = sorted(
        (
            float(v)
            for v in strengths
            if math.isfinite(float(v)) and float(v) > 0.0
        ),
        reverse=True,
    )
    if not values:
        return 0.0
    runner_up = values[1] if len(values) > 1 else 0.0
    denominator = max(runner_up, STRAY_LABEL_STRENGTH)
    if denominator <= 0.0:  # pragma: no cover - STRAY_LABEL_STRENGTH is positive
        return 0.0
    return values[0] / denominator


def _margin_for(policy: AbstentionPolicy, background: Sequence[float]) -> float:
    """Whichever estimator the policy selected. One switch, one place."""

    if policy.ranking_margin_mode == RANKING_MARGIN_LABEL_STRENGTH:
        return label_strength_margin(background)
    return ranking_margin(background)


def _median(ordered: Sequence[float]) -> float:
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


def _offers(places: Sequence[PlaceEvidence], policy: AbstentionPolicy) -> tuple[str, ...]:
    """Real places to name in a refusal — the ones that WOULD pass the gates.

    A refusal that offers a place the robot cannot actually reach is worse than
    one that offers nothing (R20 §1.3). Here "can reach" is not a config list:
    it is the same evidence and navigability test the admission uses, so the
    offer can never drift from what the gate would accept.
    """

    active = set(policy.signals)
    ok = [
        place
        for place in places
        if (
            SIGNAL_EVIDENCE_COUNT not in active
            or place.evidence_frames >= policy.min_evidence_frames
        )
        and (
            SIGNAL_NAVIGABILITY not in active
            or place.ground_evidence_fraction >= policy.min_ground_evidence_fraction
        )
        and place.label
    ]
    ok.sort(key=lambda p: (-p.evidence_frames, p.place_id))
    seen: list[str] = []
    for place in ok:
        label = " ".join(str(place.label).split())
        if label and label not in seen:
            seen.append(label)
        if len(seen) >= max(0, policy.offer_limit):
            break
    return tuple(seen)


# ------------------------------------------------------------- the gate ---


def assess_place_query(
    query: str,
    *,
    support: DetectorSupport | None,
    places: Sequence[PlaceEvidence] = (),
    policy: AbstentionPolicy | None = None,
    map_similarities: Sequence[float] | None = None,
) -> AbstentionVerdict:
    """Decide whether perception can honestly commit to ``query`` as a place.

    Existential over ``places``: admitted iff **some** place passes every gate.
    Gating only the top-ranked place would let the similarity — the signal with
    no absolute scale — decide which place is even allowed to be checked.

    ``map_similarities`` is the similarity of *every* place in the map, used
    for the ranking margin; it defaults to the similarities carried by
    ``places``, which is correct when ``places`` is the whole map and
    conservative when it is not (a narrower background can only shrink the
    margin, so the default cannot flatter a query).
    """

    active = policy if policy is not None else active_abstention_policy()
    text = " ".join(str(query).strip().split())
    offers = _offers(places, active)
    #: Card P0-D. The gates this policy selected. Defaults to all six, so the
    #: whole membership test below is a no-op on the shipping operating point.
    on = set(active.signals)

    def refuse(reason: str, signals: Mapping[str, float]) -> AbstentionVerdict:
        return AbstentionVerdict(False, text, reason, offers, None, dict(signals))

    label_head = SIGNAL_LABEL_PROBABILITY in on
    if label_head and (support is None or not support.asked):
        # Never asked is not evidence of absence. Fail closed.
        return refuse(ABSTAIN_NO_DETECTOR_SUPPORT, {"peak_probability": 0.0, "asked": 0.0})
    signals = {
        "peak_probability": float(support.peak_probability) if support is not None else 0.0,
        "frames_fired": float(support.frames_fired) if support is not None else 0.0,
        "frames_observed": float(support.frames_observed) if support is not None else 0.0,
    }
    # Two readings of the same gate, and both are needed. The peak says the
    # detector ever answered loudly; the count says it did so more than once.
    # A single lucky box in one frame is not a place.
    if (
        label_head
        and support is not None
        and support.peak_probability < active.min_label_probability
    ):
        return refuse(ABSTAIN_NO_DETECTOR_SUPPORT, signals)
    if (
        SIGNAL_LABEL_FRAMES in on
        and support is not None
        and support.frames_fired < active.min_label_frames
    ):
        return refuse(ABSTAIN_NO_DETECTOR_SUPPORT, signals)
    # Not a signal and not configurable: no place at all is no place at all.
    if not places:
        return refuse(ABSTAIN_NO_OBSERVATIONS, signals)

    background = (
        [float(v) for v in map_similarities]
        if map_similarities is not None
        else [place.similarity for place in places]
    )
    margin = _margin_for(active, background)
    signals["ranking_margin"] = float(margin)

    ranked = sorted(places, key=lambda p: (-p.similarity, p.place_id))
    # Report the gate the best candidate got furthest through, not the first
    # place's failure: "no place is pure enough" and "the one pure place is
    # overhead" are different facts and a reader deserves the later one.
    order = (
        ABSTAIN_LABEL_DISAGREEMENT,
        ABSTAIN_INSUFFICIENT_EVIDENCE,
        ABSTAIN_NOT_NAVIGABLE,
        ABSTAIN_INDECISIVE_RANKING,
    )
    # The "furthest through" report has to start at the first gate that is
    # actually running, or a dropped first gate would be reported as the reason
    # nothing passed the gates that are still there.
    place_gates = [
        reason
        for signal, reason in (
            (SIGNAL_LABEL_SUPPORT, ABSTAIN_LABEL_DISAGREEMENT),
            (SIGNAL_EVIDENCE_COUNT, ABSTAIN_INSUFFICIENT_EVIDENCE),
            (SIGNAL_NAVIGABILITY, ABSTAIN_NOT_NAVIGABLE),
            (SIGNAL_RANKING_MARGIN, ABSTAIN_INDECISIVE_RANKING),
        )
        if signal in on
    ]
    worst = place_gates[0] if place_gates else ABSTAIN_LABEL_DISAGREEMENT
    for place in ranked:
        if SIGNAL_LABEL_SUPPORT in on and (
            place.label_support <= 0 or place.label_purity < active.min_label_purity
        ):
            failed = ABSTAIN_LABEL_DISAGREEMENT
        elif (
            SIGNAL_EVIDENCE_COUNT in on
            and place.evidence_frames < active.min_evidence_frames
        ):
            failed = ABSTAIN_INSUFFICIENT_EVIDENCE
        elif (
            SIGNAL_NAVIGABILITY in on
            and place.ground_evidence_fraction < active.min_ground_evidence_fraction
        ):
            failed = ABSTAIN_NOT_NAVIGABLE
        elif SIGNAL_RANKING_MARGIN in on and margin < active.min_ranking_margin:
            failed = ABSTAIN_INDECISIVE_RANKING
        else:
            return AbstentionVerdict(
                True,
                text,
                GROUNDED,
                (),
                place.place_id,
                {
                    **signals,
                    "label_purity": place.label_purity,
                    "evidence_frames": float(place.evidence_frames),
                    "ground_evidence_fraction": place.ground_evidence_fraction,
                    "similarity": place.similarity,
                },
            )
        if order.index(failed) > order.index(worst):
            worst = failed
    return refuse(worst, signals)
