# A6 STOP-LOCAL · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard run (label `fable-a6-verify`) — A6 suite + r24 +
nominal-stop + closed-intent product path + endpointing ×2 + voice_audio +
acoustic_defects + core_hard_stop + owner_estop + realtime_ingress + both DEC
ratchets = **534 passed, 1 skipped** (the executor's count reproduced exactly);
scope = exactly two modified product files (`runtime.py` +140/−1, `config.py`
+4) plus the new leaf, test, fixture, status doc; ruff clean on all four
touched files with zero new fingerprints (the one non-baseline fingerprint on
the host is the PRE-EXISTING `research/20260823/search-before-refuse/
runtime_probe.py::F401` from 98023fb, corroborated, untouched); the hunks and
the 621-line leaf read line-by-line.

## Disposition: **ACCEPTED**

- **The latch is the panel's latch, pinned by the call, not the state**:
  `_stop_hotword_latched` is three lines into the guarded
  `RobotRuntime.emergency_stop`, and `test_both_doors_go_through_one_method`
  spies the method itself — a parallel latch cannot pass. `core/hard_stop.py`,
  `finalize_command`, `safety.py`, the arbiter, `web_panel.py`: untouched
  (corroborated by git status, not just the register).
- **The bypass property is measured with the conversation genuinely wedged**
  (held `_agent_lock`, asserted still hung at the end): the hung stack costs
  ≈1 ms; the capture thread is one bounded `put_nowait` (drop-oldest);
  the watch shares no lock with dialogue/hosted/voice-session — r24's graph
  and `PINNED_LOCK_ORDER` unchanged. Deliberately no `barge_in` on the safety
  thread; consequence (the dog finishes its sentence) stated and filed.
- **The grammar policy is the flagged owner-default, honestly priced**: all
  three modes behind one fail-closed knob (unknown keys/modes refused by
  name), DEFAULT `name_prefixed`; `bare` reproduces VOICE-GATE's 864/24 h
  exactly and its docstring says it fails the bar; the load-bearing
  observation (the name in NONE of 976 TV windows) re-verified over the tape.
  Stop vocabulary derived from `closed_intent_phrases` — no second copy
  (U33's lesson held).
- **Both A9 tail bars met for the shipped grammar on the replay tier**
  (p95 608/785 ms vs bar 800; n=64; 0 over 1.0 s shipped), with the
  latch-rate floor asserted beside the percentile, a seeded red proving the
  tail assertion can fail, and the two bare-tape >1.0 s trials pinned to
  their mechanism (whisper itself at 1.54–2.32 s) rather than waived.
  The speech-offset trigger's win over the research reference (935→608 ms
  p95) is a design result, not tuning.
- **DEC discipline**: `voice_loop.py` byte-unchanged (subclass tee with the
  seam asserted by test), zero markers, zero noqa, both ratchets green.

Accepted judgment calls, noted: the trailing-name widening ("stop, Parcel")
is beyond the measured prefix claim but re-scored at 0 false on the recorded
tape; hybrid's open window is "speaking OR moving" where moving counts as
owner-commanded because the freeze list ships no self-initiated translation —
correct today, and it must be REVISITED the day autonomous translation ships.
Undone, correctly named: ≤1/24 h is unfalsified (≈87/24 h bound), not proven —
~72 h of tape; recall ≥0.99 unmet (0.938 synthetic / 0.859 bare recorded, the
misses at 3 m off-axis) and NOT claimed; everything through-air is box-day
(no loudspeaker/AEC/mounted acoustics/real human voice — the name's
transcribability by a real owner voice is unmeasured, F3b); the transcriber
is shared with conversation (`PARCEL_STOP_HOTWORD_STT_URL` splits it; a
dedicated spotter is the A7/box-day fix); `config.py` sits at exactly the
DEC-0 1000-line ceiling — the next card touching it decomposes first.
Does not prove: any physical stop; the latch-to-motor envelope is A5's and
the acoustic path has never been through air.
