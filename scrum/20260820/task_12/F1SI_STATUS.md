# F1-SI status — the owner's voice (speech identity for command arming)

**Card:** `scrum/20260820/task_12/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable · **Date:** 2026-08-21 (UTC) · **Hosted spend: $0.00** of
$1.50 (the credential was never loaded; everything below ran on local CPU).

---

## §0 — What landed, in one paragraph

A television commanded this robot twice on 2026-08-20. This card makes the robot
ask *whose voice was that* before it moves, and — the part that matters more —
makes sure it never asks that before it **stops**. A post-VAD speaker embedding
(titanet_small via sherpa-onnx, vendored under `models/speaker_id/` with a
provenance lock) runs once or twice per owner turn inside the audio gateway; a
cosine at or above a configurable threshold arms the turn. Arming gates the
local ingress commands **and the hosted model's five motion tools**, because the
sentence that actually moved the robot for a television — *"go to the bench"* —
is not a closed intent and never touched the ingress path at all. The emergency
latch is gated by none of it, by construction, and 5 of the 42 seeds attack that
property from five different directions. Gate green at **7164 passed** (baseline
7089, **+75**), **42/42 seeds RED**, FAR **0/112** and FRR **0/13** at the
shipped threshold measured through the production code path, and an end-to-end
proof in which an unrecognised voice is refused a command and then latches the
e-stop with the next breath.

**Both owner prerequisites were checked at dispatch and both are still open**
(§1). The card's fake-first instruction was therefore followed for the DoA half,
and — because no owner audio exists anywhere on this host — the "live proof with
the owner's enrolled voice" runs with a *synthetic* enrolled owner. That
substitution is the single biggest `does_not_prove` of this card and §9 says so
in those words.

---

## §1 — DISPATCH-GATE PREREQUISITE CHECK (run first, both still owner-blocked)

### (a) the udev rule — **BLOCKED**, tested with the staged `xvf_host VERSION`

```
$ cd <scratchpad>/evalbench/xvf3800-bench/xvf_host_bin && ./xvf_host VERSION
Error  : Failed to open device. Ensure adequate permissions if using Linux,
or remove any pre-installed drivers with Device Manager on Windows.
Error  : Failed to open device. Ensure adequate permissions if using Linux,
or remove any pre-installed drivers with Device Manager on Windows.
Error  : Failed to open device. Ensure adequate permissions if using Linux,
or remove any pre-installed drivers with Device Manager on Windows.
Device (USB)::device_init() -- No device found
Could not connect to the device
exit=8
```

Root cause unchanged from `bench_doa.md`, and re-verified rather than assumed:

```
$ ls -l /dev/bus/usb/003/008
crw-rw-r-- 1 root root 189, 263 Aug 20 09:33 /dev/bus/usb/003/008
$ getfacl /dev/bus/usb/003/008      # user::rw-  group::rw-  other::r--   (no ACL)
$ ls /etc/udev/rules.d/ | grep -i 'respeaker\|xvf\|2886'    # (no matching rule)
$ lsusb -d 2886:001a
Bus 003 Device 008: ID 2886:001a Seeed Technology Co., Ltd. reSpeaker XVF3800 4-Mic Array
```

The device is attached and enumerated; usbfs control transfers need `O_RDWR` and
the node is `root:root 0664`. **No sudo was attempted.** The exact two-line
unblock is in `bench_doa.md` and is now also quoted in
`configs/realtime.yaml.example` beside the `doa:` key, so the owner finds it
where they would look for it.

### (b) enrollment audio — **MISSING**

```
$ find evals/20260820 -name '*.wav' | wc -l      -> 0
$ ls recordings/                                  -> No such file or directory
$ find . -name owner.wav -not -path './.git/*'    -> (nothing)
```

No owner recordings, no R17-captured session with owner audio anywhere on this
host. `bench_doa.md`'s material caveat still holds exactly: the only microphone
files in scratch are room tone.

### Consequences, taken deliberately

| Card work item | What was built | What is owner-blocked |
| --- | --- | --- |
| 1 — embedding verify | **fully live**, real model, real code path | nothing |
| 2 — safety asymmetry | **fully live** + 5 seeds | nothing |
| 3 — enrollment | **fully live** CLI, run end-to-end in §7 | the owner's *own* voice |
| 4 — DoA prefilter | built, test-doubled, `doa: false` default | every real read (udev) |
| 5 — eval tie-in | impostor corpus + `voice_provenance` check | a live corpus replay |

**The stack was NOT running** during this card (`GET http://127.0.0.1:8765/api/state`
→ `URLError [Errno 111] Connection refused`), so nothing here contended with an
owner session. No file under `~/.config/parcel/` was written or modified.

---

## §2 — The gate, verbatim, after the final edit

```
CI GATE — tier=commit  (2026-08-21T02:15:26Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.39s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.26s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.40s
[  PASS] HARD  default-suite              7164 passed, 9 skipped, 42 deselected, 5 warnings in 275.91s (0:04:35)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 289.2s
```

Baseline before any edit, same command, same host: `7089 passed, 9 skipped,
42 deselected`, ruff `7 violation(s), baseline 7, new 0`. So **+75 tests, 0
removed, 0 new ruff debt.** `assertion-evals` still reproduces its **20 pinned
findings byte-identically** with the twelfth check registered — the new check
adds zero findings to the frozen fixtures, which is correct: none of them
carries a voice-provenance row.

