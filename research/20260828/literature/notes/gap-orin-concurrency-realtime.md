# Gap note: running several models concurrently on Jetson AGX Orin 64 GB while a real-time control loop runs

Research note for Parcel, 2026-08-28. Question: what happens on a Jetson AGX Orin when a full-duplex speech model, a VLM, ASR/TTS and a 50-500 Hz body controller all want the same SoC at once? Specifically: GPU contention between CUDA processes on Tegra (MPS availability, time-slicing, stream priorities), the jitter this induces on real-time loops, what NVIDIA's own multi-model demos actually measure, and what robotics stacks report when co-scheduling an LLM/VLA with a controller on Orin.

Method: every source below was located with WebSearch and then read with WebFetch (HTML, forum thread, arXiv HTML, GitHub page, or a PDF converted with `pdftotext`). Numbers are transcribed from the fetched text; where a page did not state a number I say so. Where a source is on a different device than the AGX Orin 64 GB (Orin Nano, Orin NX, Xavier, TX2, Thor, dGPU) that is stated in the entry, because scheduling rules transfer across Tegra generations but absolute latencies do not. Items marked **[secondary]** are blog/aggregator text, not primary. Nothing is cited from memory.

Parcel context: Go2 EDU+ (Orin NX 16 GB inside the dog) plus an external Jetson AGX Orin 64 GB (2048-core Ampere GPU, 12-core A78AE, 204.8 GB/s LPDDR5); dev box RTX 5000 Ada 32 GB. The design under study puts speech + a discrete body/act token stream on one clock, with a separate 50-500 Hz locomotion/gaze controller.

---

## 0. One-page summary

| Question | Answer (with the source that carries it) |
|---|---|
| Do CUDA kernels from two processes run concurrently on Orin? | **No.** Without MPS, "work launched to the compute engine from work queues belonging to different CUDA contexts cannot execute concurrently"; the GPU "employs a time sliced scheduler" (MPS architecture doc, A2). Measured on Jetson: only one task executes at a time, timeslices ~1024 us on Tegra (A11, A13). |
| What is the timeslice / context-switch cost? | Tegra driver: **1024 us** timeslice, "the same length of time slices for all TSGs"; context switch **50-750 us** (measured average > 200 us on Xavier NX and Orin Nano); runlist update up to **~1 ms** (GCAPS, ECRTS 2024, A11). Bakita & Anderson measured 1024 us compute timeslices on TX2 and ~2 ms on discrete GPUs (A13). |
| Can I set GPU timeslice / per-process priority on Jetson? | **No user-space knob.** NVIDIA: "We don't provide such parameters on Jetson to change GPU scheduling behavior" (A8) and "For now we don't have the interface on Jetson platforms" (A9). The DRIVE OS `nvrm_gpusched` knobs (timeslice, runlist interleave, preemption type) exist only on DRIVE (A10). |
| Do CUDA stream priorities help? | Only within a process, and only at launch boundaries: "Higher-priority tasks do not preempt already running lower-priority tasks" (CUDA Programming Guide, A15). |
| Is CUDA MPS available on Orin? | **Yes since CUDA 12.5 / JetPack 6.1** ("MPS ... now available on Tegra platforms: Linux starting with CUDA 12.5", A1; NVIDIA forum confirmation A3/A4). Caveats: `-multiuser-server` unsupported on Tegra; MPS executables tied to the CUDA driver of the same upgrade package (search-result summary of A1's Limitations link; not re-quoted from the page); Kubernetes MPS mode fails on Orin JetPack 6.2 while manual `nvidia-cuda-mps-control -d` works (A5). **No published latency measurement of MPS on any Orin was found.** |
| What about green contexts / MIG / SM partitioning? | Thor (CUDA 13) gets MPS + green contexts, MIG "upcoming"; "The only exception is Orin (sm_87), which will continue on its current path for now" (A17). Green contexts are intra-process and "concurrent execution of independent GPU work is not guaranteed" (A16). libsmctrl TPC masking works on Tegra (tested on Xavier), within a process (A14). |
| How many CUDA processes can coexist? | **32 contexts max** on AGX Orin and Orin Nano ("out of hw chids"); NVIDIA: "The maximal concurrent CUDA processes/contexts on Orin is 32" (A6). |
| What does multi-process contention cost? | Orin Nano, int8 ResNet50/YOLOv8n: per-process throughput 210 -> ~10 img/s at 8-16 processes; execution-context duration inflates **~30x at 4 and ~70x at 8 concurrent processes**; SMs at only 15-30 % utilisation while "GPU util" reads 100 % (A18). dGPU MPS with two 50 % clients: 100 ms -> 110 / 140 ms (+10 % / +40 %), attributed to memory-bandwidth contention (A19). |
| How much jitter does GPU load put on a CPU real-time loop on AGX Orin 64 GB? | WIM measurement (JetPack 6.2, RT OTA kernel, cyclictest 1 kHz, 10 min): non-RT kernel max **318 us**; PREEMPT_RT without isolation under `glmark2` GPU load max **159 us**; PREEMPT_RT + `isolcpus=managed_irq,domain,8-11 irqaffinity=0-7 kthread_cpus=0-7` max **15 us** under GPU load (B1). Untuned RT kernel on AGX Orin: max **1074-6221 us** (B4). Module-to-module variance: 10 us vs 90+ us on two "identical" AGX Orin 64 GB modules (B3). |
| Do NVIDIA's multi-model demos publish contention numbers? | **No.** llamaspeak (ASR+LLM+TTS on AGX Orin 64 GB, "overlapping ASR/LLM/TTS generation"), Agent Studio (plugins "each ... in its own thread ... usually in the same process"), and Multi-Modal AI Studio on Thor (Riva ASR + Riva TTS + Cosmos-Reason2-8B on vLLM in separate containers) publish memory/setup but no co-run latency (C1-C3). Single-tenant AGX Orin baseline: Llama-3.1-8B W4A16 on vLLM 44.19 tok/s, TTFT 32.02 ms, ITL 22.47 ms (C4). |
| What do robotics stacks report on Orin? | Single-tenant GPU VLA on AGX Orin 64 GB: **150.5 ms mean, sigma 0.125 ms** (min 150.4 / max 151.0) with a 100 Hz ROS 2 controller running alongside (D1). Go2 stacks put a 50 Hz policy + image processing inside one 20 ms cycle on an Orin NX with 1 kHz motor loop (D6) and 50 Hz on an Orin Nano (D7). A UAV stack on Orin NX slowed from 5.5 Hz to 4.7 Hz when the flight controller competed for CPU (D11). pi0.5 on Orin AGX 32 GB: 440 ms/step vs 60 ms on A100, task accuracy 80 % -> 30 %, visible "jerkiness" (D4). GR00T N1.7-3B on Orin: 354 ms eager, 150.9 ms TensorRT (6.6 Hz) (C6). |

---

## A. GPU sharing mechanics on Tegra / Orin

### A1. NVIDIA, "CUDA for Tegra" application note (CUDA 13.3 docs)
- URL: https://docs.nvidia.com/cuda/cuda-for-tegra-appnote/index.html
- MPS: "MPS has long been supported for dGPUs attached to x86 systems. This capability is now available on Tegra platforms: Linux starting with CUDA 12.5 and QNX starting with CUDA 12.8." Platform constraints are delegated to the MPS doc's Limitations section (the search-result summary of that section says `-multiuser-server` is not supported on Tegra and that on Orin the MPS executables from a CUDA upgrade package only work with that package's driver; I could not get WebFetch to render that section, so treat those two constraints as reported-not-quoted).
- Synchronisation latency: "the synchronization mechanism on iGPU uses cudaDeviceBlockingSync flag, which blocks the CPU thread ... on platforms which requires low latency, cudaDeviceScheduleSpin flag needs to set manually."
- Determinism: "Software managed coherence is by nature non-deterministic and not recommended in a safe context. Zero-copy memory (pinned memory) is preferable in these applications."
- No time-slicing or stream-priority content on this page.

