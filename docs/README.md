# Parcel documentation

Start with the status and decision records. They distinguish what is working in
this checkout from target architecture and research proposals. This index was
last audited against the repository worktree on **2026-08-04**.

| Doc | Role |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | **Operational source of truth:** implemented vs wired vs verified, current blockers, and inert configuration surface |
| [../backlog/](../backlog/) | **The work queue that drains it:** unverified claims, blocked work, and what to pick up next |
| [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | Crucial choices, advantages, limitations, and evidence required to revisit them |
| [REDESIGN_2026_ASSESSMENT.md](REDESIGN_2026_ASSESSMENT.md) | Why the 2026 redesign happened and what was adjudicated |
| [REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) | Seven-layer portable architecture and what is wired today |

## Operations and product surfaces

| Doc | Role |
| --- | --- |
| [MOTION.md](MOTION.md) | Closed-loop `ControlManager` and Unitree Sport commissioning |
| [COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md) | Hierarchical companion navigation / instruction-following |
| [NAVIGATION_CITY.md](NAVIGATION_CITY.md) | City navigation registry, `grid_v1` default, MetaUrban path |
| [DYNAMIC_CITY_AND_BEHAVIOR.md](DYNAMIC_CITY_AND_BEHAVIOR.md) | Living-city MuJoCo scene and social action policy |
| [DEVELOPMENT_STACK.md](DEVELOPMENT_STACK.md) | Local voice + sim development profile |
| [VOICE_AI_MODELS.md](VOICE_AI_MODELS.md) | STT/TTS/reasoner model choices and trust boundary |
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

## Reading rules

- When documents disagree, inspect current code/configuration and executable
  tests first, then [CURRENT_STATUS.md](CURRENT_STATUS.md), then decision
  records. Roadmaps describe direction and never override runtime evidence.
- **Implemented** means code exists. **Wired** means a normal entry point reaches
  it. **Verified** names a repeatable test or measurement. **Operational** means
  the required service/device is available in the audited environment.
  **Commissioned** is reserved for evidence from the intended physical device
  and environment; **experimental** and **planned** paths are not admitted
  product capabilities.
- A roadmap is not an implementation claim. Look for its implementation-status
  note, then confirm against [CURRENT_STATUS.md](CURRENT_STATUS.md).
- A simulator success is not physical hardware evidence.
- A BARN/Habitat result is an external proxy, not a companion-product score.
- Paths and commands are relative to the repository root unless stated
  otherwise.

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