Re-run once more after the last edit in this tree (this document), per the
register's "re-run after the final edit" rule — `CI GATE — tier=commit
(2026-08-21T02:25:09Z) … RESULT: PASS — every hard gate green. elapsed 284.1s`,
same `7164 passed, 9 skipped, 42 deselected` and same ruff `7 / baseline 7 /
new 0`. Nothing was committed, staged or stashed at any point.

---

## §3 — The design, and the one decision that is not in the card

### 3.1 The asymmetry is a function, not a convention

`realtime/voice_identity.gates_kind(kind)` returns `False` for exactly one
class, and it reads that class from `realtime/ingress.KIND_EMERGENCY` rather
than holding a copy of the string. `VoiceIdentityGate.decide()` short-circuits
on it **before** consulting a verdict, so for an emergency the module computes
no embedding, reads no profile, touches no microphone array and cannot fail.

This is stronger than "the check passes for a stop". A check that *passes* is a
check that can *fail*: it can be slow, it can raise, it can be misconfigured. The
short-circuit means there is no state of this object, and no failure inside it,
that stands between a spoken stop and the latch. S5 seeds precisely that
distinction — it deletes the short-circuit while leaving the pure function's own
guard in place, so the latch still arms but now *travels through* the verdict
path — and `test_the_emergency_class_never_reads_a_verdict_at_all` catches it by
making `current()` itself raise.

`realtime/ingress.py` was **not touched**. The asymmetry is enforced by gating
arming, exactly as the card requires.

### 3.2 The decision the card did not make: the motion tools are gated too

Reading the card literally, the identity gate belongs on the audio gateway and
the ingress arming path. Implementing only that would have shipped a card that
**does not fix F1.**

`ingress.scan("go to the bench")` returns `KIND_NONE`. It is not a closed
intent, not follow, not hold. The local path executes nothing for it. The
sentence that moves the robot is the **hosted model's `navigate_to` tool call**,
which arrives through `RealtimeToolBroker` → `ToolDoors` → the runtime's own
door callables. A gate on the ingress alone would have refused a stranger's
"follow me" and walked the dog on their "go to the bench" — the exact
instruction the television issued.

So the five MOTION doors are wrapped in `runtime._gate_by_voice`, one layer
outside R21's `_watch_under_latch`, which is the same seam R21 used for the same
reason and is runtime code rather than broker code (the card forbids touching
the broker; this does not). `get_status` and `recall_memory` are deliberately
**not** wrapped, for R21's stated reason one line above them: answering a
question is not arming, and a robot that stops talking to visitors is a different
and worse product. Deviation logged in §8.1; seeded as **S4**.

### 3.3 Where the verdict comes from, and when

| Stage | Where | When |
| --- | --- | --- |
| frames in | `BrowserAudioGateway.accept_audio` | every 20 ms frame, before the lane |
| turn cut | `VoiceIdentityGate._observe` | the R17 tee's own `owner_gap_s` (0.75 s) |
| provisional verify | at `min_utterance_s` (1.2 s) of buffered speech | once per turn |
| final verify | at settle (gap closed, mic closed, or a transcript asks) | once per turn, on the WHOLE turn |
| decision | `runtime.submit_realtime_transcript` / `_gate_by_voice` | when a transcript or tool call arrives |

Turns are cut on the **same** silence gap the R17 capture tee cuts owner
segments on, and the runtime passes the tee's own configured `owner_gap_s` into
the gate. "Turn 4" here and "owner segment 4" in `index.json` are the same span
of audio by construction, so an investigation never has to reconcile two
segmentations.

**Every accepted frame still goes up to the provider, whoever spoke it.** The
gateway records who is speaking; it never decides whether the audio travels. It
cannot: a stranger's spoken emergency phrase has to reach the transcriber for the
latch to fire at all. **S39** seeds the opposite (a gateway that drops
unrecognised audio) and it reddens.

### 3.4 Fail-closed, in four flavours, and the one place "off" is right

1. **No profile ⇒ verification disabled ⇒ exactly the pre-card behaviour**, said
   out loud in `/api/state` and in a boot event at WARNING. This is the one
   direction where off is correct: a household that has not enrolled must not be
   locked out of its own robot by a feature it never turned on.
2. **A profile that exists and cannot be trusted is a REFUSAL, never a silent
   downgrade to (1).** Unreadable file, wrong schema, wrong dimension, zero
   vector, no model named, zero utterances — each raises with the path in the
   message. A corrupt profile quietly reading as "no profile" would turn a
   security feature off at exactly the moment every surface still said it was on.
   **S9** and **S10** seed both halves.
3. **With a profile loaded, anything short of a passing score refuses to arm**:
   a low score, a raising embedder, a turn too short to embed, a turn whose
   verdict has not been computed yet. **S12/S13/S14** seed each.
4. **The refusal is never silent** (§3.5).

### 3.5 The refusal, and why it is not "critical"

Every refusal increments `voice_rejected` and writes a WARNING panel/evidence
event. The **first per minute** is additionally offered to the whisperer as a
new `KIND_VOICE_REJECTED` always-band fact, whose hint reads:

> "Tell the owner, plainly and without alarm, that someone who is not them asked
> you to do something and you did not do it. **Do NOT claim you cannot be stopped
> by other people — anyone may still stop you.**"

It is in `ALWAYS_BAND` and deliberately **not** in `CRITICAL_KINDS`. The critical
set exists to bypass the owner's own per-minute cost budget for facts about the
owner's own requests; a voice rejection is, by construction, a fact about
somebody else's. The rate limiting lives in `VoiceIdentityGate.note_rejection`
(60 s, configurable) rather than in the whisperer, because the whisperer's budget
is a cost knob and this is a security fact. **The tension in that choice is a
real one and is written up as open risk 2** (§10.2): a *false* reject of the real
owner is a refusal of the owner's request, and it is currently subject to the
budget.

---

## §4 — The measurement that changed the design

The card asked for FAR/FRR. Producing it found a defect in this card's own first
implementation, so the numbers are reported as a sequence rather than a single
row.

**Protocol, pre-registered before the first run** (`<scratchpad>/f1si/far_frr.py`):
for every speaker in the bench's gold set with ≥4 utterances, enroll on the
first 3, hold the rest out as GENUINE trials, and use every other speaker's
utterances as IMPOSTOR trials. Every trial is pushed through `gate.observe_frame()`
in 20 ms frames and read back with `gate.current()` — i.e. **the production code
path, not `embed_bench.py`**. 5 speakers, 13 genuine trials, 112 impostor trials.

| Run | `min_utterance_s` | whole-turn re-verify | FRR | FAR | margin (min genuine − max impostor) |
| --- | --- | --- | --- | --- | --- |
| 1 (first implementation) | 0.6 s | none | **5/13 = 38.5 %** | 0/112 = 0.0 % | **−0.374** |
| 2 (raised the fragment) | 1.2 s | partial | 2/13 = 15.4 % | 0/112 = 0.0 % | +0.140 |
| 3 (**shipped**) | 1.2 s | yes | **0/13 = 0.0 %** | **0/112 = 0.0 %** | **+0.364** |

Run 1's false rejects were all genuine speakers judged on the *first fragment*
of a long utterance. A 0.6 s eager verify is enough audio to have an opinion and
not enough to be right; the bench's own zero-overlap numbers were measured on
WHOLE utterances. The fix has two halves and both are load-bearing: more audio
before the first opinion (`DEFAULT_MIN_UTTERANCE_S` 0.6 → 1.2), and a **second
embedding over the whole turn at settle time that replaces the first**
(`MAX_VERIFIES_PER_TURN = 2`, `REVERIFY_GROWTH_FACTOR = 1.5`). Deliberately
*replaces*, never `max()`-es: sampling twice and keeping the better score is a
gate that quietly lowers its own threshold. **S36** seeds the removal of the
re-verify and `test_a_long_turn_is_re_verified_on_its_whole_audio` catches it.

### 4.1 The shipped operating point

```
threshold          : 0.55
enrollments        : 5 speaker(s), 3 utterance(s) each
genuine trials     : 13      impostor trials : 112
FRR                : 0/13  = 0.0%
FAR                : 0/112 = 0.0%
genuine score      : min +0.730  mean +0.845
impostor score     : max +0.366  mean +0.009
margin (min gen - max imp) : +0.364
verify latency ms  : median 32.2  p95 95.2  max 101.3  (n=125)
```

Threshold sweep on the same 125 trials — **every value from 0.40 to 0.72 gives
0/13 FRR and 0/112 FAR.** The card's 0.55 sits almost exactly in the middle of
the measured operating window (0.366 … 0.730), which is a stronger result than
the synthesis' 0.50–0.55 range needed.

**FAR/FRR is honestly small-n and here is exactly how small.** 13 genuine trials
is 13; a 0 % FRR at n=13 has a 95 % upper bound near 25 %. Two of the five
"speakers" are espeak voices, three are LibriSpeech readers, and **none of them
is the owner**. The impostor set contains no television. What these numbers
support is "the shipped gate reproduces the bench's separation through the real
code path and the threshold is not on a cliff edge"; they do not support any
claim about this household.

### 4.2 Latency, against the card's ≤50 ms p95 budget

| Utterance length | median | p95 | max |
| --- | --- | --- | --- |
| command-length (2–3 s, the live proof, n=5) | **18.4 ms** | **32.9 ms** | 32.9 ms |
| gold set incl. 15 s LibriSpeech monologues (n=125) | 32.2 ms | 95.2 ms | 101.3 ms |

**The budget is met for the traffic it was written for** and the tail belongs to
15-second monologues, where two things apply: the buffer is capped at
`max_utterance_s = 8.0 s` in the shipped configuration (so ~100 ms is the real
worst case, not 187 ms), and that cost is paid at *settle*, when the owner has
already stopped speaking — it delays the verdict, not the microphone. The
microphone-latency cost at the *top* of a turn is the provisional verify only,
which is bounded by `min_utterance_s` of audio: ~13 ms measured. `budget_ms` is
measured and reported (`budget_exceeded` in the snapshot) rather than enforced as
a timeout, because half an embedding is worse than a slow one.

Model load: **117–167 ms**, once, at gate construction (bench: 115 ms).

---

## §5 — What each work item became

**1. Embedding verify in the audio gateway** — `realtime/voice_identity.py` (new,
the whole policy), hooked from `BrowserAudioGateway.accept_audio` beside the R17
tee and under the same law (never raise into the relay, never grow unbounded),
with one deliberate exception: it is allowed to be slow *once or twice per turn*,
which is the card's stated budget. `models/speaker_id/` vendors
`nemo_en_titanet_small.onnx` with `models.lock.json` + `pin_lock.py`, mirroring
`models/judge/` exactly — the `.onnx` is gitignored, the **lock is the committed
artifact**. The upstream URL was verified by fetching it, not asserted:
`content-length 40257283` and the first-1 MB sha256 both match the bytes on disk
byte for byte, and the full-file digest is
`ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e` (Apache-2.0).
The lock also records the measured separation and latency, so a future reader
knows what this file was chosen *for*.

**2. Safety asymmetry** — §3.1, and seeds S1–S5.

**3. Enrollment** — `tools/enroll_owner_voice.py`. N utterances (≥5, ≥1.0 s each,
mono PCM16) or an R17 capture folder cut on its own index byte ranges. Averaged
embedding, unit-normalized *before* the mean so one loud recording cannot
dominate. Written atomically at mode 0600 **outside the repository** — the tool
refuses a path inside the tree, because a voice profile in the repo is a voice
profile in a commit. The check that matters most is **self-consistency**: if any
enrollment utterance scores below the operating threshold against its own
average, the recordings are not one voice and the enrollment is refused with the
numbers printed. Re-enrollment overwrites cleanly (temp file at 0600, then
rename), so an interrupted run cannot brick the microphone. There is no merge, on
purpose.

**4. DoA sector prefilter** — `UsbDoaReader` productionizes the staged
`doa_poll.py`: `ctrl_transfer(0xC0, 0, 0x80|18, 20, 5)`, tolerant of the optional
leading status byte, `None` on any failure and never an exception. A configured
`rejected_sector` refuses a turn **unless the embedding passes** — the embedding
is always the authority; **S42** seeds a sector that overturns a pass. An
unreadable DoA contributes *nothing* rather than refusing everything (**S25**),
which is what keeps a blocked udev rule from becoming a robot that takes no
commands. `doa: false` is the shipped default, and a `rejected_sector` set
without `doa: true` is a **load-time refusal** — it is the one combination that
would silently do nothing (**S27**).

**5. Eval tie-in** — the corpus gains rows 53–58: four `impostor` commands and
two `impostor-estop` rows whose expected column reads *"the latch MUST fire for a
voice that is not the owner's. A refusal here is the worst possible outcome of
this card."* `evals/20260820/voice_corpus_v1/make_impostor_wavs.py` synthesizes
them deterministically with two espeak voices (the WAVs are gitignored; the
generator is the committed artifact). EV-1's suite was **extended, not forked**:
`check_voice_provenance` is the twelfth check in the same registry, with the
count pin in `tests/test_eval_assertions.py` moved 11 → 12 and the new name
asserted by hand.

---

## §6 — The twelfth assertion check

`voice_provenance` (dimension: provenance) reads the machine-readable row
`runtime._emit_voice_provenance` writes for **every armed turn**:

```
voice identity armed 'follow': score=0.7994 threshold=0.55 code=armed turn=1
voice identity armed 'stop': score=none threshold=0.55 code=safety_never_gated turn=0
```

Four findings, and the verdict/review split is the honest part:

| Finding | Kind | Fires when |
| --- | --- | --- |
| `armed_turn_without_verify_score` | VERDICT / provenance | verification is enabled in the state snapshot and a turn armed with `score=none` |
| `armed_below_threshold` | VERDICT / safety | a row arms while naming a score below the threshold it also names |
| `latch_was_identity_gated` | VERDICT / safety | an emergency turn armed with any code other than `safety_never_gated` |
| `armed_turns_unattributed` | **REVIEW** / provenance | turns acted and the record says verification was off |

The last one is a review candidate and never a verdict, because it is the
**shipped state on a host with nobody enrolled**. The product is not broken; the
evidence simply cannot attribute anything. **S32** seeds the over-correction
(making it a verdict) and it reddens.

The latch's own provenance row — `score=none code=safety_never_gated` — is not a
gap in the record. It is the single most valuable row in it: proof, in the
artifact, that a stop ran with no identity check standing in front of it.

`SessionEvidence.voice_identity` reads `state.realtime.gateway.voice_identity`,
and distinguishes an empty mapping ("this artifact predates the feature") from
`{"enabled": false}` ("the feature exists and nobody enrolled"). **S33** seeds
the accessor going blind.

---

## §7 — Live proof: real model, real enroller, real runtime, $0.00

`<scratchpad>/f1si/live_f1si.py`, transcript at `<scratchpad>/f1si/live_proof.txt`.
Everything below is the shipped code path — the real `tools/enroll_owner_voice.py`
CLI, the real sherpa/titanet embedder, the real `VoiceIdentityGate`, the real
`RobotRuntime.submit_realtime_transcript` and the real gated motion door. **The
only substitution is whose voice the "owner" is**: an espeak voice stands in for
the owner and a different espeak voice is the impostor, because no owner audio
exists on this host (§1b).

### 7.1 Enrollment, through the real CLI

```
enrolled 6 utterance(s) with nemo_en_titanet_small.onnx
  +0.914  enroll_01.wav
  +0.952  enroll_02.wav
  +0.959  enroll_03.wav
  +0.959  enroll_04.wav
  +0.959  enroll_05.wav
  +0.956  enroll_06.wav
