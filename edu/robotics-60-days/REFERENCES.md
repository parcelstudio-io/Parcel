# References (Module 6 focus)

Primary papers and systems cited in Days 51–60. Prefer primary sources over summaries when making adopt/reject calls.

## Imitation, diffusion, generative action

- Chi et al., *Diffusion Policy: Visuomotor Policy Learning via Action Diffusion*, arXiv:2303.04137 — https://arxiv.org/abs/2303.04137
- Zhao et al., *Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware* (ACT / action chunking) — search “Action Chunking with Transformers”
- Brohan et al. / RT-series and related BC-at-scale lineage (historical context for VLA data hunger)

## RL locomotion / navigation

- Parallel sim + domain-randomization quadruped RL literature (Isaac Gym / Isaac Lab / MuJoCo playgrounds) — use as transfer caution, not as Sport replacement proof
- Conservative / offline RL surveys for log-only learning without sidewalk exploration

## Vision-language-action and navigation foundations

- OpenVLA — https://github.com/openvla/openvla
- Physical Intelligence openpi / π models — https://github.com/Physical-Intelligence/openpi
- Gemini Robotics report — https://storage.googleapis.com/deepmind-media/gemini-robotics/gemini_robotics_report.pdf
- NVIDIA GR00T (project page / technical reports; humanoid-centric — transfer carefully)
- VLN / generalist navigation: NoMaD, NaVILA, CityWalker-class systems (see also Parcel `docs/DEPENDENCIES.md` notes)

## Safe learning

- Ames, Coogan, et al., *Control Barrier Functions: Theory and Applications*, arXiv:1903.11199 — https://arxiv.org/abs/1903.11199

## Social / city evaluation

- Habitat 3.0 — https://aihabitat.org/habitat3/
- MetaUrban — https://metadriverse.github.io/metaurban/

## Parcel internal anchors (not papers)

- Orientation: [`../INTRO.md`](../INTRO.md)
- City nav posture: `docs/NAVIGATION_CITY.md`, `docs/DYNAMIC_CITY_AND_BEHAVIOR.md`
- Companion nav architecture: `docs/COMPANION_NAVIGATION_ARCHITECTURE.md`
- RL skill env notes: `docs/IMPLEMENTATION_SKILLS_CITY_RL.md`

## Module 6 interrogation (reuse on every system)

1. What does it observe?
2. What action does it produce?
3. At what control rate and latency?
4. What data and compute did it require?
5. Does its evidence transfer to a Unitree quadruped?
6. What deterministic safety layer remains necessary?