### A2. NVIDIA, Multi-Process Service — Architecture
- URL: https://docs.nvidia.com/deploy/mps/architecture.html
- "Work launched to the compute engine from work queues belonging to different CUDA contexts cannot execute concurrently." The GPU uses "a time sliced scheduler to schedule work from work queues belonging to different CUDA contexts."
- With MPS: "MPS clients submit work directly to the GPU without passing through the MPS server"; Volta+ MPS gives each client its own GPU address space and "limited execution resource provisioning for Quality of Service (QoS)". No numbers.

### A3. NVIDIA forum, "MPS for Jetson AGX Orin" (thread 327036)
- URL: https://forums.developer.nvidia.com/t/mps-for-jetson-agx-orin/327036
- AastaLLL (NVIDIA): "MPS has started to support Jetson from CUDA 12.5." CUDA 12.5 release notes: "MPS (Multi-process service) is now supported on L4T and embedded-Linux Tegra platforms." No performance data.

### A4. NVIDIA forum, "Jetson Orin with JetPack6.1 support MPS?" (thread 317978)
- URL: https://forums.developer.nvidia.com/t/jetson-orin-with-jetpack6-1-support-mps/317978
- Moderator correction: "MPS has been supported on Jetson since CUDA 12.5 so it's available in JetPack 6.1." Binaries `nvidia-cuda-mps-server` and `nvidia-cuda-mps-control` are present; "The nvidia-cuda-mps-server instances are created on-demand when client applications connect to the control daemon." Poster had trouble following the x86 procedure; no numbers.

### A5. NVIDIA/k8s-device-plugin issue #1412, "MPS in K8s does not work on Jetson AGX Orin"
- URL: https://github.com/NVIDIA/k8s-device-plugin/issues/1412
- AGX Orin, JetPack 6.2, device plugin v0.17.3. MPS mode: no GPU resources advertised; control-daemon pods crash with "error getting GPU device minor number: Not Supported". "Time Slicing mode works without issues on the same hardware." MPS "operates correctly outside containers (tested with manual nvidia-cuda-mps-control -d)". Unresolved, "lifecycle/stale".

### A6. NVIDIA forum, "Limitation in number of concurrent CUDA contexts on AGX Orin" (thread 371518)
- URL: https://forums.developer.nvidia.com/t/limitation-in-number-of-concurrent-cuda-contexts-on-agx-orin/371518
- 33rd process calling `cudaFree(0)` fails "CUDA-capable device(s) is/are busy or unavailable"; kernel log `nvgpu ... nvgpu_channel_open_new:1286 [ERR] out of hw chids`. Limit is **32** on AGX Orin and Orin Nano (TX2 ran 48). NVIDIA: "The maximal concurrent CUDA processes/contexts on Orin is 32. But you can create more CUDA streams via multi-threads." Workaround suggested: `CUDA_DEVICE_MAX_CONNECTIONS=1` to reduce channels per context.

### A7. NVIDIA forum, "About GPU Scheduling with Timeslice" (thread 317860, AGX Orin)
- URL: https://forums.developer.nvidia.com/t/about-gpu-scheduling-with-timeslice/317860
- NVIDIA: "each channel will have time slice and when the time slice expires the next available channel needs to be executed"; "each channel Id is corresponding to a context"; priority is implemented by "repeat[ing] the corresponding channel many times in the run list"; "A context switch time out occur when an application can not finished task with in time slice. This causes the channel to reset to allow the next context to be loaded." No millisecond values given.

### A8. NVIDIA forum, "GPU scheduling parameters" (thread 239271, AGX Orin)
- URL: https://forums.developer.nvidia.com/t/gpu-scheduling-parameters/239271
- AastaLLL: "The parameter is only available on the DRIVE OS system. We don't provide such parameters on Jetson to change GPU scheduling behavior."

### A9. NVIDIA forum, "Jetson: GPU resource control (limitation, priority...)" (thread 278057, AGX Orin)
- URL: https://forums.developer.nvidia.com/t/jetson-gpu-resource-control-limitation-priority/278057
- DaneLLL: "For now we don't have the interface on Jetson platforms." Only suggestion: application-level throttling (DeepStream secondary GIEs with larger batch sizes).

