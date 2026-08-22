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

The sixth gate, and a third answer (card P1-D)
----------------------------------------------
C-3 turned the gate on over a learned map and measured **0/18** — every single
answer refused, every one ``indecisive_ranking``, on perfect-geometry data.
P0-D fixed the estimator. What remained was the posture: six AND-ed signals
fitted on a world ``SYNTHESIS.md`` §2 declared invalid, all of which must pass,
is a gate whose only reachable answer is no. Two things change here.

**A signal that can say "that isn't a bench".** :data:`SIGNAL_VLM_VETO` shows
the top candidate's best-view crop and the query noun to Qwen3-VL-2B
(``SYNTHESIS.md`` decision 4: a statistical tie with the 8B at n=40, 4.4 GB,
89 ms) and takes the admission away on an *absent* answer. It runs LAST, only
on a place that already passed every evidence gate, and it is **subtractive
only** — which is the entire safety argument for letting a 2B model near the
mission path. It is not in :data:`DEFAULT_SIGNALS`.

**A third outcome.** :data:`OUTCOME_ADMIT` / :data:`OUTCOME_ASK` /
:data:`OUTCOME_REFUSE`. Below the admit threshold the dog now *asks* — "I think
it's over there, want me to go?" — instead of refusing, whenever the shortfall
is one of :data:`ASK_ELIGIBLE_REASONS` and there is a candidate to ask about.
REFUSE is kept for the four cases where a question would be dishonest: no
evidence at all, the detector was never asked, the place is not somewhere a
robot can stand, and the veto fired. ``admitted`` still means exactly what it
meant — may motion start — so an ASK authorizes nothing.

Both are OFF unless a config says otherwise (:attr:`AbstentionPolicy.signals`,
:attr:`AbstentionPolicy.ask_below_threshold`), and the shipping verdicts do not
move.

Fail-closed, everywhere
-----------------------
Every missing signal is a refusal. An empty map is a refusal. A query the
detector was never asked about is a refusal. **Card P1-D narrows this**, and
only under a profile that asks for it: a *shortfall* against a provisional
threshold becomes a question rather than a refusal, because the thresholds were
fitted on a dead world and refusing on them is not honesty, it is
superstition. What stays fail-closed is everything that is not a threshold —
absence of evidence, absence of a candidate, physical unreachability, and an
explicit veto. This is the **opposite** of R20's
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

import logging
import math
import threading
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
    "ABSTAIN_VETO_UNAVAILABLE",
    "ABSTAIN_VLM_VETO",
    "ASK_ELIGIBLE_REASONS",
    "ASK_STATUS",
    "DEFAULT_SIGNALS",
    "GROUNDED",
    "GROUND_BAND_M",
    "MIN_EVIDENCE_FRAMES",
    "MIN_GROUND_EVIDENCE_FRACTION",
    "MIN_LABEL_FRAMES",
    "MIN_LABEL_PROBABILITY",
    "MIN_LABEL_PURITY",
    "MIN_RANKING_MARGIN",
    "OUTCOME_ADMIT",
    "OUTCOME_ASK",
    "OUTCOME_REFUSE",
    "RANKING_MARGIN_LABEL_STRENGTH",
    "RANKING_MARGIN_ROBUST_Z",
    "REGISTERED_OUTCOMES",
    "REGISTERED_RANKING_MARGIN_MODES",
    "REGISTERED_SIGNALS",
    "SIGNAL_EVIDENCE_COUNT",
    "SIGNAL_LABEL_FRAMES",
    "SIGNAL_LABEL_PROBABILITY",
    "SIGNAL_LABEL_SUPPORT",
    "SIGNAL_NAVIGABILITY",
    "SIGNAL_RANKING_MARGIN",
    "SIGNAL_VLM_VETO",
    "STRAY_LABEL_STRENGTH",
    "VETO_ABSENT",
    "VETO_PRESENT",
    "VETO_UNAVAILABLE",
    "AbstentionPolicy",
    "AbstentionVerdict",
    "DetectorSupport",
    "PlaceEvidence",
    "active_abstention_policy",
    "assess_place_query",
    "clear_veto_cache",
    "detector_prompts_for",
    "label_strength_margin",
    "ranking_margin",
    "resolve_veto",
    "use_abstention_policy",
    "use_veto",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- verdicts ---

