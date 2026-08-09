"""Fail-closed StimulusBus ↔ ReactionArbiter path (K6 / B2).

Social reactions may overlay ``expression_audio`` / ``attention`` only. They
must never claim or preempt ``base``. When the base track is busy (follow,
navigation, critical phase), the bridge vetoes lease-claiming reactions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parcel_robot.attention.arbiter import ReactionArbiter, ReactionDecision, ReactionSpec
from parcel_robot.attention.stimuli import Stimulus, StimulusBus, StimulusKind
from parcel_robot.contracts.v1 import RESOURCE_TRACKS, ReactionProposalV1, SocialCueV1

# Social path may never own locomotion.
FORBIDDEN_REACTION_TRACKS = frozenset({"base", "posture", "perception_scan"})
SAFE_REACTION_TRACKS = frozenset({"attention", "expression_audio", "voice"})


@dataclass(frozen=True, slots=True)
class ReactionTickResult:
    decision: ReactionDecision
    drained: tuple[Stimulus, ...]
    vetoed: bool
    reason: str


def default_social_specs() -> tuple[ReactionSpec, ...]:
    """Tier-2 expression/attention reactions only — no base leases."""

    return (
        ReactionSpec(
            name="soft_glance",
            tier=2,
            tracks=frozenset({"attention"}),
            base_rate=0.35,
            factor_gains={"sociability": 1.0},
            cooldown_s=1.5,
            habituation_key="gaze_soft",
        ),
        ReactionSpec(
            name="mutual_gaze_listen",
            tier=2,
            tracks=frozenset({"attention"}),
            base_rate=0.55,
            factor_gains={"sociability": 1.2},
            cooldown_s=0.8,
            habituation_key="gaze_mutual",
        ),
        ReactionSpec(
            name="gaze_aversion_think",
            tier=2,
            tracks=frozenset({"attention"}),
            base_rate=0.45,
            factor_gains={"sociability": 0.8},
            cooldown_s=1.0,
            habituation_key="gaze_aversion",
        ),
        ReactionSpec(
            name="acoustic_chuckle",
            tier=2,
            tracks=frozenset({"expression_audio"}),
            base_rate=0.25,
            factor_gains={"sociability": 1.1, "playfulness": 1.0},
            cooldown_s=2.0,
            habituation_key="chuckle",
        ),
    )


def tracks_are_social_safe(tracks: Sequence[str] | frozenset[str]) -> bool:
    track_set = frozenset(tracks)
    if not track_set:
        return False
    if track_set & FORBIDDEN_REACTION_TRACKS:
        return False
    # Also reject unknown track names outside the V1 resource vocabulary when
    # they look like motion (legacy head_gaze is remapped by the bridge).
    return True


def proposal_preempts_base(proposal: ReactionProposalV1) -> bool:
    return bool(frozenset(proposal.required_tracks) & FORBIDDEN_REACTION_TRACKS)


class SocialReactionBridge:
    """Stub-wireable bus+arbiter with hard base-preemption denial."""

    def __init__(
        self,
        *,
        specs: Sequence[ReactionSpec] | None = None,
        rng_seed: int | None = 11,
    ) -> None:
        for spec in specs or default_social_specs():
            if not tracks_are_social_safe(_normalize_tracks(spec.tracks)):
                raise ValueError(
                    f"reaction {spec.name!r} claims a forbidden track for social path"
                )
        normalized = tuple(
            ReactionSpec(
                name=spec.name,
                tier=spec.tier,
                tracks=_normalize_tracks(spec.tracks),
                base_rate=spec.base_rate,
                factor_gains=dict(spec.factor_gains),
                cooldown_s=spec.cooldown_s,
                habituation_key=spec.habituation_key,
            )
            for spec in (specs or default_social_specs())
        )
        self.bus = StimulusBus()
        self.arbiter = ReactionArbiter(normalized, rng_seed=rng_seed)
        self._last: ReactionTickResult | None = None
        self.false_base_preempt_attempts = 0

    @property
    def last_result(self) -> ReactionTickResult | None:
        return self._last

    def add_stimulus(
        self,
        kind: StimulusKind | str,
        *,
        at_s: float,
        confidence: float,
        payload: Mapping[str, object] | None = None,
        commit: bool = True,
    ) -> int:
        stimulus_kind = kind if isinstance(kind, StimulusKind) else StimulusKind(str(kind))
        unit_id = self.bus.add(
            Stimulus(
                kind=stimulus_kind,
                at_s=at_s,
                confidence=confidence,
                payload=dict(payload or {}),
            )
        )
        if commit:
            self.bus.commit(unit_id)
        return unit_id

    def ingest_social_cue(self, cue: SocialCueV1, *, at_s: float) -> int:
        return self.add_stimulus(
            StimulusKind.AFFECT,
            at_s=at_s,
            confidence=float(cue.confidence),
            payload={
                "cue_id": cue.cue_id,
                "kind": cue.kind,
                "modality": cue.modality,
                "valence": cue.valence,
                "arousal": cue.arousal,
            },
            commit=True,
        )

    def admit_proposal(self, proposal: ReactionProposalV1) -> bool:
        """Return False (and count) when a proposal would wrongly preempt base."""

        if proposal_preempts_base(proposal):
            self.false_base_preempt_attempts += 1
            return False
        if not tracks_are_social_safe(proposal.required_tracks):
            self.false_base_preempt_attempts += 1
            return False
        return True

    def tick(
        self,
        *,
        now_s: float,
        factors: Mapping[str, float] | None = None,
        base_busy: bool = False,
        critical_phase: bool = False,
        available_tracks: frozenset[str] | None = None,
    ) -> ReactionTickResult:
        drained = self.bus.drain(now_s=now_s)
        vetoed = bool(base_busy or critical_phase)
        reason = "ok"
        if base_busy:
            reason = "base_busy"
        elif critical_phase:
            reason = "critical_phase"

        tracks = available_tracks if available_tracks is not None else SAFE_REACTION_TRACKS
        # Never expose base/posture to the social arbiter.
        safe_tracks = frozenset(_normalize_tracks(tracks)) - FORBIDDEN_REACTION_TRACKS
        decision = self.arbiter.tick(
            now_s=now_s,
            stimuli=drained,
            factors=dict(factors or {"sociability": 0.7}),
            available_tracks=safe_tracks,
            vetoed=vetoed,
        )
        result = ReactionTickResult(
            decision=decision,
            drained=drained,
            vetoed=vetoed,
            reason=reason if vetoed else ("idle" if decision.reaction is None else "selected"),
        )
        self._last = result
        return result


def _normalize_tracks(tracks: Sequence[str] | frozenset[str]) -> frozenset[str]:
    """Map legacy attention names onto V1 resource tracks."""

    mapped: set[str] = set()
    for track in tracks:
        if track in {"head_gaze", "gaze"}:
            mapped.add("attention")
        elif track in {"expressive_posture", "ear_flip"}:
            # Expression overlays must not take posture/base.
            mapped.add("expression_audio")
        elif track in RESOURCE_TRACKS:
            mapped.add(track)
        else:
            mapped.add(track)
    return frozenset(mapped)


__all__ = [
    "FORBIDDEN_REACTION_TRACKS",
    "SAFE_REACTION_TRACKS",
    "ReactionTickResult",
    "SocialReactionBridge",
    "default_social_specs",
    "proposal_preempts_base",
    "tracks_are_social_safe",
]
