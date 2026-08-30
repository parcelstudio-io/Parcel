# ACOUSTIC_LOOP_V1 historical results

These JSON files are retained for provenance. They were produced by earlier
runner versions and must not be interpreted using current measurement claims.

The 2026-08-07 baseline repeated a 5/9 score over 25 virtual cases with clean
teardown. A 2026-08-29 independent audit then showed that:

- endpoint timing was sampled after full WAV playback and hid commits inside
  pause-heavy utterances;
- mixed-minus-owner power did not isolate robot output for STOP;
- the duplex reply's 22.05 kHz WAV header was stripped and raw PCM was treated
  as 16 kHz;
- prosody used inconsistent clock origins, reusable matches, and no motion
  observer.

Those historical numbers are not valid capability measurements and were not
retroactively relabeled. The corrected runner is
`virtual-pipewire-rig-v2-measurement-validity`; its retained report, exact case
findings, and red verdict are in
[`research/20260829/acoustic-eval-v2/`](../../../../research/20260829/acoustic-eval-v2/).