GROUNDED = "grounded"
ABSTAIN_NO_OBSERVATIONS = "no_observations"
ABSTAIN_NO_DETECTOR_SUPPORT = "no_detector_support"
ABSTAIN_LABEL_DISAGREEMENT = "label_disagreement"
ABSTAIN_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ABSTAIN_NOT_NAVIGABLE = "not_navigable"
ABSTAIN_INDECISIVE_RANKING = "indecisive_ranking"
#: Card P1-D. The VLM looked at the top candidate's best-view crop, was asked
#: whether it is a ``<query>``, and said no. The only *subtractive* reason in
#: this module: every other one is the absence of evidence, and this one is
#: evidence of absence.
ABSTAIN_VLM_VETO = "vlm_veto_absent"
#: Card P1-D. The veto could not be consulted — no seat, no crop, a cold seat,
#: or a declined GPU moment. NOT a refusal: ASK-eligible, and deliberately
#: separate from :data:`ABSTAIN_INDECISIVE_RANKING`. An earlier draft reused the
#: ranking reason here, so the logs said "indecisive ranking" while reporting a
#: ranking margin of 39.1 — a gate that lies about which of its signals stopped
#: it is a gate nobody can debug.
ABSTAIN_VETO_UNAVAILABLE = "vlm_veto_unavailable"

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
        ABSTAIN_VLM_VETO,
        ABSTAIN_VETO_UNAVAILABLE,
    }
)

# ------------------------------------------------- the three-way outcome ---
#
# Card P1-D. C-3 measured 0/18: every learned-map answer refused. The prototype
# ruling (audit §9) is that a gate which can only say YES or NO on evidence it
# does not yet have will say NO forever — so the gate gets a third answer, and
# it is the one a companion would actually give.

#: The evidence carried the query. Motion may be authorized.
OUTCOME_ADMIT = "admit"
#: Below the admit threshold, but there IS a candidate and nothing contradicted
#: it. "I think it's over there — want me to go?" No motion starts; the owner
#: decides. This is the default posture below threshold under a prototype
#: profile, and it is the whole content of "ask, don't refuse".
OUTCOME_ASK = "ask"
#: The honest no. Reserved, deliberately narrowly, for three cases: the VLM
#: veto fired, there is no evidence at all, or the place is physically not
#: somewhere the robot can stand.
OUTCOME_REFUSE = "refuse"

REGISTERED_OUTCOMES: frozenset[str] = frozenset(
    {OUTCOME_ADMIT, OUTCOME_ASK, OUTCOME_REFUSE}
)

#: The status an ASK carries on the hosted lane. Deliberately NOT P0-B's
#: ``unknown_place``: that one means "no place by that name exists on my map",
#: and this one means "a place I can see might be it". See
#: :meth:`AbstentionVerdict.as_ask`.
ASK_STATUS = "uncertain_place"

#: Which refusals may soften into a question, and which may not.
#:
#: ASK-eligible are the three *shortfall* reasons — the map has a candidate and
#: the evidence merely fell short of a threshold that was fitted on a world
#: SYNTHESIS.md §2 declared dead. Asking about those is honest.
#:
#: The rest stay REFUSE and each for its own reason, none of them a threshold:
#:   ``no_observations``      there is no candidate; there is nothing to ask about
#:   ``no_detector_support``  the label head was never asked, or never answered;
#:                            "want me to go to the thing I have no evidence of"
#:                            is not a question, it is a guess with a question mark
#:   ``not_navigable``        a physical claim about the world. This is the gate
#:                            that refuses corpus row 12 ("take me to the moon")
#:                            and softening it would hand that row back
#:   ``vlm_veto_absent``      something LOOKED and said no
ASK_ELIGIBLE_REASONS: frozenset[str] = frozenset(
    {
        ABSTAIN_LABEL_DISAGREEMENT,
        ABSTAIN_INSUFFICIENT_EVIDENCE,
        ABSTAIN_INDECISIVE_RANKING,
        ABSTAIN_VETO_UNAVAILABLE,
    }
)

# ----------------------------------------------- the veto's own vocabulary ---
#
# Declared HERE, not in ``parcel_robot.vlm_veto``, and the dependency runs that
# way round on purpose: the gate must be able to name the three answers without
# importing a package that can import torch. ``vlm_veto`` imports these.

