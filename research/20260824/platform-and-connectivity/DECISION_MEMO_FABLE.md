# H10 — platform and connectivity · decision memo (Fable) · 2026-08-24

Owner's questions: (a) can the body hold the cognition without gemma-26B;
(b) Unitree Go2 EDU Plus vs Deep Robotics X30 Pro (AGX Orin); (c) does either
support 5G — Wi-Fi will not always exist; (d) the dog must keep basic
capabilities offline. This memo is desk research + budgets; nothing here is
measured on hardware (none is on hand). Every fact carries its source or an
UNVERIFIED tag.

## 1. Facts

| | Unitree Go2 EDU Plus (ordered) | Deep Robotics X30 Pro |
|---|---|---|
| Compute | Jetson Orin NX, 100 TOPS, **16 GB** (vendor "Orin (40–100 TOPS)" optional module on EDU; EDU Plus = 100 TOPS) | Jetson **AGX Orin**, 275 TOPS (memory 32 or 64 GB — UNVERIFIED which) |
| Cellular | **4G module with GPS / eSIM** on PRO/X/EDU (unitree.com/go2); **no 5G** listed anywhere | resellers list **"4G/5G support"** (robotshop, robotsusa); the vendor's own spec page lists no cellular at all — UNVERIFIED |
| Wi-Fi / BT | Wi-Fi 6 dual-band, BT 5.2 | Wi-Fi (version unlisted) |
| Body | ~15 kg, payload ≈ 8 kg (max ~12), battery 8,000 mAh, **1–2 h**, L2 LiDAR (owner also ordered a Mid-360) | 56–59 kg, payload 45 kg (85 max), **2.5–4 h**, ≥ 4 m/s, ≤ 45° slope, 20 cm obstacles, IP67, −20…55 °C, RTK |
| Price | ≈ $17k with Mid-360 (owner's PO record) | "contact sales" — industrial inspection class; expect well above $100k (UNVERIFIED) |
| Character | companion form factor, indoor-safe mass | industrial inspection platform; 56 kg at 4 m/s is not a living-room companion |

Sources: unitree.com/go2 (fetched 2026-08-24); robostore/robotshop/stemfinity
Go2 EDU Plus pages; deeprobotics.cn product page (fetched; no compute or
cellular listed); robotshop/robotsusa/robotsinternational X30 pages; The
Robot Report launch article (AGX Orin 275 TOPS).

## 2. Can the body hold the cognition? (measured on the desk GPU, 2026-08-23/24)
- gemma-26B Q4: **15.3 GB VRAM** resident; 855 ms TTFT, 5.7 s usable plan;
  cannot fit an Orin NX 16 GB beside anything. Fits an AGX Orin 32 GB alone
  (tight, no perception) or 64 GB comfortably.
- Ministral-8B Q4: **6.2 GB**; talker TTFT 126 ms; PlanSketch 3/5; monologue
  agreement 0.40 (H2). Fits the Orin NX with whisper + piper + Silero and a
  small perception model (OWLv2 int8 CPU is 560 ms/frame; fp16 needs a
  GPU EP the Orin lacks a wheel for — TensorRT build is a packaging card).
- Conclusion: **the 26B is a desk/cloud-class model**, not an on-body one on
  the ordered hardware. The on-body brain is an 8B-class normalizer + the
  deterministic compound grammar (H9), and the hosted lane when a link
  exists. That is exactly the "degraded but present" the owner asked for.

## 3. 5G — buy it as a payload, not as a platform
Neither vendor gives the companion form factor *and* 5G. But 5G is a
commodity accessory: a USB/Ethernet 5G router (≈ $200–400, 200–400 g) on
the Go2's payload rail (16–60 V, USB3, GbE), or — zero engineering — the
Orin joins a **5G phone's Wi-Fi hotspot**. Latency to the hosted lane over
5G is 30–80 ms typical; the realtime lane already tolerates 350 ms socket
lag (DUPLEX-1 measured duck latency flat to 350 ms). The link-loss ladder
(§5) is what makes this safe, not the radio.

## 4. Recommendation
1. **Keep the Go2 EDU Plus.** It is the companion body; the X30 Pro's two
   advantages (AGX Orin, 5G) are both purchasable as Go2 payloads, and its
   mass/speed/price class is wrong for a living-room dog.
2. **Add a 5G router on the payload rail** (or hotspot for the prototype);
   treat cellular as the *normal* link and Wi-Fi as a bonus.
3. **Decide the on-body compute after H9**: if the 8B + grammar floor meets
   O1/O2 (≥ 0.90 PlanIR validity), the Orin NX is enough and the 26B stays
   on the desk/cloud tier; if not, mount a **Jetson AGX Orin 64 GB dev kit
   as a payload** (≈ 1.5 kg incl. heatsink, 15–60 W from the rail —
   UNVERIFIED, within the 8 kg budget) and run the 26B on the body.
4. **The custom robot** designs its compute bay for an AGX Orin 64 GB (or
   successor) and a cellular module from day one; the seams (H4 body
   contract, H7 localization contract, `LocomotionController`) do not care.

## 5. The link-loss ladder (binding for the milestone design)
Each rung is a typed capability manifest the conversation narrates ("I'm
off the network; I can still…"); transitions are automatic on link health
and never mid-motion (finish the leg or hold).

| rung | link state | brain | what works |
|---|---|---|---|
| L0 | cloud + desk (Wi-Fi/5G) | hosted mini answers; desk 26B deliberates, distills; desk GPU perception | everything in M1 |
| L1 | desk only (LAN, no cloud) | desk 26B answers and plans; desk perception | all but hosted-quality conversation |
| L2 | body only (no link) | **[SUPERSEDED by the owner's simplified floor + Codex cross-review]** no LLM required: local STOP/HOLD, the canned offline line, previously commissioned known-goal motion, Follow only after its perception spine + identity gate pass; the optional local 8B is degradation capacity and the first resident model removed under memory/thermal pressure | STOP, HOLD, canned narration, commissioned local behaviors only |
| L3 | thermal/battery floor | no LLM | closed intents (stop/come/sit), follow, hold, narrate state |
H9's O5 row measures L2 end-to-end with the network blocked.

## 6. What this memo does not settle
X30 Pro compute memory and cellular are UNVERIFIED on the vendor page; the
AGX Orin payload's weight/power on a Go2 is unverified; 5G coverage indoors
is site-specific; nothing here was run on hardware.

## Codex cross-review for Fable · 2026-08-24

**PROVISIONAL desk memo, not a purchase or deployment fact.** Vendor compute,
payload power, exposed interfaces, SDK entitlement, mounting and warranty
remain subject to written confirmation and box-day inspection. The rich L2
offline floor is also stale relative to the later owner re-scope; the first
body-only floor should be local STOP/HOLD, safe manual or known-goal motion,
Follow only after its perception spine passes, and honest offline narration.

The architectural consequence is stronger than the platform choice: desk
and cloud compute are optional accelerators. Body-local safety, state
estimation, event capture, minimal perception, gateway and durable event
logging must survive their loss. AGX capacity may improve models but cannot
repair a missing power/thermal/deployment design.
