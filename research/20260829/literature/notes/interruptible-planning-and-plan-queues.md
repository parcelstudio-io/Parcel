# Interruptible task planning for LLM/robot agents — plan revise / keep / queue, and plan histories as memory

Literature note for the Parcel Model A / Model B study. Date: 2026-08-29. Every source below was fetched and read (arXiv abs/HTML, project pages, or the Semantic Scholar API where the publisher host blocked fetches). Numbers are copied from the fetched text; anything that could only be confirmed from a search snippet is marked **[snippet-only, unverified]**.

Scope asked for: SayCan / Inner Monologue replanning; ReAct / Reflexion for embodied; LLM task planners with interruptions (ITP, CoMuRoS, RoCo, ProgPrompt, task-stack architectures); BT+LLM hybrids; goal amendment / task switching in HRI; dialogue-management plan stacks (information state, RavenClaw, Alexa Conversations, topic stacks); benchmarks that score interruption handling (InterruptBench, τ-bench family, τ-Voice, EchoChain, Full-Duplex-Bench, SID-Bench, AgentBoard).

---

## 0. One-paragraph synthesis

Three mechanisms recur across the literature for "a new instruction arrives while a plan is running":

1. **Replan-from-history** (LLM planners): the planner is re-prompted with *(completed steps, task guidelines, the new request, chat history)* and emits a fresh remainder-plan. ITP does exactly this (10/10 vs 5/10 for Code-as-Policies); Inner Monologue "switches tasks twice" when the human changes the goal mid-episode; CoMuRoS marks paused tasks `INTERRUPTED` and re-includes them in the replanned sequence. Cost: a full LLM call per interruption (seconds), and stale-assumption failures — InterruptBench shows even Claude-Opus-4.5 succeeds on only ~20–24 % of interrupted WebArena tasks.
2. **Hierarchical override** (language-conditioned policies): a slow high-level policy (YAY Robot every 4 s; Hi Robot ~1 s or *immediately* on user speech) emits a language command that a fast low-level policy (50 Hz) executes; a human utterance directly replaces the high-level output for a bounded window. This is the closest existing analogue to Parcel's "Model B injects a steering signal into Model A". Gains are large: YAY +25–50 pp on-the-fly, RT-H +60–70 pp on precise tasks, Hi Robot ~+40 pp instruction accuracy over GPT-4o.
3. **Explicit task stacks with per-task memory** (dialogue management and cognitive-robotics): RavenClaw's dialog stack + expectation agenda (2009), DiagGPT's topic stack (push / finish / jump / create), and *Robots Can Multitask Too*'s working/declarative/procedural memory where "if the task gets interrupted … the interaction history is kept safe" and retrieved on resume (intervened-task success 75–100 %).

On evaluation, the newest benchmarks converge on a taxonomy Parcel can adopt directly: **addition / revision / retraction** of intent (InterruptBench) and **contextual inertia / interruption amnesia / objective displacement** as failure modes (EchoChain). Full-duplex voice benchmarks give the latency bar: yield within ~2 s or be penalised (τ-Voice); best-in-class stop latency ≈0.26 s (Moshi on Full-Duplex-Bench) and 0.34–0.44 s interruption-response latency with 14 % false-interrupt rate (SID-model).

---

## 1. Embodied replanning lineage (SayCan → Inner Monologue → ReAct/Reflexion → LLM-Planner / ProgPrompt / InterAct / DEPS / JARVIS-1)

### 1.1 SayCan — "Do As I Can, Not As I Say" (Ahn et al., 2022) — https://arxiv.org/html/2204.01691v2
- Mobile manipulator, two office-kitchen environments; **101 instructions from 7 instruction families** (NL Single Primitive 15, NL Nouns 15, NL Verbs 15, Structured Language 15, Embodiment 11, Crowd-Sourced 15, Long-Horizon 15).
- **PaLM-SayCan: planning success 84 %, execution 74 %** (mock kitchen); **real kitchen: 81 % plan / 60 % exec** ("reduction of planning performance by 3 % and execution by 14 %"). FLAN-SayCan lower (70 % / 61 %, Table 3).
- Mechanism: LLM gives p(skill | instruction), value function gives p(success | state); product is scored per step. Open-loop.
- Limitation, verbatim: "At the current stage, the system is not easily able to react to situations where individual skills fail" — no closed-loop feedback, no interruption handling. This is the gap the rest of the lineage fills.