### A10. NVIDIA DRIVE OS, "Tegra GPU Scheduling Improvements" and "Runlist Interleave Frequency"
- URLs: https://developer.nvidia.com/docs/drive/drive-os/6.0.9/public/drive-os-linux-sdk/common/topics/graphics_content/TegraGPUSchedulingImprovements1.html ; https://developer.nvidia.com/docs/drive/drive-os/6.0.8.1/public/drive-os-linux-sdk/common/topics/graphics_content/RunlistInterleaveFrequency40.html ; sample app https://developer.nvidia.com/docs/drive/drive-os/6.0.8.1/public/drive-os-linux-sdk/common/topics/graphics_content/RunningtheGPUSchedulingSampleApplication56.html
- Same nvgpu scheduling model as Jetson, but the knobs are DRIVE-only (A8). Three parameters: Timeslice ("maximum time a channel can use an engine uninterrupted"), Runlist interleave frequency ("number of times a channel can appear on a runlist"), Preemption type. Previously "the runlist interleave frequency was fixed at 1", so a high-priority app got "only one scheduling point per iteration of all channels on the runlist".
- Worst-case bound: **"worst-case latency(high) = (h-1) x timeslice(high) + execution time(low) + channel reset"**.
- Priority classes: HIGH = "Small workloads (executable within a display refresh cycle), typically 60 frames/second"; LOW = "Long-running or potentially rogue applications".
- Sample app shows `nvrm_gpusched set timeslice 11600` (global) and `set timeslice -p <pid> 3000`, `set interleave 3`. A search-result summary of the interleave page quotes recommended upper bounds of 1.5 ms (low) and 2 ms (medium) timeslices; the fetched page text did not contain those figures, so treat them as unverified.

### A11. Wang, Liu, Wong, Kim, "GCAPS: GPU Context-Aware Preemptive Priority-based Scheduling for Real-Time Tasks", ECRTS 2024 (UC Riverside)
- URL: https://arxiv.org/html/2406.05221 ; code https://github.com/rtenlab/gcaps-super-repo
- Platforms: Jetson Xavier NX (JetPack 5.0.2) and Jetson Orin Nano (JetPack 5.1.2).
- Default Tegra driver: "the latest Tegra driver uses the same length of time slices for all TSGs" (default **1024 us**); "each process maintains a single TSG entry on each runlist"; runlist round-robin; CUDA stream priority levels "only 2 in the Pascal architecture"; preemption at "pixel level for graphics tasks and the thread-block level for compute tasks".
- Overheads: "GPU context switching can take from 50 to 750 us", measured average "> 200 microseconds" on both boards; runlist update "maximum overhead of about 1 ms".
- Effect of priority-aware preemption: case-study response times on Xavier: task 1 **45.33 ms -> 10.15 ms**, task 2 **66.97 ms -> 22.36 ms**; "up to 40 % higher schedulability"; "more consistent response times for real-time higher-priority tasks". Requires a patched nvgpu driver (JetPack 5-era).

### A12. Wang et al., "Unleashing the Power of Preemptive Priority-based Scheduling for Real-Time GPU Tasks", arXiv 2401.16529 (Jan 2024)
- URL: https://arxiv.org/html/2401.16529v1
- "The runlist is scheduled in a round-robin manner"; "During construction of the runlist, TSGs with higher priority are granted a larger time slice and more entries on the runlist. ... as of this writing, there is no interface provided to configure the time slice length and TSG priority settings from the user space."
- Kernel-thread and IOCTL approaches; overheads "minimum overhead of 16-38 microseconds", "maximum overhead of about 1 ms" on Xavier NX and Orin Nano.

### A13. Bakita & Anderson, "Demystifying NVIDIA GPU Internals to Enable Reliable GPU Management", RTAS 2024 (UNC)
- URL: https://www.cs.unc.edu/~jbakita/rtas24.pdf (read via pdftotext)
- Tested GPUs include Jetson TX2, Jetson Xavier, **Jetson Orin (CC 8.7)**. Tools: `nvdebug` (kernel module, /proc interface, works "including Tegra platforms"), `gpu-microbench`.
- Time-slicing: "Only one task executes instructions at any given time, despite each task requiring only a fraction of the GPU." Discrete GPU: "approximately 20 timeslices per 80 ms ... about 2 ms each." Jetson TX2: "1024 us for a timeslice on compute-associated channels, versus 1049 us for copy-exclusive channels"; the TX2's single runlist makes copies stall for a whole compute timeslice ("the TX2's single runlist is to fault for this strange interference").
- Channels (intra-task parallelism): "as low as two-per-context on NVIDIA's embedded 'Jetson' boards ... Observed as two on the Jetson Xavier with CUDA 10.2, and four on the Jetson Orin with CUDA 11.4. Double this number of channels are created, but CUDA appears to have a bug where only half are used on Jetson boards." Rule R2: "A task's number of channels limits intra-task parallelism."
- MPS footnote: "when MPS is enabled, each application runs as a subcontext of an MPS-created context. Our rules still likely apply if you consider all MPS-using tasks together as a single task, but we have not verified this."

### A14. Bakita & Anderson, "Hardware Compute Partitioning on NVIDIA GPUs", RTAS 2023 (libsmctrl)
- URL: https://www.cs.unc.edu/~jbakita/rtas23.pdf (pdftotext)
- Status of MPS/MIG on embedded at the time: "NVIDIA MPS or MiG can bypass this, but are only available in discrete and server GPUs respectively. Despite repeated calls from academia, NVIDIA has brought neither technology to its embedded chips." (Superseded for MPS by CUDA 12.5, A1.)
- "any GPU of Compute Capability 3.5 (2013) or greater, and CUDA 8.0 (2017) or newer supports TPC partitioning via our libsmctrl library. This includes embedded GPUs, such as that in the ARM64-based NVIDIA Xavier System-on-Chip." Partitioning is per-stream/per-kernel inside a process; the table of tested GPUs stops at Xavier (no Orin row found in the text). Default arbitration: "time-division multiplexing is used to arbitrate among active CUDA and otherwise GPU-using applications (such as display tasks) by default".

