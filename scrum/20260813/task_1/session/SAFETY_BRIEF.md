# Safety brief — first physical session, sensor-only

> **Read §1–§5 aloud, to everyone present, before the dog is powered.**
> Then sign §7. It takes four minutes.

**Card:** PS-F, tranche PS-1 · **Written:** 2026-08-13 · **Blank by design —
this brief has not been delivered.**
**Belongs to:** [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §5, §8, §9.

---

## 1 · The one thing to understand about today

**Today's hazards are mechanical, not autonomy.**

Nothing in Parcel's software will command this robot. The capture stack
subscribes and never publishes; it constructs no motion client, holds no
lease, and the vendor SDK is not installed in any Parcel environment
(verified: `import unitree_sdk2py` → `ModuleNotFoundError`). The autonomy risk
today is close to nil, and treating the session as an autonomy risk is how you
end up unprepared for what actually hurts:

**a 15 kg quadruped standing up with an unsecured 1–2 kg computer bolted to
it, a snagged cable, and a hand in a joint gap.**

Those three, in that order. Plan for those.

---

## 2 · The envelope — what is authorised today

**Authorised:** the dog powered, **seated or on blocks**, publishing sensor
data. Parcel software recording, read-only. Tape measurement and photography
with the dog **off**.

**Authorised only after the pre-stand gate** (`STAGE0_RUN_SHEET.md` §8) **and
a second stop verification** (§9): an operator-initiated **stand and sit**
under the **vendor handheld**, feet stationary, no gait, no locomotion.

**Not authorised, at any point, by anyone, today:** locomotion · gait ·
teleoperation through Parcel · arming · autonomy of any kind · stairs ·
leaving the mat · flashing firmware · installing anything on the single Orin ·
installing `unitree_sdk2py` anywhere.

If someone proposes an activity that is not on the "authorised" list, the
answer is **no**, and it is not a negotiation. It goes on the list for a later
session with a written plan.

---

## 3 · Hazards, in the order they are likely to bite

### H1 — Unsecured payload (**the most likely incident today**)

An Orin, a camera, a LiDAR and a battery bolted to a machine that lurches
upward. Anything held by tape, friction, a cable tie under tension, or "it's
fine, it's wedged in" **will** move when the dog stands, and it will move
again, harder, when the dog is stopped and drops.

*Control:* pre-stand gate S1/S2. Firm two-finger pull test in **every** axis
on **every** item. Fasteners, not friction. Nothing overhanging a leg's sweep.

### H2 — Cable snag

A cable that crosses a hip or knee sweep, runs under the trunk, or lies where
a foot can land will be yanked. Consequences, in ascending order: a lost
channel mid-record (which PS-B may report as a *dropout* when it was actually
a *human tripping over a wire*), a destroyed connector, a payload pulled off,
a destabilised dog.

*Control:* S3/S4. Service loop at every connector and an anchor **within
100 mm of it**, so a pull loads the anchor and not the plug. Trace every cable
end to end with a finger and say the route aloud. Nothing across the floor
where someone walks.

### H3 — Pinch points

Hip and knee joints, and the trunk-to-leg gap, close with real force and no
warning. This includes closing on a **cable or a tie-wrap tail**, not just on
fingers.

*Control:* S5, S8. Hands out of the leg envelope whenever the dog is powered.
No cable routed through a joint gap. Trim tie-wrap tails.

### H4 — Unexpected motion from a powered dog

**Treat every powered Go2 as capable of moving without a command from you.**
It can be commanded by the handheld (including by a bump of a stick), it can
self-right, and a stop press causes a rapid, uncommanded change of posture.
"Parcel isn't driving it" is **not** the same as "it will not move".

*Control:* the second's hand stays on stop #2 whenever the dog is powered.
Never place a hand or a head under the trunk. Handheld sticks are not left
where they can be knocked.

### H5 — The stop press drops a standing dog

An emergency damp on a standing quadruped means the legs give way and the
trunk falls — and the **payload comes down with it**, from ≈0.3 m, onto
whatever is underneath. The D455 on its bracket is likely the first thing to
hit.

*Control:* S7 padded mat under the dog **before** any stand. S9: everyone
states aloud, before the first stand, that the payload is expendable from that
moment. Do the standing stop test **once, deliberately, over the mat**, with
the recorder running. If you are not willing to drop the payload, **do not
stand the dog** — the seated take is a complete Stage-0 record.

### H6 — Electrical: powering the Orin

A mis-wired barrel jack or a wrong-voltage supply destroys the Orin silently
and instantly, and the session ends there.

*Control:* verify voltage **and polarity** with a meter **before** the
connector is mated, every time, including after any re-plug. No hot-plugging
of power. If the Orin is fed from the Go2's payload port, confirm the port's
rating against the Orin's draw and write both numbers in the run sheet §10.

### H7 — Battery

LiPo packs. Do not charge unattended, do not leave a pack on a hot surface, do
not use a pack that is swollen, dented, or has been dropped. If a pack gets
hot during the session, stop and let it cool — that is data, not an
inconvenience.

*Control:* inspect before use; photograph anything abnormal (P21).

### H8 — Laser aperture

Two LiDARs. Read each unit's laser-class label. **Absent a legible class
label, treat it as unknown and do not look into the aperture** — especially
not through a camera lens, a loupe, or binoculars, which is the case where
otherwise-eye-safe emitters stop being eye-safe.

*Control:* no close-range eye-level inspection of a powered aperture. Power
down to clean or inspect an optical window.

### H9 — Thermal

The Orin under sustained recording and the D455's metal body both get hot
enough to be unpleasant, and thermal throttling will show up in `tegrastats`
(channel 16) before it shows up in your hand.

*Control:* S10. Do not block airflow with a bracket or a cable bundle. Let
things cool before handling. **Log `tegrastats` for the whole session** — this
is the only chance to learn the thermal envelope.

### H10 — Trip hazards and the room

Ethernet, tether, tape measure, camera bag, and the mat's own edge.

*Control:* S7 clear radius ≥1.5 m; cables run to the perimeter, not across it;
the scribe works from outside the radius.

### H11 — Mounting and teardown injuries

Fastening brackets to a trunk with a tool means a slipped driver, a pinched
finger between bracket and shell, and sharp bracket edges. Most of the day's
minor injuries live here.

*Control:* mount and unmount with the dog **powered off** and, where possible,
**off the floor** on a bench or blocks.

---

## 4 · Roles, and the rule that matters

| Role | Duty |
|---|---|
| **Operator** | Hardware, cabling, vendor handheld (stop #1). Announces every action **before** doing it: "powering on", "standing in three, two, one". |
| **Safety observer (the "second")** | **Holds stop #2 and does nothing else.** No typing, no photographing, no holding the tape. Watches the dog and the people. Owns the abort call. |
| **Scribe** | Fills the sheets, calls times, reads back numbers. May be the operator. |

> **The rule: the safety observer has no second job.** The moment they pick up
> a camera, they are not a safety observer.
>
> **Fewer than two people ⇒ the dog is not powered.** Run the DEGRADE-MMP
> branch: mount, measure, photograph, record nothing. This is a legitimate
> outcome, not a failure.

---

## 5 · Stop procedure — read this verbatim

> **Anyone may call "STOP". Any reason, or no reason. It is never questioned
> in the moment, it is never argued with, and nobody is ever wrong for calling
> it.**

On **"STOP"**:

1. Operator presses stop #1. Second presses stop #2. **Both.** Do not check
   whether the other person did it.
2. Everyone steps back from the leg envelope. Hands visible.
3. Nobody touches the robot until the **second** says so.
4. The scribe writes the time and the reason in run sheet §10 — **before** any
   discussion about resuming.
5. Resuming requires the second's explicit agreement, out loud, and a re-run
   of the pre-stand gate (§8) if the dog is to stand again.

**If the dog falls:** do not catch it. Let it fall, then stop, then approach.
A falling 15 kg quadruped injures the person catching it far more reliably
than it injures itself.

**If a cable is yanked:** stop first, re-seat second. A half-seated connector
is a mid-session data loss whose signature in the bag will otherwise be
mistaken for a sensor dropout.

**If the Orin browns out mid-record:** stop, then note the wall time in §10.
The bag will be **truncated**; PS-B must record it as a truncation, and the
distinction from a dropout only survives if someone wrote down that the power
died.

---

## 6 · Before you power anything — the ten-second version

- Two people. Second has stop #2 and no other job.
- Mat down. 1.5 m clear. No cables across the floor.
- Payload pull-tested. Cables anchored within 100 mm of every connector.
- Hands out of the leg envelope from now on.
- The dog can move without your permission.
- A stop press drops a standing dog onto the mat, payload first.

---

## 7 · Brief delivered — sign before power

```text
briefed by:   ____________________   at ______ UTC
present, and each states "I understand the stop procedure":
  1. ____________________ (operator)      sig ________
  2. ____________________ (second)        sig ________
  3. ____________________ (scribe/other)  sig ________
padded mat in place:  YES / NO
two independent stops present and labelled (run sheet §5): YES / NO
```

**`NO` on either of the last two lines ⇒ the dog is not powered today.**

---

## 8 · What this brief does not do, and does not prove

- It has not been delivered. It is paperwork until someone reads it aloud.
- It is **not a risk assessment for autonomous operation**, and it does not
  become one by being signed. Nothing beyond §2's envelope is covered by any
  analysis in this repository.
- It does not make the payload safe; it makes the payload's failure
  **predictable and survivable**.
- It assumes a flat indoor floor, room temperature, and a rig that is bolted
  together. Outdoors, stairs, slopes, wet floors, and crowds are **not**
  considered anywhere in it.
- Two confirmed safety findings against the autonomy stack remain **open and
  unfixed** — a latched input-health stop still permits yaw
  (`runtime.py:5711-5712`), and the no-provider pose fallback fabricates
  `health=HEALTHY` at zero covariance (`pose.py:945-954`), both filed in
  [PHYSICAL_SESSION_PLAN.md](../PHYSICAL_SESSION_PLAN.md) §"Two confirmed
  safety findings". Neither is reachable today because nothing is armed. Both
  become live the moment anything is, and **this brief does not cover that
  day.**