### 1.2 Inner Monologue (Huang et al., 2022) — https://arxiv.org/abs/2207.05608 ; results https://ar5iv.labs.arxiv.org/html/2207.05608 ; site https://innermonologue.github.io/
- Closed-loop: feedback (passive scene description, active scene description via VQA, binary success detection, **human interaction**) is appended to the LLM's prompt as an "inner monologue" and the plan continues/replans.
- **Simulated tabletop (Table 1)**: seen tasks — CLIPort 16.0 %, CLIPort+oracle 64.5 %, IM object-feedback 40.5 %, +success 43.5 %, +scene 48.5 %; **unseen** — CLIPort 0.0 %, IM object 34.5 %, +success 37.5 %, +scene 42.5 %.
- **Real tabletop (Table 2)**: 3-block stacking 40 % → 100 %, sort fruits/bottles 50 % → 80 %; total **45 % (object-only) → 90 % (object + success)**.
- **Real kitchen mobile manipulation (Table 3), 120 evaluations**: no disturbance **SayCan 60.8 % → IM 83.3 %**; **with adversarial disturbances SayCan 30.8 % → IM 60.4 %**.
- Mid-task goal change, verbatim: "the planner incorporates the feedback correctly by **switching tasks twice**" when human instructions change the objective; when told to stop, "the LLM planner generalizes to this scenario and predicts a 'done' action"; on infeasibility it "act[s] as an interactive problem solver by proposing alternative goals to attempt".
- Relevance: the canonical proof that appending human feedback to a running plan-context yields goal switching *without* training; the numbers under disturbance (30.8 → 60.4) are the classic "closed-loop halves the failure rate" data point.

### 1.3 ReAct (Yao et al., ICLR 2023) — https://arxiv.org/abs/2210.03629
- "reasoning traces help the model induce, track, and update action plans as well as handle exceptions"; interleaved thought/action.
- ALFWorld / WebShop: "outperforms imitation and reinforcement learning methods by an absolute success rate of 34 % and 10 % respectively".

### 1.4 Reflexion (Shinn et al., NeurIPS 2023) — https://arxiv.org/html/2303.11366
- Verbal RL: self-reflection text stored in an episodic buffer; **buffer bounded to Ω = 1–3 experiences**, "we truncate the agent's memory to the last 3 self-reflections".
- ALFWorld (134 envs): "ReAct + Reflexion … completing **130 out of 134** tasks", ReAct plateau ≈104/134, **+22 % absolute over 12 consecutive trials**; HotPotQA +20 %; HumanEval pass@1 91 % (vs GPT-4 80 %).
- Replan trigger heuristic: "if the agent executes the same action and receives the same response for **more than 3 cycles**, or if the number of actions … **exceeds 30** … we self-reflect".
- Relevance: a concrete, cheap *stuck detector* + a bounded *reflection memory* — directly usable as the Model-B trigger for "revise vs keep".

### 1.5 LLM-Planner (Song et al., ICCV 2023) — https://arxiv.org/abs/2212.04088
- "generate and update plans that are grounded in the current environment"; dynamic grounded re-planning is invoked when the agent has taken too many steps toward a subgoal or failed too many times (per abstract page description); uses **<0.5 % of paired training data** on ALFRED yet competitive with full-data baselines. (A 15.36 % unseen SR figure appeared in a search snippet only — **[snippet-only, unverified]**.)

### 1.6 ProgPrompt (Singh et al., 2022) — https://ar5iv.labs.arxiv.org/html/2209.11302
- Plans as Python programs with `assert` preconditions and recovery: "Assertions provide an environment feedback mechanism to make sure that the preconditions hold, and enable error recovery when they do not" (e.g., assert close to salmon, else `find(salmon)`).
- VirtualHome SR **0.34 ± 0.08** (GPT-3) vs prior planner **0.00**; ablations: no comments 0.18 ± 0.04, no feedback 0.28 ± 0.04. Real robot: 4 tasks, with 1–3 distractors.
- Relevance: local, programmatic "keep the plan but repair the step" — a BT-like fallback expressed in code.

### 1.7 InterAct (Chen & Chang, 2023) — https://arxiv.org/abs/2308.01552
- ChatGPT as checker/sorter helper roles around a ReAct-style agent: "a remarkable success rate of **98 %** in AlfWorld, which consists of 6 different tasks".

### 1.8 DEPS — Describe, Explain, Plan, Select (Wang et al., NeurIPS 2023) — https://arxiv.org/abs/2302.01560
- Interactive planning loop: describe execution outcome → self-explain failure → re-plan → a trained selector "ranks parallel candidate sub-goals based on the estimated steps of completion". "first zero-shot multi-task agent that can robustly accomplish **70+ Minecraft tasks** and nearly double the overall performances".

