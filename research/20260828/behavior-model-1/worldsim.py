"""BM-1 world simulator: procedural state-of-the-world stream + scripted teacher.

Implements the frame schema, the five teacher rules, the scenario families, the
cue-detector noise model and the owner profiles of
``research/20260828/behavior-model-1/DESIGN.md`` (FROZEN).

Nothing here imports product code.  The act-token vocabulary and the frame
channel names are *copied by name* from
``src/parcel_robot/duplex/act_codec.py``, ``src/parcel_robot/duplex/frames.py``,
``src/parcel_robot/runtime.py`` (DEFAULT_EMOTES) and
``src/parcel_robot/contracts/v1.py`` — no product caller is exercised.

Deterministic: every episode is generated from ``(master_seed, episode_index)``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FRAME_HZ = 10.0

# ---------------------------------------------------------------------------
# Act-token vocabulary (copied by name from ActTokenCodec / default_twist_bins)
# ---------------------------------------------------------------------------

VX_BINS = (-0.3, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
VYAW_BINS = (-1.5, -0.7, 0.0, 0.7, 1.5)
GAZE_BINS = 8
FILLER_GESTURES = 4

# runtime.py DEFAULT_EMOTES (verbatim, 2026-08-28)
EMOTES = (
    "attentive_nod",
    "bow",
    "chuckle",
    "comfort_bow",
    "confused_head_tilt",
    "curious_look",
    "excited_paw_taps",
    "happy_wiggle",
    "head_nod",
    "head_shake",
    "hello_pose",
    "hop",
    "look_left",
    "look_right",
    "observing_head_tilt",
    "paw_wave",
    "play_bow",
    "shake",
    "shrug",
    "stretch",
)

SKILLS = ("come", "fetch", "follow", "go_to", "shake_paw", "sit", "stay")
COMMANDS = SKILLS + ("stop",)
JOKE_CATEGORIES = ("pun", "slapstick", "absurd", "dry", "wordplay", "callback")


def build_act_vocab() -> tuple[str, ...]:
    """Mirror of ``ActTokenCodec._build_vocabulary`` for this skill/emote set."""

    tokens: list[str] = ["<idle>", "<gaze_owner>", "<gaze_release>"]
    tokens.extend(f"<gaze_bearing_{i}>" for i in range(GAZE_BINS))
    for vx_i in range(len(VX_BINS)):
        for vyaw_i in range(len(VYAW_BINS)):
            tokens.append(f"<twist:{vx_i}:{vyaw_i}>")
    tokens.extend(f"<skill:{n}>" for n in sorted(SKILLS))
    tokens.extend(f"<emote:{n}>" for n in sorted(EMOTES))
    for i in range(FILLER_GESTURES):
        tokens.append(f"<filler_gesture_{i}>")
        tokens.append(f"<filler_speech_{i}>")
    return tuple(sorted(tokens))


ACT_VOCAB = build_act_vocab()
ACT_ID = {tok: i for i, tok in enumerate(ACT_VOCAB)}
N_ACTS = len(ACT_VOCAB)
IDLE_ID = ACT_ID["<idle>"]
EMOTE_IDS = frozenset(ACT_ID[f"<emote:{n}>"] for n in EMOTES)
SKILL_IDS = frozenset(ACT_ID[f"<skill:{n}>"] for n in SKILLS)
EMOTE_OR_SKILL_IDS = EMOTE_IDS | SKILL_IDS

# vx=0.0 is index 1; vyaw=0.0 is index 2.
VX_ZERO, VYAW_ZERO = 1, 2
VX_SLOW = 2  # 0.2 m/s


def twist(vx_i: int, vyaw_i: int) -> str:
    return f"<twist:{vx_i}:{vyaw_i}>"


# ---------------------------------------------------------------------------
# Frame schema — one categorical channel per column
# ---------------------------------------------------------------------------

DLG = ("idle", "listening", "thinking", "speaking")
CUE = (
    "none",
    "owner_speaking",
    "joke_setup",
    "joke_punchline",
    "question",
    "praise",
    "scold",
    "greeting",
    "call_name",
    "laugh",
    "sigh",
) + tuple(f"cmd:{c}" for c in COMMANDS)
CUE_CONF = ("none", "lo", "mid", "hi")
VAL = ("-2", "-1", "0", "1", "2")
ARO = ("0", "1", "2")
OWN_VIS = ("visible", "occluded", "unknown")
OWN_DIST = ("near", "mid", "far", "unknown")
OWN_BEAR = tuple(f"b{i}" for i in range(8)) + ("unknown",)
OWN_GAZE = ("at_dog", "away", "unknown")
OWN_MOTION = ("still", "walking", "approaching", "leaving")
T_SINCE_SEEN = ("lt1s", "1_3s", "3_8s", "8_20s", "gt20s")
SELF_ACT = (
    ("idle", "navigating", "following", "hold")
    + tuple(f"emote:{n}" for n in EMOTES)
    + tuple(f"skill:{n}" for n in SKILLS)
)
BASE_BUSY = ("free", "busy", "critical")
LOC_HEALTH = ("ok", "degraded", "lost")
TASK = ("none", "follow", "go_to", "come", "stay", "search_owner")
TASK_STATE = ("idle", "progressing", "blocked", "done")
ENV = ("kitchen", "living", "hall", "outdoor")
OBSTACLE = ("none", "ahead", "doorway")
PEOPLE = ("0", "1", "2+")
HIST = ("none",) + tuple(
    f"{c}{'+' if laughed else '-'}" for c in JOKE_CATEGORIES for laughed in (False, True)
)
PROF_GREET = ("warm", "brief", "playful")
PROF_PRAISE = ("frequent", "rare", "physical")
PROF_PACE = ("slow", "normal", "brisk")
PROF_SENS = ("low", "med", "high")

HIST_K = 6

CHANNELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dlg", DLG),
    ("cue", CUE),
    ("cue_conf", CUE_CONF),
    ("val", VAL),
    ("aro", ARO),
    ("own_vis", OWN_VIS),
    ("own_dist", OWN_DIST),
    ("own_bear", OWN_BEAR),
    ("own_gaze", OWN_GAZE),
    ("own_motion", OWN_MOTION),
    ("t_since_seen", T_SINCE_SEEN),
    ("self_act", SELF_ACT),
    ("base_busy", BASE_BUSY),
    ("loc_health", LOC_HEALTH),
    ("task", TASK),
    ("task_state", TASK_STATE),
    ("env", ENV),
    ("obstacle", OBSTACLE),
    ("people", PEOPLE),
) + tuple((f"hist{i}", HIST) for i in range(HIST_K)) + (
    ("prof_greet", PROF_GREET),
    ("prof_praise", PROF_PRAISE),
    ("prof_pace", PROF_PACE),
    ("prof_sens", PROF_SENS),
)

CHANNEL_NAMES = tuple(name for name, _ in CHANNELS)
CHANNEL_SIZES = tuple(len(vals) for _, vals in CHANNELS)
CHANNEL_INDEX = {name: i for i, name in enumerate(CHANNEL_NAMES)}
N_CHANNELS = len(CHANNELS)
_VAL_ID = {name: {v: i for i, v in enumerate(vals)} for name, vals in CHANNELS}

# Annotation columns (never fed to a model; used by eval.py only).
ANN_COLS = (
    "ev_chuckle",  # 1 if this frame anchors a GT chuckle event
    "tgt_chuckle",  # act id the teacher emitted for it
    "ev_lookback",
    "tgt_lookback",
    "ev_comply",
    "tgt_comply",
    "ev_comfort",
    "tgt_comfort",
    "ev_nonfunny_punch",  # non-funny punchline anchor (false-chuckle denominator)
    # A1: 1 when the anchor frame is a DETECTED-cue frame (the amended clock);
    # 0 when the cue classifier missed or mislabelled it and the ideal-dog
    # teacher still reacted to the true utterance.
    "det_chuckle",
    "det_comply",
    "det_comfort",
    # A8.1: bearing sector of a look-back anchor (1 = front bin 0, 0 = rear/side)
    "lookback_front",
    # A7: 1 on the frame where a cmd:stop cue was observed
    "ev_stop_cue",
    # A8.5: every punchline the teacher processed, and whether the
    # anticipatory-chuckle condition was satisfiable from the history channel
    "ev_punchline",
    "punch_anticipatable",
)
ANN_INDEX = {name: i for i, name in enumerate(ANN_COLS)}
N_ANN = len(ANN_COLS)

# Event timing windows, in frames, measured from the anchor (DESIGN.md M2).
WINDOWS = {
    "chuckle": (3, 15),  # [0.3, 1.5] s
    "lookback": (30, 50),  # [3, 5] s
    "comply": (0, 5),  # <= 0.5 s
    "comfort": (0, 20),  # <= 2 s
}
FALSE_CHUCKLE_WINDOW = (0, 25)  # chuckles within 2.5 s of a non-funny punchline

# ---------------------------------------------------------------------------
# Scenario families
# ---------------------------------------------------------------------------

FAMILIES = (
    "chat_at_home",
    "joke_while_following",
    "lost_outdoors",
    "command_during_emote",
    "sad_owner_far",
    "busy_navigation",
    "greeting_and_praise",
    "joke_while_lost",  # held out of training
    "command_during_chuckle",  # held out of training
)
HELD_OUT_FAMILIES = ("joke_while_lost", "command_during_chuckle")
TRAIN_FAMILIES = tuple(f for f in FAMILIES if f not in HELD_OUT_FAMILIES)


# ---------------------------------------------------------------------------
# Procedural phrase generator
# ---------------------------------------------------------------------------

_CMD_FRAGMENTS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "sit": (
        ["", "hey ", "okay ", "come on ", "alright ", "please "],
        ["sit", "sit down", "take a seat", "have a sit", "park it", "settle down"],
        ["", " please", " buddy", " now", " for me", " good dog"],
    ),
    "stay": (
        ["", "hey ", "okay ", "just ", "alright ", "please "],
        ["stay", "stay there", "hold still", "wait here", "don't move", "stay put"],
        ["", " please", " buddy", " a second", " for me", " right there"],
    ),
    "come": (
        ["", "hey ", "okay ", "come on ", "alright ", "would you "],
        ["come", "come here", "come over", "get over here", "come to me", "over here"],
        ["", " please", " buddy", " now", " boy", " quick"],
    ),
    "follow": (
        ["", "hey ", "okay ", "come on ", "alright ", "let's go "],
        ["follow me", "follow", "stay with me", "come along", "walk with me", "keep up"],
        ["", " please", " buddy", " now", " will you", " this way"],
    ),
    "stop": (
        ["", "hey ", "okay ", "whoa ", "alright ", "no "],
        ["stop", "stop that", "halt", "cut it out", "quit it", "freeze"],
        ["", " please", " buddy", " now", " right now", " a moment"],
    ),
    "fetch": (
        ["", "hey ", "okay ", "go ", "alright ", "would you "],
        ["fetch", "fetch it", "go get it", "bring it here", "grab that", "pick it up"],
        ["", " please", " buddy", " now", " for me", " boy"],
    ),
    "shake_paw": (
        ["", "hey ", "okay ", "come on ", "alright ", "can you "],
        ["shake", "shake paw", "give me your paw", "paw", "high five", "shake hands"],
        ["", " please", " buddy", " now", " for me", " good dog"],
    ),
    "go_to": (
        ["", "hey ", "okay ", "go ", "alright ", "would you "],
        [
            "go to the kitchen",
            "head to the kitchen",
            "go over to the hall",
            "go wait in the living room",
            "move to the doorway",
            "go stand by the door",
        ],
        ["", " please", " buddy", " now", " for me", " and wait"],
    ),
}

_SOCIAL_FRAGMENTS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "greeting": (
        ["", "oh ", "hey, ", "well ", "look, "],
        ["hello there", "hi buddy", "good morning", "hey you", "there you are", "morning"],
        ["", "!", " little guy", " my friend", ", how are you", " again"],
    ),
    "praise": (
        ["", "oh ", "wow, ", "hey, ", "yes, "],
        ["good boy", "well done", "that's great", "nice work", "you did it", "clever dog"],
        ["", "!", " buddy", " really", ", I mean it", " good job"],
    ),
    "scold": (
        ["", "hey, ", "no, ", "ugh, ", "come on, "],
        ["that's enough", "bad dog", "not like that", "don't do that", "stop it", "no no no"],
        ["", "!", " seriously", " again", " please", " I said"],
    ),
    "question": (
        ["", "hey, ", "so, ", "tell me, ", "hmm, "],
        [
            "where did I put my keys",
            "what do you think",
            "are you hungry",
            "do you want to go out",
            "who is at the door",
            "what was that noise",
        ],
        ["", "?", " buddy", " boy", ", huh", " do you know"],
    ),
    "call_name": (
        ["", "hey ", "oh ", "psst, ", "yo "],
        ["parcel", "buddy", "pup", "dog", "little one", "boy"],
        ["", "!", ", over here", ", look", ", listen", ", hey"],
    ),
    "laugh": (
        ["", "oh ", "hah, ", "ha ", "heh "],
        ["hahaha", "haha", "hah", "hehehe", "ha ha ha", "heh heh"],
        ["", "!", " that's good", " oh man", " stop it", " you got me"],
    ),
    "sigh": (
        ["", "oh ", "ugh, ", "hmm, ", "well "],
        ["*sigh*", "haaah", "i don't know", "it's been a day", "i'm tired", "never mind"],
        ["", "...", " i guess", " whatever", " honestly", " again"],
    ),
    "chatter": (
        ["", "so ", "anyway ", "you know, ", "by the way "],
        [
            "the weather is strange today",
            "i should probably do the dishes",
            "the bus was late again",
            "i need to call my sister",
            "we are out of coffee",
            "that plant needs water",
        ],
        ["", ".", " i suppose", " right", " apparently", " as usual"],
    ),
}

# 12 (setup, punchline) template pairs per joke category; {a}/{b} slots fill in.
_JOKE_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "pun": [
        ("why did the {a} sit on the {b}", "because it wanted to be a {a} rest"),
        ("what do you call a {a} with no {b}", "a {a}less wonder"),
        ("i tried to catch some {b} yesterday", "but they were too {a} for me"),
        ("did you hear about the {a}", "it really made the {b} laugh"),
        ("my {a} went to the {b} school", "now it has a degree in {a} studies"),
        ("what is a {a} favourite {b}", "anything with a good punch line"),
        ("i used to be a {a}", "but the {b} was too demanding"),
        ("this {a} walked into a {b}", "and said do you serve {a} here"),
        ("why is the {a} always {b}", "because it never learned to relax"),
        ("i named my {a} after a {b}", "now it answers to everything"),
        ("a {a} and a {b} had a race", "the {a} won by a nose"),
        ("what happens when a {a} meets a {b}", "you get a very confused {a}"),
    ],
    "slapstick": [
        ("so i walked into the {a}", "and knocked over the entire {b}"),
        ("i tried to carry the {b} and the {a}", "both ended up on the floor"),
        ("watch me pick up this {a}", "and there goes the {b} again"),
        ("i slipped on the {a} this morning", "landed right in the {b}"),
        ("the {a} fell off the {b}", "and then i fell off too"),
        ("i sneezed near the {a}", "the whole {b} came down"),
        ("i tried to open the {a}", "the {b} opened me instead"),
        ("i chased the {a} around the {b}", "the {a} won, obviously"),
        ("i put the {a} on the {b}", "gravity had other plans"),
        ("i leaned on the {a}", "now we both live on the {b}"),
        ("i juggled the {a} and the {b}", "the ceiling has a new dent"),
        ("i reached for the {a}", "and wore the {b} for a hat"),
    ],
    "absurd": [
        ("imagine a {a} that runs a {b}", "it charges in buttons"),
        ("last night the {a} unionised", "they demanded a bigger {b}"),
        ("i met a {a} who spoke only in {b}", "we agreed on nothing"),
        ("suppose the {a} were made of {b}", "breakfast would be a crime"),
        ("the {a} applied to be a {b}", "it got the job on charisma"),
        ("in my dream the {a} was a {b}", "and i was the landlord"),
        ("a {a} tried to sell me a {b}", "i said i already have three"),
        ("what if every {a} owned a {b}", "the queue would be enormous"),
        ("the {a} declared itself a {b}", "nobody objected"),
        ("i taught a {a} to fold a {b}", "now it critiques my technique"),
        ("the {a} invented a new {b}", "it does nothing, beautifully"),
        ("consider a {a} shaped like a {b}", "no, keep considering"),
    ],
    "dry": [
        ("i asked the {a} for help", "it declined, politely"),
        ("the {b} is broken again", "as is tradition"),
        ("i had high hopes for the {a}", "i have adjusted them"),
        ("they say the {a} improves the {b}", "they say a lot of things"),
        ("i read the manual for the {a}", "it was fiction"),
        ("the {a} took eleven minutes", "it was scheduled for two"),
        ("someone reorganised the {b}", "i have opinions"),
        ("the {a} is described as intuitive", "for whom, we may never know"),
        ("i tried the new {b}", "it exists"),
        ("the {a} promised to be quiet", "the {a} lied"),
        ("i have a system for the {b}", "the system is denial"),
        ("the {a} works perfectly", "in one very specific case"),
    ],
    "wordplay": [
        ("a {a} is just a {b} with ambition", "spelling optional"),
        ("if you rearrange {a} you get {b}", "almost, if you squint"),
        ("the plural of {a} should be {b}", "i will die on this hill"),
        ("they call it a {a}", "i call it a {b} in a hat"),
        ("{a} and {b} sound alike", "which explains the incident"),
        ("i said {a}, he heard {b}", "the sandwich was a surprise"),
        ("a {b} by any other name", "would still be a {a}"),
        ("you can spell {a} without {b}", "but why would you"),
        ("the difference between {a} and {b}", "is roughly one vowel"),
        ("i wrote a poem about a {a}", "it rhymed only with {b}"),
        ("call it a {a}, call it a {b}", "either way it's late"),
        ("the word {a} contains a {b}", "linguistically speaking, chaos"),
    ],
    "callback": [
        ("remember the {a} from tuesday", "it came back, and it brought a {b}"),
        ("you know how i mentioned the {b}", "well, the {a} agrees with me now"),
        ("so about that {a}", "the {b} never recovered"),
        ("this is like the {a} incident", "except now there is a {b}"),
        ("i said the {a} would be trouble", "look at the {b} and tell me i was wrong"),
        ("second verse, same as the {a}", "only the {b} has changed"),
        ("i promised not to mention the {a}", "the {b} has no such promise"),
        ("as foretold by the {a}", "the {b} has fallen"),
        ("we agreed never to discuss the {a}", "so let's discuss the {b}"),
        ("the {a} is back on the menu", "and it brought the {b}"),
        ("this brings us back to the {a}", "and to the {b}, sadly"),
        ("the saga of the {a} continues", "chapter four, the {b}"),
    ],
}

_SLOT_A = ("kettle", "pigeon", "ladder", "toaster", "sock", "bicycle", "lamp", "cactus")
_SLOT_B = ("bookshelf", "hallway", "umbrella", "spreadsheet", "garden", "sofa", "railing", "mailbox")

_MAX_PER_INTENT = 240


def _enumerate(fragments: tuple[list[str], list[str], list[str]]) -> list[str]:
    pre, core, suf = fragments
    out: list[str] = []
    for c in core:
        for p in pre:
            for s in suf:
                out.append(f"{p}{c}{s}".strip())
    # deterministic de-dup, stable order
    seen: set[str] = set()
    uniq = [x for x in out if not (x in seen or seen.add(x))]
    if len(uniq) > _MAX_PER_INTENT:
        stride = len(uniq) / _MAX_PER_INTENT
        uniq = [uniq[int(i * stride)] for i in range(_MAX_PER_INTENT)]
    return uniq


def _split_ids(ids: list[int], held_frac: float = 0.30) -> tuple[list[int], list[int]]:
    """Deterministic phrasing partition: exactly 70 % train / 30 % frozen-only."""

    order = sorted(ids, key=lambda i: hashlib.sha256(f"phrasing:{i}".encode()).hexdigest())
    n_held = round(held_frac * len(order))
    held = sorted(order[:n_held])
    train = sorted(order[n_held:])
    return train, held


@dataclass
class PhraseTable:
    strings: list[str]
    intent: dict[str, dict[str, list[int]]]  # intent -> {"train": ids, "held": ids}
    cmd: dict[str, dict[str, list[int]]]  # command -> {"train": ids, "held": ids}
    jokes: dict[str, dict[str, list[tuple[int, int]]]]  # category -> split -> pairs

    def n_strings(self) -> int:
        return len(self.strings)


def build_phrases() -> PhraseTable:
    strings: list[str] = []

    def add(s: str) -> int:
        strings.append(s)
        return len(strings) - 1

    intent: dict[str, dict[str, list[int]]] = {}
    for name, frags in _SOCIAL_FRAGMENTS.items():
        ids = [add(s) for s in _enumerate(frags)]
        tr, he = _split_ids(ids)
        intent[name] = {"train": tr, "held": he}

    cmd: dict[str, dict[str, list[int]]] = {}
    for name, frags in _CMD_FRAGMENTS.items():
        ids = [add(s) for s in _enumerate(frags)]
        tr, he = _split_ids(ids)
        cmd[name] = {"train": tr, "held": he}

    jokes: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for cat, templates in _JOKE_TEMPLATES.items():
        pairs: list[tuple[int, int]] = []
        for ti, (setup, punch) in enumerate(templates):
            for si, a in enumerate(_SLOT_A):
                b = _SLOT_B[(si + ti) % len(_SLOT_B)]
                pairs.append((add(setup.format(a=a, b=b)), add(punch.format(a=a, b=b))))
        idx = list(range(len(pairs)))
        tr_i, he_i = _split_ids(idx)
        jokes[cat] = {
            "train": [pairs[i] for i in tr_i],
            "held": [pairs[i] for i in he_i],
        }
    return PhraseTable(strings=strings, intent=intent, cmd=cmd, jokes=jokes)


PHRASES = build_phrases()


# ---------------------------------------------------------------------------
# Owner profiles
# ---------------------------------------------------------------------------


def all_taste_masks() -> list[int]:
    masks = []
    for m in range(1 << len(JOKE_CATEGORIES)):
        if 2 <= (m).bit_count() <= 4:
            masks.append(m)
    return masks


TASTE_MASKS = all_taste_masks()  # 50 masks


def taste_split(held_frac: float = 0.20) -> tuple[list[int], list[int]]:
    """Exactly 20 % of owner-taste profiles are frozen-test only."""

    order = sorted(TASTE_MASKS, key=lambda m: hashlib.sha256(f"taste:{m}".encode()).hexdigest())
    n_held = round(held_frac * len(order))
    return sorted(order[n_held:]), sorted(order[:n_held])


TASTE_TRAIN, TASTE_HELD = taste_split()


@dataclass
class Profile:
    taste: int
    greet: int
    praise: int
    pace: int
    sens: int

    def likes(self, category: str) -> bool:
        return bool(self.taste & (1 << JOKE_CATEGORIES.index(category)))

    def laugh_prob(self, category: str) -> float:
        return 0.86 if self.likes(category) else 0.07

    def pace_name(self) -> str:
        return PROF_PACE[self.pace]


def sample_profile(rng: random.Random, *, held_out_taste: bool) -> Profile:
    pool = TASTE_HELD if held_out_taste else TASTE_TRAIN
    return Profile(
        taste=rng.choice(pool),
        greet=rng.randrange(len(PROF_GREET)),
        praise=rng.randrange(len(PROF_PRAISE)),
        pace=rng.randrange(len(PROF_PACE)),
        sens=rng.randrange(len(PROF_SENS)),
    )


# Pace-conditioned reaction delays (frames).  All stay inside the DESIGN.md
# windows; making the base delay a function of an *observable* profile channel
# keeps the teacher stochastic but learnable.
_PACE_BASE = {"brisk": 3, "normal": 5, "slow": 7}  # chuckle: 0.3-0.9 s
_PACE_COMPLY = {"brisk": 2, "normal": 3, "slow": 4}  # comply: 0.2-0.5 s
_PACE_COMFORT = {"brisk": 5, "normal": 8, "slow": 11}  # comfort: 0.5-1.3 s
_PACE_SOCIAL = {"brisk": 3, "normal": 5, "slow": 7}


# ---------------------------------------------------------------------------
# Dialogue events
# ---------------------------------------------------------------------------


@dataclass
class DialogueEvent:
    t: int  # true world frame
    kind: str  # cue vocabulary entry (the TRUE label)
    val: int  # -2..2
    aro: int  # 0..2
    words_id: int = -1
    joke_cat: str | None = None
    joke_id: int = -1
    command: str | None = None
    # detector outcome, filled by apply_detector_noise
    obs_t: int = -1
    obs_kind: str | None = None
    obs_conf: int = 0  # index into CUE_CONF
    detected: bool = True
    mislabeled: bool = False


_FAMILY_EVENT_MIX: dict[str, dict[str, float]] = {
    "chat_at_home": {"joke": 3.0, "question": 2.0, "praise": 1.2, "greeting": 0.8,
                     "chatter": 2.0, "command": 1.5, "scold": 0.4, "call_name": 0.8,
                     "sigh": 0.5},
    "joke_while_following": {"joke": 4.0, "chatter": 1.5, "command": 1.5,
                             "call_name": 1.0, "question": 0.8, "praise": 0.8},
    "lost_outdoors": {"call_name": 2.5, "chatter": 1.5, "command": 2.0,
                      "question": 0.8, "joke": 0.8, "praise": 0.6},
    "command_during_emote": {"command": 4.0, "praise": 1.5, "greeting": 1.2,
                             "joke": 1.5, "call_name": 1.0, "scold": 0.8},
    "sad_owner_far": {"sigh": 3.0, "chatter": 1.5, "question": 1.0, "command": 1.0,
                      "joke": 0.8, "call_name": 1.0},
    "busy_navigation": {"command": 2.5, "chatter": 2.0, "question": 1.0, "joke": 1.5,
                        "praise": 1.0, "call_name": 1.0},
    "greeting_and_praise": {"greeting": 2.5, "praise": 3.0, "scold": 1.2,
                            "call_name": 1.5, "chatter": 1.5, "command": 1.2,
                            "joke": 1.0},
    "joke_while_lost": {"joke": 4.0, "call_name": 1.5, "chatter": 1.5, "command": 1.0},
    "command_during_chuckle": {"joke": 3.5, "command": 3.5, "chatter": 1.0,
                               "praise": 0.8},
}


def _weighted_choice(rng: random.Random, mix: dict[str, float]) -> str:
    total = sum(mix.values())
    r = rng.random() * total
    acc = 0.0
    for k, w in mix.items():
        acc += w
        if r <= acc:
            return k
    return next(iter(mix))


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


@dataclass
class Episode:
    family: str
    seed: int
    profile: Profile
    channels: np.ndarray  # (T, N_CHANNELS) int16
    acts: np.ndarray  # (T,) int16
    acts_ceiling: np.ndarray | None = None  # A1 ceiling teacher (observed cues)
    words: np.ndarray = None  # (T,) int32, -1 = <silence>
    ann: np.ndarray = None  # (T, N_ANN) int16
    held_out_family: bool = False
    held_out_profile: bool = False
    held_out_phrasing: bool = False
    meta: dict = field(default_factory=dict)


def _bearing_bin(bearing_rad: float) -> int:
    tau = 2.0 * math.pi
    w = bearing_rad % tau
    return round((w / tau) * GAZE_BINS) % GAZE_BINS


def _yaw_index_for_bearing(bin_idx: int) -> int:
    """Turn direction toward a remembered bearing bin (0 = straight ahead)."""

    if bin_idx == 0:
        return VYAW_ZERO
    if 1 <= bin_idx <= 3:
        return 4 if bin_idx == 2 else 3  # left
    if 5 <= bin_idx <= 7:
        return 0 if bin_idx == 6 else 1  # right
    return 3  # directly behind -> turn left hard


def _t_since_bin(n: int) -> int:
    if n < 10:
        return 0
    if n < 30:
        return 1
    if n < 80:
        return 2
    if n < 200:
        return 3
    return 4


def _dist_bin(d: float) -> int:
    if d < 1.5:
        return 0
    if d < 3.5:
        return 1
    return 2


@dataclass(eq=False)
class _Sched:
    due: int
    prio: int
    act: str
    tag: str
    expires: int
    defer_ok: bool = False
    anchor: int = -1
    event: str = ""  # "chuckle" | "lookback" | "comply" | "comfort" | ""
    detected: bool = True  # A1: anchor sits on a DETECTED-cue frame
    extra: int = -1  # per-event side channel (look-back bearing bin)


def generate_episode(
    *,
    seed: int,
    family: str,
    held_out_profile: bool,
    held_out_phrasing: bool,
    observed_only: bool = False,
) -> Episode:
    """Generate one episode.

    ``observed_only=True`` runs the CEILING teacher of amendment A1: the same
    scripted rules driven by the *detected* cue channel only (missed and
    mislabelled cues are therefore missed by the teacher too).  The sampled
    world is bit-identical because every world track is drawn before the frame
    loop; only the act stream and its ``self_act`` echo differ.
    """
    rng = random.Random(seed)
    phr_split = "held" if held_out_phrasing else "train"
    profile = sample_profile(rng, held_out_taste=held_out_profile)
    pace = profile.pace_name()

    T = rng.randrange(600, 1801)

    # ---- world tracks ----------------------------------------------------
    outdoor = family in ("lost_outdoors", "joke_while_lost")
    env_id = _VAL_ID["env"]["outdoor"] if outdoor else rng.randrange(3)
    task_name = {
        "chat_at_home": "none",
        "joke_while_following": "follow",
        "lost_outdoors": "follow",
        "command_during_emote": "none",
        "sad_owner_far": "none",
        "busy_navigation": "go_to",
        "greeting_and_praise": "none",
        "joke_while_lost": "follow",
        "command_during_chuckle": "none",
    }[family]

    dist = np.zeros(T)
    bear = np.zeros(T)
    vis = np.ones(T, dtype=bool)
    gaze = np.zeros(T, dtype=np.int16)
    motion = np.zeros(T, dtype=np.int16)

    d = rng.uniform(4.0, 6.5) if family == "sad_owner_far" else rng.uniform(1.0, 3.5)
    b = rng.uniform(0.0, 2 * math.pi)
    t = 0
    while t < T:
        seg = rng.randrange(30, 151)
        mode = rng.choices(
            ("still", "walking", "approaching", "leaving"),
            weights=(3, 4, 2, 2) if task_name == "none" else (2, 5, 2, 3),
        )[0]
        mi = OWN_MOTION.index(mode)
        dd = {"still": 0.0, "walking": 0.0, "approaching": -0.03, "leaving": 0.03}[mode]
        db = {"still": 0.0, "walking": 0.012, "approaching": 0.004, "leaving": 0.006}[mode]
        sign = rng.choice((-1.0, 1.0))
        for _ in range(min(seg, T - t)):
            d = max(0.6, min(9.0, d + dd + rng.gauss(0, 0.01)))
            b = (b + sign * db + rng.gauss(0, 0.004)) % (2 * math.pi)
            dist[t] = d
            bear[t] = b
            motion[t] = mi
            t += 1
    # gaze: persistent Markov
    g = 0
    for i in range(T):
        if rng.random() < 0.03:
            g = 1 - g
        gaze[i] = g

    # occlusions
    n_occ = {
        "chat_at_home": rng.randrange(0, 2),
        "joke_while_following": rng.randrange(1, 3),
        "lost_outdoors": rng.randrange(3, 6),
        "command_during_emote": rng.randrange(0, 2),
        "sad_owner_far": rng.randrange(0, 2),
        "busy_navigation": rng.randrange(1, 3),
        "greeting_and_praise": rng.randrange(0, 2),
        "joke_while_lost": rng.randrange(3, 6),
        "command_during_chuckle": rng.randrange(0, 2),
    }[family]
    occ_spans: list[tuple[int, int]] = []
    for _ in range(n_occ):
        start = rng.randrange(40, max(60, T - 140))
        dur = rng.randrange(45, 170)
        occ_spans.append((start, min(T, start + dur)))
        vis[start : min(T, start + dur)] = False
    # visibility flicker
    for i in range(T):
        if vis[i] and rng.random() < 0.008:
            vis[i : i + rng.randrange(1, 4)] = False

    # base_busy / obstacle / loc_health / people / task_state
    base_busy = np.zeros(T, dtype=np.int16)
    obstacle = np.zeros(T, dtype=np.int16)
    loc = np.zeros(T, dtype=np.int16)
    people = np.zeros(T, dtype=np.int16)
    p_crit = 0.26 if family == "busy_navigation" else 0.15
    i = 0
    while i < T:
        r = rng.random()
        if r < p_crit:
            state, span = 2, rng.randrange(15, 46)
        elif r < p_crit + (0.30 if task_name != "none" else 0.12):
            state, span = 1, rng.randrange(30, 121)
        else:
            state, span = 0, rng.randrange(40, 161)
        base_busy[i : i + span] = state
        if state == 2:
            obstacle[i : i + span] = rng.choice((1, 1, 2))
        i += span
    i = 0
    while i < T:
        span = rng.randrange(80, 301)
        loc[i : i + span] = 0 if rng.random() < (0.80 if not outdoor else 0.62) else rng.choice((1, 1, 2))
        i += span
    i = 0
    while i < T:
        span = rng.randrange(100, 401)
        people[i : i + span] = rng.choices((0, 1, 2), weights=(1, 6, 2))[0]
        i += span

    # ---- dialogue script -------------------------------------------------
    events: list[DialogueEvent] = []
    mix = _FAMILY_EVENT_MIX[family]
    hist: deque[tuple[str, bool]] = deque(maxlen=HIST_K)
    # seed the owner-model history so anticipation can fire early
    for _ in range(HIST_K):
        cat = rng.choice(JOKE_CATEGORIES)
        hist.append((cat, rng.random() < profile.laugh_prob(cat)))
    hist_seed = list(hist)

    cursor = rng.randrange(20, 70)
    joke_meta: list[dict] = []
    while cursor < T - 40:
        kind = _weighted_choice(rng, mix)
        if kind == "joke":
            cat = rng.choice(JOKE_CATEGORIES)
            pairs = PHRASES.jokes[cat][phr_split]
            setup_id, punch_id = pairs[rng.randrange(len(pairs))]
            punch_t = cursor + rng.randrange(15, 31)
            if punch_t >= T - 30:
                break
            events.append(DialogueEvent(t=cursor, kind="joke_setup", val=1, aro=1,
                                        words_id=setup_id, joke_cat=cat))
            events.append(DialogueEvent(t=punch_t, kind="joke_punchline", val=1, aro=1,
                                        words_id=punch_id, joke_cat=cat,
                                        joke_id=len(joke_meta)))
            laughed = rng.random() < profile.laugh_prob(cat)
            laugh_t = -1
            if laughed:
                laugh_t = punch_t + rng.randrange(5, 21)
                if laugh_t < T - 20:
                    lp = PHRASES.intent["laugh"][phr_split]
                    events.append(DialogueEvent(t=laugh_t, kind="laugh", val=2, aro=2,
                                                words_id=lp[rng.randrange(len(lp))],
                                                joke_cat=cat, joke_id=len(joke_meta)))
                else:
                    laughed, laugh_t = False, -1
            joke_meta.append({"cat": cat, "punch_t": punch_t, "laughed": laughed,
                              "laugh_t": laugh_t})
            cursor = punch_t + rng.randrange(30, 90)
            if family == "command_during_chuckle":
                # a command lands 0.4-1.2 s after the punchline (or the laugh),
                # i.e. inside the chuckle window — pure held-out composition.
                anchor = laugh_t if laughed else punch_t
                ct = anchor + rng.randrange(4, 13)
                if ct < T - 20:
                    c = rng.choice(COMMANDS)
                    cp = PHRASES.cmd[c][phr_split]
                    events.append(DialogueEvent(t=ct, kind=f"cmd:{c}", val=0, aro=1,
                                                words_id=cp[rng.randrange(len(cp))],
                                                command=c))
            continue
        if kind == "command":
            c = rng.choice(COMMANDS)
            cp = PHRASES.cmd[c][phr_split]
            events.append(DialogueEvent(t=cursor, kind=f"cmd:{c}", val=0, aro=1,
                                        words_id=cp[rng.randrange(len(cp))], command=c))
        elif kind == "chatter":
            p = PHRASES.intent["chatter"][phr_split]
            events.append(DialogueEvent(t=cursor, kind="owner_speaking", val=0, aro=1,
                                        words_id=p[rng.randrange(len(p))]))
        elif kind == "sigh":
            p = PHRASES.intent["sigh"][phr_split]
            events.append(DialogueEvent(t=cursor, kind="sigh", val=rng.choice((-1, -2)),
                                        aro=0, words_id=p[rng.randrange(len(p))]))
        else:
            p = PHRASES.intent[kind][phr_split]
            va = {"question": (0, 1), "praise": (2, 1), "scold": (-2, 2),
                  "greeting": (1, 1), "call_name": (1, 1)}[kind]
            events.append(DialogueEvent(t=cursor, kind=kind, val=va[0], aro=va[1],
                                        words_id=p[rng.randrange(len(p))]))
        cursor += rng.randrange(25, 110)

    events.sort(key=lambda e: e.t)

    # ---- cue-detector noise ---------------------------------------------
    for ev in events:
        lat = rng.randrange(1, 6)
        ev.obs_t = min(T - 1, ev.t + lat)
        if rng.random() < 0.10:  # 10 % false negatives
            ev.detected = False
            ev.obs_kind = None
        elif rng.random() < 0.03:  # 3 % mislabels (false positives for a class)
            ev.detected = True
            ev.mislabeled = True
            wrong = [k for k in CUE if k not in ("none", ev.kind)]
            ev.obs_kind = wrong[rng.randrange(len(wrong))]
            ev.obs_conf = rng.choices((1, 2, 3), weights=(5, 3, 2))[0]
        else:
            ev.obs_kind = ev.kind
            ev.obs_conf = rng.choices((1, 2, 3), weights=(1, 3, 6))[0]
        if not ev.detected:
            ev.obs_conf = 0
        # the teacher (ideal dog) reacts to the true utterance; when the cue
        # classifier misses it the reference frame is the median latency.
        ev.ref_t = ev.obs_t if ev.detected and not ev.mislabeled else min(T - 1, ev.t + 3)

    trig_by_frame: dict[int, list[DialogueEvent]] = {}
    for ev in events:
        trig_by_frame.setdefault(ev.ref_t, []).append(ev)
    if observed_only:
        # CEILING (A1): the teacher only ever sees the detected cue channel.
        trig_by_frame = {}
        for ev in events:
            if not ev.detected:
                continue
            shadow = DialogueEvent(
                t=ev.t, kind=ev.obs_kind or ev.kind, val=ev.val, aro=ev.aro,
                words_id=ev.words_id, joke_cat=ev.joke_cat, joke_id=ev.joke_id,
                command=(ev.obs_kind[4:] if (ev.obs_kind or "").startswith("cmd:") else None),
            )
            shadow.ref_t = ev.obs_t
            trig_by_frame.setdefault(ev.obs_t, []).append(shadow)

    obs_by_frame: dict[int, DialogueEvent] = {}
    for ev in events:
        if ev.detected and ev.obs_t not in obs_by_frame:
            obs_by_frame[ev.obs_t] = ev
    words_by_frame: dict[int, int] = {}
    for ev in events:
        if ev.words_id >= 0:
            words_by_frame.setdefault(ev.t, ev.words_id)

    # dialogue phase track: listening while the owner speaks, thinking after a
    # question, speaking after that.
    dlg = np.zeros(T, dtype=np.int16)
    for ev in events:
        span = 12 if ev.kind in ("laugh", "call_name", "sigh") else 20
        dlg[ev.t : min(T, ev.t + span)] = 1  # listening
        if ev.kind == "question":
            think = min(T, ev.t + span + rng.randrange(10, 26))
            dlg[min(T, ev.t + span) : think] = 2  # thinking
            dlg[think : min(T, think + rng.randrange(20, 61))] = 3  # speaking
        elif ev.kind in ("greeting", "praise", "joke_punchline"):
            dlg[min(T, ev.t + span) : min(T, ev.t + span + rng.randrange(10, 31))] = 3

    # ---- frame loop with the scripted teacher ---------------------------
    ch = np.zeros((T, N_CHANNELS), dtype=np.int16)
    acts = np.full(T, IDLE_ID, dtype=np.int16)
    words = np.full(T, -1, dtype=np.int32)
    ann = np.zeros((T, N_ANN), dtype=np.int16)

    sched: list[_Sched] = []
    busy_until = -1
    busy_self = 0  # SELF_ACT index
    last_chuckle = -10_000
    last_gaze = -10_000
    last_nonidle = 0
    cmd_pending_until = -1
    lost_since = -1
    last_bearing_bin = 0
    lost_handled: set[int] = set()
    last_seen = -1
    joke_state: dict[int, dict] = {}
    hist = deque(hist_seed, maxlen=HIST_K)
    task_state = 0
    task_state_until = 0
    prev_dlg = 0

    ci = CHANNEL_INDEX

    for f in range(T):
        # -- observation ---------------------------------------------------
        visible = bool(vis[f])
        if visible:
            last_seen = f
        since = f - last_seen if last_seen >= 0 else 10_000
        ch[f, ci["dlg"]] = dlg[f]
        cue_ev = obs_by_frame.get(f)
        if cue_ev is not None:
            ch[f, ci["cue"]] = CUE.index(cue_ev.obs_kind)
            ch[f, ci["cue_conf"]] = cue_ev.obs_conf
            ch[f, ci["val"]] = cue_ev.val + 2
            ch[f, ci["aro"]] = cue_ev.aro
        else:
            ch[f, ci["cue"]] = 0
            ch[f, ci["cue_conf"]] = 0
            ch[f, ci["val"]] = 2
            ch[f, ci["aro"]] = 1
        if visible:
            ch[f, ci["own_vis"]] = 0
            ch[f, ci["own_dist"]] = _dist_bin(float(dist[f]))
            ch[f, ci["own_bear"]] = _bearing_bin(float(bear[f]))
            ch[f, ci["own_gaze"]] = int(gaze[f])
            last_bearing_bin = int(ch[f, ci["own_bear"]])
        else:
            ch[f, ci["own_vis"]] = 1 if since < 80 else 2
            ch[f, ci["own_dist"]] = 3
            ch[f, ci["own_bear"]] = 8
            ch[f, ci["own_gaze"]] = 2
        ch[f, ci["own_motion"]] = int(motion[f])
        ch[f, ci["t_since_seen"]] = _t_since_bin(since)
        ch[f, ci["self_act"]] = busy_self if f <= busy_until else (
            {"none": 0, "follow": 2, "go_to": 1, "come": 1, "stay": 3,
             "search_owner": 1}[task_name]
        )
        ch[f, ci["base_busy"]] = int(base_busy[f])
        ch[f, ci["loc_health"]] = int(loc[f])
        ch[f, ci["task"]] = TASK.index(task_name)
        if f >= task_state_until:
            if task_name == "none":
                task_state = 0
            elif not visible and since >= 30 and task_name in ("follow", "go_to"):
                task_state = 2  # blocked
            elif int(base_busy[f]) == 2 and int(obstacle[f]) != 0:
                task_state = 2
            else:
                task_state = 1
            task_state_until = f + 5
        ch[f, ci["task_state"]] = task_state
        ch[f, ci["env"]] = env_id
        ch[f, ci["obstacle"]] = int(obstacle[f])
        ch[f, ci["people"]] = int(people[f])
        for k in range(HIST_K):
            if k < len(hist):
                cat, laughed = hist[len(hist) - 1 - k]
                ch[f, ci[f"hist{k}"]] = 1 + JOKE_CATEGORIES.index(cat) * 2 + int(laughed)
            else:
                ch[f, ci[f"hist{k}"]] = 0
        ch[f, ci["prof_greet"]] = profile.greet
        ch[f, ci["prof_praise"]] = profile.praise
        ch[f, ci["prof_pace"]] = profile.pace
        ch[f, ci["prof_sens"]] = profile.sens
        words[f] = words_by_frame.get(f, -1)

        # -- triggers ------------------------------------------------------
        for ev in trig_by_frame.get(f, ()):
            k = ev.kind
            det = bool(ev.detected and not ev.mislabeled)
            if k.startswith("cmd:"):
                name = ev.command or ""
                if name == "stop":
                    sched = [s for s in sched if s.prio <= 1]
                    sched.append(_Sched(due=f + 1, prio=0, act="<idle>",
                                        tag="comply:stop", expires=f + 6))
                    cmd_pending_until = f + 1
                    if det:
                        ann[f, ANN_INDEX["ev_stop_cue"]] = 1
                else:
                    dly = _PACE_COMPLY[pace] + rng.randrange(0, 2)
                    sched.append(_Sched(due=f + dly, prio=1, act=f"<skill:{name}>",
                                        tag=f"comply:{name}", expires=f + dly + 60,
                                        defer_ok=True, anchor=f, event="comply",
                                        detected=det))
                    cmd_pending_until = f + dly
            elif k == "joke_punchline":
                cat = ev.joke_cat or "pun"
                recent = [laughed for c, laughed in list(hist)[::-1] if c == cat][:3]
                anticipatable = sum(1 for x in recent if x) >= 2
                joke_state[ev.joke_id] = {"cat": cat, "punch_ref": f,
                                          "anticipated": anticipatable}
                ann[f, ANN_INDEX["ev_punchline"]] = 1
                ann[f, ANN_INDEX["punch_anticipatable"]] = int(anticipatable)
                if anticipatable:
                    dly = _PACE_BASE[pace] + rng.randrange(0, 3)
                    sched.append(_Sched(due=f + dly, prio=3, act="<emote:chuckle>",
                                        tag="chuckle:antic", expires=f + 15,
                                        anchor=f, event="chuckle", detected=det))
            elif k == "laugh":
                st = joke_state.get(ev.joke_id)
                if st is not None and not st["anticipated"] and f - st["punch_ref"] <= 25:
                    dly = _PACE_BASE[pace] + rng.randrange(0, 3)
                    sched.append(_Sched(due=f + dly, prio=3, act="<emote:chuckle>",
                                        tag="chuckle:react", expires=f + 15,
                                        anchor=f, event="chuckle", detected=det))
            elif k == "greeting":
                name = {"warm": "hello_pose", "playful": "paw_wave",
                        "brief": "attentive_nod"}[PROF_GREET[profile.greet]]
                sched.append(_Sched(due=f + _PACE_SOCIAL[pace], prio=4,
                                    act=f"<emote:{name}>", tag="greeting",
                                    expires=f + 20))
            elif k == "praise":
                name = "attentive_nod" if PROF_PRAISE[profile.praise] == "frequent" else "happy_wiggle"
                sched.append(_Sched(due=f + _PACE_SOCIAL[pace], prio=4,
                                    act=f"<emote:{name}>", tag="praise", expires=f + 20))
            elif k == "sigh" or (ev.val <= -1 and ev.aro == 0):
                dly = _PACE_COMFORT[pace] + rng.randrange(0, 3)
                sched.append(_Sched(due=f + dly, prio=4, act="<emote:comfort_bow>",
                                    tag="comfort", expires=f + 20, anchor=f,
                                    event="comfort", detected=det))
                if ch[f, ci["own_dist"]] == 2:  # far -> slow approach
                    for j in range(3):
                        sched.append(_Sched(due=f + dly + 2 + j, prio=5,
                                            act=twist(VX_SLOW, VYAW_ZERO),
                                            tag="approach", expires=f + dly + 12 + j))
            elif k == "scold":
                sched.append(_Sched(due=f + 1, prio=4, act="<idle>", tag="scold_idle",
                                    expires=f + 4))
                sched.append(_Sched(due=f + 3, prio=4, act="<gaze_release>",
                                    tag="scold_avert", expires=f + 12))
            elif k == "call_name":
                sched.append(_Sched(due=f + 2, prio=4, act="<gaze_owner>",
                                    tag="call_gaze", expires=f + 10))
                sched.append(_Sched(due=f + 2 + _PACE_SOCIAL[pace], prio=4,
                                    act="<emote:attentive_nod>", tag="call_attend",
                                    expires=f + 22))
            elif k == "owner_speaking" and ev.val >= 1 and ev.aro == 2:
                sched.append(_Sched(due=f + _PACE_SOCIAL[pace], prio=4,
                                    act="<emote:excited_paw_taps>", tag="excited",
                                    expires=f + 20))
            elif k == "question":
                sched.append(_Sched(due=f + 8 + rng.randrange(0, 3), prio=4,
                                    act="<emote:observing_head_tilt>", tag="question",
                                    expires=f + 40))
        # laugh-window closure -> hist update
        for jid, st in list(joke_state.items()):
            if f == st["punch_ref"] + 26:
                jm = joke_meta[jid] if 0 <= jid < len(joke_meta) else None
                hist.append((st["cat"], bool(jm and jm["laughed"])))
                joke_state.pop(jid, None)

        # rule 2 — look back / lost
        if task_name in ("follow", "go_to"):
            if not visible and lost_since < 0 and since >= 1:
                lost_since = max(last_seen, 0)
            if visible and lost_since >= 0:
                if f - lost_since >= 30:
                    sched.append(_Sched(due=f + _PACE_SOCIAL[pace], prio=2,
                                        act="<emote:attentive_nod>", tag="reunion",
                                        expires=f + 20))
                lost_since = -1
            if lost_since >= 0:
                age = f - lost_since
                key30 = lost_since * 10 + 1
                key80 = lost_since * 10 + 2
                if age == 30 and key30 not in lost_handled:
                    lost_handled.add(key30)
                    sched.append(_Sched(due=f + rng.randrange(0, 3), prio=2,
                                        act=f"<gaze_bearing_{last_bearing_bin}>",
                                        tag="lookback", expires=f + 20,
                                        anchor=lost_since, event="lookback",
                                        extra=last_bearing_bin))
                if age == 80 and key80 not in lost_handled:
                    lost_handled.add(key80)
                    yaw = _yaw_index_for_bearing(last_bearing_bin)
                    sched.append(_Sched(due=f + 1, prio=2, act=twist(VX_ZERO, yaw),
                                        tag="turn_back", expires=f + 12))
                    sched.append(_Sched(due=f + 5, prio=2,
                                        act="<emote:confused_head_tilt>",
                                        tag="turn_back_tilt", expires=f + 25))
        # blocked task -> gaze alternation at the owner
        if task_state == 2 and f % 25 == 0 and visible:
            sched.append(_Sched(due=f + 1, prio=4,
                                act="<gaze_owner>" if (f // 25) % 2 == 0 else "<gaze_release>",
                                tag="blocked_gaze", expires=f + 8))

        # rule 5 — liveness
        if dlg[f] == 1 and prev_dlg != 1 and f - last_gaze > 15:
            sched.append(_Sched(due=f + 1 + rng.randrange(0, 2), prio=5,
                                act="<gaze_owner>", tag="listen_gaze", expires=f + 10))
        if dlg[f] == 2 and rng.random() < 0.03:
            sched.append(_Sched(due=f, prio=5, act="<filler_gesture_0>",
                                tag="think_filler", expires=f + 3))
        if f - last_nonidle > 200 and rng.random() < 0.012:
            sched.append(_Sched(due=f, prio=5,
                                act="<emote:stretch>" if rng.random() < 0.5 else "<emote:curious_look>",
                                tag="liveness", expires=f + 6))
        prev_dlg = int(dlg[f])

        # -- act selection --------------------------------------------------
        sched = [s for s in sched if s.expires >= f]
        ready = [s for s in sched if s.due <= f]
        ready.sort(key=lambda s: (s.prio, s.due))
        chosen: _Sched | None = None
        for s in ready:
            aid = ACT_ID[s.act]
            critical = int(base_busy[f]) == 2
            is_body = aid in EMOTE_OR_SKILL_IDS or s.act.startswith("<twist:")
            if critical and is_body:
                if s.defer_ok:
                    s.due = f + 1
                    if s.anchor >= 0:
                        s.anchor = f  # window is measured from first allowed frame
                    continue
                sched.remove(s)
                continue
            if aid in EMOTE_IDS:
                if f <= busy_until and s.prio > 1:
                    sched.remove(s)
                    continue
                if s.act == "<emote:chuckle>":  # noqa: SIM102
                    if f - last_chuckle < 50 or f <= cmd_pending_until:
                        sched.remove(s)
                        continue
            if aid in SKILL_IDS and f <= busy_until and s.prio > 1:
                sched.remove(s)
                continue
            chosen = s
            break

        act_id = IDLE_ID
        if chosen is not None:
            act_id = ACT_ID[chosen.act]
            sched.remove(chosen)
            if chosen.event and chosen.anchor >= 0:
                ann[chosen.anchor, ANN_INDEX[f"ev_{chosen.event}"]] = 1
                ann[chosen.anchor, ANN_INDEX[f"tgt_{chosen.event}"]] = act_id
                if chosen.event != "lookback":
                    ann[chosen.anchor, ANN_INDEX[f"det_{chosen.event}"]] = int(chosen.detected)
                else:
                    ann[chosen.anchor, ANN_INDEX["lookback_front"]] = int(chosen.extra == 0)
            if act_id in EMOTE_IDS:
                name = ACT_VOCAB[act_id][len("<emote:") : -1]
                busy_until = f + rng.randrange(8, 16)
                busy_self = SELF_ACT.index(f"emote:{name}")
                if name == "chuckle":
                    last_chuckle = f
            elif act_id in SKILL_IDS:
                name = ACT_VOCAB[act_id][len("<skill:") : -1]
                busy_until = f + rng.randrange(15, 41)
                busy_self = SELF_ACT.index(f"skill:{name}")
                cmd_pending_until = -1
                # a pre-empting command clears queued expressive acts
                sched = [s for s in sched if s.prio <= 2]
            elif act_id != IDLE_ID:
                last_gaze = f
        acts[f] = act_id
        if act_id != IDLE_ID:
            last_nonidle = f

    # non-funny punchline anchors (false-chuckle denominator)
    for jm in joke_meta:
        if not jm["laughed"] and not profile.likes(jm["cat"]):
            p = min(T - 1, jm["punch_t"] + 3)
            ann[p, ANN_INDEX["ev_nonfunny_punch"]] = 1

    return Episode(
        family=family,
        seed=seed,
        profile=profile,
        channels=ch,
        acts=acts,
        words=words,
        ann=ann,
        held_out_family=family in HELD_OUT_FAMILIES,
        held_out_profile=held_out_profile,
        held_out_phrasing=held_out_phrasing,
        meta={
            "T": T,
            "n_events": len(events),
            "n_jokes": len(joke_meta),
            "taste": profile.taste,
            "pace": pace,
            "task": task_name,
        },
    )


# ---------------------------------------------------------------------------
# Text serialization (LM arm)
# ---------------------------------------------------------------------------

_DLG_S = ("idle", "lis", "think", "spk")
_VIS_S = ("vis", "occ", "unk")
_DIST_S = ("near", "mid", "far", "unk")
_MOT_S = ("still", "walk", "appr", "leave")
_TSS_S = ("t0", "t1", "t3", "t8", "t20")
_BUSY_S = ("free", "busy", "CRIT")
_TASK_S = ("-", "follow", "goto", "come", "stay", "search")
_TSTATE_S = ("idle", "prog", "blocked", "done")


def frame_line(ch_row: np.ndarray, word_id: int, act_id: int | None) -> str:
    """One compact text line per frame; default-valued fields are omitted."""

    ci = CHANNEL_INDEX
    parts: list[str] = [_DLG_S[int(ch_row[ci["dlg"]])]]
    cue = int(ch_row[ci["cue"]])
    if cue:
        conf = CUE_CONF[int(ch_row[ci["cue_conf"]])]
        parts.append(f"cue={CUE[cue]}/{conf}")
        v, a = int(ch_row[ci["val"]]) - 2, int(ch_row[ci["aro"]])
        if v or a != 1:
            parts.append(f"v{v}a{a}")
    vis = int(ch_row[ci["own_vis"]])
    if vis == 0:
        parts.append(
            f"own={_DIST_S[int(ch_row[ci['own_dist']])]},b{int(ch_row[ci['own_bear']])}"
            f",{'eye' if int(ch_row[ci['own_gaze']]) == 0 else 'away'}"
            f",{_MOT_S[int(ch_row[ci['own_motion']])]}"
        )
    else:
        parts.append(f"own={_VIS_S[vis]},{_TSS_S[int(ch_row[ci['t_since_seen']])]}")
    self_act = int(ch_row[ci["self_act"]])
    if self_act:
        parts.append(f"self={SELF_ACT[self_act]}")
    busy = int(ch_row[ci["base_busy"]])
    if busy:
        parts.append(_BUSY_S[busy])
    task = int(ch_row[ci["task"]])
    if task:
        parts.append(f"task={_TASK_S[task]}/{_TSTATE_S[int(ch_row[ci['task_state']])]}")
    obst = int(ch_row[ci["obstacle"]])
    if obst:
        parts.append(f"obs={OBSTACLE[obst]}")
    if word_id >= 0:
        parts.append(f'w="{PHRASES.strings[word_id]}"')
    line = " ".join(parts)
    if act_id is None:
        return line + " >"
    return f"{line} > {ACT_VOCAB[act_id]}"


def episode_header(ep: Episode) -> str:
    ci = CHANNEL_INDEX
    row = ep.channels[0]
    hist = " ".join(HIST[int(row[ci[f'hist{k}']])] for k in range(HIST_K))
    return (
        f"env={ENV[int(row[ci['env']])]} "
        f"prof={PROF_GREET[int(row[ci['prof_greet']])]}/"
        f"{PROF_PRAISE[int(row[ci['prof_praise']])]}/"
        f"{PROF_PACE[int(row[ci['prof_pace']])]}/"
        f"{PROF_SENS[int(row[ci['prof_sens']])]} hist={hist}"
    )


def render_context(ep: Episode, f: int, ctx: int = 32) -> str:
    """Text prompt for arm D: the last ``ctx`` frames, last one un-acted."""

    ci = CHANNEL_INDEX
    lo = max(0, f - ctx + 1)
    lines = []
    row0 = ep.channels[lo]
    hist = ",".join(HIST[int(row0[ci[f'hist{k}']])] for k in range(HIST_K))
    lines.append(
        f"# env={ENV[int(row0[ci['env']])]} "
        f"prof={PROF_GREET[int(row0[ci['prof_greet']])]}/"
        f"{PROF_PRAISE[int(row0[ci['prof_praise']])]}/"
        f"{PROF_PACE[int(row0[ci['prof_pace']])]}/"
        f"{PROF_SENS[int(row0[ci['prof_sens']])]} hist={hist}"
    )
    for t in range(lo, f):
        lines.append(frame_line(ep.channels[t], int(ep.words[t]), int(ep.acts[t])))
    lines.append(frame_line(ep.channels[f], int(ep.words[f]), None))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Split construction
# ---------------------------------------------------------------------------

SPLIT_PLAN_DEFAULT = {
    "train": {"n": 3000, "families": TRAIN_FAMILIES, "profile": "train", "phrasing": "train"},
    "dev": {"n": 500, "families": TRAIN_FAMILIES, "profile": "train", "phrasing": "train"},
    # A3 top-up (2026-08-28, post-start): slice sizes raised so every scored
    # M2 sub-score has >= 200 events.  Episode i of a slice keeps its original
    # seed, so the first 240/200/160/160 episodes are bit-identical.
    "frozen_core": {"n": 300, "families": TRAIN_FAMILIES, "profile": "train", "phrasing": "train"},
    "frozen_family": {"n": 260, "families": HELD_OUT_FAMILIES, "profile": "train", "phrasing": "train"},
    "frozen_profile": {"n": 360, "families": TRAIN_FAMILIES, "profile": "held", "phrasing": "train"},
    "frozen_phrasing": {"n": 360, "families": TRAIN_FAMILIES, "profile": "train", "phrasing": "held"},
}
FROZEN_SPLITS = ("frozen_core", "frozen_family", "frozen_profile", "frozen_phrasing")


def episode_spec(split: str, index: int, plan: dict, master_seed: int) -> dict:
    cfg = plan[split]
    fams = cfg["families"]
    seed = int(
        hashlib.sha256(f"{master_seed}:{split}:{index}".encode()).hexdigest()[:12], 16
    )
    return {
        "seed": seed,
        "family": fams[index % len(fams)],
        "held_out_profile": cfg["profile"] == "held",
        "held_out_phrasing": cfg["phrasing"] == "held",
        "split": split,
        "index": index,
    }


def _gen_one(spec: dict) -> Episode:
    ep = generate_episode(
        seed=spec["seed"],
        family=spec["family"],
        held_out_profile=spec["held_out_profile"],
        held_out_phrasing=spec["held_out_phrasing"],
    )
    ceil = generate_episode(
        seed=spec["seed"],
        family=spec["family"],
        held_out_profile=spec["held_out_profile"],
        held_out_phrasing=spec["held_out_phrasing"],
        observed_only=True,
    )
    assert ceil.channels.shape == ep.channels.shape
    ep.acts_ceiling = ceil.acts
    return ep


def _pack(episodes: list[Episode]) -> dict[str, np.ndarray | list]:
    lens = [len(e.acts) for e in episodes]
    starts = np.cumsum([0] + lens[:-1]).astype(np.int64)
    return {
        "channels": np.concatenate([e.channels for e in episodes], axis=0),
        "acts": np.concatenate([e.acts for e in episodes], axis=0),
        "acts_ceiling": np.concatenate([e.acts_ceiling for e in episodes], axis=0),
        "words": np.concatenate([e.words for e in episodes], axis=0),
        "ann": np.concatenate([e.ann for e in episodes], axis=0),
        "ep_start": starts,
        "ep_len": np.asarray(lens, dtype=np.int64),
        "ep_family": np.asarray([FAMILIES.index(e.family) for e in episodes], dtype=np.int16),
        "ep_seed": np.asarray([e.seed for e in episodes], dtype=np.int64),
        "ep_flags": np.asarray(
            [[e.held_out_family, e.held_out_profile, e.held_out_phrasing] for e in episodes],
            dtype=np.int8,
        ),
    }


def _worker(args):
    split, index, plan, master_seed = args
    ep = _gen_one(episode_spec(split, index, plan, master_seed))
    return (
        index,
        ep.family,
        ep.seed,
        ep.channels,
        ep.acts,
        ep.words,
        ep.ann,
        ep.held_out_family,
        ep.held_out_profile,
        ep.held_out_phrasing,
        ep.acts_ceiling,
    )


def generate_split(split: str, plan: dict, master_seed: int, workers: int = 24) -> dict:
    import multiprocessing as mp

    n = plan[split]["n"]
    tasks = [(split, i, plan, master_seed) for i in range(n)]
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            rows = pool.map(_worker, tasks, chunksize=8)
    else:
        rows = [_worker(t) for t in tasks]
    rows.sort(key=lambda r: r[0])
    episodes = [
        Episode(
            family=r[1], seed=r[2], profile=Profile(0, 0, 0, 0, 0), channels=r[3],
            acts=r[4], acts_ceiling=r[10], words=r[5], ann=r[6],
            held_out_family=r[7], held_out_profile=r[8], held_out_phrasing=r[9],
        )
        for r in rows
    ]
    return _pack(episodes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260828)
    ap.add_argument("--out", default=os.path.expanduser("~/.cache/parcel-0e/bm1/data"))
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--train-episodes", type=int, default=3000)
    ap.add_argument("--sample-only", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    plan = {k: dict(v) for k, v in SPLIT_PLAN_DEFAULT.items()}
    plan["train"]["n"] = args.train_episodes

    here = Path(__file__).resolve().parent
    if args.sample_only:
        write_sample_episodes(here / "sample_episodes.txt", args.seed)
        print("wrote sample_episodes.txt")
        return

    write_sample_episodes(here / "sample_episodes.txt", args.seed)

    manifest = {
        "master_seed": args.seed,
        "frame_hz": FRAME_HZ,
        "n_channels": N_CHANNELS,
        "channels": [{"name": n, "size": len(v)} for n, v in CHANNELS],
        "n_acts": N_ACTS,
        "act_vocab": list(ACT_VOCAB),
        "families": list(FAMILIES),
        "held_out_families": list(HELD_OUT_FAMILIES),
        "taste_masks_total": len(TASTE_MASKS),
        "taste_masks_train": len(TASTE_TRAIN),
        "taste_masks_held": len(TASTE_HELD),
        "phrase_strings": PHRASES.n_strings(),
        "phrasing_held_frac": 0.30,
        "windows_frames": WINDOWS,
        "splits": {},
    }
    for split in plan:
        packed = generate_split(split, plan, args.seed, workers=args.workers)
        np.savez(out / f"{split}.npz", **packed)
        acts = packed["acts"]
        ann = packed["ann"]
        manifest["splits"][split] = {
            "episodes": len(packed["ep_len"]),
            "frames": len(acts),
            "families": sorted({FAMILIES[i] for i in packed["ep_family"].tolist()}),
            "held_out_profile": bool(packed["ep_flags"][:, 1].any()),
            "held_out_phrasing": bool(packed["ep_flags"][:, 2].any()),
            "nonidle_frame_frac": round(float((acts != IDLE_ID).mean()), 5),
            "critical_frame_frac": round(
                float((packed["channels"][:, CHANNEL_INDEX["base_busy"]] == 2).mean()), 5
            ),
            "events": {
                "chuckle": int(ann[:, ANN_INDEX["ev_chuckle"]].sum()),
                "lookback": int(ann[:, ANN_INDEX["ev_lookback"]].sum()),
                "comply": int(ann[:, ANN_INDEX["ev_comply"]].sum()),
                "comfort": int(ann[:, ANN_INDEX["ev_comfort"]].sum()),
                "nonfunny_punchlines": int(ann[:, ANN_INDEX["ev_nonfunny_punch"]].sum()),
                "punchlines": int(ann[:, ANN_INDEX["ev_punchline"]].sum()),
                "anticipatable_punchlines": int(ann[:, ANN_INDEX["punch_anticipatable"]].sum()),
                "stop_cues": int(ann[:, ANN_INDEX["ev_stop_cue"]].sum()),
                "chuckle_detected_anchor": int(ann[:, ANN_INDEX["det_chuckle"]].sum()),
                "comply_detected_anchor": int(ann[:, ANN_INDEX["det_comply"]].sum()),
                "comfort_detected_anchor": int(ann[:, ANN_INDEX["det_comfort"]].sum()),
                "lookback_front_anchor": int(ann[:, ANN_INDEX["lookback_front"]].sum()),
            },
            "ceiling_agreement_frames": round(
                float((packed["acts_ceiling"] == acts).mean()), 5
            ),
        }
        print(f"{split}: {manifest['splits'][split]}", flush=True)

    manifest["frozen_splits"] = list(FROZEN_SPLITS)
    (here / "splits.json").write_text(json.dumps(manifest, indent=2))
    (out / "phrases.json").write_text(json.dumps(PHRASES.strings))
    print(f"wrote {here / 'splits.json'}")


def write_sample_episodes(path: Path, master_seed: int, n_frames: int = 30) -> None:
    """A readable excerpt per family, centred on that family's key event."""

    focus = {
        "chat_at_home": "cue=joke_punchline",
        "joke_while_following": "cue=joke_punchline",
        "lost_outdoors": "lookback",
        "command_during_emote": "cue=cmd",
        "sad_owner_far": "cue=sigh",
        "busy_navigation": "CRIT",
        "greeting_and_praise": "cue=greeting",
        "joke_while_lost": "cue=joke_punchline",
        "command_during_chuckle": "cue=cmd",
    }
    chunks: list[str] = []
    for fam in FAMILIES:
        found = False
        for attempt in range(40):
            seed = int(
                hashlib.sha256(f"sample:{master_seed}:{fam}:{attempt}".encode()).hexdigest()[:12],
                16,
            )
            ep = generate_episode(seed=seed, family=fam, held_out_profile=False,
                                  held_out_phrasing=False)
            key = focus[fam]
            centre = -1
            for f in range(len(ep.acts)):
                line = frame_line(ep.channels[f], int(ep.words[f]), int(ep.acts[f]))
                if key == "lookback":
                    if ep.ann[f, ANN_INDEX["ev_lookback"]]:
                        centre = f + 30
                        break
                elif key in line:
                    centre = f
                    break
            if centre < 0:
                continue
            lo = max(0, centre - 4)
            hi = min(len(ep.acts), lo + n_frames)
            head = [
                (f"=== family={fam} seed={seed} T={len(ep.acts)} "
                f"taste={ep.profile.taste:06b} pace={ep.profile.pace_name()} "
                f"frames {lo}..{hi - 1} ==="),
                "# " + episode_header(ep),
            ]
            body = [
                f"{f:5d} " + frame_line(ep.channels[f], int(ep.words[f]), int(ep.acts[f]))
                for f in range(lo, hi)
            ]
            chunks.append("\n".join(head + body))
            found = True
            break
        if not found:
            chunks.append(f"=== family={fam}: no frame matched focus key ===")
    path.write_text("\n\n".join(chunks) + "\n")


if __name__ == "__main__":
    main()
