# Acoustic evaluator validity rerun — verdict

**The acoustic subsystem is not mount-readiness validated.** The revised
evaluator is materially more trustworthy because it fails closed on invalid
commit timing and refuses to manufacture physical STOP or motion-sync evidence.

Immediate product findings:

1. Keep the current endpoint thresholds; calibrate or retrain completion on
   pause/resumption and incomplete-turn examples. Two pause cases produced a
   premature first turn plus a second turn, and two incomplete cases committed
   roughly 0.25 s after their final detected speech.
2. Treat 0.79 s as a failed virtual acknowledgement gate, not as mounted
   latency. Use a persistent/pre-warmed stream and measure device presentation
   separately from response leading silence on the Orin audio target.
3. Add isolated owner and robot output channels on one clock before scoring
   acoustic cessation. Add a distinct through-air spoken-STOP-to-latched-stop
   test; generic VAD interruption is not emergency-STOP recognition.
4. Add an actual BeatLayer command trace, then mounted encoder/video timing.
   The 0.9286 result supports virtual audio transport only.

The next valid rung is a motors-disabled, through-air bench with mounted
microphone/speaker, AEC double-talk cases, isolated reference capture, human
pause fixtures, and physical presentation timestamps. It is not autonomous
motion.