### 1.9 JARVIS-1 (Wang et al., 2023) — https://arxiv.org/html/2311.05997v3
- **Plan history as memory**: key–value memory where "the keys are multimodal, comprising both the task and the observation … The values are the plans that were successfully executed." Retrieval: text-embedding similarity threshold → re-rank by visual-embedding similarity → top-k plans injected into the prompt. Self-instruct exploration; **425 successful trajectories after 4 epochs**.
- **200+ tasks, 11 groups**; Diamond pickaxe **6.22 % vs 2.5 %** (VPT-RL, 20 min), **12.5 % at 60 min**; group-level vs DEPS: Wood 88.84 vs 80.23, Stone 88.69 vs 69.27, Iron 34.63 vs 16.92, Diamond **8.99 vs 2.42 %**.
- Relevance: the concrete pattern for Parcel's "global plans stored as a historical queue" — store (goal, situation) → plan, retrieve by situation similarity.

---

## 2. LLM task planners that accept interruptions

### 2.1 ITP — Interactive Task Planning with Language Models (Li, Wu, Abbeel, Malik; arXiv 2310.10645 v2, Feb 2025) — https://arxiv.org/html/2310.10645v2
- Mechanism (verbatim): "When the user sends a new request, our system is able to replan accordingly with precision based on the new request, task guidelines and previously executed steps." The system "feeds the completed steps and new request to create a new prompt" and "appends this new prompt to the previous conversation context"; "The system will consider completed steps, task guidelines, the new request, and the chat history to generate a new plan."
- Numbers: high-level planning **10/10 (100 %)** vs **Code as Policies 5/10**; dishwashing 10/10; 10 VirtualHome tasks; real robot drink-making; **GPT-4**. No latency reported.
- Relevance: the minimal "revise" implementation — state = completed-steps ledger + chat history; the plan tail is regenerated.

### 2.2 CoMuRoS — LLM-based hierarchical planning for heterogeneous robot teams with event-driven replanning (Borate et al., Nov 2025) — https://arxiv.org/html/2511.22354v1
- Task Manager LLM (static rules prompt + dynamic prompt with user commands, chat history, robot/task status, detected events) classifies tasks (independent / sequential / coordinated / infeasible) and allocates; each robot's "brain" LLM composes Python from ROS2 skill primitives; onboard VLM event monitor.
- Interruption handling (verbatim): "the user can provide information, give new commands, interrupt ongoing tasks, or change intention anytime during execution"; suspended tasks are "marked as INTERRUPTED" and "explicitly re-included in replanned sequences"; "Replanning allows robots to pause and assist teammates, then resume their own tasks using task-status monitoring". Example: user says "I don't want it anymore" → "classified as a relevant event, and replanning directs the quadruped to return the food".
- Numbers: hardware — object recovery **9/10**, formation transport **8/8**, human-assisted recovery **5/5**; 22 simulated scenarios × 3 tasks (~20 robots); replanning dataset 5 scenarios with correctness 1.0; Grok 3 averages correctness 0.91, allocation 0.96, classification 0.96, IoU 0.97, executability 0.98; 8 LLMs tested; temperature 0.5. Hardware includes a **Unitree Go2**. No planning-latency numbers.
- Relevance: an explicit *retraction* example ("I don't want it anymore") on a Go2, plus the INTERRUPTED-then-re-queued state machine — a direct template for Parcel's revise / keep / queue.

### 2.3 Robots Can Multitask Too (Ali et al., 2024) — https://arxiv.org/html/2407.13505
- Two-LLM stack: Level-1 *coordinator* (reasoning, emits actions) and Level-0 *worker* (builds/maintains memory). Memory: **working memory** (task reminder, current task state, task-relevant objects), **declarative memory** (one persistent log per task: executed actions, environment state, progress), **procedural memory** (task specs + action functions in the base prompt).
- Task switching (verbatim): "If the task gets interrupted, i.e., the robot is asked to switch to another one, the interaction history is kept safe." "When the robot continues the interrupted task, it retrieves essential information like previous actions, environment state, and task state at the interruption point."
- Numbers (NICOL robot, 50 trials per condition, GPT-3.5-turbo-0125 vs Llama-3-70B 8-bit, temp 0.2): standalone 92–100 % / 86–98 %; consecutive-with-memory 92–100 % / 98–100 %; **intervened (interrupt-then-resume) with memory: Separate 75 / 96, Arrange 100 / 82, Point 98 / 98, Recipe 92 / 92, Tower 98 / 98 %**. "noticeable boost in the success rate and retention metrics when running the experiment with the working memory enabled".
- Relevance: the cleanest published "task stack with per-task snapshot" for an LLM robot, with an interrupt/resume success number.

