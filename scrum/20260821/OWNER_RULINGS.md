# Owner rulings — standing scope decisions

Rulings the owner has made that bind future cards. Cite these by name; do
not re-litigate them, and do not quietly build past them.

## 2026-08-21 — English only, no i18n expansion yet

**Verbatim:** "No need to have Korean or i18n expansion just yet. Let's just
focus on the english work."

**What this closes.** The multilingual reply-language question that had been
owner-gated since the 2026-08-20 voice corpus run (the robot understood
"가까운 벤치로 가 줘" and produced a correct `navigate_to` in 408 ms, but
replied in English and broke an explicit promise to report back). No
reply-language policy will be designed, and no i18n work is queued.

**What it changes now.** Corpus rows 51 and 52 (`language-probe`) are
**NOT SCORED** — retained as recorded probes so the evidence is not lost,
but they may not count as pass or fail in any eval verdict, and a future
eval must not report them as capability gaps.

**What it deliberately does NOT change.**
* **Speech identity (F1-SI) stands unchanged.** The TV that hijacked two
  sessions happened to be Korean, but the defect is *speaker* identity, not
  language — an English-language TV would hijack identically.
* **The eval suite's Unicode script-anomaly check stays.** It is a
  DETECTOR of non-owner speech, not an i18n feature; it is one of the two
  signals that caught the TV deterministically.
* Nothing in the ASR/transcription path is restricted — the robot may still
  hear whatever it hears; this ruling is about what we BUILD, not about
  what the microphone is allowed to receive.

**If revisited:** the honest first step would be a reply-language policy
(match the owner's language / always English / owner-configured), then a
corpus expansion with native-speaker gold labels — not a prompt tweak.
