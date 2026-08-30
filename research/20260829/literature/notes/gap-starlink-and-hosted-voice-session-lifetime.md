# Gap note: Starlink latency/jitter/loss (mobile terminals, voice traffic) and hosted Realtime-voice session lifetime / reconnect design

Date: 2026-08-29. Scope: fills two gaps left by the first sweep for the Parcel dual-rate design (Model A = 10 Hz act-token loop + 0.5-2 Hz plan lane; Model B = owner voice -> steering injection, receipts -> narration through a hosted Realtime voice). Every source below was fetched and read (PDFs extracted with pdftotext where the fetcher could not parse them). Numbers are quoted from the source; my own arithmetic is marked "derived".

Companion note: `hosted-realtime-voice-with-local-planner.md` (same folder) already carries the base pricing table and the headline 60-min / 15-min caps. This note goes one level deeper: the periodic 15-second Starlink spike structure, in-motion outage anatomy, how voice apps actually break over Starlink, and the exact rotation / re-priming / caching mechanics of both hosted voices.

---

## Part 1 - Starlink as the uplink for a walking robot

### S1. Richter, Ververis, Bajpai (HPI) - "Breaking Through the Clouds: Performance Insights into Starlink's Latency and Packet Loss", IFIP Networking 2025
URL: https://vaibhavbajpai.com/documents/papers/proceedings/starlink-networking-2025.pdf (also IETF-123 maprg slides)
Data: RIPE Atlas (146 probes in AS14593) + Cloudflare Radar, 2022-01-01 to 2024-06-30. Metric is RIPE Atlas *TLS-handshake latency*, not ICMP RTT, so absolute values run higher than ping-based studies.
- "latency has improved since 2022 to reach 26 ms minimum, 80 ms median, and 100 ms average latency" (2024).
- Median TLS latency 81-84 ms (2022), 94-98 ms (2023), back to ~80 ms (2024).
- "Bimodal Distribution of Latencies ... first peak ... approximately 80-100 ms ... second peak ... approximately 150-250 ms".
- Packet-loss ratio table: most countries 1-4 %; Czechia 0.23 %, Chile 0.24 %, Sweden 0.53 %, Austria 0.73 %, Belgium 2.27 %, Australia 3.97 %, Netherlands 14.19 %, Philippines 18.27 %; Germany "exceeding 10%".
- "no statistically significant correlation between latency and packet loss".
- Caveat: few probes per country (e.g. Philippines 3, Czechia 1); loss figures are country aggregates over 2.5 years, not a single terminal.

### S2. Ullah et al. (VTT / Univ. Oulu / Finnish NDU) - "Starlink in Northern Europe: A New Look at Stationary and In-motion Performance", arXiv 2502.15552v2 (22 Oct 2025)
URL: https://arxiv.org/html/2502.15552v2
Flat High Performance (FHP, ESIM-class) terminal; 24 May - 27 Jun 2024; stationary at four sites near Oulu (9,288 pings) and in motion on a 6 km stretch of the E8 motorway (396 pings, 830 iPerf3 samples per direction).
- Stationary median RTT: Oulu 90 ms, Helsinki 85 ms, Frankfurt 55 ms, Amsterdam 60 ms, Reykjavik 99 ms, New York 143 ms (terrestrial reference to Helsinki 15 ms, Frankfurt 33 ms, New York 103 ms).
- In motion: "Median RTT increased by approximately 9 ms"; downlink -9 Mbps, uplink -3.2 Mbps (median).
- Stationary downlink medians > 116 Mbps everywhere (peak 249 down / 44 up); uplink median floor 19.9 Mbps.
- Outages in motion clustered at "curved highway on-ramps/off-ramps surrounded by dense trees, bridge passages" (count/duration not reported).
- Mobile plan spec quoted as "<99 ms"; met for all servers except New York.
- Conclusion: "Starlink is capable of supporting in-motion Internet connectivity, provided that the service can tolerate occasional outages."