#: The VLM looked and agreed the crop shows the queried noun.
VETO_PRESENT = "present"
#: The VLM looked and said it does not. This is the only answer that subtracts.
VETO_ABSENT = "absent"
#: No seat installed, no crop to look at, the GPU moment was declined, or the
#: model answered neither yes nor no. **Never an admit and never a refusal** —
#: it degrades to ASK, which is why enabling the veto requires the ask posture.
VETO_UNAVAILABLE = "unavailable"

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
#: Card P1-D. The Qwen3-VL-2B verification veto: the top candidate's best-view
#: crop and the query noun go to the model, and an *absent* answer removes the
#: admission. Subtractive only — it never promotes a place the evidence gates
#: refused, which is why a 2B model is allowed this close to the mission path.
#: Not in :data:`DEFAULT_SIGNALS`: the shipping operating point does not move.
SIGNAL_VLM_VETO = "vlm_veto"

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
#:
#: Card P1-D adds :data:`SIGNAL_VLM_VETO` here and NOT to
#: :data:`DEFAULT_SIGNALS`: a config may select it, nothing selects it by
#: default, and the shipped verdicts are byte-identical either way.
REGISTERED_SIGNALS: frozenset[str] = frozenset({*DEFAULT_SIGNALS, SIGNAL_VLM_VETO})

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
    #: Card P1-D. The place's BEST-VIEW crop, encoded, or ``None``. This is the
    #: only field the gate does not reason about: it is carried so the VLM veto
    #: has something to look at without the gate having to know where crops come
    #: from. A place with no crop is a place the veto cannot verify, which is an
    #: ASK — see :data:`VETO_UNAVAILABLE`.
    crop_png: bytes | None = None

    def __post_init__(self) -> None:
        if not self.place_id or len(self.place_id) > 128:
            raise ValueError("PlaceEvidence.place_id is invalid")
        if self.crop_png is not None and not isinstance(self.crop_png, (bytes, bytearray)):
            raise TypeError("PlaceEvidence.crop_png must be bytes")
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
    #: Card P1-D. WHICH seat answers :data:`SIGNAL_VLM_VETO`, named in config.
    #: Empty means "no seat" and the veto answers :data:`VETO_UNAVAILABLE` for
    #: every place, which is an ASK. A host without the weights therefore asks
    #: rather than admitting or refusing, and that degradation is a config fact
    #: rather than an accident of what happens to be importable.
    veto_model: str = ""
    #: Card P1-D. Does a shortfall become a QUESTION instead of a refusal?
    #: ``False`` is the shipped two-way gate, unchanged: below threshold is a
    #: refusal, exactly as PG-3 wrote it. ``True`` is the prototype posture —
    #: :data:`ASK_ELIGIBLE_REASONS` become :data:`OUTCOME_ASK`, and the other
    #: refusals are untouched.
    ask_below_threshold: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("AbstentionPolicy.enabled must be a boolean")
        if not isinstance(self.ask_below_threshold, bool):
            raise TypeError("AbstentionPolicy.ask_below_threshold must be a boolean")
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
        # Card P1-D. The veto is the only signal that can be UNAVAILABLE at call
        # time — no seat installed, no crop, or the GPU moment declined. An
        # unavailable veto degrades to ASK, so selecting the veto without the ask
        # posture would silently turn every unavailable answer into a refusal and
        # hand back the 0/18 this card exists to end. Making it a construction
        # error means the two keys cannot drift apart in a config.
        if SIGNAL_VLM_VETO in set(self.signals) and not self.ask_below_threshold:
            raise ValueError(
                "an enabled AbstentionPolicy that selects the vlm_veto signal must "
                "set ask_below_threshold: true — an unavailable veto degrades to "
                "ASK, and without the ask posture that degradation is a refusal"
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
            # The veto has no threshold of its own: its operating point lives in
            # ``vlm_veto.VETO_P_YES_PRESENT``, inside the model wrapper that
            # measured it. There is nothing here that could be zeroed, so the
            # per-signal check has nothing to say about it.
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
            "ask_below_threshold",
            "veto_model",
        }
        unknown = sorted(set(data) - fields)
        if unknown:
            raise ValueError(f"unknown perception.abstention key(s): {', '.join(unknown)}")
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key in {"min_label_frames", "min_evidence_frames", "offer_limit"}:
                kwargs[key] = int(value)
            elif key in {"enabled", "ask_below_threshold"}:
                kwargs[key] = bool(value)
            elif key == "signals":
                if isinstance(value, str) or not isinstance(value, (list, tuple)):
                    raise TypeError(
                        "perception.abstention.signals must be a list of signal names"
                    )
                kwargs[key] = tuple(str(item) for item in value)
            elif key in {"ranking_margin_mode", "veto_model"}:
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


