# Parcel documentation

Start with the status and decision records. They distinguish what is working in
this checkout from target architecture and research proposals.

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
| [IMPLEMENTATION_SKILLS_CITY_RL.md](IMPLEMENTATION_SKILLS_CITY_RL.md) | Skills catalog, city scene, `Dog` API |
| [DEPENDENCIES.md](DEPENDENCIES.md) | Host GPU / dependency inventory |
| [REASONER_GPU_PROFILE.md](REASONER_GPU_PROFILE.md) | Gemma / CUDA admission profiles |
| [GRID_UPDATE_PERFORMANCE.md](GRID_UPDATE_PERFORMANCE.md) | Occupancy-grid update microbenchmark |
| [RESEARCH_2026_ROADMAPS.md](RESEARCH_2026_ROADMAPS.md) | Research conclusions, implemented slices, and explicitly future work |
| [ATTENTION_STEERING_DESIGN.md](ATTENTION_STEERING_DESIGN.md) | Voice-steered attention design: audits, architecture, trainable-core staging, open decisions |

## Reading rules

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
