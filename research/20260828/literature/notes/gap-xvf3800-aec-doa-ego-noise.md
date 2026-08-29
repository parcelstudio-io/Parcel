# Gap note: XVF3800 audio front end (AEC / DoA / channels) and legged-robot ego-noise

Date: 2026-08-28. Sweep for the Parcel companion-dog behaviour model (Go2 EDU+, Jetson AGX Orin, reSpeaker XVF3800 USB 4-mic array + speaker). Every source below was fetched and read during this sweep; numbers are quoted from the fetched text. Items that could NOT be fetched are listed at the end so nobody cites them from memory.

Method note: the XMOS HTML documentation pages return HTTP 406 to non-browser clients, so the datasheet, user guide and programming guide were pulled as PDFs and converted with `pdftotext` (local copies in the session scratchpad: `xmos_datasheet.txt`, `xmos_userguide.txt`, `xmos_progguide.txt`).

---

## Part 1 — XMOS XVF3800 and the reSpeaker XVF3800 USB 4-mic array

### 1.1 XMOS XVF3800 Datasheet, release 3.2.1 (2024-10-29)
URL: https://www.xmos.com/documentation/XM-014888-PC/pdf/xvf3800_datasheet_v3.2.1.pdf

**AEC reference path (answer to the gap question).** The reference is the far-end stream the host sends TO the device, which the device then plays out through its own I2S-master DAC path. It is not an external microphone pickup and it is not something the host has to loop back separately.

> "A far-end AEC reference signal must be provided on the left (0) channel of the I2S or USB input signal. Data on the right channel is ignored. In order to ensure the far end that is playing into the room matches the far-end that the AEC is expecting, the DAC is configured to play the left input channel on both the right and left outputs." (§3.4.3)

> "It passes the converted signals to the voice pipeline, along with the far-end signal that is played on the loudspeaker after having passed through a Digital to Analog Converter (DAC) and amplifier." (§3.2.1)

> "When used in UA mode (host audio over USB) the XVF3800 has an active I2S master output which provides the far end signal to the DAC." (§3.4.1)

> "Full duplex, mono, Acoustic Echo Cancellation accommodating highly reverberant environments. (Reference audio for cancellation provided via either an I2S or USB interface)." … "Configurable bulk delay insertion to account for audio delays ensuring optimal echo cancellation with all audio output paths." (§2.2)

**AEC behaviour.**
> "At startup the AEC calibrates the adaptive filters to match the acoustic path between the loudspeaker and the microphones. This requires some far end audio content to provide a signal to the device. If the AEC detects a significant change to the acoustic path during operation, e.g. if the device is moved, it will initiate a re-convergence operation." (§3.2.2)

**Beamformer / DoA.**
> "The XVF3800 implements three beams - one free running beam that scans the environment for new speakers, and two focused beams that can track individual speakers. An alternative operating mode is also supported in which both focused beams can be fixed to a user specified azimuth angle. The final stage of the pipeline automatically selects which beam to use as the output from the device." … "The device provides a Direction of Arrival (DoA) measurement indicating the direction of the selected beam." (§3.2.3)

**ASR output.** "The output of the beamformer can be used as an input to an Automatic Speech Recognition (ASR) engine. In this mode the XVF3800 provides a configurable fixed gain to adapt the input level to the ASR engine." (§3.3)

**Table 3.1 "Pipeline parameters" (verbatim values):**

| Parameter | Value | Notes |
|---|---|---|
| Microphones | 4 off PDM | e.g. Infineon IM69D130 |
| Microphone alignment | +/- 2 dB | |
| Geometry | Linear or Square | |
| Frequency range | 80 Hz to 8 kHz | |
| Sampling rate | 16 kHz | |
| AEC tail length | 192 ms | |
| AEC reference channels | 1 mono | Output to DAC |
| Double talk detection | Continuous | |
| Reference delay | 0 to 500 ms (fixed) | Align microphone & reference signal |
| Number of beams | 3 | 2 focused + 1 scanning |
| Beamformer angle | 360 degrees | |
| Noise suppression | up to 25 dB | depending on input SNR |
| Operating distance | 0.3 m to 5 m | |
| Beamformer update time | 16 ms | |
| Input delay | min 58 ms | Microphone In to I2S out |
| Output delay | typ 50 ms | If far end processing on device is implemented |
| I2S or USB rate | 16 kHz or 48 kHz | Firmware options |
| I2S sample bit depth | 32 bits | |
| Input/Output USB sample bit depth | 16, 24 or 32 bits | Firmware options |
| Internal PLL range | +/- 1000 ppm | Meets USB Adaptive audio tolerance |

