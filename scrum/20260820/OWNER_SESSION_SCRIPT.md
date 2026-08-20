# Owner session 1 — the first spoken conversation

**Setup:** `./scripts/launch_stack.sh` → http://127.0.0.1:8765 → click the
microphone affordance (that's the arming gesture; the paid session opens on
your first words) → allow mic in the browser. Headphones recommended.
Keep the panel focused for Space to work; clicking to the MuJoCo window is
safe now (the mission-killing blur bug is fixed).

Say things in your own words — these are prompts, not incantations. Note
anything that feels wrong; that's the deliverable.

---

## 1 · Warm-up (is it a companion or a terminal?)
- "Hey, how are you doing today?"
- "What do you see around you?"
- "What's your favorite thing about New York?"

*Listen for:* warmth and personality, ~1s replies, no robotic templates.

## 2 · Navigation — the core claim
- **"Go to the sidewalk."**
  Expect: friendly reply → scan in place (that's target search, not
  confusion) → walks → **ends standing ON the sidewalk**. Watch the Mission
  log fill. If a pedestrian blocks it, **it should tell you unprompted**.
- **"Go to the lamppost."**
  Expect: stops *near* it, doesn't try to stand on it.
- ⚠️ **Skip "go to the door"** — no scene has a door yet; it will honestly
  say it can't find one. (Defect card filed.)

## 3 · The new tools
- **"Circle around me."** → orbits you (proven: 354.7° sweep).
- Move your avatar next to an obstacle, then ask again → it should
  **refuse and say why** ("there isn't room on your left").
- **"Run with me."** → follows at running pace. Then slow to a walk and
  keep chatting. It *should* ask whether to just walk — ⚠️ known bug, may
  stay silent. Either outcome is useful data.

## 4 · Body and mind
- "Wave at me please." · "Take a bow." · "Sit."
- "What are you doing right now?" · "How's your battery?"
- "What do you remember about me?"

## 5 · Interruption
- Talk over it mid-sentence → it should stop speaking and listen.

## 6 · Safety drill (do this last, once)
- Start a mission ("go to the sidewalk"), then say **"Die Stop."**
  Expect: everything halts, red banner latches.
  ⚠️ Mission log will read `navigation_disabled` — R12 fixes that wording.
- Press the release button → give a new command → confirm it moves again.
- Bonus: **Space bar** does the same latch (panel must be focused).
- Sanity check: say *"let's stop by the store"* — must **not** latch.

---

## Afterward, tell me in plain words
1. What felt genuinely good?
2. What felt wrong, awkward, slow, or fake?
3. Anything it said that wasn't true?
4. Anything you wanted to say but couldn't?

Everything is auto-recorded (transcripts, paths, mission log, whisperer
decisions). I'll package it into `evals/20260820/owner_session_1/`.