### S3. Laniewski et al. (Osnabrueck) - "Starlink on the Road: A First Look at Mobile Starlink Performance in Central Europe", arXiv 2403.13497 (Mar 2024)
URL: https://arxiv.org/html/2403.13497v1
FHP dish on a van roof, 11 Jan - 7 Mar 2024, 15,269 samples (4,196 = 27 % in motion).
- Throughput drops ~10 % in motion (download 265-270 vs 299 Mbit/s; upload 15.40 vs 17.74 Mbit/s); "once in motion, the speed of the car has no further impact" (corr. -0.15 down / -0.12 up; speed vs worst-case ping 0.13).
- Packet loss by environment: ~1 % rural clear-sky; up to 10 % urban (buildings); ~45 % near mountains with RTT up to 349 ms.
- Terminal power: mean 113 W (48-191 W); in-motion median 137 W vs 106 W stationary (relevant to a Go2 battery budget if the dish rides on the dog or a chase unit).

### S4. Zhao et al. - "Demystifying Starlink Network Performance under Vehicular Mobility with Dynamic Beam Switching", arXiv 2601.13790 (20 Jan 2026)
URL: https://arxiv.org/html/2601.13790v1
~500 km / 5 h of driving (rural, urban, suburban, highway; midwestern USA), mobile UT vs a tree-obstructed stationary UT (17.9 % FOV obstruction).
- Mobile UT outage anatomy over 5 h: SKY_SEARCH 221.4 s (45.18 %), NO_DOWNLINK 134.0 s (27.33 %), OBSTRUCTED 110.9 s (22.62 %), NO_PINGS 23.7 s (4.83 %). Derived: ~490 s outage / 18,000 s = ~2.7 % of drive time with no link.
- Stationary obstructed UT: OBSTRUCTED 367.8 s (56.21 %), SKY_SEARCH 148.2 s (22.66 %), NO_DOWNLINK 132.3 s (20.22 %), NO_PINGS 6.0 s (0.92 %) (derived ~654 s, i.e. a badly placed fixed dish is *worse* than a moving one).
- Mobile units show a "doubling of SKY_SEARCH events" from transient obstructions; a hard-obstruction beam switch "falls back to a non-primary or backup beam in the serving cell with markedly lower performance", and throughput recovery is "frequently delayed until the next scheduled handover" (i.e. up to one 15 s slot).
- Handovers under mobility occur "beyond the well-known 15-second regular handover interval".

### S5. Mohan et al. - "A Multifaceted Look at Starlink Performance", ACM WWW '24
URL: https://arxiv.org/abs/2310.09242 (PDF read: https://www.nitindermohan.com/documents/2024/pubs/starlinkWWW2024.pdf)
19.2 M M-Lab tests (34 countries) + 1.8 M RIPE Atlas + two controlled terminals; Zoom and Amazon Luna over terrestrial / 5G / Starlink.
- Zoom uplink one-way delay over Starlink "52 +/- 14 ms vs. 27 +/- 7 ms" terrestrial; downlink 35 +/- 11 vs 32 +/- 7 ms; frame rate "does not meaningfully differ ... (~27 FPS)"; Zoom compensates a "slightly higher loss rate over LEO" with FEC (146 +/- 99 kbps vs 2 +/- 2 kbps).
- "the Starlink OWD often noticeably shifts at interval points that occur at 15 s increments" - the FCC-filed reconfiguration interval; the intervals are globally synchronized.
- Luna cloud gaming (150 min): RTT 11 +/- 13 / 39 +/- 17 / 50 +/- 16 ms (terrestrial / 5G / Starlink); freezes 0 +/- 0 / 0 +/- 220 / 0 +/- 120 ms/min; game delay 133.5 / 165.8 / 167.1 ms; "occasional drops to < 20 FPS over Starlink ... coincide with Starlink's reconfiguration interval".
- Bent-pipe (dish -> gateway -> PoP) latency "36-48 ms, with the median hovering around 40 ms" across countries; cellular last-mile ~1.5x lower.
- "reconfigurations result in brief sub-second connection disruptions"; their 2023 terminal "did not experience second-long outages"; bufferbloat confirmed under load.

