# Workstream S — Sol 5.6 Ultra: duplex pure modules

Rules as in task_4: new files only (`src/parcel_robot/duplex/`), numpy/stdlib
imports, injected clocks/seeds, frozen signatures (Opus builds against this
text), tests in-card, ruff clean.

---

## D-S1 — Frame contract + interleaver · `src/parcel_robot/duplex/frames.py`

```python
TEXT_SILENCE = "<silence>"
ACT_IDLE = "<idle>"

@dataclass(frozen=True)
class DuplexFrame:
    t: int                    # frame index on the shared clock
    epoch: int
    text: str                 # token text | TEXT_SILENCE
    act: str                  # act token   | ACT_IDLE

class FrameInterleaver:
    """Merge asynchronous text/act event feeds onto the fixed frame clock."""
    def __init__(self, *, frame_hz: float = 10.0): ...
    def push_text(self, token: str, *, epoch: int) -> None: ...
    def push_act(self, token: str, *, epoch: int) -> None: ...
    def set_epoch(self, epoch: int) -> None:  # drops queued items from older epochs
    def tick(self, *, now_s: float) -> DuplexFrame: ...
    def snapshot(self) -> dict[str, object]: ...
```

Merge rules pinned by tests: `tick` ALWAYS returns a frame (idle/silence
fill — the always-streaming discipline is enforced here, not by callers);
queued text drains one token per frame FIFO; multiple act pushes in one
frame window keep the LAST (acts are states, not a backlog — a stale glance
must not queue behind a twist); `set_epoch` drops all queued items from
older epochs and `tick` never emits a frame whose content epoch != current;
frame index increments monotonically even across epoch bumps; drift-free
frame timing from injected `now_s` (no cumulative error at 10 Hz over
10,000 ticks).

## D-S2 — Act token codec · `src/parcel_robot/duplex/act_codec.py`

```python
@dataclass(frozen=True)
class TwistBins:
    vx_bins: tuple[float, ...]      # e.g. (-0.3, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    vyaw_bins: tuple[float, ...]    # e.g. (-1.5, -0.7, 0.0, 0.7, 1.5)

class ActTokenCodec:
    def __init__(self, *, twist: TwistBins, gaze_bins: int = 8,
                 skills: Iterable[str] = (), emotes: Iterable[str] = (),
                 filler_gestures: int = 4): ...
    def vocabulary(self) -> tuple[str, ...]: ...
    def encode_twist(self, vx: float, vyaw: float) -> str: ...       # nearest bin
    def decode(self, token: str) -> ActCommand: ...                  # typed union
    def is_idle(self, token: str) -> bool: ...

@dataclass(frozen=True)
class ActCommand:
    kind: str        # "idle" | "twist" | "gaze" | "skill" | "emote" | "filler_gesture"
    vx: float = 0.0
    vyaw: float = 0.0
    bearing_rad: float | None = None
    name: str | None = None
```

Tests: encode→decode round-trip lands on bin centers; out-of-range twists
clamp to edge bins (never raise — the codec is a boundary, the SafetyLimits
clamp downstream is the authority); unknown token → ValueError; vocabulary
is stable/sorted (token order is a model-facing contract — a reordering is
a breaking change and the test pins the exact list for the default config).

## D-S3 — Filler pool · `src/parcel_robot/duplex/fillers.py`

```python
@dataclass(frozen=True)
class FillerEntry:
    text: str
    gesture: str | None = None       # e.g. "<thinking_pose>"
    min_gap_s: float = 20.0          # no-repeat window for this entry

class FillerPool:
    def __init__(self, entries: Iterable[FillerEntry], *, rng_seed: int | None): ...
    def pick(self, *, now_s: float, personality_gain: float = 1.0
             ) -> FillerEntry | None: ...   # None only if pool empty/all suppressed
    def notify_spoken(self, entry: FillerEntry, *, now_s: float) -> None: ...
    @classmethod
    def default(cls, *, rng_seed: int | None = None) -> "FillerPool": ...
```

`default()` ships ≥6 owner-voiced variations ("Hmm, let me think…", "Just a
sec while I check that…", "Give me a moment…", "Good question — checking…",
…). Tests: consecutive picks never repeat within `min_gap_s`; all-suppressed
falls back to the least-recently-used entry rather than None when at least
one entry exists (the dog must never go mute past the 2 s ceiling because
of its own no-repeat rule — pin this explicitly); seeded determinism.
