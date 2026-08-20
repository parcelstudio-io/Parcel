All benches complete. Composing the final report.

# XVF3800 DoA + Speaker-Embedding Feasibility Bench — Final Report

**Bench dir (all artifacts):** `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/evalbench/xvf3800-bench/`
Success criteria were pre-registered before any prototype run in `SUCCESS_CRITERIA.md` in that dir. Zero repo files touched; zero audio-interface opens; no firmware/DFU/reset operations; live stack undisturbed (evidence below).

## Methodology

**Bench A (DoA read path):** enumerated USB descriptors via sysfs/lsusb (no device open needed), mapped kernel driver bindings per interface, researched the control protocol (Seeed python SDK + XMOS user guide + host_control README), downloaded the official `xvf_host` 3.0.0 Linux x86_64 binary set into scratch, and attempted reads two independent ways (xvf_host binary, raw pyusb control transfers), recording verbatim outcomes. Non-disruption verified by before/after ALSA stream state and USB device-number stability.

**Bench B (speaker embeddings, offline):** no owner speech existed on disk (see caveat), so gold set = 5 speakers, 28 utterances: 2 espeak-ng synthetic voices (`en+m3`, `en+f4`, ctypes → WAV, 8 utterances each using the actual voice_corpus_v1 query texts) + 3 real LibriSpeech test-other speakers (4 utterances each, from the Resemblyzer repo samples). Pairs: 74 same-speaker, 304 cross-speaker (378 total). Two CPU ONNX models via sherpa-onnx 1.13.6 (py3.14 wheel, installed with `pip --target` into scratch — repo venv untouched): 3dspeaker eres2net (26MB) and NeMo titanet_small (40MB). Metrics: cosine separation, zero-overlap margin, best-threshold error count, per-utterance latency.

## Bench A results: DoA read path — EXISTS, blocked only by a udev permission

Interface map (USB 2886:001a, bus 3 dev 8): IF0 UAC control, IF1 UAC stream OUT, IF2 UAC stream IN (live capture path, `snd-usb-audio`), **IF3 Vendor Specific — the XMOS control interface, NO kernel driver bound (free to claim without touching audio)**, IF4 DFU (never touched), IF5 HID (`usbhid`, mute-button class, root-only hidraw4, no DoA).

| Check (pre-registered) | Result | Evidence (denominator) |
|---|---|---|
| SC-A1 channel exists | **PARTIAL — hardware+software path confirmed, 0 successful reads** | `xvf_host` runs on this host (prints usage, v3.0.0); read attempt fails only on permissions |
| SC-A2 60s poll | **BLOCKED** | 0/6 polls ok in attempt run (`results/doa_poll.csv`) |
| SC-A3 non-disruption | **PASS** | ALSA `pcm0c/sub0/status` closed→closed; device stayed Bus 003 Device 008 (no re-enumeration = no reset); only EP0 control attempts + sysfs reads |
| SC-A4 read latency | unmeasured (blocked) | — |

