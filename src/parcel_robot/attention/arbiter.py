"""Reaction selection engine: tiers, tracks, Improv scoring, habituation."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .stimuli import Stimulus


@dataclass(frozen=True)
class ReactionSpec:
    name: str
    tier: int  # 1 = lease-claiming, 2 = tracks-only
    tracks: frozenset[str]  # {"head_gaze", "expressive_posture", ...}
    base_rate: float  # 0..1
    factor_gains: Mapping[str, float]  # Improv exponents, from temperament
    cooldown_s: float
    habituation_key: str | None = None

    def __post_init__(self) -> None:
        if self.tier not in {1, 2}:
            raise ValueError("reaction tier must be 1 or 2")
        if not 0.0 <= self.base_rate <= 1.0:
            raise ValueError("base_rate must be in [0, 1]")
        if not math.isfinite(self.cooldown_s) or self.cooldown_s < 0.0:
            raise ValueError("cooldown_s must be finite and non-negative")


@dataclass(frozen=True)
class ReactionDecision:
    reaction: str | None  # None = no reaction this tick
    weights: Mapping[str, float]  # full audit record
    seed: int
    suppressed: Mapping[str, str]  # name -> filter reason


@dataclass
class _HabituationState:
    repetitions: int = 0
    signed_weight: float = 0.0
    last_fire_s: float | None = None
    last_decay_s: float | None = None
    engaged: bool = True


class ReactionArbiter:
    """Selection engine only — no runtime / brain imports."""

    def __init__(
        self,
        specs: Iterable[ReactionSpec],
        *,
        rng_seed: int | None,
        commitment_bonus: float = 1.25,
        min_dwell_s: float = 0.6,
        signed_tau_s: float = 5.0,
        signed_floor: float = -1.0,
    ) -> None:
        self._specs = tuple(specs)
        names = [spec.name for spec in self._specs]
        if len(names) != len(set(names)):
            raise ValueError("reaction names must be unique")
        if not math.isfinite(commitment_bonus) or commitment_bonus < 1.0:
            raise ValueError("commitment_bonus must be finite and >= 1")
        if not math.isfinite(min_dwell_s) or min_dwell_s < 0.0:
            raise ValueError("min_dwell_s must be finite and non-negative")
        self._commitment_bonus = float(commitment_bonus)
        self._min_dwell_s = float(min_dwell_s)
        self._signed_tau_s = float(signed_tau_s)
        self._signed_floor = float(signed_floor)
        self._rng = random.Random(rng_seed)
        self._seed_counter = 0 if rng_seed is None else int(rng_seed)
        self._last_reaction: str | None = None
        self._last_reaction_at: float | None = None
        self._cooldowns: dict[str, float] = {}
        self._habituation: dict[str, _HabituationState] = {}
        self._track_holders: dict[str, str] = {}

    def tick(
        self,
        *,
        now_s: float,
        stimuli: Sequence[Stimulus],
        factors: Mapping[str, float],
        available_tracks: frozenset[str],
        vetoed: bool,
    ) -> ReactionDecision:
        if not math.isfinite(now_s):
            raise ValueError("now_s must be finite")

        self._decay_signed(now_s)
        suppressed: dict[str, str] = {}
        weights: dict[str, float] = {}

        if vetoed:
            for spec in self._specs:
                suppressed[spec.name] = "t0_veto"
                weights[spec.name] = 0.0
            seed = self._next_seed()
            return ReactionDecision(None, weights, seed, suppressed)

        # Commitment / dwell: keep the current reaction while dwelling.
        if (
            self._last_reaction is not None
            and self._last_reaction_at is not None
            and (now_s - self._last_reaction_at) < self._min_dwell_s
        ):
            seed = self._next_seed()
            weights = {self._last_reaction: 1.0}
            return ReactionDecision(self._last_reaction, weights, seed, suppressed)

        candidates: list[tuple[ReactionSpec, float]] = []
        stimulus_energy = _stimulus_energy(stimuli)

        for spec in self._specs:
            ready_at = self._cooldowns.get(spec.name, float("-inf"))
            if now_s < ready_at:
                suppressed[spec.name] = "cooldown"
                weights[spec.name] = 0.0
                continue
            if not spec.tracks.issubset(available_tracks):
                suppressed[spec.name] = "tracks_unavailable"
                weights[spec.name] = 0.0
                continue
            # Held tracks block other reactions until notify_outcome clears them.
            held_by_other = any(
                (holder := self._track_holders.get(track)) is not None and holder != spec.name
                for track in spec.tracks
            )
            if held_by_other:
                suppressed[spec.name] = "track_held"
                weights[spec.name] = 0.0
                continue

            score = self._improv_score(spec, factors, stimulus_energy)
            if spec.habituation_key is not None:
                hab = self._habituation.setdefault(spec.habituation_key, _HabituationState())
                # Repetition penalty + signed Kismet term for gaze-class keys.
                score *= max(0.05, 1.0 - 0.15 * hab.repetitions)
                if spec.habituation_key.startswith("gaze") or "gaze" in spec.habituation_key:
                    score *= max(0.0, 1.0 + hab.signed_weight)

            if score <= 0.0:
                suppressed[spec.name] = "zero_score"
                weights[spec.name] = 0.0
                continue

            if self._last_reaction == spec.name:
                score *= self._commitment_bonus

            # Under unit factors score≈1, so Bernoulli(base_rate) holds.
            weight = score * spec.base_rate
            weights[spec.name] = weight
            candidates.append((spec, weight))

        seed = self._next_seed()
        rng = random.Random(seed)
        if not candidates:
            return ReactionDecision(None, weights, seed, suppressed)

        # Normalize relative scores, then fire with mean(base_rate*score).
        # Single-candidate unit-factor case → P(fire) ≈ base_rate.
        total = sum(weight for _, weight in candidates)
        if total <= 0.0:
            return ReactionDecision(None, weights, seed, suppressed)
        mean_rate = total / len(candidates)
        if rng.random() > min(1.0, mean_rate):
            return ReactionDecision(None, weights, seed, suppressed)

        pick = rng.choices(
            [spec for spec, _ in candidates],
            weights=[weight for _, weight in candidates],
            k=1,
        )[0]
        self._last_reaction = pick.name
        self._last_reaction_at = now_s
        for track in pick.tracks:
            self._track_holders[track] = pick.name
        return ReactionDecision(pick.name, weights, seed, suppressed)

    def notify_outcome(self, reaction: str, *, success: bool, now_s: float) -> None:
        """Record outcome; ``success=False`` resets signed weight for the key.

        Disengagement reset is exposed on the frozen API via ``success=False``
        (keeps the ``notify_outcome`` signature unchanged).
        """

        if not math.isfinite(now_s):
            raise ValueError("now_s must be finite")
        match = next((spec for spec in self._specs if spec.name == reaction), None)
        if match is None:
            raise ValueError(f"unknown reaction: {reaction}")
        self._cooldowns[reaction] = now_s + match.cooldown_s
        if match.habituation_key is not None:
            hab = self._habituation.setdefault(match.habituation_key, _HabituationState())
            if success:
                hab.repetitions += 1
                if match.habituation_key.startswith("gaze") or "gaze" in match.habituation_key:
                    # Drive toward negative floor (disengage after dwell).
                    hab.signed_weight = max(self._signed_floor, hab.signed_weight - 0.35)
                    hab.engaged = True
                hab.last_fire_s = now_s
                hab.last_decay_s = now_s
            else:
                # Reset-on-disengagement: clear signed weight for this key.
                hab.signed_weight = 0.0
                hab.repetitions = 0
                hab.engaged = False
                hab.last_fire_s = now_s
                hab.last_decay_s = now_s
        # Release tracks on completion.
        self._track_holders = {
            track: holder
            for track, holder in self._track_holders.items()
            if holder != reaction
        }
        if self._last_reaction == reaction:
            self._last_reaction = None
            self._last_reaction_at = None

    def snapshot(self) -> dict[str, object]:
        return {
            "last_reaction": self._last_reaction,
            "last_reaction_at": self._last_reaction_at,
            "cooldowns": dict(self._cooldowns),
            "track_holders": dict(self._track_holders),
            "habituation": {
                key: {
                    "repetitions": state.repetitions,
                    "signed_weight": state.signed_weight,
                    "last_fire_s": state.last_fire_s,
                    "last_decay_s": state.last_decay_s,
                    "engaged": state.engaged,
                }
                for key, state in self._habituation.items()
            },
            "specs": [spec.name for spec in self._specs],
        }

    def _improv_score(
        self,
        spec: ReactionSpec,
        factors: Mapping[str, float],
        stimulus_energy: float,
    ) -> float:
        # w = Scale(Π factor_i ^ gain_i); missing factors default to 1.
        # Unit factors + full stimulus energy → score 1.0 so base_rate dominates.
        product = 1.0
        for name, gain in spec.factor_gains.items():
            value = float(factors.get(name, 1.0))
            if value < 0.0 or not math.isfinite(value):
                return 0.0
            product *= max(value, 1e-6) ** float(gain)
        product *= max(stimulus_energy, 1e-6)
        return float(max(0.0, min(1.5, product)))

    def _decay_signed(self, now_s: float) -> None:
        """Exponential pull toward floor using dt since last decay/post-fire.

        Using ``now - last_fire`` every tick would re-apply the full horizon on
        an already-decayed weight (compounding). Baseline is ``last_decay_s``
        (set at fire and after each decay step) so τ is honored once.
        """

        tau = max(self._signed_tau_s, 1e-3)
        for state in self._habituation.values():
            baseline_s = state.last_decay_s
            if baseline_s is None:
                baseline_s = state.last_fire_s
            if baseline_s is None:
                continue
            if not state.engaged:
                # After disengagement reset, recover toward neutral/positive.
                state.signed_weight = min(0.0, state.signed_weight + 0.2)
                state.last_decay_s = now_s
                continue
            dt = max(0.0, now_s - baseline_s)
            if dt <= 0.0:
                continue
            target = self._signed_floor
            state.signed_weight = target + (state.signed_weight - target) * math.exp(
                -dt / tau
            )
            state.last_decay_s = now_s

    def _next_seed(self) -> int:
        self._seed_counter += 1
        # Mix arbiter RNG state so successive ticks differ under one seed.
        return (self._seed_counter * 1_000_003) ^ self._rng.randint(0, 2**31 - 1)


def _stimulus_energy(stimuli: Sequence[Stimulus]) -> float:
    if not stimuli:
        return 1.0  # ambient baseline; temperament factors still modulate
    return float(max(0.05, min(1.0, max(item.confidence for item in stimuli))))


__all__ = [
    "ReactionArbiter",
    "ReactionDecision",
    "ReactionSpec",
]