### A15. CUDA Programming Guide, stream priorities
- URL: https://docs.nvidia.com/cuda/cuda-programming-guide/03-advanced/advanced-host-programming.html
- "Higher-priority tasks do not preempt already running lower-priority tasks. The GPU does not reassess work queues during task execution, and increasing a stream's priority will not interrupt ongoing work." "When selecting work to launch, pending tasks in higher-priority streams take precedence over those in lower-priority streams." Priorities are hints, "without enforcing strict ordering".

### A16. CUDA Programming Guide, green contexts
- URL: https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/green-contexts.html
- "A green context (GC) is a lightweight context associated, from its creation, with a set of specific GPU resources." "MPS targets different processes, while green contexts is applicable within a single process too." "concurrent execution of independent GPU work is not guaranteed. It is best to think of all the techniques described under the Green Contexts section as removing factors which can prevent concurrent execution." SM-count granularity for Tegra is in a table WebFetch did not render (a search-result summary says multiples of 2 on CC 7.x/8.x and all Tegra SoCs; unverified).

### A17. NVIDIA blog, "What's New in CUDA Toolkit 13.0 for Jetson Thor" (2025)
- URL: https://developer.nvidia.com/blog/whats-new-in-cuda-toolkit-13-0-for-jetson-thor-unified-arm-ecosystem-and-more/
- Thor: MPS "enabling multiple processes to share the GPU concurrently, avoiding the context-switch overhead"; green contexts "pre-assign GPU resources, specifically streaming multiprocessors (SMs) to ensure deterministic execution ... improving predictability in latency-sensitive workloads"; MIG "an upcoming feature in future releases ... so that time-critical modules like SLAM are unaffected by the resource demands of less time-sensitive tasks."
- **"The only exception is Orin (sm_87), which will continue on its current path for now."**

### A18. Chakraborty, Tavernier, Kourtis, Pickavet, Oikonomakis, Colle, "Profiling Concurrent Vision Inference Workloads on NVIDIA Jetson - Extended", arXiv 2508.08430 (Aug 2025)
- URL: https://arxiv.org/html/2508.08430v1
- Devices: Jetson Orin Nano (8 GB) and Jetson Nano; JetPack not stated. States "Jetson GPUs ... do not support MPS. As a result, these devices must rely on either space or time multiplexing" (true before JetPack 6.1; the authors do not say which JetPack they ran).
- ResNet50 int8 on Orin Nano: ~210 img/s single process (bs 1), ~320 img/s (bs 16); with 8 concurrent processes per-process throughput ~10 img/s. YOLOv8n int8: ~210 img/s alone; 16 processes -> ~10 img/s each; GPU memory 3.5x.
- Execution-context duration "increases significantly, by approximately 30x and 70x" with 4 and 8 concurrent processes vs 1-2.
- Utilisation: "GPU utilisation can reach 100 % under specific optimisations, critical low-level resources, such as SMs and tensor cores, often operate only at 15 % to 30 % utilisation"; tensor cores "nearly 30 %".
- CPU side matters: "certain CPU-side events, such as thread scheduling, context switching, etc., frequently emerge as bottlenecks"; kernel launches "20-100 us" each; process blocking time "a dominant factor" at 4+ processes.

### A19. NVIDIA forum, "MPS interference problem" (thread 312930) — dGPU, model unspecified
- URL: https://forums.developer.nvidia.com/t/mps-interference-problem/312930
- One 50 % MPS client: 100 ms. Two 50 % clients: 110 ms and 140 ms (**+10 % / +40 %**). Robert Crovella (NVIDIA): "One possible source would be contention for memory bandwidth". Unresolved.

### A20. NVIDIA forum, "MPS vs no MPS: drastic increase in kernel latency" (thread 336175) — H100, CUDA 12.9
- URL: https://forums.developer.nvidia.com/t/mps-vs-no-mps-drastic-increase-in-kernel-latency/336175
- Softmax kernel alone ~65 us; co-run with a long compute kernel, no MPS: ~65 us (time-sliced, appears concurrent in nsys but is sequential); MPS with no share set: **~100 ms**; MPS with 50 % share: ~65 us. NVIDIA (njuffa): "GPU are not well suited to latency-sensitive use cases." Not Jetson, but it is the clearest record that a misconfigured MPS can add two orders of magnitude of latency.

### A21. Gilman & Walls, "Characterizing Concurrency Mechanisms for NVIDIA GPUs under Deep Learning Workloads", Performance 2021
- URL: https://arxiv.org/abs/2110.00459 (abstract only)
- Ampere dGPU. "the lack of fine-grained preemption mechanisms, robust task prioritization options, and contention-aware thread block placement policies limits the effectiveness of NVIDIA's concurrency mechanisms"; "low, predictable turnaround times [are] difficult on current NVIDIA hardware."

### A22. Ali & Yun, "Protecting real-time GPU kernels on integrated CPU-GPU SoC platforms" (BWLOCK++), ECRTS 2018
- URL: https://arxiv.org/abs/1712.08738 (abstract only)
- Tegra K1: "in the worst case scenario, the GPU kernels can suffer as much as 4X slowdown in the presence of co-running memory intensive CPU applications." Old silicon, but the mechanism (shared DRAM fabric) is the same one the 2025 review cites for Orin: "the Orin's GPU and specialized accelerators (including the DLA, VIC, and PVA) all share a common memory bus" (A23).

### A23. Abdul Majeed & Meribout, "Scheduling Techniques of AI Models on Modern Heterogeneous Edge GPU - A Critical Review", arXiv 2506.01377 (Jun 2025)
- URL: https://arxiv.org/html/2506.01377v1
- Review of layer-pipelining across GPU/DLA on Xavier/Orin; explicitly does not treat time-slicing/MPS/priorities. Useful only for the shared-memory-fabric statement above and for the DLA-offload precedent (Jedi: 128 fps vs 50-55 fps GPU-only on Xavier YOLOv3).

---

## B. CPU-side real-time jitter on AGX Orin under GPU load