### 2.4 RoCo (Mandi, Jain, Song; 2023) — https://arxiv.org/html/2307.04738
- Dialog-based multi-robot planning; plan validated by text parsing → IK feasibility → collision check; failed feedback "is appended to each agent's prompt" and agents re-plan (avg **1.0–3.5 re-plan attempts** on successful runs).
- RoCoBench: Sweep Floor 0.95±0.05, Pack Grocery 0.44±0.06, Move Rope 0.65±0.11, Arrange Cabinet 0.75±0.10, Make Sandwich 0.80±0.08, Sort Cubes 0.93±0.06. Real-world human-in-the-loop sorting: **9/10** (object init variation), **8/10** (task-order constraints), ~5.3–5.5 steps.
- Relevance: feedback-appended replanning with a human participant as a dialog agent; shows replanning rounds are few (1–3.5) when validators are cheap.

---

## 3. Language-conditioned policies with real-time correction (tight speech↔motion coupling)

### 3.1 Interactive Language: Talking to Robots in Real Time (Lynch et al., 2022) — https://arxiv.org/abs/2210.06407 ; https://interactive-language.github.io/
- BC policy on **~600,000 language-labelled trajectories** (Language-Table); **93.5 % success on 87,000 unique language strings**; "capable of being guided by a human via real-time language to address a wide range of precise long-horizon rearrangement goals, e.g. 'make a smiley face out of blocks'"; examples such as "nudge the green star down and left a bit" issued while the robot moves. (A 5 Hz control-rate figure appeared in a search snippet; the fetched pages do not state it — **[snippet-only, unverified]**.)
- Relevance: the earliest large-scale demonstration that a single flat policy can absorb *new* language mid-motion; the lower bound on "speech tightly coupled to movement".

### 3.2 YAY Robot — Yell At Your Robot (Shi et al., 2024) — https://arxiv.org/html/2403.12910v1 ; https://yay-robot.github.io/
- Hierarchy: "the high-level policy is queried at fixed intervals, specifically **every 4 seconds** as the average skill length"; low-level operates on **50 Hz** data. Humans "intervene through corrective language commands, **temporarily overriding the high-level policy** and directly influencing the low-level policy for on-the-fly adaptation"; corrections are logged "from 2 seconds prior to the intervention for more context".
- Numbers: data 1170 / 317 / 265 trajectories (41,517 / 7,008 / 3,236 skill segments) for bag packing / trail mix / plate cleaning; baselines 0 % / 20 % / 60 %; **on-the-fly corrections +25–50 pp (bag), +30–45 pp (trail mix), +15–25 pp (plate)**; fine-tuning on corrections "+20 % on average" per stage (20–45 / 15–20 / 15–25 pp).
- Relevance: the most direct precedent for Model B → Model A steering: an utterance replaces the high-level command for a bounded window, and the same utterances become training labels.

### 3.3 RT-H — Action Hierarchies Using Language (Belkhale et al., RSS 2024) — https://arxiv.org/html/2403.01823v2
- Language motions ("move arm forward") as an intermediate layer; in correction mode the operator can "type a new language motion correction … or use hotkeys", re-queried at "a fixed frequency" with options to "enter a new language motion correction, keep running the previously entered … or exit correction mode".
- Numbers: PaLI-X 55B; 100K demos (70K kitchen + 30K diverse); 8 eval tasks; RT-H "surpassing RT-2 by **15 % on average**"; with human corrections "**60–70 %** on the harder precise tasks"; **30 correction episodes per task** for RT-H-Intervene, which "substantially outperforms RT-2-IWR … despite using the same amount of data"; corrections give "near perfect success rates".
- Relevance: enumerates exactly the keep / replace / exit semantics for a correction channel.

### 3.4 Hi Robot (Shi et al., ICML 2025) — https://arxiv.org/html/2502.19417v1
- High-level VLM (PaliGemma-3B) takes images + open-ended prompt + user interjections and emits an intermediate language command plus optional verbal reply; low-level π0 VLA executes action chunks. "The high-level component runs at lower frequency (reinvoked **every second** or upon user interaction)"; "When the system receives a user intervention, the high-level inference is triggered **immediately** to recompute" the command. Replies are grounded in the current image ("that's not trash").
- Training: synthetic "situated" interjections — a VLM given (image, skill label) "imagines an appropriate interaction that might have led to" the action, producing user prompts + robot verbal responses.
- Numbers: Instruction Accuracy and Task Progress metrics; "approximately **40 % higher instruction accuracy than GPT-4o**"; 20 trials per task per method; inference on 1–2 RTX 4090. GPT-4o high-level "frequently loses context once physical interaction begins"; flat VLA "reverts to clearing all items" on partial instructions.
- Relevance: this *is* the Model A / Model B split (low-level continuous policy + slow language-level reasoner that also produces the spoken reply), with an explicit "interrupt → immediate re-inference" rule and a synthetic-interjection data recipe that Parcel's sim can copy.

---

## 4. Behaviour-tree + LLM hybrids