wrote /tmp/f1si-live-m_r0tar5/owner_voice_profile.json (mode 0600)
speaker verification will arm on the next lane construction; the emergency latch is NOT identity-gated and never will be.
   mode=0600  dim=192  utterances=6  model=nemo_en_titanet_small.onnx  sha256=ad4a1802485d8b34…
```

### 7.2 The runtime builds the gate from that profile

```
   gate built in 117 ms (model load included)
   enabled=True  embedder=sherpa  threshold=0.55
   profile={'model': 'nemo_en_titanet_small.onnx', 'dim': 192, 'utterances': 6, ...}
   [event] realtime | voice identity: speaker verification ARMED at threshold 0.55 against 6 enrolled utterance(s); the emergency latch is NOT identity-gated
```

### 7.3 The enrolled owner speaks a HELD-OUT sentence

```
   'Please follow me over to the bench near the lamppost.'  (2.47s)
   verdict: {"code": "armed", "passed": true, "score": 0.7994, "threshold": 0.55, "seconds": 2.267, "turn": 1, "verify_ms": 32.91, ...}
   submit('follow me') -> executed=True reply='Owner-follow enabled'
   navigate_to(bench) -> 'walking to bench'
```

### 7.4 A DIFFERENT voice asks for the same thing, mid-session

```
   'Follow me over to the bench near the lamppost.'  (2.21s)
   verdict: {"code": "not_owner", "passed": false, "score": 0.252, "threshold": 0.55, "seconds": 2.027, "turn": 2, ...}
   submit('follow me') -> executed=False
   error: the speaker embedding scored 0.252, below the 0.55 threshold for the enrolled owner
   navigate_to(bench) -> refused: I did not recognise the voice that asked for that,
                         so I am not going to go there. Anyone can still stop me.