Other datasheet numbers: "Adjustable gain over a 60 dB range with automatic gain control"; "Typical core (VDD) power consumption: 345 mW (I2S) / 400 mW (USB)"; USB is "UAC 2.0 audio class in Adaptive Mode"; I2S and USB audio transports "are mutually exclusive and selected when the firmware image is built"; "The audio pipeline processes data with a sample rate of 16 kHz so, if 48 kHz inputs are used, a Sample Rate Converter block is introduced".

**ERLE:** the datasheet publishes NO ERLE figure in dB. The only quantitative suppression figure is "Noise suppression up to 25 dB depending on input SNR". (See user guide: ERLE appears only qualitatively as a tuning concept.)

**DoA resolution / update rate:** no angular accuracy or resolution specification is published. The nearest figure is "Beamformer update time 16 ms". Azimuth is reported as a float in radians (user guide, below).

### 1.2 XMOS XVF3800 User Guide, release 3.2.1 (2024)
URL: https://www.xmos.com/documentation/XM-014888-PC/pdf/xvf3800_user_guide_v3.2.1.pdf

**Convergence and the mobile-device caveat.**
> "The AEC requires a reference signal be present in order to converge on a room transfer function estimate - this process will take a few seconds after reference audio has begun being provided. If the AEC has not been allowed to converge, the XVF3800 will tend to over-suppress near-end speech in its output to avoid undesirable artefacts being relayed to the far-end." (§2.5.4)

> "When the AEC reaches convergence (which is expected to take less than 30 seconds)…" (§4.2.5). `AEC_AECCONVERGED` is a read-only 0/1 flag; "Once this value is set to 1 internally, it is never reset".

> Path Change Detector (PCD): "If a path change is detected, heavy near-end suppression during far-end activity is applied in order to allow the AEC time to reconverge to its new environment. If the device incorporating the XVF3800 is not intended for a mobile application (for example, a wall-mounted sound bar), then detection of path changes is not necessary." `AEC_PCD_COUPLINGI` in [0,1] (outside the range disables the PCD); `AEC_AECPATHCHANGE` reads 1 while "the device output is currently heavily suppressed during far-end activity". (§4.2.13)

**ERLE (qualitative only).**
> "AEC_PCD_MINTHR and AEC_PCDP_MAXTHR are used to set sensitivity thresholds, and their use depends on the overall Echo Return Loss Estimate (ERLE) of the device. For devices with a high ERLE (implying a high ratio between the provided reference signal and the resultant AEC residual, and therefore high cancellation), use AEC_PCD_MINTHR to limit the lower bound. Decreasing this value from its default of 0.02 will increase the sensitivity of the PCD. For devices with a low ERLE, use AEC_PCD_MAXTHR to limit the upper bound. Decrease this value from its default of 0.2 to increase the sensitivity of the PCD."

**Reference gain coupling.** "In the UA device variant, when the host sets the output volume, the AEC_FAR_EXTGAIN is internally set to be the same as the gain set by the host, so the user shouldn't need to set this command externally. In the I2S variant … the user would manually need to set the AEC_FAR_EXTGAIN". `AUDIO_MGR_SYS_DELAY` is a "Delay, measured in samples, that is applied" to align mic and reference (procedure in §4.2.4).

**DoA commands (§3.5.1–3.5.2).**
> "`AEC_AZIMUTH_VALUES`. The output of the command contains 4 values: Focused beam 1, Focused beam 2, Free running beam, Auto selected beam. Each value is the azimuth angle of the corresponding beam, provided in both radians and degrees." Command table: `AEC_AZIMUTH_VALUES READ 4 radians`.

> "`AEC_SPENERGY_VALUES` … Any value above 0 indicates speech. Higher values indicates louder or closer speech, however noise, echo and reverb can cause the energy level to decrease. 0 - beam 1, 1 - beam 2, 2 - free-running beam, 3 - auto-select beam" (4 floats).