### S6. Zhao, Fang, Wang, Liu (SFU) - "Realtime Multimedia Services over Starlink: A Reality Check", ACM NOSSDAV '23
URL: https://henryfang.net/assets/pdf/zhao2023realtime.pdf (ACM DOI 10.1145/3592473.3592562)
Dec 2022 + 4 months; two dishes (urban Pacific West Coast, rural US Mid-South); Zoom Meeting API per-minute stats; 887,628 ping samples.
- App-reported outages: "average of the outage time is about 6.46 seconds, with the longest outage being 18s" (2022-23 hardware/constellation).
- Zoom: "Starlink network exhibits significant variations, particularly during network outages lasting longer than 1 second. However, Starlink network outages shorter than 0.5 seconds have marginal impacts on the Zoom meeting performance."
- "the audio loss rate is highly correlated with Starlink network outages ... longer network outages yielding higher average audio loss rates".
- Interactive round-trip (screen change seen by peer): 0.69 s Starlink vs 0.57 s terrestrial (variance 0.0095 vs 0.0073); "terrestrial network made about 23.5% more interactions".
- Ping RTT sits in steady states that switch "for roughly every 15 seconds", with "approximately 30ms" steps, occasionally jumping to 180 ms and emptying a 5 s stream buffer while the app reports no outage.

### S7. Casparsen, Jakobsen, Nielsen, Popovski, Leyva Mayorga (Aalborg) - "Statistical Characterization and Prediction of E2E Latency over LEO Satellite Networks", arXiv 2601.08439 (13 Jan 2026; npj Wireless Technology 2026)
URL: https://arxiv.org/abs/2601.08439 (body read at https://arxiv.org/html/2601.08439v1)
500 Hz bidirectional one-way probes (2 ms spacing), NTP sub-ms sync, Aalborg (57 N), multi-month traces.
- "deterministic 15-second periodic behavior"; boundary regions are "the first 140 ms and the last 75 ms of each period" - derived: 215 ms of every 15 s (1.4 % of time) is a spike zone.
- Spike magnitude at period start "reaching an average of 74 ms above the mean latency".
- Period-aware prediction: "99th-percentile latency prediction errors below 50 ms"; short-horizon MSE ~65 ms^2 after 1 s, ~21 ms^2 after 5 s (~8 ms / ~4.5 ms absolute); GMM(3) classifies the current period to AUPRC 0.95 in 1.6 s.
- Purpose stated: let apps "proactively adapt through pacing, buffering, quality adjustment, or safe-mode transitions".

### S8. Garcia, Sundberg, Brunstrom (Karlstad) - "A Detailed Characterization of Starlink One-way Delay", ACM LEO-NET '25 (dataset on Zenodo)
URL fetched: https://zenodo.org/records/16275284 (paper DOI 10.1145/3748749.3749090 returned 403)
- Setup confirmed from the dataset page: "unobstructed Starlink user terminal located in Karlstad, Sweden, during April 2025"; send/receive on "two Ethernet ports of a single hardware timestamping NIC"; 1,437 files, 5.9 GB.
- The abstract sentence "minor diurnal variation, clear uplink/downlink asymmetry, and strong latency inflation during periodic 15-second reconfiguration events" came from the search snippet of the ACM page, NOT from a fetched page - treat as unverified corroboration of S7.

### S9. Garcia, Sundberg, Brunstrom - "Characterizing the Configuration of Starlink Queuing", arXiv 2605.27717 (26 May 2026, accepted IMC '26)
URL: https://arxiv.org/abs/2605.27717
- Starlink uses "drop-front buffer management" and "does not implement per-flow fair queuing"; drop-front lowers queueing delay but "may also interfere with the assumptions made by loss-based congestion controls". Implication: a robot's bulk uplink (telemetry, logs) will steal from voice unless the robot shapes its own egress; the network will not isolate the flows.

### S10. Ramirez-Arroyo et al. - "Towards Reliable Connectivity: Measurement-Driven Assessment of Starlink and OneWeb NTN and 5G TN", arXiv 2512.19639 (Dec 2025)
URL: https://arxiv.org/html/2512.19639v1
Three-day campaign, Copenhagen; one-way delay at a 5 Mbps target flow.
- Urban: Starlink DL median 36 ms / UL 43 ms; outage probability 12-17 %. Suburban: 26 / 32 ms; coverage loss 3 %. Forest: 99 / 376 ms; coverage loss 49 %.
- Starlink + OneWeb multi-connectivity cuts urban outage "from approximately 12-21% to 2%".
- Authors' verdict: satellite is viable backup, "Cellular networks superior for real-time applications".