### B1. WIM Tech Blog, "Is PREEMPT_RT Enough? Validating Real-Time Performance on Jetson Orin" **[secondary, but a full measurement protocol]**
- URL: https://www.wimcorp.co.kr/tech/en/posts/embedded/preempt-rt-jetson-orin/
- Setup: "Jetson Orin AGX 64GB", JetPack 6.2 (L4T 36.x), "NVIDIA RT Package (OTA)", "MAXN + jetson_clocks", `cyclictest -p 80 -i 1000 -l 600000 -m -a 8-11` (10 min).
- Combined load: non-RT max **318 us**; PREEMPT_RT max **56 us** ("82 % improvement").
- PREEMPT_RT, no isolation, single loads (avg / max): GPU `glmark2` 3.6 / **159 us** (FAIL); EtherCAT 1 kHz DC 3.8 / 113 us; storage `fio` 5.3 / 145 us; `stress-ng` 6.1 / 47 us.
- PREEMPT_RT + `isolcpus=managed_irq,domain,8-11 irqaffinity=0-7 kthread_cpus=0-7`: GPU **15 us**, EtherCAT 6 us, storage 7 us, system 15 us. "All three parameters must be used together for complete isolation." Conclusion: "PREEMPT_RT alone produces jitter spikes exceeding 100us under GPU, Storage, and EtherCAT loads. CPU isolation is mandatory, not optional."

### B2. ProventusNova, "PREEMPT_RT real-time kernel on Jetson Orin - build, latency, and thread setup" **[secondary]**
- URL: https://proventusnova.com/blog/jetson-orin-preempt-rt-real-time-kernel/
- Quiet system, isolated core, 1 kHz, 60 s: "Min: 18 Act: 24 Avg: 21 Max: 87" us. Worst-case table: standard L4T 5.15 "15-30 ms under load"; PREEMPT_RT "150-500 us" under load; quiet "50-120 us". "CUDA workloads on other cores can cause DMA-related IRQ latency spikes: if running CV inference alongside RT control, pin CUDA work to non-RT cores." Requirements: `mlockall(MCL_CURRENT | MCL_FUTURE)` ("without it, page faults in your RT thread can stall for milliseconds"), SCHED_FIFO, pre-faulted 1 MB stack, `CONFIG_PREEMPT_LAZY` off.

### B3. NVIDIA forum, "[JetPack 6.2][AGX Orin 64GB][PREEMPT_RT] Large cyclictest latency variation between different modules, up to 90+ us even with CPU isolation" (thread 381288)
- URL: https://forums.developer.nvidia.com/t/jetpack-6-2-agx-orin-64gb-preempt-rt-large-cyclictest-latency-variation-between-different-modules-up-to-90-us-even-with-cpu-isolation/381288
- Two identical AGX Orin 64 GB modules, L4T 36.4.3, `isolcpus=8-11 nohz_full=8-11 rcu_nocbs=8-11`. Board A ~10 us typical, stable max; board B "Latency quickly exceeds 50 us", "Maximum latency can reach 90 us or higher" even with isolation. DaneLLL (NVIDIA): "The deviation between the two modules are huge. This not not expected." No GPU load in the test; no resolution.

### B4. NVIDIA forum, "Jetson orin AGX PREEMPT-RT RT-test" (thread 330785)
- URL: https://forums.developer.nvidia.com/t/jetson-orin-agx-preempt-rt-rt-test/330785
- Kernel 5.15.148-rt-tegra, `cyclictest -t 8 -D 2h --policy=fifo` with no isolation: min 5-7 us, avg 17-31 us, **max 1074-6221 us**. NVIDIA only suggested comparing against non-RT under `jetson_clocks` + stress.

### B5. NVIDIA forum, "Kernel Crash on Jetson Orin NX Due to Real-Time Priority and cudaStreamCreate" (thread 273906)
- URL: https://forums.developer.nvidia.com/t/kernel-crash-on-nvidia-jetson-orin-nx-due-to-real-time-priority-and-cudastreamcreate-process/273906
- Orin NX, JetPack 5.1.2, `sched_rt_runtime_us=-1`: RT-priority processes calling `cudaStreamCreate` on CPU0 hang CPU0 and crash the kernel. NVIDIA: "If the cuda stream causes the kernel crash with a high ratio, please launch the application on other cores. This issue looks more like a limitation rather than a bug."

### B6. NVIDIA Jetson Linux r36.4 Developer Guide, Kernel Customization (RT kernel)
- URL: https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/Kernel/KernelCustomization.html
- RT kernel via OTA packages `nvidia-l4t-rt-kernel nvidia-l4t-rt-kernel-headers nvidia-l4t-rt-kernel-oot-modules nvidia-l4t-display-rt-kernel`; "The UEFI runtime services are enabled by default which may increase latency. ... We do not recommend using UEFI runtime services while running RT applications." No GPU caveats listed.

---

## C. NVIDIA multi-model demos and single-tenant baselines

### C1. Jetson AI Lab, llamaspeak (archive)
- URL: https://www.jetson-ai-lab.com/archive/tutorial_llamaspeak.html
- "overlapping ASR/LLM/TTS generation and verbal interruptability"; hardware "Jetson AGX Orin (64GB) Jetson AGX Orin (32GB) Jetson Orin NX (16GB)"; "22GB for nano_llm container image", models ">10GB", NVMe recommended. Riva (ASR/TTS) container + NanoLLM/MLC LLM. **No latency or tok/s numbers.**

### C2. Jetson AI Lab, Agent Studio (archive)
- URL: https://www.jetson-ai-lab.com/archive/agent_studio.html
- "each plugin runs asynchronously its own thread and queue of data ... Usually they're in the same process, but could make requests to microservices." Supports LLM + VLM + ASR + TTS + vision simultaneously on AGX Orin 64/32, NX 16, Nano 8. "keep an eye on the system resources ... models are cached in memory even after you remove them". **No performance numbers.**

### C3. Jetson AI Lab, Multi-Modal AI Studio (Thor)
- URL: https://www.jetson-ai-lab.com/tutorials/multi-modal-ai-studio/
- "written for Jetson AGX Thor because it uses the RIVA SDK and Cosmos-Reason2-8B together on the same device." Riva `parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer` ASR + `magpie_tts_ensemble_Magpie-Multilingual` TTS + Cosmos-Reason2-8B on vLLM (`--gpu-memory-utilization 0.7`, `--max-model-len 8192`); separate containers on ports 50051 / 8010 / 8092. Has a TTFA / turn-taking timeline tool but **publishes no numbers**.