Verbatim failures:
- `./xvf_host VERSION` → `Error : Failed to open device. Ensure adequate permissions if using Linux, or remove any pre-installed drivers with Device Manager on Windows.` (exit code 0, note: tool doesn't set rc)
- pyusb `ctrl_transfer(0xC0, ...)` → `USBError: [Errno 13] Access denied (insufficient permissions)`

Root cause: `/dev/bus/usb/003/008` is `root:root 0664`, no ACL, no udev rule for 2886 anywhere, and sudo requires interactive auth. usbfs control transfers need O_RDWR.

**Exact unblock (2-minute owner action, does NOT reset the device or disturb the stream — udev trigger only re-applies node permissions):**
```
sudo tee /etc/udev/rules.d/99-respeaker-xvf3800.rules <<< 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001a", MODE="0660", GROUP="plugdev", TAG+="uaccess"'
sudo udevadm control --reload && sudo udevadm trigger --action=change /sys/bus/usb/devices/3-1
```
Then either of these works immediately (both staged in the bench dir):
- `cd .../xvf3800-bench/xvf_host_bin && ./xvf_host AEC_AZIMUTH_VALUES` (4 azimuths: beam1, beam2, free-running, auto-selected) and `./xvf_host AEC_SPENERGY_VALUES` (speech energy)
- `python3 .../xvf3800-bench/doa_poll.py 60 4` — 60s poll of `DOA_VALUE` (resid=20, cmdid=18 → `[angle_deg 0-359, vad_flag]` as 2×uint16 via `ctrl_transfer(0xC0, 0, 0x80|cmdid, resid, n)`), CSV-logged, tolerant of the optional leading status byte.

## Bench B results: speaker embeddings — PASS on every criterion

28 utterances / 5 speakers; 74 same-speaker + 304 cross-speaker pairs; CPU only, 4 threads.

| Metric | eres2net (26MB) | titanet_small (40MB) | Criterion |
|---|---|---|---|
| same-speaker cos, mean (n=74) | +0.727 (min +0.577) | +0.802 (min +0.640) | — |
| cross-speaker cos, mean (n=304) | +0.046 (max +0.384) | +0.033 (max +0.431) | — |
| mean separation | **0.68** | **0.77** | ≥0.30 PASS |
| zero-overlap margin (min same − max cross) | **+0.193** | **+0.209** | >0 PASS |
| pair errors at best threshold | **0/378** (t=0.577) | **0/378** (t=0.640) | — |
| cross real-vs-real max (visitor proxy, n=48) | +0.384 | **+0.234** | — |
| latency median / p95 (n=28) | 54.0 / 240.2 ms | **27.1 / 126.1 ms** | ≤250ms PASS |
| latency by duration (titanet, n=21 ≤7s) | — | 10ms @1.1s, 28ms @2.7s, 63ms @6s | — |
| model load (one-time) | 204 ms | 115 ms | — |
| footprint (pylib 118MB + models 64MB) | 188MB total | | <2GB PASS |

Hardest cross pairs (verbatim, titanet): `es_m3_05 vs es_f4_05 = 0.431`, `es_m3_08 vs es_f4_08 = 0.405` — both are the two espeak voices speaking the *same sentence* (shared synthesis engine + content, worst case by construction); still 0.21 below the weakest same-speaker pair (0.640). Hardest real-human cross pair: `1688-142285-0001 vs 1998-15444-0000 = 0.234` (eres2net 0.384).

**Caveat (material):** no real owner-voice audio exists on disk — the mic-commissioning WAVs in `/tmp/claude-1000/` are room tone only (measured: `mic_respeaker.wav` peak 0.054, flat RMS 0.006; `mictest.wav` peak 0.0012), and the 52 corpus WAVs were not retained (only `live_run_1/*.json`). Recording now would open the reSpeaker capture device, which was forbidden while the live stack owns it. Owner-enrollment numbers are therefore not measured; the LibriSpeech same/cross numbers are the proxy.

## Costs

Hosted API spend: **$0.00** (cap $2 — never needed; credential never loaded). Everything ran on local CPU + free downloads (~70MB models, 1.8MB xvf_host set, 12 flac samples, pip wheels).

## Ranked recommendation for the F1 gating stack

1. **Primary: post-VAD embedding verify with titanet_small via sherpa-onnx** — measured effect size is decisive: same/cross means 0.802 vs 0.033 (Cohen's d ≈ 9; zero overlap on 378 pairs), at 27ms median added latency in-process in the audio gateway, 40MB model, 115ms one-time load. Enroll the owner with 5-10 utterances (the existing `record.sh` flow, run while the live stack is paused), average the enrollment embeddings, start threshold at 0.50-0.55 (midpoint of measured worst gap: 0.431 max-impostor vs 0.640 min-genuine), fail-closed per the FIX-A convention: below threshold → turn not armed.
2. **Prefilter: XVF3800 DoA sector + hardware VAD gate** — the read path exists on this host and is one udev line away; `DOA_VALUE` returns `[angle, vad]` in a single ~ms control read that cannot disturb the audio stream (separate vendor interface, EP0 only). For the TV-hijack failure specifically this is nearly free: the TV sits at a fixed azimuth, so reject turns whose DoA lies in the TV sector unless embedding verify passes. Blocked-by: the udev rule above; then run `doa_poll.py 60 4` to land SC-A2/A4.
3. **Do not rely on AEC state for F1** — AEC only cancels the robot's own speaker reference; TV audio is an independent source and passes through untouched.

Suggested next bench (after the udev rule + a 30s owner enrollment recording): re-run `embed_bench.py` with real owner positives against the same negatives, and validate DoA sector stability with the TV actually playing — both scripts are staged and take minutes.

Key file paths:
- `.../xvf3800-bench/SUCCESS_CRITERIA.md` (pre-registered criteria)
- `.../xvf3800-bench/results/embed_bench.json` (full stats), `.../results/doa_poll.csv` (blocked-attempt log)
- `.../xvf3800-bench/doa_poll.py`, `.../xvf_host_bin/xvf_host`, `.../embed_bench.py`, `.../build_gold.py`, `.../audio/manifest.json`

Sources: [Seeed XVF3800 Python SDK](https://wiki.seeedstudio.com/respeaker_xvf3800_python_sdk/), [host_control README](https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/blob/master/host_control/README.md), [Seeed XVF3800 intro](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/), [XMOS XVF3800 host application guide](https://www.xmos.com/documentation/XM-014888-PC/html/modules/fwk_xvf/doc/user_guide/03_using_the_host_application.html)