### S11. Chintareddy et al. - "A Vertical Look at UAV Connectivity in the Wild: Cellular vs. Starlink", arXiv 2605.27755 (26 May 2026)
URL: https://arxiv.org/abs/2605.27755
10+ flights, 4.5+ h, 18,000+ samples, rural, Verizon vs Starlink on a moving UAV.
- Starlink: "95% of Round-Trip Time (RTT) measurements below 50 ms" and "95% exceeding 25 Mbps"; cellular "80% under 150 ms", 5 Mbps. Cellular handovers rise 3-4x above 330 m; worst-case handover RTT hit +275 ms.
- Counterpoint to S10: with clear sky, a *moving* Starlink terminal beats rural cellular on latency.

### S12. Starlink (official) - "Improving Starlink's Latency" (2024 engineering note)
URL: https://starlink.com/public-files/StarlinkLatency.pdf
- Goal "stable 20 millisecond (ms) median latency and minimal packet loss".
- US peak hour: median "from 48.5ms to 33ms" (>30 % cut); p99 "from over 150ms to less than 65ms" (>60 % cut); outside US median -25 %, worst-case -35 %.
- Method: "anonymized measurements from millions of Starlink routers every 15 seconds"; peak = 6-9 PM local.
- Physics: "1.8-3.6ms per leg, and usually under 10ms for the round-trip"; extra latency when routed over laser links; 6 new US PoPs in 2024; fq_codel added to the WiFi router; "Buffers across our network have been right sized to reduce bufferbloat".

### S13. The Register (16 Jul 2025) quoting Starlink's network update
URL: https://www.theregister.com/2025/07/16/starlink_network_update/ (starlink.com/updates/network-update did not render for the fetcher)
- "median peak-hour latency is 25.7 milliseconds for customers in the United States"; median peak-hour download 200 Mbps; 6 M+ customers; 100+ US gateway sites; 7,800+ satellites; goal still 20 ms.

### S14. Shi, Zhang, Hu (Manitoba) - "Deciphering Region-Level Signatures from Latency Measurements in LEO Satellite Internet", arXiv 2606.29324 (Jun 2026)
URL: https://arxiv.org/html/2606.29324v1
- LENS dataset, 10 ms RTT sampling, 18-23 Jan 2026: minimum RTT ~15-18 ms (Bruhl, Seattle, Victoria) vs 35-40 ms (Ulukhaktok, Arctic, far from PoP). Confirms the 2026 floor is PoP distance, not the satellite hop.

### S15. Wang et al. - "A Large-Scale IPv6-Based Measurement of the Starlink Network", arXiv 2412.18243 (v. Jan 2026)
URL: https://arxiv.org/abs/2412.18243 - 5.98 M active IPv6 addresses, 208 regions / 165 countries, 49 PoPs, 98 backbone links; no latency numbers in the abstract. Context only.

### S16. PacketStorm blog (2026) - secondary, vendor-sourced
URL: https://packetstorm.com/starlink-satellite-internet-in-2026-bandwidth-latency-and-packet-loss-analyzed/
- Ookla US median download ~54 Mbps (late 2022) -> ~105 (Q1 2025) -> 220 Mbps (late 2025); "median 25-50 ms", "99th percentile under 65 ms", "<1% [loss] in clear conditions". Unattributed; use only as a sanity check on S12/S13.

### What the Starlink evidence says, condensed
1. Baseline (2025-26, clear sky, stationary or slow-moving): ~26-50 ms RTT median, p99 < 65 ms (S12, S13, S11, S14). Older RIPE-Atlas TLS numbers (80 ms median) are a different metric and era (S1).
2. The dominant jitter source is deterministic: a globally synchronised 15 s reconfiguration cycle whose first 140 ms and last 75 ms carry spikes averaging +74 ms (S7), visible as ~30 ms RTT steps and occasional 180 ms jumps (S6), sub-second disruptions (S5), FPS drops to < 20 in cloud gaming (S5). It is predictable to p99 < 50 ms with a period-aware model (S7).
3. Motion itself costs little (+9 ms RTT, -10 % throughput, no speed dependence: S2, S3); obstruction is what kills the link. A moving terminal spent ~2.7 % of a 5 h drive in outage (S4); forest coverage loss reached 49 % (S10); urban loss up to 10 % (S3).
4. What breaks voice is gaps > 1 s; gaps < 0.5 s are absorbed (S6). Audio loss tracks outages directly (S6). 2022-23 app-reported outages averaged 6.46 s (S6); 2023-24 controlled terminals saw only sub-second disruptions (S5), so the tail improved but a moving/obstructed dish still sees seconds-long holes (S2, S4).
5. The network gives no flow isolation (drop-front, no fair queuing: S9) and had bufferbloat under load (S5, acknowledged in S12) - the robot must shape its own uplink.

