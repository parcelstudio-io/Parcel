# Hosted real-time speech model as the voice of a locally-planned robot

Literature note, 2026-08-29. Topic: engineering patterns and measured numbers for a hosted
speech-to-speech model (OpenAI Realtime API / gpt-realtime family, Gemini Live) acting as the
*voice* of a robot whose planner runs locally — tool/function-call latency, interruption (barge-in)
handling, live context injection, 2026 pricing, session/context limits, published robot
integrations, and open (self-hostable) alternatives with measured numbers.

Every source below was fetched and read on 2026-08-29. Numbers are quoted from the page as read;
where a number comes from a secondary/marketing page it is flagged `[secondary]`. Nothing here is
cited from memory. Pages that returned HTTP 403 (openai.com/index/*, medium.com, hackernoon.com)
are listed at the end as "not readable" and are NOT cited.

---

## 0. Headline numbers (one screen)

| Quantity | Value | Source |
|---|---|---|
| gpt-realtime-2 / 2.1 audio price | $32 / 1M audio-input tokens, $0.40 cached, $64 / 1M audio-output; text $4 / $0.40 / $24; image $5 | OpenAI pricing page (S3) |
| gpt-realtime-2.1-mini audio price | $10 / $0.30 / $20 (audio in / cached / out); text $0.60 / $0.06 / $2.40 | S3, S8 |
| OpenAI audio tokenisation | 1 token per 100 ms of input audio; 1 token per 50 ms of output audio (=> 600 tok/min heard, 1,200 tok/min spoken => $0.0192/min listen, $0.0768/min speak at $32/$64) | OpenAI cost guide (S4) |
| gpt-realtime-2 / 2.1 context | 128,000-token window, 32,000 max output, knowledge cutoff Sep 30 2024; tier-1 limit 200 RPM / 40K TPM, tier-5 20,000 RPM / 15M TPM | model cards (S9, S10) |
| gpt-realtime (Aug 2025 GA) context | 32,768 tokens; 4,096 max response; 28,672 max input; 16,384 for instructions+tools; session max 60 min (was 30) | OpenAI dev blog (S5) |
| Gemini 3.1 Flash Live price | audio in $3.00 / 1M or $0.005/min; audio out $12.00 / 1M or $0.018/min; text in $0.75, text out $4.50; video in $1.00 or $0.002/min | Gemini pricing (S21) |
| Gemini 2.5 Flash native audio price | $3.00 audio/video in, $12.00 audio out, $0.50 text in, $2.00 text out | S21 |
| Gemini audio tokenisation | 32 tokens per second of audio; 263 tokens per second of video | S22 |
| Gemini Live limits | audio-only session 15 min, audio+video 2 min (extendable by context compression); connection lifetime ~10 min; resumption handle valid 2 h; GoAway carries `timeLeft` | S25 |
| Gemini Live context | 131,072 in / 65,536 out (3.1 Flash Live); 131,072 in / 8,192 out (2.5 native audio) | S28, S29 |
| Measured OpenAI WebRTC response latency (Jan 2025, gpt-4o-realtime era) | ~1.7 s (1.68 / 1.78 / 1.66 s manual; 1.764 / 1.86 / 1.796 s VAD); STUN RTT 60–70 ms | webrtcHacks (S1) |
| Measured end-of-speech -> first audio byte (Jun 2026, 20 convs, Tel Aviv) `[secondary]` | OpenAI Realtime ~410 ms median; Gemini Live ~380 ms; Pipecat-JS ~440 ms | S54 |
| Full-Duplex-Bench v1.5 (overlap) | GPT-4o Realtime stop latency 0.23 s / response 1.50 s on user interruption; Gemini 2.0 Flash Live 2.20 s / 2.62 s; Moshi 1.16 s / 1.47 s; Freeze-Omni 1.42 s / 1.35 s | S48 |
| Full-Duplex-Bench-v3 (multi-step tool use, zero-latency mock tools) | gpt-realtime-1.5: pass@1 0.600, tool-selection F1 0.876, arg accuracy 0.680, latency 6.89 s, take-turn 96.0 %, interrupts user 13.5 %, filler 16.9 %; gemini-3.1-flash-live-preview: 0.540 / 0.817 / 0.588 / 4.25 s, silent in 22 % of scenarios; Cascaded Whisper->GPT-4o->TTS: 0.450 / 10.12 s | S49 |
| DuplexSLA-Bench turn-taking (no prefill) | GPT-Realtime-1.5 semantic-vad-high 96.50 % acc / 1.57 s delay; server-vad-40ms 85.50 % / 0.83 s; Gemini-3.1-flash-live 93.17 % / 1.17 s; PersonaPlex 22.34 % / 0.47 s; Freeze-Omni 10.67 % / 0.36 s | S50 |
| DuplexSLA-Bench tool-call delay | ASR+LLM cascade 91.33 % acc / 2.77 s; DuplexSLA (7B, from Step-Audio 2 mini) 85.56 % / 0.64 s; legal trigger window = not >1.0 s early, not >3.0 s after audio end | S50 |
| tau-voice | GPT-5 (text, reasoning) 85 %; voice agents 31–51 % clean, 26–38 % realistic noise/accents (30–45 % of text capability retained); 79–90 % of failures are agent behaviour | S51 |
| Moshi (open) | 7B temporal transformer + 6-layer depth transformer; Mimi 12.5 Hz, 1.1 kbps, 80 ms frame; 160 ms theoretical / 200 ms practical on L4; 24 GB GPU for bf16; weights CC-BY 4.0; no tool calling | S39–S41 |
| PersonaPlex (NVIDIA, open) | 7B, Moshi weights; trained 6 h on 8xA100, 1,840 h CS + 410 h QA dialog; FDB user-interruption latency 0.070 s (paper) / 0.240 s (HF card), smooth turn-taking 0.170 s; tested on A100 80 GB; no tool calling; NVIDIA Open Model License | S44–S46 |
| Kyutai Unmute (open cascade, Realtime-compatible protocol) | STT 1B: 0.5 s delay + semantic VAD (2.6B: 2.5 s); TTS latency ~750 ms on one L40S -> ~450 ms on 3 GPUs; total < 1 s; min 16 GB VRAM; tool calling "not fully integrated yet" | S42, S43 |
| OpenAI chat-supervisor reference pattern | realtime model says "give me a moment to check on that", then "~2s" gap until the supervisor's (gpt-4.1) answer is spoken | S16 |
| Robot integrations | WSO2 Go2 EDU: Jetson Orin NX (100 TOPS), Flask lock-wrapper around non-thread-safe Unitree SDK, onboard mic/speaker "incredibly noisy" -> Jabra Speak 710; ROS 2 `by_your_command`: Silero VAD < 50 ms, 1–2 s voice response, < 100 ms playback; Reachy Mini: 60 Hz MovementManager, tools in background tasks, 1 FPS JPEG to Gemini | S31–S38 |

---

## 1. OpenAI Realtime API — mechanisms

### S1. webrtcHacks — "Measuring the response latency of OpenAI's WebRTC-based Realtime API"
URL: https://webrtchacks.com/measuring-the-response-latency-of-openais-webrtc-based-real-time-api/
- Method: Wireshark RTP capture, libWebRTC `neteq_rtpplay` -> WAV, silero-vad speech segments, Audacity alignment. Measurements taken 2025-01-04 (gpt-4o-realtime era); article says conditions "have improved since then".
- Numbers: response latency (user speech end -> model speech start) 1.68 s, 1.78 s, 1.66 s manually; 1.764 s, 1.86 s, 1.796 s by VAD. STUN RTT "around 60-70 ms". RTP offset 56 ms. Sample size: 3 speaker switches / 13 speech events.
- Relevance: the only fully independent packet-level measurement found; ~1.7 s is the realistic *conversational* turn latency of early 2025, not the 300–500 ms marketing figure.

### S2. OpenAI docs — Realtime conversations guide
URL: https://developers.openai.com/api/docs/guides/realtime-conversations
- Interruptions: with WebRTC/SIP "the server will automatically truncate unplayed audio when there's a user interruption". With WebSocket the client must watch `input_audio_buffer.speech_started`, stop playback, and send `conversation.item.truncate` (`item_id`, `content_index`, `audio_end_ms`).
- Manual control: set `turn_detection.interrupt_response` and `turn_detection.create_response` to `false` to keep VAD but stop automatic responses — "will retain all the behavior of VAD but not automatically create new Responses".
- Out-of-band responses: `response.create` with `"conversation": "none"`, optional `metadata`, `output_modalities`, and a custom `input` array (new items or `item_reference`s). `input: []` yields a response "ignoring all other instructions and context".
- Function calling: tools in `session` or per-`response`; call surfaces in `response.done` as `output[i].type == "function_call"` with `name`, `arguments`, `call_id`; return via `conversation.item.create` `{type: "function_call_output", call_id, output}` then `response.create`.
- Per-response override: `response.create` may carry `instructions`/`tools` that "override the Session's configuration for this Response only".
- Session: `session.update` may change most fields any time except `voice` after first audio; "The maximum duration of a Realtime session is 60 minutes"; audio chunk <= 15 MB.
- `conversation.item.create` accepts message roles `user` / `assistant` with `input_text`, `input_audio`, `input_image` (data URL). (The cookbook in S13 also uses `role: "system"`.)
- Push-to-talk recipe: `turn_detection: null`, `response.cancel` on key-down, `input_audio_buffer.commit` + `response.create` on key-up.

### S3. OpenAI pricing page
URL: https://developers.openai.com/api/docs/pricing
- gpt-realtime-2.1 and gpt-realtime-2: audio in $32.00 / cached $0.40 / out $64.00; text $4.00 / $0.40 / $24.00; image $5.00 / $0.50.
- gpt-realtime-1.5 and gpt-realtime: same audio; text out $16.00.
- gpt-realtime-2.1-mini and gpt-realtime-mini: audio $10.00 / $0.30 / $20.00; text $0.60 / $0.06 / $2.40; image $0.80 / $0.08.

### S4. OpenAI docs — Managing Realtime costs
URL: https://developers.openai.com/api/docs/guides/realtime-costs
- "1 token per 100 ms" of input audio; "1 token per 50ms" of output audio.
- "32k context model with 4,096 max output tokens can only include 28,224 tokens" of input; truncation `retention_ratio` server default 1.0, recommended 0.8 (drop 20 % at once to keep the prefix cache).
- Caching is automatic when a Response's input tokens match a previous Response; "keep a session's history static"; "Removing or changing content in the conversation will 'bust' the cache"; truncation busts the cache near the start.
- Tips: mini models, `conversation.item.delete`, replace old messages with summaries, `post_instructions` cap on input tokens per response; read `usage` in `response.done`.

### S5. OpenAI developer blog — "Developer notes on the Realtime API"
URL: https://developers.openai.com/blog/realtime-api
- Session up to 60 min ("increased from 30"); token window 32,768; max response 4,096; max input 28,672; instructions+tools 16,384 (numbers for `gpt-realtime-2025-08-28`).
- "The service will automatically drop some audio tokens when a transcript is available."
- `idle_timeout_ms` on `server_vad`: fires `input_audio_buffer.timeout_triggered` after response audio ends + delay, committing an empty segment (lets the model re-prompt a silent user).
- Async function calling (GA only): the model "continues while awaiting function responses", with automatic placeholder responses to avoid hallucinating a result; beta model lacks it and "pending MCP tool calls without output may not be treated well".
- Sideband: dual connections (client + application server) keep "business logic, tool use, and security on server side".
- Temperature removed in GA (beta was 0.6–1.2, default 0.8). Image input GA only. EU residency via `eu.api.openai.com`. Hosted prompts with version pinning.

### S6. OpenAI community — "Introducing gpt-realtime and Realtime API updates" (2025-08-28)
URL: https://community.openai.com/t/introducing-gpt-realtime-and-realtime-api-updates-for-production-voice-agents/1355039
- "The Realtime API is officially out of beta and ready for your production voice agents!"; new: remote MCP servers, image input, SIP, reusable prompts; two voices Cedar and Marin; price cut 20 %.

### S7. OpenAI community — "New Realtime Voice Models in the API" (2026-05-07, gpt-realtime-2)
URL: https://community.openai.com/t/new-realtime-voice-models-in-the-api/1380471
- gpt-realtime-2: "$32 / 1M audio input tokens, $0.40 / 1M cached input tokens, $64 / 1M audio output tokens"; "GPT-5-class reasoning"; GPT-Realtime-Translate $0.034/min (70+ -> 13 languages); GPT-Realtime-Whisper $0.017/min. Charts for Audio MultiChallenge and Big Bench Audio referenced but no numbers in text.

### S8. OpenAI community — gpt-realtime-2.1 and 2.1-mini (2026-07-06)
URL: https://community.openai.com/t/new-realtime-models-on-the-api-gpt-realtime-2-1-and-gpt-realtime-2-1-mini/1385896
- "improved alphanumeric recognition, silence and noise handling, and interruption behavior"; "p95 latency by at least 25% across Realtime voice models through improved caching"; configurable reasoning effort; pricing table as in S3. Users note same knowledge cutoff (2024-09-30) as 2.
- (The developers.openai.com changelog (S20) lists these entries as "May 7" / "Jul 6" — the community posts and pricing page date them 2026.)

### S9 / S10. Model cards gpt-realtime-2.1 and gpt-realtime-2
URLs: https://developers.openai.com/api/docs/models/gpt-realtime-2.1 , https://developers.openai.com/api/docs/models/gpt-realtime-2
- "128,000 context window", "32,000 max output tokens", cutoff "Sep 30, 2024"; inputs text/audio/image, outputs text/audio; function_calling, prompt_caching, reasoning tokens.
- Rate limits: Tier 1 200 RPM / 40K TPM; Tier 2 400 / 200K; Tier 3 5,000 / 800K; Tier 4 10,000 / 4M; Tier 5 20,000 / 15M.

### S11. OpenAI docs — Webhooks and server-side controls (sideband)
URL: https://developers.openai.com/api/docs/guides/realtime-server-controls
- WebRTC: the SDP fetch response "will contain a `Location` header that has a unique call ID that can be used on the server to establish a WebSocket connection to that same Realtime session" -> `wss://api.openai.com/v1/realtime?call_id=rtc_xxxxx`.
- SIP: webhook `realtime.call.incoming` carries `call_id`; same WS endpoint.
- "The server connection can be used to monitor the session, update instructions, and respond to tool calls."

### S12. OpenAI docs — Voice activity detection
URL: https://developers.openai.com/api/docs/guides/realtime-vad
- `server_vad`: `threshold` 0–1 ("A higher threshold will require louder audio to activate"), `prefix_padding_ms`, `silence_duration_ms`; example 0.5 / 300 / 500.
- `semantic_vad`: `eagerness` `low | medium | high | auto` (auto = medium); low "let the user take their time to speak", high "chunk the audio as soon as possible".
- `create_response` / `interrupt_response` only in conversation mode.

### S13. OpenAI cookbook — Context summarization with Realtime API
URL: https://developers.openai.com/cookbook/examples/context_summarization_with_realtime_api
- "a 32k-token context window" but degrade earlier; demo `SUMMARY_TRIGGER = 2_000`, production "20,000–32,000 tokens"; keep last 2 turns verbatim.
- Summary injected as `conversation.item.create` with `"role": "system"` and `input_text` (a system item, not assistant, so the model does not "switch from audio responses to text responses"); old items removed with `conversation.item.delete`.
- Audio "≈ 10 × more tokens" than equivalent text.

### S14. OpenAI cookbook — Realtime prompting guide
URL: https://developers.openai.com/cookbook/examples/realtime_prompting_guide
- "Use clear, labeled sections in your system prompt": Role & Objective, Personality & Tone, Context, Reference Pronunciations, Tools, Instructions/Rules, Conversation Flow, Safety & Escalation. "The model strongly closely follows sample phrases."

### S15. OpenAI Agents SDK — Realtime agents guide
URL: https://openai.github.io/openai-agents-python/realtime/guide/
- Tools execute "asynchronously by default" (`async_tool_calls`); `tool_approval_required` pauses until approve/reject.
- On interruption the session emits `audio_interrupted` and "updates history to keep the server-side conversation aligned with what users actually heard"; `RealtimePlaybackTracker` truncates "at the actual playback position rather than assuming all generated audio has already been heard" (needed when the speaker is remote/has buffering — i.e., a robot).
- `session.send_message()` injects text/structured items and starts a response; `realtime_handoff()` swaps agent = `session.update` with new instructions/tools; guardrails run on accumulated text/transcript deltas, and a tripped audio guardrail interrupts and sends a recovery message.

### S16. OpenAI reference app — openai-realtime-agents (Chat-Supervisor & Sequential Handoff)
URL: https://github.com/openai/openai-realtime-agents
- Chat-Supervisor: the realtime model answers immediately; for tool/complex work it says "Let me think" / "give me a moment to check on that" and forwards to a text supervisor (gpt-4.1); "~2s between the end of 'give me a moment to check on that.' being spoken aloud and the start of the response". Trade-off: "More assistant responses will start with 'Let me think'". realtime-mini + gpt-4.1 "should be cheaper than using the full 4o-realtime model".
- Sequential handoffs: "A handoff triggers a session.update event with new instructions and tools."

### S17. Latent Space — "OpenAI Realtime API: The Missing Manual" (Dec 2024, Pipecat/Daily authors)
URL: https://www.latent.space/p/realtime-api
- Target "800ms voice-to-voice latency"; ~500 ms time-to-first-byte from US clients; ~300 ms budget left for endpointing.
- At that time: 128k context, 15-min session cap, ~800 audio tokens/min; VAD `silence_duration_ms` default 500 ms (don't go lower except demos; 800 ms–1 s for reflective tasks); "VAD is still sometimes buggy".
- Audio 16-bit 24 kHz = 384 kbps (~500 kbps base64; 300–400 kbps with permessage-deflate). Tools must be flattened (`type`, `name`, `description`, `parameters` at top level). 9 client / 28 server events; minimal client "75 lines".
- Interrupt: send `conversation.item.truncate` so server context matches what was heard. Input transcription lags and "does not always match what the model hears". For > 15 min, save transcript and reload as initial message in a new session.

### S18 / S19 / S20. OpenAI docs — WebRTC guide, Realtime overview, changelog
URLs: https://developers.openai.com/api/docs/guides/realtime-webrtc , https://developers.openai.com/api/docs/guides/realtime , https://developers.openai.com/api/docs/changelog
- WebRTC: ephemeral key or unified SDP flow; data channel carries all JSON events; audio handled by the peer connection.
- Transport rule of thumb: WebRTC "for browser and mobile clients that capture or play audio directly"; WebSocket "when your server already receives raw audio from a media pipeline, call system, or worker"; SIP for telephony.
- Changelog: Realtime API launched 2024-10-01 (WebSockets); GA 2025-08-28; SIP IP ranges 2025-01-13; remote MCP in Responses API 2025-05-20.

---

## 2. Gemini Live API — mechanisms

### S21. Gemini API pricing
URL: https://ai.google.dev/gemini-api/docs/pricing
- Gemini 2.5 Flash Native Audio (Live): input $0.50 text, $3.00 audio/video; output $2.00 text, $12.00 audio; free tier available.
- Gemini 3.1 Flash Live Preview: input $0.75 text, "$3.00 or $0.005/min" audio, "$1.00 or $0.002/min" image/video; output $4.50 text, "$12.00 or $0.018/min" audio.
- Gemini 3.5 Live Translate $3.50 in / $21.00 out per 1M ($0.0053 / $0.0315 per min); 3.5 Transcribe Live $3.50 / $21.00.

### S22. Gemini API tokens
URL: https://ai.google.dev/gemini-api/docs/tokens
- Audio "32 tokens per second"; video "263 tokens per second"; images <= 384 px = 258 tokens, else 768x768 tiles of 258.

### S23. Gemini Live API overview
URL: https://ai.google.dev/gemini-api/docs/live
- "Stateful WebSocket connection (WSS)"; input "raw 16-bit PCM audio, 16kHz, little-endian", output 24 kHz; "Users can interrupt the model at any time"; function calling + Google Search; transcripts of both sides; 70 languages.

### S24. Gemini Live — Tool use
URL: https://ai.google.dev/gemini-api/docs/live-tools
- Client must answer with `session.send_tool_response` (no automatic execution).
- "Function calling executes sequentially by default, meaning execution pauses until the results of each function call are available."
- Async: add `behavior: "NON_BLOCKING"` to the function; the tool response carries `scheduling` = `INTERRUPT` ("Interrupt what it's doing and tell you about the response it got right away"), `WHEN_IDLE` ("Wait until it's finished with what it's currently doing"), or `SILENT` ("do nothing and use that knowledge later on in the discussion").
- Code execution and Google Maps "Not supported" on 3.1 Flash Live and 2.5 Flash Live.

### S25. Gemini Live — Session management
URL: https://ai.google.dev/gemini-api/docs/live-session
- Audio-only session "limited to 15 minutes"; audio+video "limited to 2 minutes"; extendable via context-window compression (sliding window; configurable trigger token count).
- "The lifetime of a connection is limited as well, to around 10 minutes." Session resumption handles (SessionResumptionUpdate) valid 2 h after termination. `GoAway` message with `timeLeft`; generation-complete signal.

### S26. Gemini Live — Capabilities guide
URL: https://ai.google.dev/gemini-api/docs/live-guide
- Automatic activity detection: `start_of_speech_sensitivity`, `end_of_speech_sensitivity`, `prefix_padding_ms`, `silenceDurationMs`; recommends 500–800 ms silence ("too low" splits utterances).
- Interruption: server message with `interrupted` flag; "you should stop playing audio and clear queued playback here" (client-side flush).
- Mid-session context: on Gemini 3.1 Flash Live `send_client_content` only for initial context (`initial_history_in_client_content: true`); afterwards inject text with `send_realtime_input`. On 2.5 Flash Live `send_client_content` with `turn_complete` works throughout.
- Proactive audio (2.5): model declines to answer irrelevant audio. Affective dialog (2.5). Thinking: `thinkingLevel` (3.1) / `thinkingBudget` (2.5).

### S27. Gemini API changelog (Live entries)
URL: https://ai.google.dev/gemini-api/docs/changelog
- 2025-04-09: asynchronous function calls in Live API; "Configurable Interruption Handling"; "Context window compression with a sliding window mechanism".
- 2025-09-23: `gemini-2.5-flash-native-audio-preview-09-2025` "with improved function calling and speech cut off handling". 2025-12-12: `...-12-2025`. 2026-03-26: `gemini-3.1-flash-live-preview`, "audio-to-audio (A2A)".

### S28 / S29. Gemini model cards
URLs: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview , https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025
- 3.1 Flash Live: input 131,072 / output 65,536 tokens; inputs text/images/audio/video, outputs text+audio; function calling and search grounding supported; code execution, URL context, file search, caching not supported; updated March 2026.
- 2.5 native audio 12-2025: 131,072 / 8,192; thinking supported; knowledge cutoff January 2025.

### S30. Google AI developer forum — "Live API latency spikes"
URL: https://discuss.ai.google.dev/t/live-api-latency-spikes/106814
- User (2025-10-03, `gemini-live-2.5-flash-preview`, 8 kHz PCM): "7-15 seconds to first token" spikes, transcription up to 30 s late. Google reply (2025-11-25): low `end_of_speech_sensitivity` + 8 kHz audio made noise keep the turn open until ~30 s server timeout; fix = `end_of_speech_sensitivity` HIGH, `silence_duration_ms` 1000, drop `media_resolution`.
- Lesson: hosted VAD misconfiguration, not model latency, produced multi-second stalls — the robot must own endpointing.

---

## 3. Measured behaviour of hosted duplex models (benchmarks)

### S48. Full-Duplex-Bench v1.5 (arXiv 2507.23159, overlap behaviour; v. Apr 2026)
URL: https://arxiv.org/html/2507.23159
- Systems: Freeze-Omni, Moshi, Gemini 2.0 Flash Live, Amazon Nova Sonic, GPT-4o Realtime.
- User interruption: respond rate 0.72 / 0.50 / 0.33 / 0.24 / 0.78; stop latency 1.42 / 1.16 / 2.20 / 2.25 / 0.23 s; response latency 1.35 / 1.47 / 2.62 / 2.75 / 1.50 s.
- Backchannel: resume rate 0.80 / 0.06 / 0.93 / 0.98 / 0.70; stop latency 0.66 / 0.42 / 0.66 / 0.64 / 0.21 s.
- Talking to others: resume rate 0.25 / 0.19 / 0.99 / 0.90 / 0.02 (GPT-4o Realtime stops in 0.18 s but almost never resumes). Background speech: resume 0.25 / 0.07 / 0.30 / 0.98 / 0.04.
- Take-away: OpenAI's barge-in stop is ~0.2 s, but it treats every overlap as an interruption (does not resume after backchannels/side talk); Gemini 2.0 resumed well but stopped slowly (2.2 s).

### S49. Full-Duplex-Bench-v3 (arXiv 2604.04847, 2026-04-06; naturalistic speech + multi-step tool use)
URL: https://arxiv.org/html/2604.04847
- Systems: gpt-realtime-1.5, gemini-2.5-flash-native-audio-preview-12-2025, gemini-3.1-flash-live-preview, Grok, Ultravox v0.7, Cascaded Whisper->GPT-4o->TTS. 100 real human recordings, 4 domains, 21 self-correction (mid-utterance intent change) cases. Mock APIs are "deterministic, zero-latency" — so latencies below are pure model behaviour.
- Latency definitions: base "Δt = t_agent_start − t_user_end; if Δt<0, the event is an Interruption"; First Response Latency ("Time until any speech, including filler sentences"), Tool Call Latency ("Time until the first API invocation"), Task Completion Latency ("Time until the agent delivers the factual answer").
- Table 2: GPT-Realtime pass@1 0.600, tool F1 0.876, arg acc 0.680, response quality 0.792, latency 6.89 s; Gemini 3.1: 0.540 / 0.817 / 0.588 / 0.718 / 4.25 s; Gemini 2.5: 0.490 / 0.786 / 0.593 / 0.554 / 7.26 s; Grok 0.430 / 6.65 s; Ultravox 0.410 / 8.40 s; Cascaded 0.450 / 10.12 s.
- Turn-taking: take-turn / interrupt / filler = GPT-Realtime 96.0 % / 13.5 % / 16.9 %; Gemini 2.5 92.0 / 14.1 / 8.9; Gemini 3.1 78.0 / 19.2 / 31.7; Grok 94.0 / 25.5 / 44.3; Ultravox 96.0 / 47.9 / 88.0; Cascaded 100 / 33.0 / 26.9.
- Gemini 3.1 "silent worker": no speech in 22 % of scenarios despite correct tool calls. Self-correction pass@1: GPT-Realtime 0.588, Gemini 2.5 0.471, Gemini 3.1 0.353, Cascaded 0.176.

### S50. DuplexSLA-Bench (arXiv 2605.20755, May 2026; in-conversation tool calling)
URL: https://arxiv.org/html/2605.20755
- 2,100 cases: 1,200 turn-taking (normal/pause/interrupt/backchannel x 300) + 900 tool-call (single/multi/backchannel-action x 300). Correct tool call = same function name, matching args, trigger "not earlier than the ground-truth offset by more than 1.0 s, and not later than the end of the audio by more than 3.0 s".
- Table 5 (tool calls): ASR+LLM cascade 91.33 % avg acc / 2.77 s delay (single 89.33 % / 2.33 s; multi 89.33 % / 4.71 s; backchannel-action 95.33 % / 1.27 s); DuplexSLA ("7B speech-LM, initialized from Step-Audio 2 mini") 85.56 % / 0.64 s.
- Table 7 (turn-taking, no prefill): DuplexSLA 94.34 % / 0.30 s; Freeze-Omni 10.67 % / 0.36 s; PersonaPlex 22.34 % / 0.47 s; MiniCPM-o 82.00 % / 0.61 s; Gemini-3.1-flash-live 93.17 % / 1.17 s; GPT-Realtime-1.5 semantic-vad-high 96.50 % / 1.57 s; GPT-Realtime-1.5 server-vad-40ms 85.50 % / 0.83 s (pause acc drops to 79.70 %).
- Take-away: hosted models buy turn accuracy with ~1–1.6 s of endpointing delay; a 40 ms server VAD cuts that to 0.83 s but mis-fires on pauses (79.7 %).

### S47. Full-Duplex-Bench v1.0 (arXiv 2503.04721; Mar 2025, rev. Aug 2025)
URL: https://arxiv.org/html/2503.04721 (abstract: https://arxiv.org/abs/2503.04721)
- Table III: Moshi pause-handling TOR 0.985, backchannel TOR 0.980, smooth turn-taking TOR 1.000 / latency 0.265 s, interruption TOR 1.000 / 0.257 s; Gemini Live TOR 0.255 / 0.310 / 0.091, turn-taking latency 0.655 s, interruption 1.183 s; Freeze-Omni interruption 1.409 s; dGSLM 2.531 s.
- Commercial models "handle pauses more effectively", end-to-end open models "respond faster but interrupt more frequently".

### S51. tau-voice (arXiv 2603.13686, 2026-03-14)
URL: https://arxiv.org/abs/2603.13686
- 278 grounded multi-turn tasks with policies + environment interaction. "GPT-5 (reasoning) achieves 85%, voice agents reach only 31–51% under clean conditions and 26–38% under realistic conditions with noise and diverse accents–retaining only 30–45% of text capability"; "79–90% of failures stem from agent behavior".

### S52. FD-Bench (arXiv 2507.19040, Interspeech 2025)
URL: https://arxiv.org/abs/2507.19040
- Moshi, Freeze-omni, VITA-1.5; 40 h generated speech, 293 conversations, 1,200 interruptions; all three fail "to respond to user interruptions" under frequent disruption and noise.

### S53. Openbenchmarks — voice agent latency (phone-call TTFAB, 2026-08-01)
URL: https://openbenchmarks.com/voice-agent-latency
- Telephony platforms p50 / p95: Telnyx 1,296 / 1,856 ms; ElevenLabs 1,424 / 1,768; Bland 1,520 / 2,248; Vapi 1,558 / 2,008; Retell 1,740 / 2,259 (108 calls x 4 turns each). OpenAI Realtime and Gemini Live explicitly NOT measured: they "answer a socket, not a phone".

### S54. `[secondary]` vadimall.com — OpenAI Realtime vs Gemini Live vs Pipecat (June 2026)
URL: https://vadimall.com/posts/openai-realtime-vs-gemini-live-vs-pipecat-voice-ai-typescript
- 20 reservation conversations, wired, Tel Aviv; median end-of-user-speech -> first audio byte: OpenAI Realtime ~410 ms, Gemini Live ~380 ms, Pipecat-JS ~440 ms. Interruption: OpenAI "free" via WebRTC (~0 lines), Gemini needs manual buffer flush on `interrupted` (~40 lines). Tool calls: OpenAI `response.function_call_arguments.done` on the data channel; Gemini `sendToolResponse()`.

### S55. `[secondary, low trust]` autointerviewai.com Gemini Live review (2026-08-19)
URL: https://www.autointerviewai.com/blog/google-gemini-live-voice-to-voice-review-2026
- Claims Gemini 2.0 Flash Live model latency 100–200 ms, OpenAI Realtime 250 ms model latency / 470 ms total from India, cascade 1,150 ms; ~$0.05/min vs ~$0.08/min. Vendor-adjacent, no methodology; not used for any load-bearing claim.

---

## 4. Published robot integrations

### S31 / S32. WSO2 — Unitree Go2 EDU voice agent with OpenAI Realtime API
URLs: https://wso2.com/library/blogs/how-we-gave-life-to-an-ai-agent-with-unitree-go2-robot/ , https://github.com/wso2-incubator/unitree-go2-realtime-agent
- Runs on the Go2's "NVIDIA Jetson Orin NX with 100 TOPS"; built in "three weeks".
- Tools exposed to the Realtime model: product-info (fuzzy match over markdown), conference speakers/agenda (OAuth2 API), "Robot Controller Toolset: dance, go forward, turn right, stretch, sit, etc.", "Take Photo Tool" (sit -> capture -> upload -> stand).
- "The Python SDK for the robot wasn't concurrency-safe" -> "lightweight Flask service that wrapped the SDK"; `POST /action/dance` acquires a lock and executes SDK commands sequentially.
- Audio: "The Go2's onboard speaker and microphone were incredibly noisy" -> Jabra Speak 710 + wireless mic on a 3D-printed mount; only two USB-C + one USB-A.
- Repo: Apache 2.0, Python 3.11.9, unitree_sdk2 python + cyclonedds, portaudio/ffmpeg; test mode runs off-robot. No latency numbers published.

### S33. HackMD — Configuring Unitree Go2 EDU for real-time voice with OpenAI (cascaded, ~2024)
URL: https://hackmd.io/@c12hQ00ySVi6JYIERU7bCg/ByAOr12qJg
- Cascade (SpeechRecognition/Whisper -> ChatGPT -> pyttsx3/gTTS) targeting "~3 seconds" speech-in to voice-out; "The Go2's internal speaker isn't directly accessible through their SDK"; BenBen assistant is a closed loop to Unitree servers.

### S34. Mamezou — Controlling robots with OpenAI Realtime API's WebRTC + ROS 2 (2024-12-30)
URL: https://developer.mamezou-tech.com/en/robotics/ai/voice-operation/
- Industrial cleaning robot (Pico-ITX SBC, ROS 2); browser WebRTC client; tools map to ROS 2 topics/services via rosbridge_websocket + roslibjs (e.g. `start_cleaning` with TurnLeft/TurnRight).
- Pain points then: "RPD (Requests per Day) limit for the Realtime API is 100"; "maximum duration of a Realtime session is 30 minutes"; "conversation history up to that point is lost" on reconnect; "simple arithmetic seems difficult" for the model.

### S35. `by_your_command` — ROS 2 voice command processor (OpenAI Realtime + Gemini Live)
URL: https://github.com/pondersome/by_your_command
- Pipeline "Microphone → audio_capturer → echo_suppressor → /audio_filtered → silero_vad → /prompt_voice → ROS Bridge → WebSocket → Agent"; OpenAI 24 kHz resampled to 16 kHz for ROS; Gemini 16 kHz in / 24 kHz out.
- Interruption = `response.cancel` + `conversation.item.truncate` + `/interruption_signal` to the player (PyAudio `abort()`).
- Measured: "Voice Detection: < 50ms latency (Silero VAD)", "Response Generation: 1-2 seconds for voice response", "Audio Playback: < 100ms from API to speakers".
- Commands parsed from model output with `@` compound syntax (`tenhut@rightish`); arm presets + behaviours stop/follow/track/sleep/wake/move/turn. Session cycling + `ConversationContext` to carry history across sessions; `PauseDetector`. Apache 2.0; "not ready for production use".

### S36. Frank Fu — voice-controlled ES02 robot on RDK X5 via OpenAI Realtime (2025-06-18)
URL: https://frankfu.blog/openai/the-detailed-development-of-a-real-time-robot-control-system-based-on-the-openai-realtime-api/
- WebSocket client on RDK X5 (< $100 hardware); function calls -> `advance / rotate / leg_length` -> SBUS over `/dev/ttyS1` at 100,000 bps; a 100 ms watchdog resets channels to 1000 so a stale command cannot keep the robot moving.

### S37 / S38. Pollen Robotics Reachy Mini conversation app (Gemini Live default, OpenAI Realtime alternative; Google AI post 2026-04-13)
URLs: https://github.com/pollen-robotics/reachy_mini_conversation_app , https://dev.to/googleai/build-a-talking-robot-with-gemini-live-and-reachy-mini-20e2
- Layers: mic -> fastrtc (WebRTC I/O) -> LLM handler (Gemini 3.1 Flash Live default or OpenAI, `MODEL_NAME`) -> tool dispatch -> MovementManager (60 Hz loop) -> robot. "tool calls run in background tasks so the audio stream isn't blocked"; result "sent back to the LLM so it can narrate what happened".
- Motion is layered: "queues primary moves (dances, emotions, goto poses, breathing) while blending speech-reactive wobble". Camera: "1 FPS video loop" of JPEG frames to Gemini. Tools: dance, stop_dance, play_emotion, stop_emotion, camera, move_head, head_tracking, go_to_sleep, sweep_look, remember, forget + MCP search_web/get_weather/get_time. Apache 2.0.
- Quoted rationale: "the moment you make an LLM tool call synchronous, latency kills the UX".

---

## 5. Open / self-hostable alternatives

### S39 / S40 / S41. Kyutai Moshi
URLs: https://arxiv.org/abs/2410.00037 , https://arxiv.org/html/2410.00037v2 , https://github.com/kyutai-labs/moshi
- 7B Helium temporal transformer (32 layers, d=4096) + 6-layer depth transformer; Mimi codec 24 kHz -> 12.5 Hz, 1.1 kbps, 8 quantisers, 80 ms frame; "theoretical latency of 160ms (80ms for the frame size of Mimi + 80ms of acoustic delay)", "as low as 200ms on an L4 GPU".
- Training: 7M h unsupervised audio, Fisher 2,000 h, > 20k h synthetic dialog; text 2.1T tokens.
- Two parallel audio streams (user/system) + inner-monologue text stream; no turn boundaries.
- Deploy: PyTorch bf16 needs "24GB" GPU; MLX int4/int8; Rust/Candle int8/bf16. Code MIT (Python) / Apache 2.0 (Rust); weights CC-BY 4.0. No tool/function calling.

### S44 / S45 / S46. NVIDIA PersonaPlex-7B-v1 (2026-01-14/15)
URLs: https://github.com/NVIDIA/personaplex , https://arxiv.org/html/2602.06053 , https://huggingface.co/nvidia/personaplex-7b-v1
- Moshi weights fine-tuned "in 6 hours on 8xA100" (24,576 steps, batch 32) on "1840 hours of customer service dialog interactions across 105,410 dialogs, and 410 hours of general Question-Answering dialogs across 39,322 dialogs"; text role prompt + voice-embedding conditioning.
- Full-Duplex-Bench: user-interruption latency 0.070 s (paper Table 2) / 0.240 s (HF card), smooth turn-taking latency 0.170 s; pause TOR 0.584 (synthetic) / 0.662 (Candor), backchannel TOR 0.327 (vs Moshi 0.985 / 0.980 / 1.000); Service-Duplex-Bench GPT-4o score 4.48 vs Moshi 1.75.
- Tested on A100 80 GB; Ampere/Hopper supported; `--cpu-offload`. Code MIT; weights NVIDIA Open Model License (+ CC-BY-4.0 note). No tool calling. (DuplexSLA-Bench measures it at 22.34 % turn-taking accuracy without prefill — S50.)

### S42 / S43. Kyutai Unmute + Delayed Streams Modeling (STT/TTS)
URLs: https://github.com/kyutai-labs/unmute , https://github.com/kyutai-labs/delayed-streams-modeling
- Unmute = STT -> LLM (vLLM) -> TTS over a WebSocket "protocol based on OpenAI's Realtime API"; "TTS latency decreases from ~750ms when running everything on a single L40S GPU to around ~450ms" with 3 GPUs; response "below a second"; minimum 16 GB VRAM (Gemma 3 1B); tool calling "a common requirement" but "not fully integrated yet" (do it in a FastAPI wrapper around vLLM). MIT.
- STT `kyutai/stt-1b-en_fr`: ~1B params, "a 0.5 second delay", semantic VAD; `kyutai/stt-2.6b-en`: "a 2.5 second delay"; "a H100 can process 400 streams in real-time"; L40S Rust server "64 simultaneous connections at a real-time factor of 3x". Weights CC-BY 4.0.

---

## 6. Cross-cutting engineering patterns (what the sources agree on)

1. **Two channels, one session.** OpenAI's sideband (`?call_id=`) and the Agents SDK let the audio endpoint (robot mic/speaker over WebRTC or a WebSocket fed by the robot's audio pipeline) be separate from the process that owns tools, instructions and context injection. Gemini has no sideband; the single WebSocket client must do both.
2. **Context injection is text, not audio.** OpenAI: `conversation.item.create` (`system`/`user` text items), `session.update.instructions`, per-response `instructions`, and out-of-band `response.create` with `conversation:"none"` + `input`/`metadata`. Gemini: `send_realtime_input(text=...)` (3.1) or `send_client_content(turn_complete=False)` (2.5). Audio costs ~10x text tokens (S13) and the full history is re-read per response (cached at 1/80th price only if the prefix is untouched — S4).
3. **Long-running tools must be asynchronous.** OpenAI GA async function calling with placeholder utterances (S5); Agents SDK `async_tool_calls` default (S15); Gemini `NON_BLOCKING` + `scheduling INTERRUPT|WHEN_IDLE|SILENT` (S24); Reachy Mini and chat-supervisor both narrate a filler first and finish later (S16, S38). The chat-supervisor pattern measured "~2s" from filler to answer even with a fast text model.
4. **Barge-in is cheap on the wire, expensive in semantics.** OpenAI stops output in ~0.2 s (S48) but classifies backchannels and side-talk as interruptions (resume rate 0.02–0.70); Gemini resumes well but stops in ~2 s (2.0 Flash) and needs client-side flushing (S26, S54). Both expose `interrupt_response`/`create_response`-style switches so the client can keep VAD but decide itself.
5. **Endpointing dominates turn latency.** DuplexSLA-Bench: 0.83 s (40 ms server VAD) to 1.57 s (semantic VAD high) for GPT-Realtime-1.5, 1.17 s for Gemini 3.1 (S50); silence_duration 500–800 ms recommended by both vendors (S12, S17, S26); a mis-set Gemini VAD produced 7–15 s stalls (S30). Local VAD (Silero < 50 ms, S35) plus push-to-talk-style commits is the robust path.
6. **Sessions are finite.** OpenAI 60 min (S2/S5); Gemini 15 min audio / ~10 min connection with resumption handles (S25); older deployments hit a 100 RPD cap and 15–30 min sessions (S17, S34). Every robot integration implements session cycling with a text summary carried forward (S13, S35).
7. **Tool-use accuracy of hosted duplex models is ~0.6 pass@1 even with zero-latency tools** (S49), argument accuracy 0.59–0.68, and 22 % silent completions on Gemini 3.1; tau-voice shows voice agents retain only 30–45 % of text-model task capability under realistic acoustics (S51). Deterministic validation of every proposal is mandatory.
8. **Robot-side facts repeat across integrations:** the vendor SDK is not concurrency-safe -> one lock-holding motion server (S31); onboard mic/speaker unusable -> external audio (S31, S33); a watchdog resets motion if the voice link stalls (S36); motion runs on its own 60 Hz loop and only *queues* moves from tool calls (S38).

---

## 7. What this means for Parcel's Model A / Model B

**Model A (local, duplex, 10 Hz, trainable) must never wait on the hosted voice.** Every measured hosted number — 0.4 s best-case first audio (S54), 0.8–1.6 s turn-taking delay (S50), 1.5–2.6 s response latency under overlap (S48), 4–7 s task-completion latency for a tool chain even with zero-latency tools (S49), "~2 s" chat-supervisor gap (S16) — is 4–70 frames of Parcel's 10 Hz clock. The hosted model is a *narrator and intent source*, not a controller; Model A's act-token stream and global-plan queue are the only things allowed to move the dog.

**Model B's "steerable injection" has a direct API analogue in both vendors — use it rather than inventing one.**
- Owner command -> hosted model emits a *proposal* tool call (`navigate`, `amend_goal`, `queue_goal`) that Parcel's deterministic broker already validates; Model B then decides revise / keep / queue against the historical plan queue. Treat the hosted call as advisory: pass@1 0.60, arg accuracy 0.68 (S49).
- Return the tool result *asynchronously* (OpenAI GA async function calling, S5; Gemini `NON_BLOCKING`, S24) so the voice says "Sure, I'll check the sofa" immediately and Model A starts moving in the same frame. Completion is a second event: OpenAI `function_call_output` + `response.create` (or out-of-band `response.create` with `conversation:"none"`, `input:[state item]`, `metadata:{event:"goal_done"}`) -> "Done! Should I go back to the door?"; Gemini `scheduling: INTERRUPT` for arrivals/blocked, `WHEN_IDLE` for progress, `SILENT` for routine StateDigest updates (S24 gives exactly these three semantics).
- The existing whisperer StateDigest should be sent as small *text* items (`role:"system"` per S13) at a low, event-driven rate; never as audio, never by editing earlier items (cache-bust, S4). Keep the instruction block + tool schemas well under the 16,384-token cap seen on gpt-realtime (S5) and budget the 128k window of gpt-realtime-2.x (S9) at ~1,800 audio tokens/min of conversation (S4).

**Barge-in should be split into a fast reflex and a slow decision.** The wire-level interruption (`input_audio_buffer.speech_started` / Gemini `interrupted`) arrives ~0.2 s after the owner starts talking (S48); Model B should map it to a *soft* Model A signal (slow, hold heading, keep plan) rather than a stop, because 30–98 % of overlaps are backchannels or side-talk that the hosted model cannot yet classify (S48). The hard decision (revise / keep / queue) waits for the validated tool call 0.8–1.6 s later (S50). Use `interrupt_response:false` + `create_response:false` (S2, S12) so Parcel, not the vendor VAD, decides when a response starts — the vendor VAD mis-setting that produced 7–15 s stalls (S30) is exactly the failure a companion cannot afford.

**Cost and session budget for an "always listening" dog.** Input audio is billed whether or not the model answers: $0.0192/min (gpt-realtime-2.x) or $0.005/min (Gemini 3.1 Live) just to listen, before context re-reads and speech output at $0.0768/min or $0.018/min (S3, S4, S21, S22). Streaming 8 h/day to OpenAI is ~$9/day for listening alone; Gemini ~$2.4. The XVF3800 array + local Silero/Kyutai VAD (< 50 ms, S35; 0.5 s semantic STT delay, S43) must gate what is streamed, and sessions must be cycled every 60 min (OpenAI) / 15 min (Gemini audio) with a text summary carried over (S13, S25, S35).

**Model B's narration representation should be a compact, timestamped text event stream** (what Model A is doing, what changed, what it needs), because that is the only thing any hosted model can ingest mid-turn cheaply; Full-Duplex-Bench-v3's "silent worker" result (22 % no speech on Gemini 3.1, S49) means Model B must be able to *force* narration via an out-of-band response with explicit `instructions` ("say one sentence confirming X") rather than assume the model will speak after a tool result.

**Local fallback for Starlink dropouts.** Moshi/PersonaPlex are 7B duplex models needing ~24 GB (bf16) and score 22 % turn-taking accuracy without prefill (S41, S50) with no tool calling; Unmute's STT->LLM->TTS cascade on 16 GB gives < 1 s and can host tools in the LLM wrapper (S42). On the Orin 64 GB the realistic offline voice is a cascade (Kyutai STT 1B, small text LLM, Kyutai TTS) that speaks the same Model B event stream — same narration contract, lower quality.

**Evaluation should adopt the benchmark vocabulary that already exists.** Instrument the sim-to-real rig to log, per turn: first-response latency, tool-call latency, task-completion latency, take-turn / interrupt / filler rates, self-correction pass@1 (S49), and tool-trigger legality within (−1.0 s, +3.0 s) of the ground-truth offset (S50); add tau-voice-style noise/accent conditions (S51) to the instruction-navigation matrix since voice agents lose 55–70 % of text capability there.

---

## 8. Open questions the sources do not answer

- No public measurement of OpenAI/Gemini *tool round-trip* latency from a robot on a Jetson over a satellite link; all measured numbers are wired/urban clients or zero-latency mocks.
- OpenAI's own "delivering low-latency voice AI at scale" post (openai.com/index/…) and the gpt-realtime / gpt-realtime-2 launch pages returned HTTP 403 and could not be read; official p50/p95 figures remain uncited.
- Whether gpt-realtime-2.x async function calling can return *multiple* deferred outputs for one call (progress -> done) or requires one output per call_id; whether Gemini `SILENT` results still count toward the 15-min audio budget.
- No source measures barge-in-to-*motion* latency on a real robot; every integration stops audio, none reports when the wheels/legs reacted.
- No source measures hosted-model behaviour when the robot's own speaker leaks into the mic array (echo) while moving; by_your_command uses an echo_suppressor node but gives no numbers.
- Current Realtime API per-tier concurrency/session limits beyond RPM/TPM (the 2024 "100 RPD" cap in S34 is clearly obsolete but no replacement figure was found).

## Not readable on 2026-08-29 (HTTP 403) — not cited
- https://openai.com/index/delivering-low-latency-voice-ai-at-scale/
- https://openai.com/index/introducing-gpt-realtime/
- https://openai.com/api/pricing/ (used developers.openai.com/api/docs/pricing instead)
- https://medium.com/wso2-ai-blog/how-we-gave-life-to-an-ai-agent-with-the-unitree-go-2-robot-f9c7afec0a77 (used wso2.com copy instead)
- https://hackernoon.com/openai-realtime-api-pricing-in-2026-real-world-data-from-4000-measured-sessions
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/overview (404)