# ------------------------------------------------------- the veto's seam ---
#
# Card P1-D, post-verification. The veto was originally a keyword argument with
# no producer: `assess_place_query(veto=...)` existed, the roster could select
# the signal, and NOTHING in the product ever passed one — so the shipped path
# answered `unavailable` for every place and the measured 5-of-7 admissions were
# reachable only from a harness that monkeypatched the gate. The verifier caught
# it. This is the producer.
#
# It resolves HERE, inside the gate, rather than at the two call sites, for one
# reason: there are two call sites today (`navigation.semantic_map` and
# `online_map.online_map`) and a third one is a plausible edit. A seam that each
# caller has to remember to thread is a seam that a new caller silently drops,
# which is exactly the defect being repaired.

_VETO_LOCK = threading.Lock()
_VETO_RUNNERS: dict[str, Any] = {}
_VETO_OVERRIDE: Any = None


def use_veto(veto: Any) -> None:
    """Install (or clear, with ``None``) a process-wide veto callable.

    Tests and harnesses use this instead of monkeypatching the gate.
    """

    global _VETO_OVERRIDE
    with _VETO_LOCK:
        _VETO_OVERRIDE = veto


def clear_veto_cache() -> None:
    """Drop resolved seats. A new model id resolves fresh after this."""

    with _VETO_LOCK:
        _VETO_RUNNERS.clear()