---

## Part 2 - Hosted Realtime voice: session lifetime, reconnect, re-priming, caching

### OpenAI Realtime API

H1. Realtime conversations guide - https://developers.openai.com/api/docs/guides/realtime-conversations
- "The maximum duration of a Realtime session is 60 minutes."
- `session.update`: "Most session properties can be updated at any time, except for the voice the model uses for audio output, after the model has responded with audio once during the session."
- Barge-in: "The client should send a conversation.item.truncate event to remove the unplayed portion of the model's last response from the conversation" (item_id, content_index, audio_end_ms).

H2. "Developer notes on the Realtime API" (OpenAI dev blog, 2025) - https://developers.openai.com/blog/realtime-api
- "Realtime sessions can now last up to 60 minutes, up from 30 minutes."
- gpt-realtime: token window 32,768; max response 4,096; max input 28,672; "The session instructions plus tools can have a maximum length of 16,384 tokens."
- "The service will automatically truncate (drop) messages when the session reaches 28,672 tokens" - and truncation "busts the token prompt cache"; the GA service "automatically drops some audio tokens when a transcript is available to save tokens".
- `"truncation": "disabled"` returns errors instead; retention_ratio 0.8 truncates 20 % at once to preserve cache hits between truncations.

H3. Managing costs guide - https://developers.openai.com/api/docs/guides/realtime-costs
- "Realtime API costs are accrued when a Response is created, and is charged based on the numbers of input and output tokens." "The entire conversation is sent to the model for each Response."
- Audio token rates: user audio "1 token per 100 ms of audio" (derived: 600 tokens/min); assistant audio "1 token per 50ms of audio" (derived: 1,200 tokens/min).
- "Realtime API supports prompt caching, which is applied automatically"; modifying instructions "mid-session will reduce the cache rate for subsequent turns"; "Clearing out old messages is a good way to reduce input token sizes and cost".

H4. Prompt caching guide - https://developers.openai.com/api/docs/guides/prompt-caching
- Minimum cacheable prefix: "1,024 visible input tokens" (GPT-5.6+), "2,048" for earlier models.
- Cache reads "0.1x" the input rate (90 % off).
- Lifetime: GPT-5.6+ "30 minutes after its most recent write or reuse"; earlier models in_memory "around 5 to 10 minutes of inactivity, up to one hour", 24h retention "typically around 30 minutes ... up to 24 hours".
- "Cache reuse requires the entire rendered prefix to match."

H5. Pricing - https://developers.openai.com/api/docs/pricing (per 1 M tokens)
- gpt-realtime-2.1 / gpt-realtime-2: audio in $32.00, cached $0.40, out $64.00; text in $4.00, cached $0.40, out $24.00; image $5.00 / $0.50.
- gpt-realtime-2.1-mini / gpt-realtime-mini: audio $10.00 / $0.30 / $20.00; text $0.60 / $0.06 / $2.40.
- Derived per-minute: listening (audio input, first pass) $0.0192/min; speaking $0.0768/min (2.x); mini $0.006 / $0.024. Cached audio re-read is 80x cheaper than first pass ($0.40 vs $32).

H6. Create client secret (API reference) - https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create
- `expires_after.seconds`: default 600, range 10-7200; `anchor`: "created_at".
- "The session itself may continue after that time once started. A secret can be used to create multiple sessions until it expires."
- Session `truncation`: "auto" (default) or "disabled"; `RetentionRatioTruncation.retention_ratio` 0.0-1.0.