### 4.1 LLM-BT (Zhou et al., ICRA 2024) — https://arxiv.org/html/2404.05134v1
- ChatGPT emits descriptive steps → BERT parser → initial BT; **BT Update algorithm**: on Failure, find the failed condition node, search an Action Template Library for actions whose post-conditions satisfy it, build a fallback subtree (sequence node ensuring preconditions), and insert it — when there is a conflict "𝒯exp is added before all nodes in Ct for raising the priority", i.e., environmental changes get higher-priority subtrees.
- Numbers: cargo sorting, 5 cases × 20 non-professional users: **18/17/16/18/18 of 20 (~85 %)**; household service **15/14/15/16/17 of 20 (~75 %)**; failure attribution dominated by "unclear requirements expressed by users" (10 failures; 16/100 in household), parser failures on novel steps 6/84, "1 failure caused by an unsolvable external disturbance".
- Relevance: a keep-the-plan-and-patch-it mechanism with priority insertion — cheap local revision without a full replan.

### 4.2 LLM-HBT (Wang et al., Oct 2025) — https://arxiv.org/html/2510.09963v1
- "When a behavior tree condition node fails, the allocator leverages LLM-based reasoning to infer the most appropriate robot" and returns an assignment plus a candidate action node; the new subtree "is directly merged … by replacing fi", or for collaboration one robot "temporarily suspends execution at fi while monitoring its status" while the other "incorporates the delegated subtree at the root".
- Numbers: **60 tasks across 3 simulated scenarios** (quadruped; quadruped + drone; + arm); in scenario 3 "baselines succeed in only **40 %** of tasks, whereas LLM-HBT still achieves **100 %**"; real café: "Across **ten repeated trials**, … completed the collaborative task without failure" (wheeled-legged robot + arm).
- Relevance: suspend-at-node / resume-on-status is a BT-native way to implement "queue" semantics.

(Also seen but not fetched in depth: BTGenBot, LLM-as-BT-Planner, CommandSwarm.)

---

## 5. Dialogue management: information state, dialog stacks, topic stacks

### 5.1 Larsson & Traum (2000), "Information state and dialogue management in the TRINDI dialogue move engine toolkit", Natural Language Engineering — DOI 10.1017/S1351324900002539 (read via Semantic Scholar API; 609 citations)
- Abstract: "an architecture and toolkit for building dialogue managers … based on the notions of information state and dialogue move engine … a framework for experimenting with implementations of different theories of information state, information state update and dialogue control."
- Relevance: the canonical formalism — state = informational components (incl. plan/QUD stacks), dialogue moves, update rules, control strategy. Model B's "revise / keep / queue" is an update-rule set over an information state.

### 5.2 RavenClaw (Bohus & Rudnicky, Computer Speech & Language 2009) — https://www.cs.brandeis.edu/~cs115/CS115_docs/Ravenclaw.pdf
- Hierarchical task decomposition; "a dialog stack, which captures the discourse structure at runtime, and an expectation agenda, which captures what the system expects to hear from the user in any given turn"; handles "user-initiated topic shifts", suspension and later resumption, with a distributed error-handling decision process. Deployed in LARRI, RoomLine, Let's Go! bus information.
- Relevance: the mature engineering pattern — a stack of task agents plus an *agenda of expected inputs* — for deciding whether an utterance is a sub-dialogue (push), a focus shift (suspend), or a barge-in to the current task.

### 5.3 Alexa Conversations (Acharya et al., NAACL 2021) — https://www.amazon.science/publications/alexa-conversations-an-extensible-data-driven-approach-for-building-task-oriented-dialogue-systems
- Simulator-driven data generation from seed dialogues + API/entity specs; "out-of-the-box support for natural conversational phenomena like entity sharing across turns or **users changing their mind during conversation** without requiring developers to provide" explicit flows; ">50 % improvement in turn-level action signature prediction accuracy" on movie-ticket booking.
- Relevance: industrial precedent that mind-changes are handled by *simulating* them at data-generation time rather than by hand-authored flows — exactly what Parcel's sim should do.

### 5.4 Converse (Xie et al., Salesforce, 2022) — https://arxiv.org/abs/2203.12187
- "an and-or tree structure to represent tasks and offers powerful multi-task dialogue management"; "supports task dependency and task switching".

### 5.5 DiagGPT (Cao, 2024) — https://arxiv.org/html/2308.08043v4
- **Topic stack** with explicit actions: load topics from a checklist onto the stack; "finish the current topic … removes the top topic"; stay; "jump to an existing topic … retrieve and prioritize a previous topic from the stack"; create new topic. Four agents (Chat, Topic Manager, Topic Enricher, Context Manager).
- Numbers: 20 scenarios; completion 1.0, success 1.0, rounds 7.0 vs GPT-4 7.7, quality 9.0/10, comparison score 11.5 vs 8.5.
- Relevance: an LLM-operated stack API (push / pop / jump / create) — a ready vocabulary for Model B's queue operations.

