# Workstream A — expressive liveness (sim, no hardware dependencies)

Goal: the dog visibly *lives* in the MuJoCo viewer — breathing at idle,
orienting to speech, nodding on the beats of its own voice — with every motion
additive, clamped, and subordinate to safety. Design source:
[../../../docs/RESEARCH_2026_ROADMAPS.md](../../../docs/RESEARCH_2026_ROADMAPS.md) §1
(speech-synced motion) and §2 (steps 1–2).

---

## A1 — IdleLayer + deterministic reaction hooks · **Owner: Claude Opus**

New module `src/parcel_robot/expression.py` + wiring in `runtime.py`.

**What.** A 10 Hz expressive offset channel producing small additive targets:
`ExpressiveOffsets(body_height_m, body_pitch_rad, head_yaw_rad, head_pitch_rad)`.
Two producers composed by a tiny `MotionMixer` (priority: reaction > idle):

- **IdleLayer** (always on when standing): sinusoidal breathing 0.2–0.3 Hz at
  ±4 mm body height; occasional weight shift + look-around every 4–8 s
  (seeded RNG injected for determinism in tests).
- **ReactionHooks** (event-driven, each a small state machine with a fixed
  duration and cosine ease-in/out):
  - voice activity begins (hook from `MicrophoneVoiceLoop` speech_start or
    `submit_voice_text` partial) → head-orient toward owner bearing within
    300 ms, hold while speech continues;
  - turn submitted, reply pending → "thinking" pose (head tilt ~8°, slight
    body-height drop) owning the gap until `tts_start`;
  - `tts_start` → release thinking pose.

**Amplitude gating (ELEGNT rule):** full amplitude when idle/conversing;
head-only when navigation or follow is active; zero when any of: E-stop
latched, proximity state ≠ clear, battery critical, or a pose/trajectory
skill is executing. Read these from existing runtime state — do not add new
state.

**Execution path.** Offsets apply to the *pose channel only* (the stance the
pose runner holds), never the SE2 velocity channel. In sim the runtime applies
them to the held stance joints via the existing `RobotProfile.stand_joints()`
+ a small mapping (body height → hip/knee delta via `profile` IK helpers;
head yaw/pitch → a viewer-visible head field in the snapshot for now —
the Go2 has no articulated neck; the viewer renders the head cone from it).
Add `expression` block to `snapshot()`: current offsets, active producer,
gating mode.

**Hard clamps in one place** (`ExpressiveOffsets.clamped()`): |height| ≤ 2 cm,
|pitch| ≤ 6°, |head yaw| ≤ 40°, |head pitch| ≤ 12°.

**Acceptance.**
- Unit tests: gating matrix (E-stop/nav/critical battery → zero or head-only),
  clamp enforcement, reaction timing (speech_start → orient within 3 ticks),
  determinism with seeded RNG.
- Runtime test: snapshot exposes `expression`; follow-bench suite unchanged
  (0 hard collisions — expression must not perturb navigation commands).
- Viewer: head cone + breathing visible (extend `viewer.html` state consumer;
  keep it minimal).

---

## A2 — ProsodyTap DSP module · **Owner: ChatGPT Sol 5.6 Ultra**

New file `src/parcel_robot/prosody.py` + `tests/test_prosody.py`. **Import
only numpy + stdlib.** No Parcel imports except none — this is a pure module;
Opus wires it in A4.

**Contract (frozen — do not rename):**

```python
@dataclass(frozen=True)
class BeatTrack:
    duration_s: float
    accents: tuple[Accent, ...]        # Accent(time_s: float, strength: float in (0,1])
    envelope_hop_s: float              # 0.010
    rms_envelope: tuple[float, ...]    # normalized 0..1
    arousal: float                     # 0..1 scalar for the whole chunk

def analyze_wav_chunk(wav_bytes: bytes) -> BeatTrack: ...
def analyze_pcm16(pcm: bytes, sample_rate_hz: int) -> BeatTrack: ...
```

**Algorithm (from the research; keep it this simple):** 10 ms-hop RMS
envelope; accent candidates = local maxima of the half-wave-rectified
d(envelope)/dt (onset strength), gated by a pitch-prominence check
(autocorrelation F0 over a 40 ms window centered on the peak; accept voiced
peaks whose F0 sits above the chunk's median F0 or whose onset strength is in
the top quartile); enforce ≥120 ms minimum inter-accent spacing (keep the
stronger). `strength` = onset strength normalized to the chunk max. `arousal`
= weighted mix of normalized mean RMS (0.5), speaking-rate proxy = accents/s
scaled (0.3), and F0 range (0.2), clipped to [0,1]. Handle: WAV header parsing
(mono 16-bit PCM; resample not required — accept any rate via
`analyze_pcm16`), chunks < 200 ms (return empty accents, arousal from RMS
only), silence (arousal 0, no accents).

