# Task 25 — AIR-1: the robot's voice reaches its own mic, and the numbers say so

**Executor:** Claude Opus (harness + tools) · **Owner:** the live session
(~1.3 h) · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
**Evidence:** the design study §B; `docs/ACOUSTIC_BRINGUP_PLAN.md` §5.3
(ERLE ≥ 20 dB gate, `:350-354`); `backlog/BLOCKED.md` B3 (speaker on the
array's own amp; a clipped 3 W driver breaks AEC and shows up as false
barge-ins); `scrum/20260820/research/bench_doa.md` (the udev rule); the
08-20 sessions were run with headphones, so hardware AEC on this array has
never been measured and the only field failure on record (the TV hijack,
F1) is an acoustics/identity failure.

## Why
Full-duplex through air is the riskiest unknown in the goal and the
cheapest to retire: everything needed is on the desk. Three facts shape it:
the XVF3800 is **16 kHz-only in both directions** (`/proc/asound/card2/stream0`)
while the hosted lane plays 24 kHz and Piper 22.05 kHz; PipeWire downmixes
the two processed beams unless the ear picks ch1; and the production ear is
the browser with Chrome's AEC3 already in the loop — two AECs stack.

## Work (agent-executable before the owner sits down)
1. `tools/xvf3800_probe.py`: device/channel map, DoA poll (100 consecutive
   `DOA_VALUE` reads, 0 permission errors once the udev rule is in), the 16 kHz
   rate pin (PortAudio 24 kHz on `hw:2,0` fails with −9997 — pin it as a
   seeded test so nobody routes around the PipeWire node), ch0/ch1 RMS
   while speaking.
2. `tools/measure_erle.py`: robot speech (a fixed 10 s probe phrase through
   the array's amp) vs array capture ch1 with the owner silent, first 2 s
   excluded; reports ERLE and residual level; a double-talk arm (owner
   speaks over the robot at 1 m) reports the residual vs server-VAD
   threshold.
3. `tools/bargein_through_air.py`: with the R17 tee, scores interrupt
   latency (inbound onset → `sink.interrupt`), false barge-ins during a
   10-min robot monologue with the owner silent, and a TV-on arm with DoA
   sector + enrolled profile; emits the scorecard the plan's gate reads.
4. A runbook in `task_25/SESSION.md`: the owner's steps in order with
   minutes (speaker on the JST-PH2.0 amp at ≈0.4 sink volume;
   `speaker-test -D plughw:2,0 -r 16000 -c 2`; udev + `udevadm trigger`;
   `pip install pyusb`; `doa: true`; enroll voice; 20 turns + 20
   interruptions + 10 min silent; TV arm).

## Pre-registered acceptance (owner session)
ERLE **≥ 20 dB** at 1 m at normal level; **0/20** robot utterances
transcribed as owner turns; interrupt **p50 ≤ 0.52 s** (n = 20); false
barge-in **≤ 2 %** over the 10-min monologue; TV-on arm **0**
owner-attributed turns in 10 min; DoA poll ≥ 95 % ok; hosted spend ≤ $2.
Misses are reported as misses with their mechanism (clipping, AEC3
double-cancel, downmix) — the plan's week-3 purchase gate reads these rows.

OWNS: `tools/xvf3800_probe.py`, `tools/measure_erle.py`,
`tools/bargein_through_air.py`, `configs/realtime*.example` device notes,
`tests/test_air1_*.py` (rate pin, scorecard schema), `task_25/` docs.
MUST NOT TOUCH: `lane.py` (MARK-1/TURN-1), `audio_gateway.py` (MARK-1), the
legacy loop's `echo_guard_scale` (a digest-locked file — owner re-freeze).

## Definition of done
Tools + runbook landed with seeded rate-pin RED; every owner row listed
OWNER-GATED with the exact command; after the session, `AIR1_STATUS.md`
carries the scorecard verbatim.