H7. Microsoft Q&A, 25 Mar 2026 - first-turn cached tokens - https://learn.microsoft.com/en-us/answers/questions/5834804/why-does-the-first-response-in-my-openai-realtime
- "If the prefix exceeds the minimum caching threshold (1,024 tokens) and matches a prefix that was recently processed on the same backend host, then the model will report cached input tokens, even on the very first turn."
- "The Realtime API treats system instructions and internal session preamble as part of the prompt prefix ... When identical or near-identical system instructions are reused across sessions, the service can reuse previously computed token representations". This is the mechanism that makes session rotation cheap.

H8. Microsoft Q&A, 26 Jan 2026 - Azure cap - https://learn.microsoft.com/en-us/answers/questions/5741275/gpt-realtime-maximum-session-length-30-minutes
- Azure OpenAI: "The maximum session duration is 30 minutes." vs OpenAI direct 60 min; no extension planned. (If Parcel ever routes via Azure EU, halve every timer below.)

H9. LiveKit agents issue #2341 and PR #2360 (merged 30 May 2025) - https://github.com/livekit/agents/issues/2341 , https://github.com/livekit/agents/pull/2360
- Error text seen: "Your session hit the maximum duration of 30 minutes."
- Fix shipped: `RealtimeModel(max_session_duration=20 * 60)` - default 20 min, proactive timer (not error-driven), "wait for the current generation to complete before reconnecting", replays chat history into the fresh session, emits `session_reconnected`. This is the reference implementation of rotation-before-expiry.

H10. OpenAI community, session_expired thread (2024 - Feb 2025) - https://community.openai.com/t/realtime-api-session-expired/975036
- Wire format of the kill: `{"type": "error", "code": "session_expired", "message": "Your session hit the maximum duration of 15 minutes."}` (15 min at beta; 30 min by Feb 2025; 60 min at GA per H1/H11).
- "calling session.update() does not extend the expiration timer"; the developer pattern was DB-stored history + periodic session.update of the prompt.

H11. OpenAI community, post-GA timeout thread (13 Sep 2025) - https://community.openai.com/t/realtime-api-session-timeout-post-ga/1357331 - confirms the 60-min figure; no server-side knob to end a session earlier; a Dec 2025 question about enforcing shorter sessions from the backend went unanswered.

### Google Gemini Live API

H12. Session management - https://ai.google.dev/gemini-api/docs/live-session
- "audio-only sessions are limited to 15 minutes"; "audio-video sessions are limited to 2 minutes"; extendable with context-window compression.
- "the lifetime of a connection is limited as well, to around 10 minutes."
- GoAway carries `timeLeft` ("remaining time" before ABORTED); server sends SessionResumptionUpdate with `newHandle` while "resumable"; "Resumption tokens are valid for 2 hr after the last sessions termination"; reconnect by passing the handle in SessionResumptionConfig.

H13. Live API reference - https://ai.google.dev/api/live
- ContextWindowCompressionConfig.triggerTokens default "80% of the model's context window limit"; slidingWindow.targetTokens default "trigger_tokens/2".
- SessionResumptionConfig.handle: "If not present then a new session is created."

H14. Firebase AI Logic limits - https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs
- "Session context window is limited to 128k tokens"; audio-only ~15 min, video+audio ~2 min.
- "Connection length is limited to about 10 minutes" with a going-away notice "about 60 seconds before the connection ends".
- Agent Platform quota: "1,000 concurrent sessions per Firebase project" and "4M tokens per minute".
- Audio: 16-bit PCM 16 kHz in, 24 kHz out; video 1 FPS at 768x768.

H15. Firebase AI Logic session management - https://firebase.google.com/docs/ai-logic/live-api/sessions
- Resumption windows: ~10 min after a connection drop (short-term); "2 hours" (Gemini Developer API); "24 hours" (Agent Platform). Resumed sessions come back "with its context intact"; system instructions are preserved at the start of the compressed context. Defaults restated: triggerTokens 80 % of window, targetTokens 50 % of trigger.