**Performance budget:** < 5 ms for a 3 s chunk on CPU (vectorized numpy; no
per-sample Python loops).

**Acceptance (write these tests):** synthetic click-train WAV → accents within
±15 ms of ground truth; pure silence → no accents, arousal 0.0; loud fast
amplitude-modulated tone vs quiet slow one → strictly higher arousal;
< 200 ms chunk → no crash, no accents; malformed WAV → ValueError. Include a
speed test asserting the budget with `time.perf_counter` (generous 3× margin
for CI noise).

---

## A3 — Endpointing module: Silero VAD v6 + Smart Turn v3 · **Owner: ChatGPT Sol 5.6 Ultra**

New file `src/parcel_robot/endpointing.py` + `tests/test_endpointing.py`.
Imports: numpy, stdlib, and `onnxruntime` **lazily inside methods** (module
import must succeed without it). No Parcel imports.

**Contract (frozen):**

```python
class SileroVad:
    def __init__(self, model_path: str, *, threshold: float = 0.5): ...
    def process(self, frame: np.ndarray) -> float:  # int16 mono, 512 samples @16 kHz → speech prob
    @property
    def available(self) -> bool: ...                # model file + onnxruntime present

class TurnEndpointer:
    """Dual-timeout semantic endpointing (Smart Turn v3 pattern)."""
    def __init__(self, model_path: str | None, *,
                 complete_silence_s: float = 0.20,
                 incomplete_silence_s: float = 2.5): ...
    def observe(self, *, is_speech: bool, audio_tail: np.ndarray | None,
                now_s: float) -> str:   # returns "speaking" | "hold" | "commit"
    @property
    def detail(self) -> str: ...        # e.g. "smart-turn-v3" | "fixed-timeout-fallback"
```

Semantics: while `is_speech`, return "speaking" and reset silence tracking.
On silence, run the turn model on the recent audio tail (8 s max, int8 ONNX,
Whisper-Tiny-encoder-style input — follow the pipecat-ai/smart-turn v3 repo's
preprocessing exactly; document the model download URL in the module
docstring): probability ≥ 0.5 ("complete") → "commit" after
`complete_silence_s` of silence; otherwise "hold" until
`incomplete_silence_s` elapses, then "commit" regardless. If the model or
onnxruntime is unavailable → `detail` reports the fallback and the class
degrades to a single fixed `incomplete_silence_s` timeout (current Parcel
behavior, loudly).

**Acceptance:** deterministic tests with a stubbed inference callable
(constructor accepts `_infer` injection for tests): complete-sounding tail →
commit at ~0.2 s; incomplete → hold then commit at 2.5 s; model-missing
fallback path; frame-size validation errors. No network access in tests; the
real ONNX path is exercised only if the model file exists
(`pytest.mark.skipif`).

---

## A4 — Integration + metrics · **Owner: Claude Opus** (after A1–A3 land)

1. **BeatLayer** in `expression.py`: consumes `BeatTrack` (from A2, tapped in
   `SentenceChunkedSynthesizer` → `SpeakerSink` seam right before enqueue,
   timestamps rebased to the playback clock) → schedules head-nod apexes
   (reaction-priority offsets through the A1 mixer, arousal scales amplitude).
   Sim-only lag compensation constant (default 0 in sim; config key for
   hardware later). Epoch-tag scheduled nods; `SpeakerSink.interrupt()` (and
   thus barge-in) flushes pending ones — extend the session's
   `audio_turn_start`/interrupt callbacks, do not invent a new channel.
2. **Mic-loop endpointing**: `MicrophoneVoiceLoop` accepts an optional
   `endpointer`; when present, Silero probability (fed the same frames)
   replaces the energy `voiced` decision (energy floor stays as pre-gate) and
   utterance finalization consults `TurnEndpointer.observe` instead of the
   fixed hangover. Config: `speech.vad_model`, `speech.turn_model`,
   `speech.endpointing: energy|semantic`. Missing models → loud fallback to
   energy mode (existing behavior).
3. **Metrics** (follow `VoiceEndOfSpeechToFirstAudio` pattern in runtime):
   `ApexToAccentError` (per scheduled vs delivered nod, sim clock),
   `TurnCommitLatency` (end-of-speech → commit), `FalseInterruptRate` counter
   (barge-ins later classified as backchannel — count only for now). Expose in
   `/api/state` under `speech` / `expression`.

**Acceptance:** sim run with scripted TTS audio shows nods at accents with
P50 ApexToAccentError < 30 ms; endpointing tests for both modes; full suite +
follow-bench green; ledger row appended if any eval-visible number moves.