---

## 6. Interruption and task-switching in HRI

### 6.1 Interruption Handling for Conversational Robots (Cao et al., Jan 2025) — https://arxiv.org/html/2501.01568
- Intent taxonomy: cooperative agreement, cooperative assistance, cooperative clarification, disruptive. Strategies: agreement → brief acknowledgment ("ya", nod) and continue; assistance → acknowledge and "continue with the remaining planned content"; clarification → "an LLM prompted to address the clarification requested and then continue with the remaining previously planned content"; disruptive → yield the floor (if aggressive within 5 s, first "express its intent to maintain the turn").
- Numbers: **21 participants** (M = 22.38 y); "**successfully handled 93.69 % (n = 104/111)** of user-initiated interruptions"; intent classification **88.78 %**; observed mix **76.03 % disruptive** (n = 92; 45.65 % of those opinion questions), agreement 18, clarification 9, assistance 2; "speech recognition errors caused the majority of interruption handling failures"; negative correlation between unhandled interruptions and perceived inclusion (ρ(42) = −.43, p = .005).
- Relevance: the "keep talking vs yield vs answer-then-resume" policy for the *narration* side, with a resume-the-planned-content primitive.

### 6.2 "You're delaying my task?! The Impact of Task Order and Motive on Perceptions of a Robot" (Carter, Hiatt, Rosenthal; HRI 2022) — DOI 10.1109/HRI53351.2022.9889307 (abstract read via Semantic Scholar API; listed at https://humanrobotinteraction.org/2022/toc.html)
- Robot interleaves a delivery task with an investigative task under three motive framings. "While participants acknowledged that interleaving tasks should be allowed, they rated the robot as **more competent when its tasks were not interleaved**. They were most receptive to interleaving when they knew the investigative task was for another person and less receptive to long task detours away from the delivery route, especially when the inspection task was motivated by curiosity."
- Relevance: queueing (finish current, then do the new one) is perceived as more competent than interleaving unless the reason is narrated — a direct argument for Model B narrating *why* it re-orders the queue.

---

## 7. Benchmarks that score interruption handling

### 7.1 InterruptBench — "When Users Change Their Mind" (Zou et al., Apr 2026) — https://arxiv.org/html/2604.00892
- **165 human-verified WebArena-Lite tasks, 5 domains** (Reddit, GitLab, CMS, Map, OneStopShop); interruption types **Addition / Revision / Retraction**, injected at **60 % of the baseline trajectory length**; single- and multi-turn (0–3 interruptions).
- Single-interruption success: Claude-Opus-4.5 **21.21 / 20.00 / 23.64 %** (add/rev/retract); Claude-Sonnet-4.5 15.15 / 13.94 / 15.76; Haiku-4.5 12.12 / 9.70 / 11.52; Qwen3-480B 11.52 / 7.27 / 10.91; DeepSeek-V3.1 12.12 / 9.09 / 11.52; Mistral-Large-3 11.52 / 5.45 / 9.70. Multi-turn: Opus 5.45 % (no interruption) → 41.82 % (3 interruptions — interruptions can *help* by clarifying); DeepSeek regressed 21.21 → 20.61 % from 2 to 3.
- Efficiency: token inflation **+37.6 to +1,699 tokens/episode** vs action deltas −0.99 to +0.82; both-fail cases cost most (Haiku +2,624, Sonnet +1,128, Opus +351 tokens); success-with-reuse quadrants show "near-zero or negative action overhead" for stronger models. Agents "continue with stale assumptions"; larger models better at "repairing committed trajectories".
- Relevance: the taxonomy + injection protocol + effectiveness/efficiency metrics are directly portable to Parcel's instruction-navigation matrix.

### 7.2 τ-bench (Yao et al., 2024) — https://arxiv.org/abs/2406.12045 and τ²-bench (Barres et al., 2025) — https://arxiv.org/html/2506.07982v1
- τ-bench: simulated user + agent with tools and policy; gpt-4o "<50 %" success, "pass^8 < 25 % in retail"; pass^k measures consistency across k trials.
- τ²-bench: **115 retail / 50 airline / 114 telecom** tasks (telecom sampled from 2,285 compositional tasks); dual control (user also has tools). Telecom pass^1: Claude 3.7 Sonnet 49 %, GPT-4.1 34 %, o4-mini ≈50 %; GPT-4.1 retail 74 %, airline 56 %; moving from no-user to dual-control costs GPT-4.1 **−18 %**, o4-mini **−25 %** — "LLMs still face significant challenges when solving problems with an active user". Neither benchmark scripts mid-task mind-changes explicitly.