```

Both doors refused — the local ingress path **and** the hosted model's tool.

### 7.5 THE ASYMMETRY: the same unrecognised voice says the stop phrase

```
   'Die stop.'  (0.64s)
   verdict: {"code": "not_owner", "passed": false, "score": 0.3372, ...}   <- still not the owner
   submit(stop phrase) -> executed=True kind=emergency reply='Stopping.'
   agent.safety.emergency_stopped = True
```

**0.337 against a 0.55 threshold — measurably not the owner — and the dog
stopped.** That is the card's binding constraint, live, with the real model.

### 7.6 What the record says

```
   [realtime] voice identity: speaker verification ARMED at threshold 0.55 against 6 enrolled utterance(s); the emergency latch is NOT identity-gated
   [realtime] voice identity armed 'follow': score=0.7994 threshold=0.55 code=armed turn=1
   [realtime] voice identity armed 'navigate_to': score=0.7994 threshold=0.55 code=armed turn=1
   [realtime] voice identity REFUSED to arm 'follow': the speaker embedding scored 0.252, below the 0.55 threshold for the enrolled owner
   [realtime] voice identity REFUSED to arm 'navigate_to': the speaker embedding scored 0.252, below the 0.55 threshold for the enrolled owner
   [safety  ] Emergency stop latched
   [safety  ] Emergency stop latched by voice: 'Die stop'
   [realtime] voice identity armed 'stop': score=none threshold=0.55 code=safety_never_gated turn=0

   gate snapshot:
     enabled True | threshold 0.55 | turns_seen 3 | turns_verified 3
     voice_accepted 1 | voice_rejected 2 | verify_errors 0 | sector_rejected 0
     narrations 1 | budget_ms 50.0 | budget_exceeded 0
     latency_ms {'n': 5, 'median': 18.37, 'p95': 32.85, 'max': 32.85}
     doa None
     reason "an enrolled owner profile is loaded; unverified voices cannot arm a command (the emergency latch is never identity-gated)"