> "The auto selection algorithm will switch between beams rapidly in some circumstances. The two focused beams update relatively slowly, but the free running beam is designed to be sensitive so that it can rapidly pick up the speech signal for a new talker entering the soundscape. As a result it can also pick up any noise signals present."

> "`AUDIO_MGR_SELECTED_AZIMUTHS` … returns 2 values, the first of which is the processed azimuth which will be NAN if there is no speech, otherwise it will be the azimuth of the current speaker. The second is the current azimuth of the auto select beam."

> Fixed-beam mode: `AEC_FIXEDBEAMSAZIMUTH_VALUES` / `AEC_FIXEDBEAMSELEVATION_VALUES` (radians, default (0,0)), `AEC_FIXEDBEAMSONOFF`, `AEC_FIXEDBEAMSGATING`. "When using fixed mode, both focused beams must be fixed." "Since the azimuth angle provided by the DoA function is dependent on the measurements of the acoustic path, the values reported by AEC_AZIMUTH_VALUES might not precisely match the fixed beam azimuth value." Linear geometry reports 0–180° only; square geometry 360°.

**Output channel mux (Table 3.2, `AUDIO_MGR_OP_L` / `AUDIO_MGR_OP_R` take (category, source)).** Categories: 0 Silence; 1 Raw microphone data before amplification (sources 0–3); 2 Unpacked mic data; 3 Amplified mic data with system delay (0–3, "the microphone signal passed to the SHF logical cores"); 4 Far end (reference) data; 5 Far end with system delay; 6 Processed data ("0,1: Slow-moving post-processed beamformed outputs, 2: Fast-moving post-processed beamformed output, 3: The 'auto-select' beam … recommended option"); 7 AEC residual / ASR data ("0,1,2,3: AEC residuals for the specified microphone, or ASR ouput for the specified beam"); 8 User chosen channels (default for left = copy of 6/3); 9 Post SHF DSP channels; 10 Far end at native rate; 11 Amplified mic before system delay; 12 Amplified far end with system delay ("the reference signal passed to the SHF logical cores"). Default: left = processed AEC+beamformer output, right = silence (or a raw mic on the dev kit).

**ASR output (§8).**
> "The ASR audio is extracted after the beamformer, and it is not fed into the post processor. This means it has no noise suppression, which is desirable as ASR performance is usually degraded by non-linear processing." … "One recommendation is an output level of -52 dBov for a 61 dBSPL level at the device. Typically this will result in an AEC_ASROUTGAIN around 36 dB lower than PP_AGCGAIN". Enable with `AUDIO_MGR_OP_R 7 3` + `AEC_ASROUTONOFF 1`.

**Mic HPF.** `AEC_HPFONOFF`: 4th-order Butterworth, corner selectable 70/125/150/180 Hz or off; "These typically require the system to be flat above 200Hz."