H16. Live API best practices - https://ai.google.dev/gemini-api/docs/live-api/best-practices
- "Audio tokens accumulate at approximately 25 tokens per second" (derived: 1,500/min; 128k window = ~85 min of raw audio, so the 15-min figure is what remains after output and history growth).
- Worked compression example: trigger 25,000 tokens, sliding window 8,000 tokens.
- Send audio "in chunks of 20ms to 40ms"; "Don't buffer input audio significantly (such as 1 second) before sending".
- On interruption the server sends `interrupted: true` and the client "must immediately discard your client-side audio buffer".

H17. Live API capabilities - https://ai.google.dev/gemini-api/docs/live-api/capabilities
- 128k tokens for native-audio models, 32k for others; VAD knobs start/end sensitivity, prefix_padding_ms, silence_duration_ms; client-side VAD should use "at least 500ms" silence.

H18. Gemini pricing - https://ai.google.dev/gemini-api/docs/pricing (per 1 M tokens, paid tier)
- gemini-2.5-flash-native-audio-preview-12-2025: text in $0.50, audio in $3.00, text out $2.00, audio out $12.00.
- gemini-3.1-flash-live-preview: text in $0.75, audio in "$3.00 or $0.005/min", video "$1.00 or $0.002/min", text out $4.50, audio out "$12.00 or $0.018/min"; page says context caching at standard 3.1 Flash rates, but see H19/H21.

H19. Google AI forum, Google staff reply 7 Jul 2026 - https://discuss.ai.google.dev/t/does-gemini-live-native-audio-bill-cumulative-prompt-tokens-on-every-turn-cost-seems-to-scale-with-turn-count-not-call-duration/173248
- "Gemini Live re-bills the entire cumulative context on every single turn"; raw audio tokens from earlier turns are kept and "re-processed and charged at the standard audio input rate on every turn".
- User data: cost tracks turn count, not minutes (a 5.8-min call cost 37 % less than a 5.6-min call).

H20. Google AI forum, Google staff 5-9 Jan 2026 - https://discuss.ai.google.dev/t/gemini-live-api-sessions-exceeding-15-minute-limit-without-compression/114104
- "15 min is an approximation. It really depends on the context window size"; the limit is the 128k window filling, not a clock; 27-51-min production sessions were seen with compression enabled.

H21. Gemini caching doc - https://ai.google.dev/gemini-api/docs/caching
- Implicit caching "enabled by default for all Gemini 2.5 and newer models"; minimum 2,048 (2.5) / 4,096 (3.x) tokens; no statement that Live/native-audio sessions get it, and H19 says the full audio context is re-billed at standard rate. Treat Gemini Live as uncached until proven otherwise.

### Session lifetime, condensed
| | OpenAI Realtime (direct) | Azure OpenAI | Gemini Live |
|---|---|---|---|
| Hard session cap | 60 min (H1, H2) | 30 min (H8) | none with compression; ~15 min audio / ~2 min A+V without (H12, H20) |
| Connection cap | = session | = session | ~10 min, GoAway ~60 s early (H12, H14) |
| Expiry signal | `error` code `session_expired` (H10) | same family | GoAway.timeLeft then ABORTED (H12) |
| Server-side resume | none; replay text history (H9, H10) | none | handle valid 2 h (24 h Agent Platform), ~10 min after a drop (H15) |
| Context | 32,768 window; 28,672 input; 16,384 instr+tools; auto-truncate (H2) | same | 128k; sliding-window compression 80 % -> 40 % of window by default (H13) |
| Instruction re-priming | cached across sessions if identical prefix >= 1,024 tok and reused within ~30 min: $0.40/1M vs $4/1M text (H4, H5, H7) | same | re-billed every turn at standard rate (H19) |
| Ephemeral credential | client secret 600 s default, 10-7200 s, can open several sessions (H6) | | n/a |

---

## What this means for Parcel's Model A / Model B