### 7.3 τ-Voice (Ray, Dhandhania, Barres, Narasimhan; Mar 2026) — https://arxiv.org/html/2603.13686v1
- **278 tasks** (retail 114, airline 50, telecom 114); tick-based full-duplex orchestrator at **200 ms** ticks; "When users interrupt, agents must **yield within 2 seconds** or face penalization"; interruption/backchannel decisions evaluated every 2 s by an LLM.
- Numbers: GPT-5 text baseline **85 %**; voice agents clean audio **31–51 %**, realistic **26–38 %** ("retain only 30–45 % of text SOTA"); ablations (retail): accents −10 pp avg (−18 xAI, −1 Google), turn-taking −7 pp, noise −4 pp; latency OpenAI 0.90 s, xAI 1.15 s, Google 1.14 s; responsiveness 100 / 83 / 69 %; agent interrupt rate xAI 84 %, OpenAI 14 %, Google 21 %; selectivity xAI 57 %, Google 54 %, OpenAI 6 %; 79–90 % of failures are agent behaviour.
- Relevance: an evaluation harness design (tick orchestrator, seeded simulator, yield deadline) that Parcel's 10 Hz duplex frame clock can mirror.

### 7.4 EchoChain (Modi et al., Apr 2026) — https://arxiv.org/html/2604.16456v1
- **200 interrupted conversations**; interruptions injected at standardized offsets from assistant speech onset; failure taxonomy: **contextual inertia** (acknowledge but don't apply), **interruption amnesia** (apply then revert), **objective displacement** (abandon the original task).
- Numbers: Mean Pass Rate **<50 % for all four models**; Grok Voice Agent best **48.5 %**; paired half-duplex control: "total failures drop by **40.2 %** relative to interrupted runs"; Gemini Live fails by amnesia/displacement, Nova by inertia, GPT-realtime balanced; cloned voices validated (χ² = 0.92, p = 0.63).
- Relevance: the three failure modes map one-to-one onto Parcel's revise / keep / queue errors (inertia = failed revise; amnesia = failed keep-after-revise; displacement = failed queue).

### 7.5 Full-Duplex-Bench (Lin et al., ASRU 2025) — https://arxiv.org/html/2503.04721v2
- Dimensions: pause handling, backchannel, smooth turn-taking, user interruption (**200 synthetic interruption samples**; Candor pause 216, turn-taking 119, ICC backchannel 55).
- User-interruption takeover rate / stop latency: **Moshi 1.000 / 0.257 s**, Freeze-Omni 0.867 / 1.409 s, Gemini Live 0.891 / 1.183 s, dGSLM 0.917 / 2.531 s; smooth-turn latency Moshi 0.265 s, dGSLM 0.352 s, Freeze-Omni 0.953 s, Gemini Live 1.301 s.

### 7.6 SID-Bench — Semantic-Aware Interruption Detection (Xia et al., Qwen, Mar 2026) — https://arxiv.org/html/2603.24144
- **3,700 instances** (~10 h): interruption-at-beginning 1,000, in-middle 1,200, uninterrupted backchannel 1,000, noise 200, silence 300. Metrics: FIR (false interruption rate), IRL (interruption response latency), APT (average penalty time).
- SID-model (audio encoder + Qwen-0.6B, K = 3 smoothing): **IRL 0.444 s EN / 0.338 s ZH, FIR 0.140 / 0.138, APT 0.921 / 0.656**; Moshi IRL 2.517 s but FIR 0.010; FSMN-VAD FIR 0.906; "nearly threefold reduction in APT".
- Relevance: a barge-in *semantic* gate — deciding whether speech is a real instruction (revise) or a backchannel (keep) — with the latency/false-alarm trade-off quantified.

### 7.7 PACE — Playback-Aligned Context Engine (Wang et al., Alibaba, Aug 2026) — https://arxiv.org/html/2608.07631v1
- Problem: Generative Context Mis-anchoring — "subsequent user speech may be interpreted based on content the user never heard" because generation runs ahead of playback. Mechanism: server OutputTurnLedger + client PlaybackAck → playback boundary; on interruption, snapshot boundary, re-inject the last 5 s of *actually played* audio, then release post-interruption speech.
- Numbers: GCM-Bench **108 cases**; referent-anchoring accuracy **25.0 % → 96.3 % (+71.3 pp)**; Elaborate 2.78 → 94.44, Next 61.11 → 97.22, Repeat 11.11 → 97.22; Full-Duplex-Bench compatibility: turn-obedience 100 %, quality 4.975 → 4.995, interruption latency 771 → 830 ms (+59 ms).
- Relevance: Model B's narration ledger must record what was *spoken and heard*, not what was generated — otherwise "go back there" resolves to a place the robot never said aloud.

### 7.8 AgentBoard (Ma et al., NeurIPS 2024) — https://arxiv.org/html/2401.13178
- **9 tasks, 1,013 environments**; progress rate = highest matching score (continuous) or mean over annotated subgoals; embodied subset (ALFWorld/ScienceWorld/BabyAI) progress/success: GPT-4 **65.5 / 43.3 %**, Claude2 34.1 / 24.6, GPT-3.5 35.6 / 17.2, Llama3-70B 29.6 / 12.7; GPT-4 overall progress 70.0 %; open-weight models "peak early and generally stop progressing after about 6 steps". No interruption scoring.
- Relevance: the progress-rate metric is what Parcel needs to score *partial* credit when a goal is amended mid-episode.

---

## 8. Not obtained / flagged

- **Model Interruption Bench (OpenReview)** — host blocked; search snippet says: user speaks a step-by-step math solution, the model must interrupt inside an error window on error audio and stay silent on correct audio; backchannels not counted. **Not fetched — do not cite.**
- **XLand "goal interventions"** (Open-Ended Learning Team, 2021) — PDF too large to fetch; snippet claims evaluation at 1.5× episode length with the goal changed after the first third. Unverified.
- Interactive Language 5 Hz and LLM-Planner 15.36 % — snippet-only.

---

## 9. What this means for Parcel's Model A / Model B

**Architecture.** The literature's best-performing pattern is *exactly* the proposed split: a fast continuous policy (Model A, cf. π0 in Hi Robot at action-chunk rate, YAY's 50 Hz low level, Parcel's 10 Hz frame clock) and a slower language-level reasoner (Model B, cf. Hi Robot's high-level VLM at ~1 Hz, YAY's 4 s cadence) that (a) emits a steering command and (b) produces the spoken reply. Two rules to copy verbatim: **re-invoke Model B immediately on any owner utterance** (Hi Robot) and **let a correction temporarily override the high-level command for a bounded window, then revert** (YAY, RT-H keep/replace/exit).

**Revise / keep / queue as an information-state update.** Model B's decision is an update-rule set over a small information state: current goal, plan tail, completed-steps ledger (ITP), per-task snapshot (Robots-Can-Multitask: actions, env state, progress at interruption), and a stack/queue of suspended goals (RavenClaw dialog stack; DiagGPT push / finish / jump / create; CoMuRoS `INTERRUPTED` flag). Three cheap classifiers gate it: (1) a semantic barge-in detector (SID-Bench: <0.5 s, ~14 % false-interrupt) to separate backchannels from instructions; (2) an intent type — addition / revision / retraction (InterruptBench) mapped to queue / revise / cancel; (3) a stuck detector (Reflexion: same action & response >3 cycles or >30 steps) that can trigger self-initiated revision.

**Plan history as memory.** Store every global plan as (goal text, StateDigest at creation, plan, outcome) — JARVIS-1's key = (task, observation), value = successful plan — and retrieve by situation similarity when a new goal arrives; bound the *reflection* memory to 1–3 entries (Reflexion) so the prompt stays small. The queue is the same store filtered to `suspended`.

**Narration.** Model B's narration ledger must be playback-aligned (PACE): record what was actually spoken before an interruption so "go back to the door" resolves against what the owner heard. Use the conversational-robot strategies (Cao et al. 2025): acknowledge-and-continue for agreement/assistance, answer-then-resume-planned-content for clarification, yield for disruptive. Narrate *why* a queue is reordered — users rate interleaving as less competent unless the motive is explained (Carter et al. 2022).

**Training in sim.** Generate situated interjections synthetically (Hi Robot: VLM imagines the utterance that would have led to the observed skill; Alexa Conversations: simulate mind-changes from seed dialogues) and inject them at a fixed fraction of the trajectory (InterruptBench: 60 %). Log corrections with 2 s of prior context (YAY) so they double as supervised labels for Model B.

**Evaluation.** Add an interruption axis to the 5 × 5 instruction-navigation matrix: addition / revision / retraction × single / multi-turn, scored on (i) success, (ii) progress rate (AgentBoard) for partial credit, (iii) efficiency (extra steps/tokens vs an uninterrupted run — InterruptBench), (iv) yield latency with a 2 s deadline (τ-Voice) and stop latency (Full-Duplex-Bench), and (v) the EchoChain failure classes (inertia / amnesia / displacement). Expect the baseline to be low: the best LLM agents handle ~20 % of interrupted long-horizon tasks, and voice agents retain 30–45 % of text capability under realistic audio.

**Numbers to plan around.** High-level cadence 1–4 s; correction latency target <0.5 s to acknowledge, <2 s to yield/redirect; closed-loop feedback roughly doubles success under disturbance (SayCan 30.8 → IM 60.4 %); interrupt-then-resume with per-task memory 75–100 % on simple tabletop tasks; on-the-fly language corrections add +15–50 pp on manipulation stages.