**Licensing / evaluation limit.** "The XK-VOICE-SQ66 development kit … will stop processing audio after 8 hours of continuous use … Licensed production XVF3800 devices do not have this restriction." The DFU tool "is licensed under the GPL version 2". Programming guide (v2.0.0, mirror https://docs.pawpaw.ltd/assets/files/xvf3800_programming_guide_v2.0.0-9feacc5b50a855dd9cd4db108558dc4e.pdf): source headers carry "This Software is subject to the terms of the XCORE VocalFusion Licence" (proprietary); user-DSP hook receives `azimuth direction of arrival data on the 3 tracking beams (not auto select)`.

### 1.3 Seeed Studio wiki — Getting Started with reSpeaker XVF3800 USB Mic Array
URL: https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/ (source md: https://github.com/Seeed-Studio/wiki-documents/blob/docusaurus-version/sites/en/docs/Sensor/reSpeaker_XVF3800_USB_4_Mic_Array/respeaker_xvf3800_usb_4_mic_array.md)

- "Quad PDM MEMS microphones in circular pattern, supporting 360° far-field voice capture (5m)"; geometry string "0.033, -0.033, 0.000, 0.033, 0.033, 0.000, -0.033, 0.033, 0.000, -0.033, -0.033, 0.000" (a 66 mm square, i.e. XMOS "square" geometry, 360° DoA).
- Codec "TLV320AIC3104"; "3.5mm AUX Headphone Jack"; "JST speaker interface, supports 5W amplified speakers"; "USB Audio Class 2.0 compliant"; "60dB AGC range"; "12x WS2812 individually-addressable RGB LEDs"; "LED array following the direction of the incoming voice".
- Firmware variants: `respeaker_xvf3800_usb_dfu_firmware_v2.0.x.bin` — "16 kHz sampling rate with 32-bit depth", "Channel 0: Conference, Channel 1: ASR"; `respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.x.bin` — "Channel 0: Processed audio (Conference), Channel 1: Processed audio (ASR), Channel 2-5: Mic 0-3 raw data"; `respeaker_xvf3800_i2s_dfu_firmware_v1.0.x.bin` — 2-ch 32-bit; `respeaker_xvf3800_i2s_master_dfu_firmware_v1.0.x_48k.bin` — "2-channel audio with a 48 kHz sampling rate" (Home Assistant). Linux flashing: `sudo dfu-util -R -e -a 1 -D <fw>.bin`.
- Seeed does not state the AEC reference path; the XMOS datasheet §3.4.3 answers it: the host's USB playback stream (left channel) is the reference and is what the board's DAC/amp plays.

### 1.4 Seeed wiki — reSpeaker XVF3800 Control with Python
URL: https://wiki.seeedstudio.com/respeaker_xvf3800_python_sdk/
- `DOA_VALUE` read returns `[doa_angle, vad_flag]`: angle in "degrees (0–359)" as uint16 words, `1 = speech detected, 0 = silence`; the example polls with `time.sleep(0.1)` (~10 Hz). LED commands `led_effect`, `led_color`, `led_speed`, `led_brightness (0–255)`; `save_configuration` / `clear_configuration`.

### 1.5 reSpeaker GitHub repo — host_control README and firmware folders
URLs: https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/blob/master/host_control/README.md ; https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/tree/master/xmos_firmwares/usb ; …/xmos_firmwares/i2s ; https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/blob/master/xmos_firmwares/usb/changelog.md
- host_control default tuning: `AUDIO_MGR_REF_GAIN: 8.0`, `AUDIO_MGR_MIC_GAIN: 90`, `AUDIO_MGR_SYS_DELAY: 12`, `PP_FMIN_SPEINDEX: 1300.0`, `PP_AGCMAXGAIN: 64.0`, `PP_AGCGAIN: 2.0`, `AEC_ASROUTGAIN: 1.0`. Output mux categories 0–12 as in the XMOS guide; left default "auto-select beam", right default silence.
- USB firmware files present: `respeaker_xvf3800_usb_dfu_firmware_v2.0.6/7/9/10.bin`, `…_6chl_v2.0.8.bin`, `…_v2.0.9_48k.bin`, `…_v2.1.0.bin`, `…_v2.1.0_16k6ch.bin`, `…_v2.1.0_48k2ch.bin`. I2S: `application_xvf3800_i2s_master_v1.0.8_48k.bin`, `application_xvf3800_i2s_slave_v1.0.8_16k.bin`, `respeaker_xvf3800_i2s_dfu_firmware_v1.0.4/1.0.7.bin`, `…_i2s_master_dfu_firmware_v1.0.5_48k.bin`, `…_v1.0.7_48k_test5.bin`.
- Changelog: v2.0.6 "Read-only `DOA_VALUE` command" returning "detected direction from 0 to 359 degrees", default HP/line-out gain "from 0 dB to 6 dB"; v2.0.8 audio profile "ua-io16-6ch-sqr" for "six-channel, 16 kHz capture", "Raw microphone signals to USB capture channels 3 through 6"; v2.0.9 "Restoration of saved fixed-beam settings after startup"; v2.0.10 USB recovery after bus resets, "Decoupled DOA state tracking from the active LED effect"; v2.1.0 "Configurable USB direct-output routing for channels 3 through 6" (`AUDIO_MGR_OP_CH3-6`), `AIC3104_HP_LEVEL` / `AIC3104_LINEOUT_LEVEL` with flash persistence, default output gain 8 dB.

### 1.6 CNX Software — ReSpeaker XMOS XVF3800 4-mic array board (2025-07-29)
URL: https://www.cnx-software.com/2025/07/29/respeaker-xmos-xvf3800-4-mic-array-board-features-esp32-s3-module-works-over-usb/
- Mic spec: "-26 dBFS" sensitivity, "Acoustic Overload Point – 120 dBL", "SNR – 64 dBA", "Up to a 5-meter range"; "DNN-based noise suppression", "60dB Automatic Gain Control"; "Maximum Sampling Rate – 16Khz"; "Speaker connector for up to 5W speakers"; price "$54.50" with XIAO ESP32S3 / "$49.99" without.

### 1.7 XVF3800 on a legged robot in the wild
URL: https://github.com/offroad-robotics/sst_as_a_heuristic_for_frontier_exploration (MIT) — Boston Dynamics Spot with "A ReSpeaker 4-Mic Array" on a backpack mast, ODAS-based sound-source tracking (ICRA 2024 paper / Queen's MASc thesis). The README gives no ego-noise numbers; it is evidence that a reSpeaker array has been fielded on a quadruped, nothing more.

---

## Part 2 — Ego-noise on legged robots (levels, spectra, effect on detection, suppression)

### 2.1 ANAVI: Audio Noise Awareness using Visuals of Indoor environments for NAVIgation (CoRL 2024; Jain, Veerapaneni, Bisk, CMU)
URL: https://arxiv.org/html/2410.18932
- Setup: robot action sounds were recorded once, then "We use a laptop speaker to play the robot action's audio; acting as the sound source" and "mobile phones … record audio at the listener" — the dB values are re-radiated levels, not live-robot measurements.
- Table 1 (bedroom in an apartment): Unitree Go2 (running) 70 dB at 0.5 m S, 63 dB at 1 m N, 54 dB at 5 m W; Stretch (fast forward) 52 / 49 / 47 dB.
- Table 2 (bedroom, single-family house): Go2 running 69.7 dB at 1m-west (LOS, in room), 67.1 at 1m-south, 66.1 at 1m-south-1m-east (no LOS), 67.3 at 2m-north, 66.7 at 2m-south, 61.1 at 2m-north-2m-west (no LOS), 65.4 at 3m-west, 65.4 at 3m-south; Stretch 54.2 / 52.1 / 49.7 / 51.7 / 50.5 / 45.3 / 48.6 / 48.2.
- Framing: "robot vacuums may be as loud as 70 decibels, which concerns many people with sensitive ears."

### 2.2 MUTE — Minimizing Acoustic Noise: Enhancing Quiet Locomotion for Quadruped Robots in Indoor Applications (IROS 2025; Cao, Nie, Zhang, Gao)
URL: https://arxiv.org/html/2506.23114
- Platform "Unitree Go1 EDU". Measurement: "a sound pressure sensor mounted approximately 30 cm above the ground … updates at a frequency of 20 Hz", "about 50 cm from the foot-ground collision point".
- "When the robot is stationary, with only the motor fan running, the noise level is approximately 55 dBA."
- Table II (0.5 m/s): DreamWaQ MNL/PNL wood 73.51/83.18, carpet 71.90/80.80, tiles 72.34/80.93, average 72.58/81.64 dBA; Built-in MPC 79.74/84.03, 77.92/81.25, 79.38/83.12, average 79.01/82.80; MUTE β=0 average 68.91/76.52; MUTE β=1 wood 65.78/73.18, carpet 62.48/69.52, tiles 66.15/76.22, average 64.80/72.97 dBA.
- "On average, MUTE reduces noise levels by approximately 8 dBA compared to the baseline, equating to a 2.5-fold decrease in sound pressure." Office course: 91.7 m at 0.36 m/s, MNL 68.25 dBA, PNL 76.8 dBA.
- Source attribution: "The primary source of noise in quadruped robots during locomotion is the repetitive impact of the robot's feet striking the ground"; motor noise "relatively minor compared to the noise produced by foot-ground collisions". Mechanism: "imposes constraints on the foot's velocity just prior to contact".

### 2.3 Human-Centered Development of Guide Dog Robots: Quiet and Stable Locomotion Control (arXiv 2505.11808, 2025)
URL: https://arxiv.org/html/2505.11808
- Unitree Go1 with Beelink SEi12 (i7-12450H) onboard PC. Noise recorded by "a researcher holding a smartphone at ear level" walking alongside through a 2 m zone.
- Default controller ≈ 60 dB at 0.6–1.2 m/s ("similar to a vacuum cleaner"); new controller "reduces noise by nearly 10 dB compared to the default controller", "50 dB on average", "even lower than the noise level of wheeled systems tested in [26] (65 dB)".
- Sources: "(1) impact noise from foot-ground contact and (2) collision noise between linkages and gears due to mechanical backlash"; fix = lower gait frequency + gentle touchdown. User study (n=4): all noticed the reduction; one said the default would be "disruptive in office or library settings".

### 2.4 Auditory Localization and Assessment of Consequential Robot Sounds: A Multi-Method Study in VR (arXiv 2504.00697, 2025; Wessels, de Heuvel, Müller, Maier, Bennewitz, Kraus)
URL: https://arxiv.org/html/2504.00697
- Recording: "two calibrated GRAS 64AE 1/2\" microphones, a camera, and a HeadAcoustics SQobold mobile data acquisition system on each robot", mics "positioned closely to the parts of the robots that were aurally identified as dominant sound sources".
- Levels: Go1 "74 dBA measured at approximately 15 cm distance"; Turtlebot 2i "72 dBA … approximately 10 cm"; HSR "57 dBA … approx. 10 cm". Go1 sound = "impulsive impact sound for every step combined with a high-frequency electric motor whirring".
- Human localization error (VR, sounds normalized to 80 dBA): Go1 9.76° head-on / 9.39° radial; Turtlebot 8.64° / 9.22°; HSR 13.15° / 12.40°.

### 2.5 Sound Matters: Auditory Detectability of Mobile Robots (arXiv 2404.06807, 2024; Agrawal, Wessels, de Heuvel, Kraus, Bennewitz)
URL: https://arxiv.org/html/2404.06807
- Go1 recorded with "a 3DIO FS XLR Binaural Microphone" at "a height of 7 cm", "at a fixed distance of 1 m"; Go1 spectrum "a rhythmic alternation of lower frequency components resembling an impact sound" vs the wheeled robot's "continuous high-frequency consequential sound".
- Backgrounds: "high-noise background level at 83 dB(A)", "low-noise background was adjusted at 60 dB(A)".
- Detection: wheeled robot detected only at "3.45 m (SD = 1.24 m)"; quadruped at "17.80 m (SD = 4.09 m)"; across robots, high noise 2.75 m (SD 0.71) vs low noise 18.60 m (SD 4.68). Annoyance (1–7): wheeled 4.39 vs quadruped 2.61.

### 2.6 Sound Judgment: Properties of Consequential Sounds Affecting Human-Perception of Robots (HRI 2025; arXiv 2502.02051)
URL: https://arxiv.org/html/2502.02051
- Five robots incl. "Go1 EDU PLUS quadruped (Unitree)"; no dB reported. 79.2% of sound-condition participants mentioned sound unprompted; 53.3% preferred quiet; 45.1% disliked loud; participants preferred "rhythmic sounds" and requested "natural or animal sounds" over machine-like noise.

### 2.7 Ego-noise reduction of a mobile robot using noise spatial covariance matrix learning and MVDR (IROS 2023; Lagacé, Ferland, Grondin, Sherbrooke)
URL: https://arxiv.org/html/2303.00829 — code https://github.com/introlab/egonoise (open source, ROS)
- Clearpath Jackal UGV (wheeled, not legged) with "16SoundsUSB" array, 16 omnidirectional mics at "32000 samples/sec".
- Input SNR ≈ −6 to +1.6 dB; large room average input SNR "−2.69 dB". SDR −1.75 → 9.57 dB; WER 90.3% → 35.5%; music-detection AP 0.487 → 0.685; "only 90 sec of ego-noise data" for the dictionary; "0.5 sec audio segment in 0.2 sec" on a laptop (Python/NumPy).

### 2.8 Partially Adaptive Multichannel Joint Reduction of Ego-noise and Environmental Noise (ICASSP 2023; Fang, Wittmer, Twiefel, Wermter, Gerkmann)
URL: https://arxiv.org/pdf/2303.15042
- "humanoid interactive robot NAO H25 from Softbank", external electret mics "mounted in the same position of the built-in microphone array (M = 4)"; ego-noise from "pre-defined right-arm movements in a crouching posture"; test SNRs "randomly chosen from {−5 dB, −4 dB, ···, 5 dB}", env noise at 0 dB, "average SNR of −2.1 dB for the joint noise scenario and −1.8 dB for the ego-noise only scenario"; 16 kHz, 64 ms Hann STFT. Results (Si-SDR / POLQA / WER) are given as a figure; the partially adaptive VAE-NMF scheme is best under joint ego+environmental noise.

### 2.9 A Robust Speech Recognition System against the Ego Noise of a Robot (Interspeech 2010; Ince, Nakadai, Rodemann, Hasegawa, Tsujino, Imura; Honda RI)
URL: https://www.isca-archive.org/interspeech_2010/ince10_interspeech.pdf
- Legged humanoid, "8 microphones located on top of the head"; "head motions were 8.4dB higher compared to arm motions in average"; joint angles every 5 ms, 10 ms audio frames; template subtraction α=1, β=0.5.
- "real-world scenario with a robot, where the SNR is [0 5]dB for the arm motion and [−5 0]dB for the head motion noise … 15% and 18% average WCR improvement is attained"; masking "improved up to 10%"; selective white-noise superposition "20% improvement for the problematic head-motion noise".

### 2.10 Single-Channel Robot Ego-Speech Filtering during Human-Robot Interaction (2024; Li, Hindriks, Kunneman)
URL: https://arxiv.org/abs/2403.02918
- Pepper's own speech + fan noise vs human barge-in; "signal processing approach without post-filtering yielded the best performance in terms of Word Error Rate … with low reverberation, while the CRNN approach is more robust for reverberation"; works when "human speech has a high volume or high pitch".

### 2.11 A Terrain Perception Method for Quadruped Robots Based on Acoustic Signal Fusion (Sensors 2026)
URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12845680/
- Deep Robotics Lite2; BOYA external mic at the foot end; 8 kHz; concrete footstep energy "concentrated below 1000 Hz"; recordings "may also include interference from robot induced sources such as structural vibrations, motor and transmission noise, and transient joint impacts"; acoustic fusion raises terrain accuracy 78.28% → 82.52% (99.53% with a 1 s window). Shows footstep transients are strong enough at an on-body mic to classify terrain — i.e. they will be strong enough to pollute a laughter/speech detector.

---

## Not fetchable this sweep (do not cite from memory)
- XMOS HTML doc pages (406 to non-browsers) — PDFs used instead.
- Boston Dynamics "Spot Sounds" support article (Salesforce JS shell; search snippet claimed 110 dBA buzzer / 80 dB speaker, unverified).
- ScienceDirect "online terrain classification framework for legged robots based on acoustic signals" (403).
- Zhang et al., "Exploring Consequential Robot Sound" IROS 2021 — abstract only (quieter → less discomforting; higher pitch → more competent/warm).
- No paper was found that measures ASR/sound-event-detection degradation at a body-mounted microphone on Spot, Go1/Go2 or ANYmal while walking; the ANYmal query returned nothing relevant. This is a genuine hole, not a search failure.

---

## What this means for Parcel

1. **Route every robot utterance through the reSpeaker's own DAC.** The XVF3800 AEC reference is the left channel of the USB playback stream, played by the board's I2S-master DAC to the JST/3.5 mm speaker. TTS sent to the Go2's built-in speaker or any other audio device is invisible to the AEC and will come back as un-cancelled echo into the duplex model. Mono only; AEC tail 192 ms; bulk reference delay fixed 0–500 ms; `AEC_FAR_EXTGAIN` tracks host volume automatically in the USB build.
2. **Barge-in while the dog moves will be degraded by design.** The AEC needs "a few seconds" of far-end audio to converge and "will tend to over-suppress near-end speech" until it does; the Path Change Detector applies "heavy near-end suppression during far-end activity" whenever the acoustic path shifts — which is continuously true for a walking, head-turning dog. Budget: (a) play a short far-end "warm-up" at boot; (b) experiment with `AEC_PCD_COUPLINGI` (raise to slow detection, or set outside [0,1] to disable) and watch `AEC_AECPATHCHANGE`; (c) treat the model's owner-interrupt channel as unreliable during robot-speech-plus-locomotion and prefer to speak while standing.
3. **Latency budget.** "Input delay min 58 ms" mic-in → out plus "typ 50 ms" output delay; add USB and host buffering. For a Moshi-style 80 ms frame clock this is roughly one frame of front-end latency each way, before the model.
4. **DoA is a speech-conditioned bearing, not a sound-localizer.** Azimuth is available as 4 beam angles in radians (`AEC_AZIMUTH_VALUES`), a NAN-when-silent "selected azimuth" (`AUDIO_MGR_SELECTED_AZIMUTHS`), or Seeed's integer 0–359° `DOA_VALUE` + VAD bit; the beamformer updates every 16 ms and no accuracy spec is published. It is driven by speech energy, and the free-running beam "can also pick up any noise signals present" — footstep impacts will steer it. For "look back at the owner when lost": use `AUDIO_MGR_SELECTED_AZIMUTHS` (speech-gated) as the yaw target; convert body-frame azimuth using the array's mounting orientation; expect the number to jump between beams.
5. **On-body SNR during locomotion is far worse than the ego-noise literature assumes.** Go1 at 0.5 m/s measures 72–79 dBA mean / 81–84 dBA peak at a sensor 30 cm above ground; stationary fan floor ≈ 55 dBA; Go1 ≈ 74 dBA at 15 cm; Go2 running ≈ 70 dB at 0.5 m. Conversational speech at 1–3 m is roughly 55–65 dB SPL at the robot, so the mic-side SNR while trotting is on the order of −10 to −25 dB, versus the −5…+5 dB regimes in which template subtraction (Ince: +15–18% WCR) and covariance-MVDR (Lagacé: WER 90→35%) were shown to work. The XVF3800's "up to 25 dB" suppression is for stationary/diffuse noise; footstep noise is impulsive and low-frequency (<1 kHz energy on hard floors), i.e. exactly the component classical NS handles worst.
6. **Consequences for the two target behaviours.** (a) Laughter reward: laughter and footstep impacts are both impulsive; gate the laughter detector on gait phase / foot-contact events from the Go2 state stream (known to the controller, so template-style subtraction à la Ince/Lagacé is feasible with the 6-channel raw-mic firmware and ~90 s of calibration per gait) or only score laughter while the dog is standing or in a quiet gait. (b) Track-loss "look back": use the speech-gated DoA plus the vision track, and expect the audio bearing to be unavailable while trotting.
7. **Prefer a quiet-gait policy when listening.** MUTE (−8 dBA, 2.5× lower pressure) and the guide-dog controller (−10 dB, ≈50 dB at ear level) show foot-velocity-at-contact shaping is the lever; a "listening gait" or simply stopping (55 dBA fan floor) is the cheapest SNR gain available. Mount the array on the top/head of the body, away from feet (the 72 dBA MUTE figure was 50 cm from the contact point).
8. **Firmware pick.** `respeaker_xvf3800_usb_dfu_firmware_v2.1.0_16k6ch.bin` (Conference, ASR, 4 raw mics, 16 kHz/32-bit) is the right variant: the ASR channel skips the post-processor ("no noise suppression"), which suits a learned front end better than the Conference channel, and the raw mics enable custom ego-noise processing and later re-training. Note `AEC_ASROUTONOFF` semantics and the `-52 dBov @ 61 dBSPL` gain recommendation.
9. **Licensing.** XVF3800 firmware/DSP is proprietary ("XCORE VocalFusion Licence"); the 8-hour stop applies to the XMOS eval kit, not "licensed production XVF3800 devices" (reSpeaker ships production silicon — verify on the unit by running >8 h). DFU tooling GPLv2; introlab/egonoise is open source and ROS-ready; Seeed host tools are on GitHub.
10. **Measurement protocol to close the hole (first day with a Go2).** Record 6-ch raw + Conference + ASR at stand / walk 0.5 m/s / trot 1.0 m/s on carpet and wood, with an owner talking and laughing at 1, 2, 3 m and with TTS playing through the reSpeaker speaker; compute per-gait SNR, XVF3800 VAD false-positive rate, laughter-detector precision, `AEC_AECPATHCHANGE` duty cycle, and DoA error vs a known speaker bearing. Those six numbers decide whether the duplex model can listen while moving or must adopt a stop-to-listen behaviour.
