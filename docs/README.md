# Parcel documentation

Start with the engineering handbook. It is the current executive design,
implementation/quality audit, robotics textbook, tradeoff record, and roadmap for
this checkout. This index was reconciled on **2026-08-22** against committed
baseline `71b39a1` plus the visible in-flight perception/map/patrol worktree.
Specialist pages retain their original audit dates; a dated design or evidence
record does not become current merely because it is linked here.

| Doc | Authority | Role |
| --- | --- | --- |
| [CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) | **Living/current** | Canonical executive architecture, worktree-aware capability and quality snapshot, robotics foundations, tradeoffs, risks and delivery gates |
| [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | **Living decision record** | Crucial choices, advantages, limitations and evidence required to revisit them |
| [../backlog/](../backlog/) | **Operational queue** | Unverified claims, blocked work and ready repository cards; dated/closed material below its front door is history |
| [REDESIGN_2026_ASSESSMENT.md](REDESIGN_2026_ASSESSMENT.md) | **Dated rationale** | Why the 2026 redesign happened and what was adjudicated; later implementation facts defer to the handbook |
| [REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) | **Target design record** | Seven-layer portable target architecture; current wiring claims defer to the handbook |
| [archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md](archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md) | **Archived history** | Retired status matrix begun August 4 and amended through August 9; intentionally removed from the live current-status surface |

## Learning tracks

- [Parcel learning center](../edu/INTRO.md) — routes between the two curricula.
- [Robotics in 60 days](../edu/robotics-60-days/README.md) — mechanics,
  estimation, planning, control, safety, software, voice and learned robotics.
- [Physics in 60 days](../edu/physics-60-days/README.md) — the mechanics,
  electricity, sensing, waves, thermals and controls underneath the robot.

The curricula are complete, complementary teaching material. Their dated examples
may describe the local voice cascade that preceded the hosted production lane;
the handbook is the current product authority.

## Operations and product surfaces

| Doc | Role |
| --- | --- |
| [MOTION.md](MOTION.md) | Closed-loop `ControlManager` and Unitree Sport commissioning |
| [COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md) | Hierarchical companion navigation / instruction-following; specialist detail beneath the current handbook |
| [NAVIGATION_ALGORITHM_2026.md](NAVIGATION_ALGORITHM_2026.md) | **Current navigation research decision:** detailed algorithms, interfaces, controller/model placement, phases, and promotion gates |
| [NAVIGATION_CITY.md](NAVIGATION_CITY.md) | City navigation registry, `grid_v1` default, MetaUrban path |
| [DYNAMIC_CITY_AND_BEHAVIOR.md](DYNAMIC_CITY_AND_BEHAVIOR.md) | Living-city MuJoCo scene and social action policy |
| [EMBODIED_EXPRESSION.md](EMBODIED_EXPRESSION.md) | Simulator pose/gesture palette, reaction arbitration, and physical Unitree commissioning boundary |
| [DEVELOPMENT_STACK.md](DEVELOPMENT_STACK.md) | Explicit legacy/local voice + simulator profile; hosted Realtime is the production launcher default |
| [CI.md](CI.md) | **Versioned CI/eval runner definition:** commit/nightly tiers, hard regression gates, local commands, and self-test; hosted GitHub execution is not yet verified |
| [VOICE_AI_MODELS.md](VOICE_AI_MODELS.md) | STT/TTS/reasoner model choices and trust boundary |
| [VOICE_PROVIDER_ARCHITECTURE.md](VOICE_PROVIDER_ARCHITECTURE.md) | **Current voice-provider decision:** public benchmark/review evidence, normalized pricing, robot-specific scorecard, shortlist, and replaceable provider contracts |
| [AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md](AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md) | Latency metrics and owner-relative spatial commands |
| [ACOUSTIC_BRINGUP_PLAN.md](ACOUSTIC_BRINGUP_PLAN.md) | No-root audio bring-up, the Tier-1 virtual-rig acoustic baseline, the AEC ladder, and the owner runbook for everything transducer-gated |
| [IMPLEMENTATION_SKILLS_CITY_RL.md](IMPLEMENTATION_SKILLS_CITY_RL.md) | Skills catalog, city scene, `Dog` API |
| [DEPENDENCIES.md](DEPENDENCIES.md) | Host GPU / dependency inventory |
| [REASONER_GPU_PROFILE.md](REASONER_GPU_PROFILE.md) | Gemma / CUDA admission profiles |
| [GRID_UPDATE_PERFORMANCE.md](GRID_UPDATE_PERFORMANCE.md) | Occupancy-grid update microbenchmark |
| [RESEARCH_2026_ROADMAPS.md](RESEARCH_2026_ROADMAPS.md) | Research conclusions, implemented slices, and explicitly future work |
| [ATTENTION_STEERING_DESIGN.md](ATTENTION_STEERING_DESIGN.md) | Voice-steered attention design: audits, architecture, trainable-core staging, open decisions |
| [YIELD_POLICY.md](YIELD_POLICY.md) | Blocked-by-a-person yield policy: the first per-personality *numeric* temperament knob, its defaults, the truthfulness rules on what a yielding dog may say, and what it may never touch |
| [DUPLEX_DUAL_STREAM_DESIGN.md](DUPLEX_DUAL_STREAM_DESIGN.md) | Always-streaming dual-head duplex agent: frame contract, filler policy, D0→D2 staging |
| [INSTRUCTION_NAV_HILLCLIMB.md](INSTRUCTION_NAV_HILLCLIMB.md) | Language-grounded navigation hillclimb: layer plan, model shortlist (VLFM/NaVILA/SigLIP-2), experiment ladder, eval spec |
| [HARDWARE_PORTABILITY_AUDIT.md](HARDWARE_PORTABILITY_AUDIT.md) | How Go2-coupled the code is (~2% vendor code behind proven seams), the leak list, and the custom-hardware migration bill |
| [NAV_GENERALIZATION_AUDIT.md](NAV_GENERALIZATION_AUDIT.md) | How hardcoded the navigation stack is: ~43% config-exposed / ~56% baked / ~1% profile-derived, the 12 drift-capable constant families, and the 5-scenario stress test |
| [STRATA_GENERALIZATION_PLAN.md](STRATA_GENERALIZATION_PLAN.md) | Researched plan to fix the five hardcoded strata (pose seam, classical tracking, relation/vocab registries, authority triple) + the six-instrument robust eval program |
| [PAUSE_SEMANTICS.md](PAUSE_SEMANTICS.md) | Cross-channel pause, stop, resume, and time-freeze conventions |
| [RUNTIME_CONCURRENCY_AND_CLOCKS.md](RUNTIME_CONCURRENCY_AND_CLOCKS.md) | Process/thread ownership, queues, cancellation, clock domains, and real-time limitations |
| [GATEWAY_TTL_LATENCY_DERIVATION.md](GATEWAY_TTL_LATENCY_DERIVATION.md) | Frozen N24/RC-4 gateway TTL derivation evidence; retain as a pinned record rather than current physical commissioning proof |

## Reading rules

- When documents disagree, inspect current code/configuration and executable
  tests first, then the worktree-aware audit in
  [CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md),
  then dated specialist designs, historical snapshots and decision records. Roadmaps describe direction
  and never override runtime evidence.
- **Implemented** means code exists. **Wired** means a normal entry point reaches
  it. **Verified** names a repeatable test or measurement. **Operational** means
  the required service/device is available in the audited environment.
  **Commissioned** is reserved for evidence from the intended physical device
  and environment; **experimental** and **planned** paths are not admitted
  product capabilities.
- A roadmap is not an implementation claim. Look for its implementation-status
  note, then confirm against current code/executable evidence and the handbook.
- The archived legacy matrix is historical evidence only. New operational changes
  update the handbook's quality/capability snapshot, not the archive.
- A simulator success is not physical hardware evidence.
- A BARN/Habitat result is an external proxy, not a companion-product score.
- Paths and commands are relative to the repository root unless stated
  otherwise.

## Historical link-health note

Completed `scrum/` folders are immutable evidence. One 2026-08-13 session plan
links to a `RESEARCH_FINDINGS.md` artifact that never entered Git, and several
historical agent transcripts use expired UI-only UUID handles or source-line
anchors. They are preserved rather than silently rewritten. Live/canonical docs
have no known missing local file target after this reconciliation.

## Eval entry points (outside `docs/`)

- Product-facing companion scenarios and ledger:
  [evals/companion_nav/results/README.md](../evals/companion_nav/results/README.md)
- Offline BARN / Habitat research proxies:
  [evals/external/README.md](../evals/external/README.md)
- Frozen PlanIR gates:
  [evals/companion/planner_quality_v2/README.md](../evals/companion/planner_quality_v2/README.md)
- Duplex D0 scripted-turn gate:
  [evals/companion/duplex_v1/README.md](../evals/companion/duplex_v1/README.md)
- Tier-1 acoustic gate (virtual PipeWire rig; no hardware, no root):
  [evals/companion/acoustic_loop_v1/README.md](../evals/companion/acoustic_loop_v1/README.md)
  — measures audio, not decisions about audio. Reports carry
  `does_not_prove`: no room, no transducer, no echo, and therefore no AEC
  claim of any kind.