### C4. Jetson AI Lab, "GenAI Benchmarking: LLMs and VLMs on Jetson"
- URL: https://www.jetson-ai-lab.com/tutorials/genai-benchmarking/
- vLLM `bench serve`, `RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16`, `gpu-memory-utilization 0.8`: single user **44.19 tok/s output, mean TTFT 32.02 ms, mean ITL 22.47 ms** (50 requests, 10,303 tokens). "Going from concurrency 1 to 8, the Output Token Throughput should increase significantly ... the Mean TTFT and Mean ITL will also likely increase." Concurrency-8 numbers not shown.

### C5. NVIDIA blog, "Getting Started with Edge AI on NVIDIA Jetson: LLMs, VLMs, and Foundation Models for Robotics" (11 Dec 2025)
- URL: https://developer.nvidia.com/blog/getting-started-with-edge-ai-on-nvidia-jetson-llms-vlms-and-foundation-models-for-robotics/
- "gpt-oss-20b on Jetson AGX Orin: 40 tokens/sec generation speed via Open WebUI"; AGX Orin 64 GB listed for gpt-oss-20b, quantized Llama 3.1 70B, LLaVA-13B, Qwen2.5-VL-7B. GR00T: "sub-30 ms latency" via TensorRT (note: the GR00T README's own Orin number is 150.9 ms, C6, so the 30 ms figure is a dGPU/Thor-class claim). Mentions combining "vision, language, and speech (ASR and TTS) models on a single device" with no co-run numbers.

### C6. NVIDIA/Isaac-GR00T, scripts/deployment/README.md
- URL: https://github.com/NVIDIA/Isaac-GR00T/blob/main/scripts/deployment/README.md
- GR00T N1.7-LIBERO 3B, bf16, 4 denoising steps, 1 camera, E2E: **Jetson Orin 354.0 ms (2.8 Hz) eager -> 150.9 ms (6.6 Hz) TensorRT full pipeline**; AGX Thor 112.8 -> 80.4 ms (12.4 Hz); H100 85.8 -> 27.9 ms (35.9 Hz). LIBERO success PyTorch 100 % vs TRT 95 % ("within simulation noise").

### C7. NVIDIA forum, "Real-Time Inference on Thor & RTX: Pi0.5 / GR00T N1.6/1.7, Thor 23 Hz, RTX 5090 50-80 Hz" (thread 368788)
- URL: https://forums.developer.nvidia.com/t/real-time-inference-on-thor-rtx-pi0-5-gr00t-n1-6-1-7-thor-23-hz-rtx-5090-50-80hz/368788
- Independent developer with hand-written CUDA kernels: Thor pi0.5 **44 ms (23 Hz)**, pi0 46 ms; RTX 5090 pi0.5 17.58 ms (57 Hz); GR00T N1.6 Thor 41-45 ms (22-24 Hz), 5090 12.5-13.1 ms; pi0-FAST Thor 8.1 ms/token. No Orin numbers, nothing else co-running.

### C8. NVIDIA blog, "Delivering Server-Class Performance at the Edge with Jetson Orin" (2023)
- URL: https://developer.nvidia.com/blog/delivering-server-class-performance-at-the-edge-with-nvidia-jetson-orin/
- "PeopleNet and DashcamNet provide examples of dense models that can be run concurrently on the GPU and the two DLAs. The DLA can be used to offload some AI applications from the GPU and this concurrent capability enables them to operate in parallel." No concurrent-mode numbers.

### C9. NVIDIA blog, TensorRT Edge-LLM (8 Jan 2026)
- URL: https://developer.nvidia.com/blog/accelerating-llm-and-vlm-inference-for-automotive-and-robotics-with-nvidia-tensorrt-edge-llm/
- Qwen3 + EAGLE-3 speculative decoding, NVFP4, chunked prefill; chart only, no numbers in text; nothing on multi-tenancy.

---

## D. Robotics stacks that co-schedule inference with a controller on Orin

### D1. Williams, Gupta, George, Sarkar, "LiteVLA-Edge: Quantized On-Device Multimodal Control for Embedded Robotics", arXiv 2603.03380 (Mar 2026)
- URL: https://arxiv.org/html/2603.03380v1
- "NVIDIA Jetson AGX Orin (64GB)"; SmolVLM-256M, LoRA r=8, "4-bit (Q4_K_M) GGUF"; latency **mean 150.5 ms, sigma 0.125 ms ("sigma<0.2 ms"), min 150.4 ms, max 151.0 ms, 6.64 Hz**. ROS 2 node "subscribes to camera feeds and publishes velocity commands asynchronously ... while the VLA 'thinks' at 6.6 Hz, the low-level robot controller can maintain a steady 100 Hz heartbeat." This is the only AGX Orin 64 GB jitter measurement found; it is single-tenant on the GPU (the controller is CPU-side).

### D2. Same authors, "LiteVLA-H: Dual-Rate VLA Inference for Onboard Aerial Guidance and Semantic Perception", arXiv 2605.00884 (May 2026)
- URL: https://arxiv.org/html/2605.00884
- AGX Orin, FP16, 2048-token context. Action loop "Single action token in 50.65 ms, corresponding to 19.74 Hz"; semantic responses "149.90-164.57 ms, corresponding to 6.08-6.67 Hz"; semantic period = K x action period, K = 3; "action queries are admitted immediately, while semantic queries are opportunistic and non-blocking". Prefill ~47.8 ms, 1.4 ms/token, prefill fraction 0.944. Memory 2.2 GB; power 22.1 W dual-rate (18.5 W action-only, 24.2 W semantic-only). **No jitter / cross-rate interference reported.** One process, time-partitioned; no streams/priorities described. CC BY 4.0.

### D3. Yang et al. (PKU / PrimeBot / AIRS), "Jetson-PI: Towards Onboard Real-Time Robot Control via Foresight-Aligned Asynchronous Inference", arXiv 2607.12659 (2026)
- URL: https://arxiv.org/html/2607.12659v3 ; code github.com/PKU-SEC-Lab/Jetson-PI
- pi0 / pi0.5 on Jetson Orin (30 W / 50 W) and Thor. Orin: control frequency **0.70 Hz -> 6.06 Hz** (8.66x vs naive PyTorch, 5.41x vs vla.cpp); reaction time **1420.8 ms -> 165.1 ms**; +14.8 % LIBERO success vs VLASH. Asynchronous inference "parallelizing action execution and subsequent inference" with a future-correction module. CC BY 4.0.

### D4. Pohland et al. (UC Berkeley / Microsoft), "Offload or Overload: A Platform Measurement Study of Mobile Robotic Manipulation Workloads", arXiv 2603.18284 (Mar 2026)
- URL: https://arxiv.org/html/2603.18284
- "Nvidia Jetson Orin AGX with 32GB" and Thor 128 GB vs A100 offload. pi0.5 **440 ms on Orin vs 60 ms on A100**; task accuracy "drops to 30 % on the Orin" from 80 %; "jerkiness" observed. Full stack (VLMaps + pi0.5 + GraphEQA + RTAB-Map/nvblox + DreamZero) "requires a minimum of approximately 50GB of memory". No concurrent-execution jitter data; "modern robotics workloads require GPUs beyond what is typically fitted on board robots today".

### D5. Wang, Liang, Li, Zhou, Rasmussen, "History-Conditioned Spatio-Temporal Visual Token Pruning for Efficient VLN", arXiv 2603.06480 (Mar 2026)
- URL: https://arxiv.org/html/2603.06480
- "ran StreamVLN completely onboard the robot on an NVIDIA Jetson Thor T5000" (Unitree Go2). "average inference time for a batch of 4 actions was ~1.43 s (0.70 fps) without pruning and ~1.25 s (0.80 fps) with pruning"; "separate inference and motor controller threads" giving "only small pauses in otherwise continuous motion"; Isaac ROS Visual SLAM on 3 hardware-synced cameras ran concurrently. No jitter numbers.

### D6. "Learning Diverse Natural Behaviors for Enhancing the Agility of Quadrupedal Robots", arXiv 2505.09979 (May 2025)
- URL: https://arxiv.org/html/2505.09979v1
- "Unitree Go2 robot, which is equipped with a Jetson Orin NX, an Intel RealSense D435i"; "stable control frequency at 50 Hz"; "motors executing torque at a rate of 1000 Hz"; "image processing and policy inference ... completed within each 20ms cycle"; "all computations are accelerated using CUDA"; Cyclone DDS + LCM. No measured latency distribution.

### D7. "Quadruped robot traversing 3D complex environments with limited perception", arXiv 2404.18225
- URL: https://arxiv.org/html/2404.18225
- Go2, "policies are executed on the onboard NVIDIA Jetson Orin Nano of the Go2", "control frequency of 50Hz", PD to torque. No latency numbers.

### D8. Zhang et al. (NTU), "RoamFlow: Reinforcement-Aligned One-Step Action MeanFlow Policy for Image-Goal Navigation", arXiv 2606.29934 (2026)
- URL: https://arxiv.org/html/2606.29934
- "Unitree Go2 quadruped equipped with an NVIDIA Jetson Orin NX (16GB)", D435i, ROS1 Noetic; "the whole navigation and control loop is executed onboard at a frequency of 10 Hz"; real-world inference 37.2 ms; "The inference latency consistently remains below 100 ms. Despite minor jitter in computation timing, the system maintains a stable inference rate." CC BY 4.0.

### D9. "Visual Embodied Brain (VeBrain)", arXiv 2506.00123 (Jun 2025)
- URL: https://arxiv.org/html/2506.00123
- Go2 + D435i + Jetson AGX Orin onboard: Locotrack-small point tracker "15Hz execution frequency" + low-level locomotion controller onboard; the MLLM runs "on a Tesla A100 GPU in the cloud, running at 0.5Hz". The split (heavy model off-board, tracker + controller on the Orin) is itself the finding.

### D10. Venkatesha, Kundu, Panda, "Fast and Cost-effective Speculative Edge-Cloud Decoding with Early Exits", arXiv 2505.21594 (May 2025)
- URL: https://arxiv.org/html/2505.21594
- Go2 with "an onboard NVIDIA Jetson Orin board, which includes an 8-core ARM Cortex-A78AE ... and 16GB of 128-bit LPDDR5" (i.e. the EDU's Orin NX 16 GB); quantized Qwen-2-VL-2B draft on device, Qwen-2-VL-7B on A100. Table 8(a): **drafting latency 288 ms (gamma = 4), verification 620 ms, communication 120 ms**; "21 % speedup over conventional cloud-based autoregressive decoding". Locomotion concurrency not addressed.

### D11. "Hardware- and Vision-in-the-Loop Validation of Deep Monocular Pose Estimation for Autonomous Maritime UAV Flight", arXiv 2606.19176 (2026)
- URL: https://arxiv.org/html/2606.19176
- Jetson Orin NX: pose network alone **5.5 Hz (0.18 s)**; "When the flight controller (FC) is also running onboard and competing for CPU resources, the rate decreases to 4.7 Hz (average inference time 0.21 s)"; "achievable update rates are constrained not only by network architecture but also by GPU utilization, CPU scheduling, memory bandwidth, and operating conditions such as temperature and concurrent processes." One of the few explicit co-run slowdown numbers on an Orin.

### D12. Khandelwal, "Multi-Model AI Resource Allocation for Humanoid Robots: A Survey on Jetson Orin Nano Super", dev.to (Jan 2024) **[secondary]**
- URL: https://dev.to/ankk98/multi-model-ai-resource-allocation-for-humanoid-robots-a-survey-on-jetson-orin-nano-super-310i
- Aggregates A19/A20 (the +10-40 % and 65 us -> 100 ms MPS anecdotes), NVIDIA power docs, OM1/LeRobot/Reachy repos. Author's own (uncited) numbers: "~1-2ms per inter-model communication" serialization; targets 24 Hz VLA / 5 Hz perception. Recommendation: "avoid static hardware partitioning as your primary tool. Favor event-driven architectures with prioritized CUDA streams and async messaging".

### D13. HackMD, "Configuring Unitree Go2 EDU for Real-Time Voice Interaction with OpenAI" **[secondary]**
- URL: https://hackmd.io/@c12hQ00ySVi6JYIERU7bCg/ByAOr12qJg
- Go2 EDU head has mic array + 3 W speaker; stock BenBen assistant is cloud GPT-3.5; "no official SDK endpoints to directly access the voice recognition or TTS engine"; expected "~3 seconds" end-to-end. Nothing on-device; included only to record that no Go2 EDU deployment with on-device speech + locomotion co-scheduling was found.

---

## E. What this means for Parcel

1. **Treat the Orin GPU as a single time-sliced core, not a pool.** Across processes there is no kernel-level concurrency (A2, A13); the quantum is ~1 ms (A11, A13), each switch costs 50-750 us (A11), and NVIDIA exposes no timeslice or per-process priority knob on Jetson (A8, A9, A12). With N GPU-active processes, a kernel that needs t ms of GPU time can take up to roughly N x t ms of wall time plus switches. For a full-duplex speech model stepping every 80 ms, three other GPU tenants (VLM, ASR, TTS) can therefore inflate one step by several ms of switching and by whatever GPU time those tenants burn in the same window; the DRIVE formula (A10) is the right mental model: worst-case latency(high) = (h-1) x timeslice + execution time(low) + reset.

2. **Keep the 50-500 Hz controller entirely off the GPU and on isolated CPU cores.** Every Go2 stack found runs the locomotion policy on CPU-scale compute (Orin NX / Orin Nano) at 50 Hz with a 200-1000 Hz motor loop (D6, D7, D8), and the only AGX Orin jitter measurement with a controller alongside a VLA has the controller on the CPU side (D1). Measured recipe for AGX Orin 64 GB: RT OTA kernel + `isolcpus=managed_irq,domain,8-11 irqaffinity=0-7 kthread_cpus=0-7` + `mlockall` gives max 15 us under GPU load, versus 159 us without isolation and 318 us on the stock kernel (B1, B2). Never give a CUDA-initialising thread RT priority on CPU0 (B5). Budget for a 90 us outlier because module-to-module variance exists (B3), and validate each physical module with cyclictest before trusting it.

3. **Collapse GPU tenants into one process with streams, or use MPS deliberately.** NVIDIA's own multi-model demos do exactly this: Agent Studio runs ASR/LLM/TTS/VLM plugins as threads in one process (C2); llamaspeak overlaps ASR/LLM/TTS on an AGX Orin 64 GB (C1). Stream priorities are non-preemptive hints (A15) but they do pick the next launch, which is enough when each kernel is short. MPS on Orin (JetPack >= 6.1) is the escape hatch for multi-process designs (A1, A3), but there is no Orin measurement of it, dGPU reports show +10-40 % per client from memory-bandwidth contention (A19) and 100 ms stalls when misconfigured (A20), and container tooling is broken on Orin (A5). If Parcel uses MPS, set explicit active-thread percentages and measure.

4. **Orin will not get the Thor determinism features.** Green contexts + MPS + MIG are the Thor story; "Orin (sm_87) ... will continue on its current path for now" (A17). SM partitioning on Orin is limited to intra-process green contexts with no concurrency guarantee (A16) or the research libsmctrl (A14). Design for time-slicing, not spatial isolation.

5. **Memory bandwidth, not memory size, is the shared bottleneck.** 64 GB fits the whole stack (llamaspeak needs a 22 GB container plus >10 GB of models, C1; a full manipulation stack needs ~50 GB, D4), but GPU, DLA, CPU share one 204.8 GB/s fabric (A23) and the +10-40 % MPS contention was memory-bandwidth-attributed (A19). Single-stream LLM decode is bandwidth-bound, so every co-tenant steals decode tokens/s from the speech model. Offloading detectors to the two DLAs is the documented (unquantified) relief valve (C8).

6. **Expect single-tenant VLA latencies of 150-440 ms on Orin, and design the act-token stream around asynchrony.** GR00T N1.7 150.9 ms TRT (C6), LiteVLA-Edge 150.5 ms (D1), pi0.5 440 ms with accuracy collapse and jerkiness (D4), Jetson-PI's asynchronous scheme recovering 6 Hz from 0.7 Hz (D3), LiteVLA-H's K = 3 dual-rate partition (D2). For Parcel, the speech/act model's slow "semantic" path and fast "act" path should be admitted at different rates in one process, and the body controller should interpolate/hold across late act tokens rather than block.

7. **The AGX Orin 64 GB co-tenancy number Parcel needs does not exist in the literature.** Nobody has published "speech LLM + VLM + ASR + TTS on one AGX Orin with per-step jitter". The closest are: single-tenant sigma 0.125 ms (D1), Orin Nano 30x/70x context inflation at 4/8 processes (A18), Orin NX 5.5 -> 4.7 Hz with a CPU co-tenant (D11). The cheapest way to close it is a two-day microbenchmark on the dev Orin: cyclictest on isolated cores + a 1 kHz CUDA "heartbeat" kernel logger (Bakita's exec_logger pattern, A13) while the candidate speech model decodes, then add the VLM and ASR one at a time and record per-step p50/p99. That experiment should be a gate before committing to the one-clock speech+act design on a single Orin.

8. **Process-count hygiene.** The 32-context ceiling (A6) is far away for five models, but a ROS 2 graph in which many nodes each open CUDA (Isaac ROS, camera, SLAM, detectors) can reach it; set `CUDA_DEVICE_MAX_CONNECTIONS` deliberately and keep GPU-using nodes few.

## F. Gaps and caveats
- No primary measurement of MPS on any Orin; no measurement of stream-priority effectiveness on Orin under an LLM decode load; no AGX Orin 64 GB multi-model jitter study. The GCAPS numbers are JetPack 5 (nvgpu of L4T R35); the JetPack 6 driver may differ in detail but NVIDIA's forum answers in 2024-2026 (A7-A9) describe the same runlist/timeslice model.
- Two numbers came only from search-result summaries and could not be re-quoted from the fetched page: the DRIVE-doc 1.5 ms / 2 ms timeslice recommendations (A10) and the Tegra MPS limitations (`-multiuser-server`, driver-package coupling) (A1). Both are flagged inline.
- B1 and B2 are vendor/consultancy blogs, not papers; B1's protocol is complete enough to reproduce.
