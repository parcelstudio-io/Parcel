# Parcel documentation

Start with the redesign pair for current architecture and decisions:

| Doc | Role |
| --- | --- |
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

## Eval entry points (outside `docs/`)

- Product-facing companion scenarios: `evals/companion_nav/`
- Offline BARN / Habitat research proxies: `evals/external/README.md`
- Frozen PlanIR gates: `evals/companion/planner_quality_v2/README.md`
