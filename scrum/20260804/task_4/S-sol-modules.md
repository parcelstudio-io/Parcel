# Workstream S — Sol 5.6 Ultra: pure modules, frozen contracts

Rules for every card: new files only; imports limited to numpy/stdlib (no
`parcel_robot.runtime`, no `parcel_robot.brain`); deterministic under
injected seeds/clocks (no `time.time()` inside logic — accept `now_s`);
every public function/dataclass exactly as written here (Opus builds against
these signatures sight-unseen); tests in the same card; ruff clean.

---

## S1 — Preemption policy table · `src/parcel_robot/core/preemption.py`

The single source of truth that replaces 16 hand-enumerated stop sites.

```python
class PreemptionAction(str, Enum):
    NONE = "none"            # channels coexist
    PAUSE = "pause"          # suspend, record ResumeIntent, resume later
    STOP = "stop"            # destructive cancel (today's only behavior)
    DEFER = "defer"          # new claimant queues until current releases

@dataclass(frozen=True)
class ChannelSpec:
    name: str                # "navigation" | "follow" | "spatial" | ...
    source: str              # CommandArbiter source name
    priority: int            # mirrors SOURCE_PRIORITIES
    pausable: bool = False

@dataclass(frozen=True)
class PreemptionDecision:
    action: PreemptionAction
    reason: str

class PreemptionTable:
    def __init__(self, channels: Iterable[ChannelSpec],
                 rules: Mapping[tuple[str, str], PreemptionAction]): ...
    def decide(self, claimant: str, active: str) -> PreemptionDecision: ...
    def channels(self) -> tuple[ChannelSpec, ...]: ...
    @classmethod
    def default(cls) -> "PreemptionTable": ...
```

`default()` encodes today's actual behavior (mined from the audit: who stops
whom — manual stops everything; voice-motion stops follow/nav/spatial;
pose stops follow/nav/spatial; navigation cancels follow; search pauses
follow with resume — the ONE existing resume) so O2's replacement is
behavior-preserving by construction. Unknown channel pairs → STOP with
reason "undeclared_pair" (fail closed, loudly greppable). Full matrix test:
every declared pair has an explicit expectation; adding a channel without
rules fails a completeness test.

## S2 — Resume + generation tokens · `src/parcel_robot/core/resume.py`

```python
@dataclass(frozen=True)
class ResumeIntent:
    channel: str
    payload: Mapping[str, object]     # typed per channel by the consumer
    suspend_reason: str
    suspended_at_s: float
    valid_for_s: float                # expiry; stale resumes are dropped
    requires_fresh_observation: bool = False

    def expired(self, now_s: float) -> bool: ...

class ResumeStore:
    """At most one intent per channel; replace-on-suspend, take-on-resume."""
    def record(self, intent: ResumeIntent) -> None: ...
    def take(self, channel: str, *, now_s: float) -> ResumeIntent | None: ...
    def peek(self, channel: str, *, now_s: float | None = None) -> ResumeIntent | None: ...
    def clear(self, channel: str | None = None) -> None: ...
    def snapshot(self) -> dict[str, object]: ...

class GenerationTokens:
    """Per-channel monotonic tokens replacing the global _behavior_generation."""
    def bump(self, channel: str) -> int: ...
    def current(self, channel: str) -> int: ...
    def is_current(self, channel: str, token: int) -> bool: ...
```

`peek` drops expired intents when `now_s` is provided (returns `None`); prefer
passing `now_s` so callers never see a stale resume. `take` already filters
expiry. (Arbitration 2026-08-04: peek must not return expired.)

Thread-safe (one lock; these are touched from control + voice threads).
Tests: expiry, replace-on-suspend, take-clears, peek-drops-expired,
unknown-channel token starts at 0, bump isolation between channels (the
audit's core complaint about the global counter: bumping one channel must
not invalidate another's in-flight checks — pin that as the named
regression test).

## S3 — Typed channel details · `src/parcel_robot/core/details.py`