def resolve_veto(policy: AbstentionPolicy) -> Any:
    """The veto callable for ``policy``, built once per model id and cached.

    ``parcel_robot.vlm_veto`` is imported HERE and not at module scope, for two
    independent reasons: that package imports names from this one (so a
    top-level import is a cycle), and the gate is on the mission path while the
    seat can pull in a tensor library. A host that never selects the signal
    never imports the package at all.

    Any failure to build a seat resolves to ``None``, which the gate reads as
    :data:`VETO_UNAVAILABLE` and therefore as an ASK. A missing model is a
    question, never a crash and never a silent admission.
    """

    with _VETO_LOCK:
        if _VETO_OVERRIDE is not None:
            return _VETO_OVERRIDE
        key = str(policy.veto_model or "")
        if key in _VETO_RUNNERS:
            return _VETO_RUNNERS[key]
    try:
        from parcel_robot.vlm_veto import runner_for

        # ``veto_callable()`` and not the runner itself: the gate calls
        # ``veto(query, place)``, and a VetoRunner is not callable. The first
        # draft returned the runner, every call raised TypeError, and the gate
        # dutifully read that as "unavailable" — so the veto looked wired,
        # answered nothing, and the product asked about everything. Caught by
        # the CI eval row in ``tests/test_p1d_eval_rows.py``.
        runner = runner_for(key).veto_callable()
    except Exception:
        logger.warning("vlm veto seat %r could not be built; asking instead", key,
                       exc_info=True)
        runner = None
    with _VETO_LOCK:
        _VETO_RUNNERS[key] = runner
        return runner


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
    #: Card P1-D. ``""`` means "derive it": admitted ⇒ ADMIT, otherwise REFUSE,
    #: which is exactly the two-way gate PG-3 shipped. Every construction that
    #: predates this card therefore keeps its meaning without being edited.
    outcome: str = ""
    #: The place an ASK is asking ABOUT — the best candidate's label. Empty on
    #: an admit (the place is already named by ``place_id``) and on a refusal
    #: with no candidate.
    candidate: str = ""

    def __post_init__(self) -> None:
        if self.admitted and self.reason != GROUNDED:
            raise ValueError("an admitted verdict must report the GROUNDED reason")
        if not self.admitted and self.reason not in ABSTENTION_REASONS:
            raise ValueError(f"unknown abstention reason: {self.reason!r}")
        outcome = str(self.outcome or "")
        if not outcome:
            outcome = OUTCOME_ADMIT if self.admitted else OUTCOME_REFUSE
        if outcome not in REGISTERED_OUTCOMES:
            raise ValueError(f"unknown abstention outcome: {self.outcome!r}")
        # The two fields cannot disagree. ``admitted`` is what every existing
        # caller reads to decide whether motion may start, so an ASK that also
        # said ``admitted=True`` would authorize the motion it was asking
        # permission for.
        if self.admitted and outcome != OUTCOME_ADMIT:
            raise ValueError("an admitted verdict must carry the ADMIT outcome")
        if not self.admitted and outcome == OUTCOME_ADMIT:
            raise ValueError("an ADMIT outcome must be an admitted verdict")
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "candidate", " ".join(str(self.candidate).split())[:160])

    @property
    def asks(self) -> bool:
        """Is this a question rather than an answer?"""

        return self.outcome == OUTCOME_ASK

    @property
    def refuses(self) -> bool:
        return self.outcome == OUTCOME_REFUSE

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

    def question(self) -> str:
        """The ASK sentence. Empty for any other outcome.

        A companion's version of a refusal. It names what the robot thinks it
        found, says plainly that it is not sure, and puts the decision with the
        owner — which is the whole of "ask, don't refuse" in one sentence.
        """

        if self.outcome != OUTCOME_ASK:
            return ""
        target = self.candidate or self.query or "it"
        if self.candidate and self.query and self.candidate.lower() != self.query.lower():
            return (
                f"I am not sure, but I think the {target} I have seen might be "
                f"what you mean by {self.query}. Want me to go and look?"
            )
        return (
            f"I think I have seen {target}, but I am not sure enough to set off "
            "on my own. Want me to go and look?"
        )

    def as_ask(self) -> dict[str, Any]:
        """The ASK, in the shape P0-B's broker already speaks.

        The hosted lane already has an ask-not-refuse result:
        ``tool_broker``'s ``{"status": "unknown_place", "place", "valid_places",
        "detail", "reason"}``, which the model reads and turns into a question.
        This is the same envelope for the case that envelope does not cover —
        the map DOES have a candidate, it is simply not decisive — so the model
        reads one shape, not two. The status differs (``uncertain_place`` vs
        ``unknown_place``) because the two facts differ and a companion that
        says "I have never heard of it" about a place it can see is lying.

        Returns ``{}`` for a non-ASK verdict. **This card does not wire it**:
        the broker and ``runtime.py`` are MUST-NOT-TOUCH, so the one-line
        consumption is a handoff, recorded in ``P1D_STATUS.md``.
        """

        if self.outcome != OUTCOME_ASK:
            return {}
        return {
            "status": ASK_STATUS,
            "tool": "navigate_to",
            "detail": self.question(),
            "place": self.query,
            "candidate": self.candidate,
            "place_id": self.place_id,
            "valid_places": list(self.alternatives),
            "reason": self.reason,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "query": self.query,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
            "place_id": self.place_id,
            "signals": dict(self.signals),
            "outcome": self.outcome,
            "candidate": self.candidate,
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
    crop = item.get("thumbnail")
    if not isinstance(crop, (bytes, bytearray)):
        crop = None
    return PlaceEvidence(
        crop_png=bytes(crop) if crop is not None else None,
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


def _veto_answer(
    veto: Any, query: str, place: PlaceEvidence
) -> tuple[str, float | None]:
    """Ask the installed veto about one place. Never raises into the gate.

    Accepts either a callable returning a :data:`VETO_PRESENT` /
    :data:`VETO_ABSENT` / :data:`VETO_UNAVAILABLE` string, or one returning an
    object with a ``.verdict`` (which is what
    :class:`parcel_robot.vlm_veto.VetoAnswer` is). The gate deliberately does not
    import ``vlm_veto`` — that package can import torch, and the gate is on the
    mission path.
    """

    if veto is None:
        return VETO_UNAVAILABLE, None
    try:
        answer = veto(query, place)
    except Exception:  # a broken seat is unavailable, not a refusal
        logger.warning("vlm veto raised; treating as unavailable", exc_info=True)
        return VETO_UNAVAILABLE, None
    verdict = getattr(answer, "verdict", answer)
    p_yes = getattr(answer, "p_yes", None)
    if verdict not in (VETO_PRESENT, VETO_ABSENT, VETO_UNAVAILABLE):
        logger.warning("vlm veto returned %r; treating as unavailable", verdict)
        return VETO_UNAVAILABLE, None
    try:
        p_yes = float(p_yes) if p_yes is not None else None
    except (TypeError, ValueError):
        p_yes = None
    return str(verdict), p_yes


def assess_place_query(
    query: str,
    *,
    support: DetectorSupport | None,
    places: Sequence[PlaceEvidence] = (),
    policy: AbstentionPolicy | None = None,
    map_similarities: Sequence[float] | None = None,
    veto: Any = None,
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

    def refuse(
        reason: str,
        signals: Mapping[str, float],
        *,
        candidate: PlaceEvidence | None = None,
    ) -> AbstentionVerdict:
        """Card P1-D: the ONE place a shortfall becomes a question.

        Every refusal in this function routes through here, so the ADMIT / ASK /
        REFUSE decision is made once and cannot be forgotten at one call site.
        The rule is small: the posture must be on, the reason must be a
        shortfall (:data:`ASK_ELIGIBLE_REASONS`), and there must be a candidate
        to ask ABOUT. Anything else is the refusal PG-3 always returned.
        """

        askable = (
            active.ask_below_threshold
            and reason in ASK_ELIGIBLE_REASONS
            and candidate is not None
        )
        if not askable:
            return AbstentionVerdict(
                False, text, reason, offers, None, dict(signals), OUTCOME_REFUSE
            )
        return AbstentionVerdict(
            False,
            text,
            reason,
            offers,
            candidate.place_id,
            dict(signals),
            OUTCOME_ASK,
            candidate.label,
        )

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
    #: The place an ASK will name. Card P1-D: the best-ranked candidate the map
    #: actually produced, chosen BEFORE any gate runs, because the question
    #: "might this be what you meant" is about the map's best guess and not
    #: about which threshold it happened to miss.
    front_runner = ranked[0] if ranked else None
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
            passed = {
                **signals,
                "label_purity": place.label_purity,
                "evidence_frames": float(place.evidence_frames),
                "ground_evidence_fraction": place.ground_evidence_fraction,
                "similarity": place.similarity,
            }
            # ------------------------------------------------- the veto ---
            # LAST, and only on a place that already passed every evidence
            # gate. That ordering is the whole safety argument for putting a
            # 2B model on this path: it can only ever take an admission away,
            # so a hallucinating verifier costs a question, never a place the
            # evidence did not earn. It is also why it runs at most once per
            # query instead of once per candidate — the crop it is shown is
            # the winner's, and asking about the losers would be paying GPU
            # time to re-rank, which is the thing a veto is not.
            if SIGNAL_VLM_VETO in on:
                # THE PRODUCER. ``veto=None`` from a caller means "use whatever
                # the config named", not "there is no veto" — see resolve_veto.
                # An explicit callable still wins, so a test can inject a stub
                # without touching process state.
                seat = veto if veto is not None else resolve_veto(active)
                answer, p_yes = _veto_answer(seat, text, place)
                passed["veto"] = 1.0 if answer == VETO_PRESENT else 0.0
                if p_yes is not None:
                    passed["veto_p_yes"] = float(p_yes)
                if answer == VETO_ABSENT:
                    # Evidence of absence, not absence of evidence. A REFUSE,
                    # and never softened into a question: something looked at
                    # the picture and said no.
                    return AbstentionVerdict(
                        False,
                        text,
                        ABSTAIN_VLM_VETO,
                        offers,
                        None,
                        passed,
                        OUTCOME_REFUSE,
                        place.label,
                    )
                if answer == VETO_UNAVAILABLE:
                    # No seat, no crop, or the GPU moment was declined. The
                    # evidence says yes and nothing contradicts it, but the
                    # signal the config selected did not run — so this is the
                    # one place an ADMIT degrades, and it degrades to ASK.
                    # The policy invariant guarantees the posture is on.
                    return refuse(
                        ABSTAIN_VETO_UNAVAILABLE, passed, candidate=place
                    )
            return AbstentionVerdict(
                True, text, GROUNDED, (), place.place_id, passed
            )
        if order.index(failed) > order.index(worst):
            worst = failed
    return refuse(worst, signals, candidate=front_runner)
