# Independent verdict: Go2Env is not locomotion-training ready

## Decision

**REFUTED.** The current `src/parcel_robot/rl/Go2Env` must not be used to train,
rank, or promote generalized Go2 locomotion policies.

I derived this decision from the frozen raw records and the preregistered
all-critical-gates rule, independently of the experiment's headline. The raw
runs are byte-identical, the subject source hashes still match the
preregistration, and the verifier passed all 14 integrity/recomputation checks.
Seven critical fidelity gates fail.

## Why the two passes are insufficient

The model and API dimensions are internally plausible, and different joint
targets alter MuJoCo state. Neither property makes a learning task valid. The
observation joint order disagrees with actuator order; velocity, height, and
upright fields are false or unrelated to their labels; falls never terminate;
and reset observations retain prior actions. A learner can therefore optimize
mislabelled rewards and history leakage while appearing to train normally.

The offline path is additionally unsafe as evidence: it emits numerical and
boolean physics claims without saying that no physics produced them.

## Required repair order

1. Establish one model-index map from actuator IDs to joint qpos/dof addresses
   and use it for actions, observations, reward state, logging, and exported
   policy metadata. Pin the exact ordered joint names.
2. Derive post-step telemetry from MuJoCo state: root translation/velocity,
   normalized orientation or projected gravity, base height, joint state, and
   contact/foot state. Mark offline values invalid instead of inventing them.
3. Add fall/invalid-state termination with explicit thresholds, dwell or
   hysteresis, and a separately reported truncation cause. Reset every episode
   field, including last action and commands.
4. Make control timing explicit: policy period, physics timestep, integer
   decimation, action hold, and reward accumulation must agree.
5. Replace fixed task metrics with measured quantities and add command-tracking,
   energy/torque, slip/contact, posture, joint-limit, collision, and smoothness
   terms whose units and frames are tested.
6. Only after the fidelity gates pass, add procedurally split terrains and
   domain randomization for mass/payload, friction, motor strength, latency,
   disturbances, and sensor noise. Keep a frozen held-out MuJoCo suite and an
   independent simulator transfer suite.

Then rerun this exact audit unchanged. Passing it would be necessary, not
sufficient: a subsequent frozen baseline-policy experiment must demonstrate
stable standing, velocity tracking, fall recovery, terrain generalization, and
cross-simulator rank correlation before any policy comparison can inform
physical commissioning.

## Evidence boundary

This verdict concerns only the checked-in local environment and tracked Go2
MuJoCo model. It says nothing about a trained controller because none was run,
and nothing about physical Go2 safety or sim-to-real transfer.