Frozen dataclasses replacing the stringly `_detail` dicts, with exact-shape
`as_dict()` so the panel/tests see identical JSON:
`NavigationDetail`, `SpatialDetail`, `FollowDetail`, `VoiceDetail` — fields
mined from every current producer/consumer (grep before writing; the dict
keys in `runtime.py` today are the contract). Each has
`@classmethod from_dict()` for migration and `replace(**kw)` convenience.
Tests: `as_dict()` round-trip equals the current literal shapes captured
from `runtime.py` (copy the shapes into the test as goldens — drift fails).

## S4 — Stimulus bus · `src/parcel_robot/attention/stimuli.py`

Per task_3 card V2, contracts restated:

```python
class StimulusKind(str, Enum):
    SPEECH_ONSET = "speech_onset"; SUMMONS_PROSODY = "summons_prosody"
    NAME_HIT = "name_hit"; AFFECT = "affect"; KEYWORD = "keyword"
    SPEECH_END = "speech_end"

@dataclass(frozen=True)
class Stimulus:
    kind: StimulusKind
    at_s: float
    confidence: float                  # 0..1
    payload: Mapping[str, object] = field(default_factory=dict)
    unit_id: int = 0                   # IU lifecycle identity

class StimulusBus:
    def add(self, stimulus: Stimulus) -> int: ...
    def revoke(self, unit_id: int) -> bool: ...
    def commit(self, unit_id: int) -> bool: ...
    def drain(self, *, now_s: float, max_age_s: float = 2.0
              ) -> tuple[Stimulus, ...]: ...   # committed, fresh, FIFO

def summons_prosody_score(pcm: np.ndarray, sample_rate_hz: int) -> float: ...
def name_fusion_score(name_posterior: float, facing_deg: float,
                      distance_m: float) -> float: ...
```

`summons_prosody_score`: F0 mean/rise/variance + energy over the window;
rising-contour high-energy calls score high, flat conversation low. Tests
with synthetic contours (rising call vs monotone vs silence), REVOKE before
COMMIT removes, drain drops stale, thread-safety smoke.

## S5 — ReactionArbiter core · `src/parcel_robot/attention/arbiter.py`

Per task_3 card V3, the selection engine only. Key contracts:

```python
@dataclass(frozen=True)
class ReactionSpec:
    name: str
    tier: int                          # 1 = lease-claiming, 2 = tracks-only
    tracks: frozenset[str]             # {"head_gaze", "expressive_posture", ...}
    base_rate: float                   # 0..1
    factor_gains: Mapping[str, float]  # Improv exponents, from temperament
    cooldown_s: float
    habituation_key: str | None = None

@dataclass(frozen=True)
class ReactionDecision:
    reaction: str | None               # None = no reaction this tick
    weights: Mapping[str, float]       # full audit record
    seed: int
    suppressed: Mapping[str, str]      # name -> filter reason

class ReactionArbiter:
    def __init__(self, specs: Iterable[ReactionSpec], *, rng_seed: int | None,
                 commitment_bonus: float = 1.25, min_dwell_s: float = 0.6): ...
    def tick(self, *, now_s: float, stimuli: Sequence[Stimulus],
             factors: Mapping[str, float], available_tracks: frozenset[str],
             vetoed: bool) -> ReactionDecision: ...
    def notify_outcome(self, reaction: str, *, success: bool, now_s: float) -> None: ...
    def snapshot(self) -> dict[str, object]: ...
```

Habituation inside: cooldown filter, repetition penalty per habituation_key,
Kismet signed decay (w → −W, τ configurable, reset on disengagement) for
gaze-class keys. **Reset-on-disengagement:** `notify_outcome(success=False)`
clears signed weight / repetitions for that reaction's habituation key
(frozen signature unchanged). Signed decay advances from last-decay /
post-fire baseline so τ is honored once (not re-applied every tick).
`_track_holders` is a hard filter in `tick`. Tests: determinism under seed;
veto zeroing; track contention + holder blocking; 10k-draw rate bands
(base_rate 0.4 → observed 0.36–0.44); soft commitment after dwell
(`min_dwell_s=0`, bonus>1) prevents A↔B flicker vs bonus=1; τ≈5 over 5s
lands near e^{-1}; signed habituation goes negative then recovers via
`notify_outcome(False)`.