### Model A (10 Hz act-token loop + 0.5-2 Hz plan lane) - fully on the Orin
- Nothing in the 10 Hz loop may touch Starlink. Even the good case has a deterministic +74 ms spike for 215 ms every 15 s (S7) and sub-second disruptions at every reconfiguration (S5); the moving-dog case adds ~2.7 % outage time (S4) and seconds-long holes at tree lines and structures (S2, S6). A 100 ms control tick cannot be hostage to that.
- The 0.5-2 Hz plan lane may *consult* a hosted model but must not *wait* for it: budget the cloud call as a 500-2,000 ms optional hint with a local default, and treat any gap > 1 s (the threshold where voice apps visibly break, S6) as "cloud absent" for that tick.
- If a cloud plan hint is used, phase it to the 15 s cycle: the period is globally synchronised (S5) and classifiable in 1.6 s with p99 error < 50 ms (S7); schedule the request to complete outside the first 140 ms / last 75 ms of each period.

### Model B (owner voice -> steering; receipts -> narration via hosted Realtime voice)
- Transport: use the WebRTC path (UDP) rather than WebSocket, and size the jitter buffer for a +74 ms periodic spike plus 30 ms steps (S6, S7) - a 100-150 ms adaptive buffer covers the boundary regions without adding perceptible delay on the ~26-50 ms baseline (S12, S13).
- Barge-in and "resume after side-talk" already run locally through the XVF3800 + local VAD; keep that, because audio loss over Starlink tracks link outages one-for-one (S6) and the hosted model cannot see a gap it never received. On any detected hole > 1 s, mute the uplink, send `conversation.item.truncate` (H1) on reconnect, and let the local cascade voice carry the receipt narration.
- Uplink shaping is the robot's job: Starlink drop-front queues without fair queuing (S9) mean telemetry bursts will drop voice packets; rate-limit non-voice egress and never send receipt bursts in the 15 s boundary windows.

### Session rotation design (both providers)
- OpenAI: rotate proactively at a natural pause before 60 min (LiveKit ships a 20-min default timer and replays history, H9); never rely on catching `session_expired` (H10), and remember `session.update` does not extend the clock (H10). Carry over (a) the unchanged instruction block, (b) a text summary + last N turns as `conversation.item.create` text items, (c) any pending function-call state. Keep the instruction block byte-identical and >= 1,024 tokens so the new session's prefix hits the cache (H4, H7): derived re-prime cost for a 3 k-token instructions+summary preamble is ~$0.012 uncached vs ~$0.0012 cached per rotation - negligible against speaking at $0.0768/min (H5). Put per-minute robot state into later items, not into `instructions`, since editing instructions "will reduce the cache rate" (H3).
- Credentials: mint client secrets on the Orin-side gateway with `expires_after.seconds` long enough to cover a rotation (default 600 s, max 7,200 s); one secret can open the replacement session (H6).
- Gemini: the binding limit is the ~10-min connection, not the 15-min audio figure. Always enable context-window compression (e.g. trigger 25k / target 8k, H16) and hold the latest resumption handle; on GoAway (~60 s warning, H14) reconnect with the handle (valid 2 h, H12). Because every turn re-bills the full audio context (H19), keep the compressed window small and prefer a text summary over raw audio history; this is a cost knob, not just a memory knob.
- Budget reality for an all-day dog: at 25 tok/s (H16) Gemini listens for $0.005/min; OpenAI first-pass listening is $0.0192/min but context re-reads are 80x cheaper when cached (H5). The local VAD gate (only stream when the owner addresses the dog) remains the single biggest cost lever in both cases.
- Fallback: the Starlink evidence (2.7 % outage in motion, 49 % in forest, 12-17 % urban one-way outage at 5 Mbps) says a hosted voice will be absent a noticeable fraction of an outdoor walk. Model B's contract must be satisfiable by the local cascade so the dog is never mute; the hosted voice is quality-on-top.

### Open items this sweep could not settle
- No paper measured WebRTC/Opus specifically over Starlink; the closest are Zoom (S5, S6) and cloud gaming (S5). A local measurement with the Parcel gateway over the owner's Starlink terminal (log OWD at 100 Hz for an hour, align to 15 s boundaries) would close this in a day.
- Starlink Mini / in-motion behaviour at walking speed and at 0.5 m height (a dog-mounted dish) is unmeasured in the literature; all mobility studies used roof-mounted FHP terminals.
- Reconnect *gap* duration for a fresh OpenAI WebRTC session (ICE + session.created + first cached response) was not found in any source; needs measurement.
- Whether Gemini Live resumption handles survive a Starlink IP change (CGNAT re-assignment after an outage) is undocumented.
