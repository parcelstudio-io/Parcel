# Day 53: Diffusion, Flow Matching, and Action Tokenization

## Mental model

Classical policies often regress a single action. Real robot behavior is multimodal: at a fork you may turn left *or* right; both are valid. Diffusion policies and flow-matching policies model a *distribution* over action sequences, then sample (or decode) one coherent chunk. Action tokenization is the discrete cousin: quantize continuous actions into tokens and train a sequence model as if actions were language.

```text
score / flow view (intuition):
  noisy action chunk A_T  --denoising / flow-->  clean chunk A_0 ~ π(·|o)

tokenization view:
  continuous a  ->  codebook ids  ->  autoregressive / masked decode  ->  â
```

Diffusion Policy (Chi et al., 2023) is the landmark case study: visual observations condition a denoising network that outputs action sequences for manipulation, with receding-horizon execution. The idea transferred culturally into robotics even where the exact architecture did not.

## Tradeoffs and industry trends

Why the industry moved here:

- Multimodal action distributions beat averaged, blurry regressors on intersection behaviors and contact-rich skills.
- Chunked generative actions inherit IL’s smoothness benefits.
- The same generative toolkit powers VLA stacks (Day 54): tokens for text *and* actions.

What the hype understates:

| Axis | Generative action models | Implication for Parcel |
| --- | --- | --- |
| Inference cost | Many denoising steps (or a big flow net) | May blow 10 Hz brain budget |
| Latency variance | Sampling can jitter | Bad for hard deadlines |
| Calibration | Pretty samples ≠ calibrated risk | Cannot be the safety case |
| Data hunger | Needs broad coverage to fill modes | City long-tail still empty |
| Embodiment | Often arms / humanoids | Go2 transfer not free |

Flow matching and consistency-style distillation aim to cut sampling to one or few steps—important if you care about p99 latency, not just demo videos. Action tokenization (FAST-like / VQ approaches in recent VLA work) trades quantization error for transformer tooling and speculative decoding tricks. Neither removes the need for a deterministic gate.

Module 6 questions, answered honestly for Diffusion Policy-class systems:

1. **Observe:** images (+ sometimes proprioception), not full urban LiDAR stacks by default.
2. **Act:** continuous action chunks (e.g., end-effector or joint targets), not Parcel PlanIR.
3. **Rate/latency:** often ~1–10 Hz effective closed loop after chunking; denoising can dominate.
4. **Data/compute:** substantial teleop; GPU training; non-trivial onboard inference.
5. **Unitree transfer:** weak unless you rebuild action space as body-velocity / SE(2) and recollect.
6. **Safety layer:** still mandatory—generative modes include unsafe modes.

## ASCII diagram

```text
  observation o_t
       |
       v
  condition encoder (vision / state)
       |
       v
  sample A^{(T)} ~ noise
       |
       +--> denoising / flow steps (N) --> A^{(0)} chunk
       |                                    |
       |                                    v
       |                         take first k actions
       |                                    |
       +------- replan <---- new o ---------+
                                            |
                                            v
                               typed bounds + collision shield
                                            |
                                            v
                               Sport / skill backend
```

## Map to Parcel / Go2

Parcel’s productive use of diffusion/flow is as a **multimodal proposer**, not as Sport.

Codebase-relative context:

- Discrete twist vocabulary already exists for duplex research: `ActTokenCodec` / `TwistBins` in `duplex/act_codec.py` bins `vx`/`vyaw` inside the `SafetyLimits` envelope—generative action tokens should reuse that seam, not invent joint codes.
- `DuplexCoordinator` (`duplex/coordinator.py`) owns conversational ACT-like frames; it must not become a second writer past `CommandArbiter`.
- Accepted motion still faces `VelocitySmoother` (`core/velocity_smoother.py`), collision/reactive gates, and `ControlManager` watchdogs.
- `PlanValidator._FORBIDDEN_ARGUMENT_KEYS` blocks plans that smuggle coordinates/joints—diffusion samples need an adapter into `SE2Goal` or typed skills first.

Prototype uses: waypoint polylines / velocity ribbons into `ProposerBus`; shadow-log token predictions vs what the arbiter committed. Reject: DDPM on the balance path. Distilled one-step flow still needs p99 timing evidence (Day 39), not average FPS.

## Overconfidence story

A lab ported Diffusion Policy to “sidewalk navigation” by treating `(vx, vyaw)` as the action and training on campus teleop. Sampling produced gorgeous multimodal trajectories around a static obstacle course. In a live crowd, a sampled mode threaded a gap that existed only in the camera’s partial view; LiDAR had a pedestrian the vision-conditioned diffuser never reliably represented. The generative model was overconfident in a mode that was geometrically elegant and socially illegal. The missing piece was not more denoising steps—it was a LiDAR collision gate with veto power over samples.

## Retrieval questions

1. Why can a mean-squared-error policy fail at a fork where a diffusion policy can succeed?
2. What latency failure mode is unique to iterative denoising versus a single forward regressor?
3. (Week-back) From Day 51: how do action chunks and receding-horizon diffusion execution relate?

## Optional 10-minute exercise

Read the Diffusion Policy paper’s abstract/method skim (arxiv 2303.04137) and fill a half-page Module 6 card for Parcel: observe, act, rate, data, Go2 transfer path (rewrite actions as what?), and the exact process that may veto a sample. State whether you would classify it adopt / prototype / shadow / reject for sidewalk follow.