PROOF COMPLETE — cost $0.00 (local CPU only, no hosted session)
```

### 7.7 Two defects this proof found that no test had

1. **The counters counted embeddings, not turns.** The first run of §7.6 read
   `turns_verified: 5, voice_accepted: 2` for a three-turn session with one
   accepted turn — the provisional and final looks at the same sentence were two
   votes. A panel number that double-counts is worse than no number, because it
   looks like evidence. Fixed by a `_tally_locked` that counts once per turn, by
   the turn's FINAL verdict; pinned by
   `test_the_counters_count_turns_and_not_embeddings`.
2. **A refusal sentence that stopped mid-thought.** `tool.replace("_", " ")`
   rendered as *"I am not going to navigate to."* Fixed with an explicit
   `VOICE_TOOL_PHRASES` map (unknown tool ⇒ "do that", always grammatical).

---

## §8 — Deviations, with reasons

**8.1 — `runtime.py` is edited, and it is not on the card's OWNS list.** It is
also not on the MUST NOT TOUCH list, and there is no other seam: the ingress
arming decision lives in `submit_realtime_transcript` and the motion doors are
runtime callables. Edits are surgical — a gate call before the action branches,
two helper methods, the `_gate_by_voice` wrapper on five doors (R21's own
pattern), the provenance emitter, and the gate's construction beside the R17 tee's.
`ingress.py`, `lane.py`, `protocol.py`, `tool_broker.py`, `prompting.py` and the
yield code are untouched.

**8.2 — `whisperer.py` gains a class.** Not on either list. One new kind, one
band entry, one hint, one `__all__` line. Required by work item 1's "whisperer
always-band fact".

**8.3 — `evals/assertions/evidence.py` gains an accessor.** The card names
"EV-1's assertion suite"; the check cannot tell "verification was off" from
"this artifact predates the feature" without reading the state, and inlining
that read in `checks.py` would have put state-shape knowledge in two places.

**8.4 — `sherpa_onnx` is NOT added to the venv or `requirements-lock.txt`.** The
production import is lazy and optional; a missing package reports
`verify_disabled` with the reason and the robot still boots, records and stops.
Adding a 118 MB wheel to the lock would make the commit gate depend on it and
would change every contributor's environment for a feature that is inert without
an owner action. Every measurement in §4 and §7 ran the real package from the
bench's staged `pip --target` tree on `PYTHONPATH`. **This is the one thing an
owner must install before enrollment works**, and it is on the owner-gated list.

**8.5 — The threshold stays at the card's 0.55 even though §4.1 shows 0.40–0.72
all measure 0/0.** The card is the design authority and 0.55 is inside the range
the synthesis blessed. The measured curve is reported so the owner can move it
with numbers rather than vibes; a suggested change is owner-gated, not taken.

**8.6 — The corpus's impostor WAVs are generated, not committed.** They are
gitignored by the corpus's existing `*.wav` rule; the deterministic generator is
the committed artifact, so the corpus reproduces without carrying audio.

**8.7 — `tests/test_eval_assertions.py` (EV-1's file) is edited**, moving the
check-count pin 11 → 12. The card says "extend, do not fork"; the pin is the
mechanism that makes extension visible, so extending it is the instruction.

---

## §9 — does_not_prove (read this before believing §7)

1. **No claim here is about the owner's actual voice.** No owner audio exists on
   this host. The "enrolled owner" in §7 is espeak `en+m3` and the impostor is
   espeak `en+f4`. Synthetic speech has no room, no distance and no channel;
   it does not exercise the acoustic conditions a television arrives in. The
   FRR the owner will actually experience is **unmeasured**.
2. **No claim here is about a television.** The impostor set contains two espeak
   voices and three LibriSpeech readers. A TV is compressed, band-limited,
   reverberant and often multi-speaker. The bench's finding that two espeak
   voices reading the same sentence are the *hardest* cross pair (0.431) makes
   this set adversarial in one specific way and unrepresentative in others.
3. **Zero DoA reads have ever succeeded on this host.** Every DoA claim in this
   card is a claim about code exercised by a test double plus the bench's
   already-recorded non-disruption measurement. The double asserts the
   *mechanism* (EP0 control transfers only, no `set_configuration`, no interface
   claim, no audio open); it cannot re-measure the ALSA stream. Nothing here
   re-proves SC-A3.
4. **This card does not stop the hosted model from ANSWERING an unverified
   voice.** It gates local command execution and the five motion tools. A
   visitor — or a television — can still have a conversation with the robot and
   still cause billed hosted turns. Making the model refuse to *talk* to an
   unrecognised voice would require the lane or the prompting plane, both of
   which this card may not touch. What changed is that the robot no longer
   *moves* for them.
5. **The 0/0 FAR/FRR is n=13 and n=112 over 5 non-owner speakers.** See §4.1 for
   the honest reading. It is a code-path reproduction of the bench's separation,
   not a field measurement.
6. **The gateway path in §7 is in-process.** The gateway↔gate wiring is proven by
   `test_the_gateway_feeds_the_gate_and_still_hands_every_frame_to_the_lane`
   through the real relay, but §7 feeds the gate directly. No browser, no
   websocket and no hosted session was involved in any measurement in this
   document.
7. **`aec.constructed: false` is quoted from prior evidence, not re-measured.**
   The stack was not running.

---

## §10 — Open risks

**10.1 — A verdict can go stale.** A turn's verdict persists until the next turn
begins. If the owner speaks (armed), leaves the room, and the hosted model then
issues a tool call minutes later with nobody having spoken since, that call is
armed by a verdict about an old sentence. Any intervening speech — including the
television's — replaces the verdict, so the window is "nothing at all was heard
since", which is also the window in which the model has no new instruction to act
on. A `max_verdict_age_s` knob would close it; it was not added because it is
another configuration surface and the DoD does not ask for it. **Named here so
the next card can take it deliberately.**

**10.2 — A false reject of the real owner is subject to the cost budget.** The
narration class is always-band but not critical (§3.5). If the gate wrongly
refuses the owner and the whisperer's per-minute budget is spent, the owner gets
a counter and a panel event but no spoken explanation — which reads exactly like
a robot that has stopped working. The card specifies always-band and that is what
shipped; moving it into `CRITICAL_KINDS` is an owner-visible cost decision.

**10.3 — Continuous background noise never closes a turn.** The gap rule needs
silence. A room with a constantly-running television produces frames without a
0.75 s gap, so the turn is verified once at 1.2 s (on the TV) and stays that way:
the verdict is `not_owner` and commands refuse — the correct outcome — but the
owner speaking *over* that noise is in the same turn and will also be refused
until a gap appears. Untested against real continuous audio.

**10.4 — Threshold 0.55 has never been measured against the owner.** §4.1's
window is wide on a proxy set. A real enrollment that passes the enroller's own
self-consistency check at 0.55 is evidence the owner's turns will clear it, but
that is an inference, not a measurement.

**10.5 — `sherpa_onnx` absent ⇒ the feature is off.** With a profile enrolled but
the package missing, the runtime emits a WARNING and degrades to
`verify_disabled` rather than refusing to boot. That is the right blast radius
but it means a broken install shows up as *reduced security*, which is the
direction that deserves suspicion. The snapshot's `reason` is the mitigation.

**10.6 — The impostor corpus rows have never been replayed.** Rows 53–58 exist
and their WAVs generate; no corpus run has executed them, because a replay needs
the live stack and a hosted session.

---

## §11 — Owner-gated list (nothing below was attempted)

1. **The udev rule** — two lines, ~2 minutes, `sudo`. Verbatim in `bench_doa.md`
   and now beside the `doa:` key in `configs/realtime.yaml.example`. Unblocks
   work item 4's live half. Does not reset the device or disturb the stream.
2. **An enrollment recording** — ~1 minute of your speech, 5–10 utterances, then
   `tools/enroll_owner_voice.py --wav …`. **This is the switch that turns the
   whole card on.** Until it happens the gate reports `verify_disabled` and the
   robot behaves exactly as it did before.
3. **Install `sherpa-onnx` into `.parcel/`** (or point `voice_identity.model` at
   a build that has it). Deliberately not done for you — §8.4.
4. **Decide the threshold.** 0.55 shipped; 0.40–0.72 all measure 0/0 on the proxy
   set. Consider re-measuring after (2) with your own held-out utterances.
5. **Decide whether a voice rejection may bypass the cost budget** — open risk
   10.2.
6. **The television's azimuth**, once (1) lands: `rejected_sector: [start, end]`.
7. Still standing from the synthesis: the reply-language policy for Korean, and
   the q34 `"Dye. Stop."` matcher-widening measurement.

---

## §12 — Seeds — 42, all RED, R9 session-B + AUDIT_R12_R16 register §1

Harness `<scratchpad>/f1si/seed_f1si.py`, results `<scratchpad>/f1si/seeds_final.txt`
+ `seeds.json`. ONE GOLD snapshot of all eight touchable files at startup; per
seed: repair drift from GOLD, mutate exactly one file, **purge every
`__pycache__` under `src/`, `evals/`, `scripts/`, `tests/` and `tools/`**, run a
**fresh-interpreter canary that must SEE the mutation on disk** (a seed whose
canary fails is BROKEN, never RED), run the named pytest target, restore from
GOLD in a `finally`, purge again, assert byte-identical. The harness asserts at
import time that every mutable path is inside this card's OWNS.
**No test, config or fixture file was ever mutated.**

GOLD hashes (sha256, first 16) — the same bytes the closing gate scored:

```
2fe244ec8322efd0  src/parcel_robot/realtime/voice_identity.py
c1082363d22f8dea  src/parcel_robot/realtime/audio_gateway.py
1f0cb83239a3ff45  src/parcel_robot/realtime/config.py
ae5e21ede6577556  src/parcel_robot/realtime/whisperer.py
8b49a37d8e19d4cd  src/parcel_robot/runtime.py
55cca26f2f072967  evals/assertions/checks.py
cd94713b2e1363c0  evals/assertions/evidence.py
b9b8d331b0f48b28  tools/enroll_owner_voice.py
```

| # | Seeded defect | File | Target test | Result |
| --- | --- | --- | --- | --- |
| S1 | ASYMMETRY DIRECTION A: the emergency latch becomes identity-gated | voice_identity | `test_a_strangers_stop_still_latches_while_their_command_does_not_arm` | **RED** |
| S2 | ASYMMETRY DIRECTION B: an unverified voice arms a command anyway | voice_identity | `test_a_strangers_stop_still_latches_while_their_command_does_not_arm` | **RED** |
| S3 | ASYMMETRY DIRECTION B at the runtime seam: the ingress gate is removed | runtime | `test_a_strangers_stop_still_latches_while_their_command_does_not_arm` | **RED** |
| S4 | the MOTION TOOLS lose the gate: "go to the bench" from a TV walks the dog again | runtime | `test_a_strangers_stop_still_latches_while_their_command_does_not_arm` | **RED** |
| S5 | the latch SHORT-CIRCUIT is removed: a stop now waits on an embedding | voice_identity | `test_the_emergency_class_never_reads_a_verdict_at_all` | **RED** |
| S6 | THRESHOLD IGNORED: every verified turn arms | voice_identity | `test_the_threshold_is_the_line_and_it_comes_from_configuration` | **RED** |
| S7 | a threshold of 55 (the percentage somebody meant) is admitted instead of refused | config | `test_a_typo_in_the_voice_identity_block_is_a_refusal` | **RED** |
| S8 | a typo in the voice_identity block silently reads as the default | config | `test_a_typo_in_the_voice_identity_block_is_a_refusal` | **RED** |
| S9 | MISSING PROFILE ARMS ANYWAY: a CORRUPT profile is silently read as absent | voice_identity | `test_an_absent_profile_is_none_and_a_broken_one_is_a_refusal` | **RED** |
| S10 | a ZERO-VECTOR profile is accepted: it scores 0.0 against every voice on earth | voice_identity | `test_a_profile_that_cannot_be_trusted_is_refused` | **RED** |
| S11 | verification being OFF stops being said out loud in the snapshot | voice_identity | `test_no_profile_means_verification_is_off_and_the_snapshot_says_so_loudly` | **RED** |
| S12 | a PENDING turn arms: silence counts as a passing score | voice_identity | `test_a_turn_that_has_not_been_verified_yet_does_not_arm` | **RED** |
| S13 | a turn TOO SHORT to embed arms | voice_identity | `test_an_utterance_too_short_to_embed_does_not_arm` | **RED** |
| S14 | a verify that RAISES arms instead of refusing (fail-OPEN) | voice_identity | `test_a_verify_that_raises_refuses_to_arm_and_counts_itself` | **RED** |
| S15 | an embedding from ANOTHER MODEL is scored instead of refused | voice_identity | `test_an_embedder_from_another_model_refuses_rather_than_scoring` | **RED** |
| S16 | the profile is written WORLD-READABLE instead of 0600 | voice_identity | `test_the_profile_is_written_at_mode_600_and_re_enrollment_overwrites` | **RED** |
| S17 | the enroller writes the owner's biometric profile INSIDE the repository | enroll | `test_the_enroller_refuses_to_write_inside_the_repository` | **RED** |
| S18 | the enroller accepts recordings that are not one voice | enroll | `test_the_enroller_refuses_recordings_that_are_not_one_voice` | **RED** |
| S19 | REJECTION SILENT: the narration is never allowed, so the owner never hears it | voice_identity | `test_a_rejection_is_counted_every_time_and_spoken_once_per_minute` | **RED** |
| S20 | REJECTION SILENT at the runtime seam: no whisperer fact | runtime | `test_the_runtime_speaks_the_refusal_and_still_writes_the_ledger` | **RED** |
| S21 | the rejection class leaves the ALWAYS band and can be suppressed | whisperer | `test_the_rejection_class_is_always_band_and_is_not_a_budget_bypass` | **RED** |
| S22 | the refused turn's own COUNTER stops moving | voice_identity | `test_a_rejection_is_counted_every_time_and_spoken_once_per_minute` | **RED** |
| S23 | DoA DISTURBS THE STREAM: the reader claims the USB interface before reading | voice_identity | `test_the_doa_reader_only_ever_issues_ep0_control_reads` | **RED** |
| S24 | a DoA read that FAILS raises into the relay instead of returning None | voice_identity | `test_a_doa_read_that_fails_is_none_and_never_an_exception` | **RED** |
| S25 | an UNREADABLE DoA refuses every command (the udev rule becomes load-bearing) | voice_identity | `test_an_unreadable_doa_contributes_nothing_rather_than_refusing_everything` | **RED** |
| S26 | a wrapped sector INVERTS: everything except the television is rejected | voice_identity | `test_a_sector_wraps_without_inverting` | **RED** |
| S27 | a rejected sector with NO DoA reader is accepted and silently does nothing | config | `test_a_typo_in_the_voice_identity_block_is_a_refusal` | **RED** |
| S28 | VERIFY SCORE DROPPED: an armed turn writes no provenance row at all | runtime | `test_every_armed_turn_carries_its_verify_score` | **RED** |
| S29 | VERIFY SCORE DROPPED: the row is written but the SCORE is thrown away | runtime | `test_every_armed_turn_carries_its_verify_score` | **RED** |
| S30 | the assertion suite stops noticing a dropped score | checks | `test_eval_assertions.py` + `test_the_assertion_suite_catches_a_score_dropped_from_provenance` | **RED** |
| S31 | the assertion suite stops noticing an identity-gated LATCH | checks | `test_the_assertion_suite_catches_a_latch_that_went_through_an_identity_check` | **RED** |
| S32 | an UNVERIFIED session becomes a VERDICT (over-correction) | checks | `test_an_unverified_session_is_a_review_candidate_and_never_a_verdict` | **RED** |
| S33 | the state accessor stops finding the gate: every session looks unverified | evidence | `test_the_assertion_suite_catches_a_score_dropped_from_provenance` | **RED** |
| S34 | the new check is dropped from the registry | checks | `test_every_check_has_a_dimension_and_the_dimension_set_is_fixed` | **RED** |
| S35 | the verify runs ONCE PER FRAME instead of once per turn | voice_identity | `test_one_verify_per_turn_and_not_one_per_frame` | **RED** |
| S36 | the WHOLE-TURN re-verify is removed: back to the measured 38.5 % FRR | voice_identity | `test_a_long_turn_is_re_verified_on_its_whole_audio` | **RED** |
| S37 | the gate RAISES into the socket reader thread instead of refusing | voice_identity | `test_the_gate_never_raises_into_the_relay` | **RED** |
| S38 | the gateway stops feeding the gate: every turn is forever PENDING | audio_gateway | `test_the_gateway_feeds_the_gate_and_still_hands_every_frame_to_the_lane` | **RED** |
| S39 | the gateway REFUSES a stranger's audio: their stop phrase never reaches the ASR | audio_gateway | `test_the_gateway_feeds_the_gate_and_still_hands_every_frame_to_the_lane` | **RED** |
| S40 | a gateway with no gate stops saying so: "off" becomes an absent key again | audio_gateway | `test_a_gateway_without_a_gate_says_so_and_behaves_exactly_as_before` | **RED** |
| S41 | the profile's EMBEDDING leaks into /api/state (biometric material in a tab) | voice_identity | `test_the_profile_never_leaves_its_embedding_in_a_snapshot` | **RED** |
| S42 | the sector OVERTURNS a passing embedding (belt beats suspenders) | voice_identity | `test_a_rejected_sector_refuses_only_what_the_embedding_already_refused` | **RED** |

`final whole-tree check: 0 file(s) needed a final repair` — all eight files
byte-identical to GOLD at teardown.

**The card names six seed classes by hand and all six are here:** asymmetry
broken both directions → **S1–S5**; threshold ignored → **S6** (with S7/S8 for
the config route); missing profile arms anyway → **S9–S11** (the corrupt-profile
route, which is the one that would actually happen); rejection silent →
**S19–S22**; DoA claim disturbs the stream → **S23** (with S24–S27); verify score
dropped from provenance → **S28–S29** (with S30–S34 for the suite going blind).

**Three sweeps.** Sweep 1 was 37/42 RED with 3 harness bugs (invalid mutation
text, wrong indentation) and **two GREEN seeds that were real findings about the
TESTS, not the harness**:

* **S5 GREEN** — deleting the latch short-circuit in `decide()` passed, because
  the test only asserted the embedder was never called and no audio had been fed.
  The test now makes `current()` itself raise, which pins the property the
  short-circuit actually provides.
* **S37 GREEN** — making `observe_frame` re-raise passed, because the only
  exception the test produced was caught one level deeper, around `embed()`. The
  test now also breaks the gate's own bookkeeping, exercising the outer firewall.

Both tests were strengthened rather than the seeds retired. Sweep 3 — against the
same bytes the closing gate scored — is **42/42 RED, 0 not RED, 0 files needing
repair**.

---

## §13 — Card DoD, line by line

| DoD item | Status |
| --- | --- |
| gate green | §2 — every hard gate PASS, **7164 passed** (+75, 0 removed), ruff 0 new |
| ≥8 seeds RED | **42/42 RED**, §12 |
| …asymmetry broken both directions | S1–S5 (five routes, not two) |
| …threshold ignored | S6, S7, S8 |
| …missing profile arms anyway | S9, S10, S11 |
| …rejection silent | S19, S20, S21, S22 |
| …DoA claim disturbs the stream (guarded by test double) | S23, and S24–S27 |
| …verify score dropped from provenance | S28, S29, and S30–S34 |
| live proof: owner's enrolled voice accepting | §7.3 — **with a SYNTHETIC owner**; the real owner's voice is owner-blocked (§1b, §9.1) |
| live proof: a synthetic voice rejected mid-session | §7.4 — refused at both doors, score 0.252 |
| costs | **$0.00**, no hosted session, credential never loaded |
| FAR/FRR reported, honestly small-n | §4.1 — 0/112 FAR, 0/13 FRR, and §4.1's paragraph on what n=13 does not support |
| item 1 — embedding verify, ≤50 ms p95, fail-closed, counted, narrated | §3, §4.2, §5 |
| item 2 — safety asymmetry, seeded | §3.1, S1–S5 |
| item 3 — enrollment tool, outside the repo, mode 600, clean re-enrollment | §5, §7.1 |
| item 4 — DoA sector prefilter | §5 — built and doubled; **live half owner-blocked** (§1a) |
| item 5 — impostor corpus + EV-1 voice-provenance check | §5, §6 |
| standard register | §0–§13; deviations §8, does_not_prove §9, owner-gated §11, live §7 |

---

## §14 — Files

**New:** `src/parcel_robot/realtime/voice_identity.py` ·
`tools/enroll_owner_voice.py` · `models/speaker_id/{pin_lock.py,models.lock.json}`
(the 40 MB `.onnx` is gitignored, as the judge's `.gguf` is) ·
`tests/test_realtime_voice_identity.py` (74 tests) ·
`evals/20260820/voice_corpus_v1/make_impostor_wavs.py`

**Edited:** `realtime/audio_gateway.py` (the verify hook, turn-end, snapshot) ·
`realtime/config.py` (the additive `voice_identity:` block) ·
`realtime/whisperer.py` (`KIND_VOICE_REJECTED`) · `realtime/__init__.py` ·
`runtime.py` (gate construction, ingress arming, five gated motion doors,
provenance emitter) · `evals/assertions/checks.py` (check 12) ·
`evals/assertions/evidence.py` (accessor) · `tests/test_eval_assertions.py`
(count pin 11 → 12) · `evals/20260820/voice_corpus_v1/queries.tsv` (rows 53–58) ·
`configs/realtime.yaml.example`

**Untouched, as the card requires:** `realtime/ingress.py`, `realtime/lane.py`,
`realtime/protocol.py`, `realtime/tool_broker.py`, `realtime/prompting.py`, and
the yield code.

Nothing was committed, staged or stashed **by this card**.

### 14.1 — HEAD moved during this session, and it was not me

At dispatch, `HEAD` was `8473a51`. At close it is `2c27496`, behind
`877d9f4`. Both commits are authored and committed by
**`Jae <contact@parcelstudio.io>`** — the owner — while this card was running;
`git reflog` shows them as ordinary `commit:` entries after the pre-existing
`reset: moving to HEAD`. This is recorded because an auditor comparing HEAD
against the dispatch snapshot will otherwise see a discrepancy and reasonably
suspect the executor.

Verified, rather than assumed, that nothing of this card leaked into them:

```
$ git log -2 --format="%H %ci %an <%ae> %s"
2c274967… 2026-08-20 17:58:40 -0400 Jae <contact@parcelstudio.io> feat: land hosted realtime companion and embodied voice navigation
877d9f46… 2026-08-17 06:04:20 -0400 Jae <contact@parcelstudio.io> Implemented voice agent

$ for f in runtime.py audio_gateway.py config.py whisperer.py checks.py; do
      git show HEAD:<path> | grep -c '_gate_by_voice\|voice_identity\|VOICE_REJECTED\|voice_provenance'
  done
0  0  0  0  0
```

Every F1-SI file is `untracked` at HEAD (`voice_identity.py`,
`enroll_owner_voice.py`, `test_realtime_voice_identity.py`,
`models/speaker_id/models.lock.json`, this document), and none of the five edited
files carries a single F1-SI marker in the committed tree. **No seeded mutation
leaked in either** — the seed harness restores from GOLD in a `finally` and its
closing whole-tree check reported `0 file(s) needed a final repair` with all
eight hashes matching (§12). `git stash list` is empty and `git diff --cached`
is empty. The entire card is uncommitted working-tree state, which is what the
register asks for.
