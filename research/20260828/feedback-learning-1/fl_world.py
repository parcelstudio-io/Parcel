"""FL-1 world: BM-1's ``worldsim`` episode generator driven by FL-1 owners.

READ-ONLY reuse of ``research/20260828/behavior-model-1/worldsim.py``: the
generator, the frame schema, the phrase tables, the scripted teacher, the
cue-detector noise and the M2 windows all come from there.  Nothing in that
folder is modified; FL-1 injects its owners by swapping ``worldsim``'s
``sample_profile`` / ``DialogueEvent`` bindings inside a context manager and
post-processes the returned arrays.

FL-1 frame schema (AMENDMENTS F2) = worldsim's 19 world channels + 4 profile
channels + ``joke_cat`` + 18 per-category history channels.  BM-1's
``hist0..hist5`` (last-6 GLOBAL joke events) are DROPPED and replaced, because
F2 requires a per-category (laughed, total, recency) state.  ``joke_cat`` is an
FL-1 addition: BM-1's ``cue`` vocabulary marks ``joke_punchline`` but carries no
category, so BM-1's arm C literally cannot condition a chuckle on the category.
"""

from __future__ import annotations

import contextlib
import random
from dataclasses import dataclass

import numpy as np
import owners as O
import worldsim as W
from owners import CATEGORIES, NCAT, HistoryState, Owner

# --- FL-1 channel layout ----------------------------------------------------
BASE_N = 19                                     # dlg .. people
PROF_SLICE = slice(W.CHANNEL_INDEX["prof_greet"], W.CHANNEL_INDEX["prof_sens"] + 1)
BASE_NAMES = tuple(W.CHANNEL_NAMES[:BASE_N])
PROF_NAMES = tuple(W.CHANNEL_NAMES[PROF_SLICE])
FL_CHANNEL_NAMES = BASE_NAMES + PROF_NAMES + ("joke_cat",) + O.HIST_CHANNEL_NAMES
FL_CHANNEL_SIZES = (
    tuple(W.CHANNEL_SIZES[:BASE_N])
    + tuple(W.CHANNEL_SIZES[PROF_SLICE])
    + (NCAT + 1,)
    + O.HIST_CHANNEL_SIZES
)
FL_N_CHANNELS = len(FL_CHANNEL_NAMES)
JOKE_CAT_IDX = BASE_N + 4
HIST_SLICE = slice(JOKE_CAT_IDX + 1, FL_N_CHANNELS)

CHUCKLE_ID = W.ACT_ID["<emote:chuckle>"]
IDLE_ID = W.IDLE_ID
SELF_CHUCKLE = W.SELF_ACT.index("emote:chuckle")
SELF_TASK_MAX = 4  # SELF_ACT[0:4] are task states; >= 4 means mid-emote / mid-skill

DECISION_OFFSET = 3   # 0.3 s after the punchline reference frame -- the earliest
                      # frame inside BM-1's M2 chuckle window [3, 15] and always
                      # strictly before the laugh cue (laugh delay >= 5 frames).
HIST_CLOSE = 26       # worldsim closes the laugh window 2.6 s after the punchline


class FLProfile(W.Profile):
    """worldsim ``Profile`` whose humour is an FL-1 owner's continuous taste."""

    def __init__(self, owner: Owner, rng: random.Random):
        super().__init__(
            taste=0,
            greet=rng.randrange(len(W.PROF_GREET)),
            praise=rng.randrange(len(W.PROF_PRAISE)),
            pace=rng.randrange(len(W.PROF_PACE)),
            sens=rng.randrange(len(W.PROF_SENS)),
        )
        self.owner = owner

    def likes(self, category: str) -> bool:
        return self.owner.likes(CATEGORIES.index(category))

    def laugh_prob(self, category: str) -> float:
        return float(self.owner.p_laugh[CATEGORIES.index(category)])


@contextlib.contextmanager
def _owner_patch(owner: Owner, recorder: list):
    """Swap worldsim's profile sampler and event class for the duration."""

    class _Rec(W.DialogueEvent):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            recorder.append(self)

    old_sample, old_event = W.sample_profile, W.DialogueEvent
    W.sample_profile = lambda rng, *, held_out_taste: FLProfile(owner, rng)
    W.DialogueEvent = _Rec
    try:
        yield
    finally:
        W.sample_profile, W.DialogueEvent = old_sample, old_event


@dataclass
class Joke:
    ep: int
    cat: int
    punch_ref: int      # teacher reference frame for the punchline
    decision: int       # frame at which the anticipatory decision is emitted
    laughed: bool
    laugh_ref: int      # -1 if the owner did not laugh
    setup_t: int
    evaluable: bool     # the world allowed a chuckle at ``decision``


@dataclass
class FLEpisode:
    ch: np.ndarray        # (T, FL_N_CHANNELS) int16
    acts: np.ndarray      # (T,) int16
    ann: np.ndarray       # (T, N_ANN) int16 (worldsim's M2 annotations)
    jokes: list[Joke]
    family: str
    seed: int


JOKE_FAMILIES = ("chat_at_home", "joke_while_following", "command_during_chuckle",
                 "joke_while_lost", "command_during_emote", "greeting_and_praise")


def _raw_episode(owner: Owner, seed: int, family: str):
    rec: list = []
    with _owner_patch(owner, rec):
        ep = W.generate_episode(seed=seed, family=family,
                                held_out_profile=False, held_out_phrasing=False)
    punch = {e.joke_id: e for e in rec if e.kind == "joke_punchline" and e.joke_id >= 0}
    laugh = {e.joke_id: e for e in rec if e.kind == "laugh" and e.joke_id >= 0}
    setup = {}
    for e in rec:
        if e.kind == "joke_setup":
            setup.setdefault(e.joke_cat, []).append(e.t)
    jokes = []
    for jid in sorted(punch):
        pe = punch[jid]
        le = laugh.get(jid)
        jokes.append({
            "cat": CATEGORIES.index(pe.joke_cat),
            "punch_ref": int(pe.ref_t),
            "laughed": le is not None,
            "laugh_ref": int(le.ref_t) if le is not None else -1,
            "setup_t": max(0, int(pe.t) - 30),
        })
    return ep, jokes


def _clear_chuckle(acts, ch_self, frame, T, task_self=0):
    """Remove a chuckle emission at ``frame`` and its self_act busy span."""
    acts[frame] = IDLE_ID
    f = frame + 1
    while f < T and ch_self[f] == SELF_CHUCKLE:
        ch_self[f] = task_self
        f += 1


def build_episode(owner: Owner, seed: int, family: str, hist: HistoryState,
                  ep_index: int, rng: np.random.Generator,
                  q_echo: float = 0.0, m_mask: float = 0.0,
                  behavior: str = "teacher") -> FLEpisode:
    """One FL-1 episode: worldsim frames, FL-1 chuckle relabel, FL-1 history.

    ``hist`` is mutated in place so a sequence of episodes for one owner carries
    that owner's accumulated history forward.
    """
    ep, jokes = _raw_episode(owner, seed, family)
    T = len(ep.acts)
    acts = ep.acts.copy()
    ann = ep.ann.copy()
    wch = ep.channels
    self_col = wch[:, W.CHANNEL_INDEX["self_act"]].copy()
    busy = wch[:, W.CHANNEL_INDEX["base_busy"]]
    task_self = {"none": 0, "follow": 2, "go_to": 1, "come": 1, "stay": 3,
                 "search_owner": 1}[W.TASK[int(wch[0, W.CHANNEL_INDEX["task"]])]]

    # 1. strip worldsim's own anticipatory chuckles (its 2-of-last-3 GLOBAL rule)
    for j in jokes:
        pr = j["punch_ref"]
        if pr < T and ann[pr, W.ANN_INDEX["ev_chuckle"]] == 1:
            for f in range(pr, min(T, pr + 16)):
                if acts[f] == CHUCKLE_ID:
                    _clear_chuckle(acts, self_col, f, T, task_self)
                    break
            ann[pr, W.ANN_INDEX["ev_chuckle"]] = 0
            ann[pr, W.ANN_INDEX["tgt_chuckle"]] = 0

    # 2. place FL-1 anticipatory chuckles: target = the owner's own reaction
    out_jokes: list[Joke] = []
    for j in jokes:
        pr, g = j["punch_ref"], j["punch_ref"] + DECISION_OFFSET
        laugh_ref = j["laugh_ref"]
        evaluable = (
            g < T - 20
            and int(busy[g]) != 2                      # not a critical frame
            and acts[g] == IDLE_ID
            and self_col[g] < SELF_TASK_MAX             # not already mid-emote/skill
            and (laugh_ref < 0 or laugh_ref > g)       # F3: decision precedes the laugh
        )
        if evaluable and j["laughed"]:
            acts[g] = CHUCKLE_ID
            ann[pr, W.ANN_INDEX["ev_chuckle"]] = 1
            ann[pr, W.ANN_INDEX["tgt_chuckle"]] = CHUCKLE_ID
            for f in range(g + 1, min(T, g + 13)):
                if self_col[f] >= SELF_TASK_MAX:
                    break
                self_col[f] = SELF_CHUCKLE
            # habituation: suppress worldsim's reactive chuckle for 5 s
            for f in range(g + 1, min(T, g + 51)):
                if acts[f] == CHUCKLE_ID:
                    _clear_chuckle(acts, self_col, f, T, task_self)
                    if laugh_ref >= 0 and laugh_ref < T:
                        ann[laugh_ref, W.ANN_INDEX["ev_chuckle"]] = 0
                        ann[laugh_ref, W.ANN_INDEX["tgt_chuckle"]] = 0
        out_jokes.append(Joke(ep=ep_index, cat=j["cat"], punch_ref=pr, decision=g,
                              laughed=j["laughed"], laugh_ref=laugh_ref,
                              setup_t=j["setup_t"], evaluable=bool(evaluable)))

    # 3. FL-1 channel tensor
    ch = np.zeros((T, FL_N_CHANNELS), dtype=np.int16)
    ch[:, :BASE_N] = wch[:, :BASE_N]
    ch[:, W.CHANNEL_INDEX["self_act"]] = self_col
    ch[:, BASE_N:BASE_N + 4] = wch[:, PROF_SLICE]

    # joke_cat: known from the joke content, from the setup to 2.5 s past the punchline
    for j in out_jokes:
        a, b = j.setup_t, min(T, j.punch_ref + HIST_CLOSE)
        ch[a:b, JOKE_CAT_IDX] = j.cat + 1

    # per-category history, updated when each laugh window closes
    order = sorted(out_jokes, key=lambda j: j.punch_ref)
    bounds = [0]
    for j in order:
        bounds.append(min(T, j.punch_ref + HIST_CLOSE))
    bounds.append(T)
    cur = hist.channels()
    pos = 0
    for i, j in enumerate(order):
        stop = bounds[i + 1]
        ch[pos:stop, HIST_SLICE] = cur
        pos = stop
        dog = bool(acts[j.decision] == CHUCKLE_ID) if behavior == "teacher" else False
        obs = O.observe_laugh(j.laughed, dog, rng, q_echo, m_mask)
        hist.observe(j.cat, obs)
        cur = hist.channels()
    ch[pos:T, HIST_SLICE] = cur

    return FLEpisode(ch=ch, acts=acts, ann=ann, jokes=out_jokes,
                     family=family, seed=seed)


def owner_stream(owner: Owner, n_jokes: int, seed: int, rng: np.random.Generator,
                 families: tuple[str, ...] = JOKE_FAMILIES,
                 max_eps: int = 24, **kw) -> tuple[list[FLEpisode], HistoryState]:
    """Consecutive episodes for one owner until ``n_jokes`` jokes are collected."""
    hist = HistoryState()
    eps: list[FLEpisode] = []
    got = 0
    r = random.Random(seed)
    for k in range(max_eps):
        fam = families[k % len(families)]
        e = build_episode(owner, seed * 131 + k * 7919 + r.randrange(1 << 20), fam,
                          hist, k, rng, **kw)
        eps.append(e)
        got += len(e.jokes)
        if got >= n_jokes:
            break
    return eps, hist


def main() -> None:  # pragma: no cover - sample dump
    rng = np.random.default_rng(1)
    o = O.sample_owner(0, O.SEED_BASE + O.EVAL_SEED_OFFSET)
    eps, _hist = owner_stream(o, 12, 12345, rng)
    e = eps[0]
    print("FL channels:", FL_N_CHANNELS, "sizes:", FL_CHANNEL_SIZES)
    print("episode T:", len(e.acts), "family:", e.family, "jokes:", len(e.jokes))
    for j in e.jokes:
        print(f"  joke cat={CATEGORIES[j.cat]:9s} p={o.p_laugh[j.cat]:.2f} punch_ref={j.punch_ref} "
              f"decision={j.decision} laughed={j.laughed} laugh_ref={j.laugh_ref} "
              f"eval={j.evaluable} act@dec={W.ACT_VOCAB[e.acts[j.decision]]}")


if __name__ == "__main__":
    main()


# --- loss events (H-FL1c) ---------------------------------------------------
LOSS_MIN_FRAMES = 20  # a real loss, not visibility flicker


def loss_events(ep: FLEpisode) -> list[int]:
    """Frames at which the owner is lost while the dog is on a follow/go_to task."""
    task = ep.ch[:, W.CHANNEL_INDEX["task"]]
    vis = ep.ch[:, W.CHANNEL_INDEX["own_vis"]]
    out: list[int] = []
    T = len(vis)
    f = 0
    while f < T:
        if vis[f] != 0 and W.TASK[int(task[f])] in ("follow", "go_to"):
            g = f
            while g < T and vis[g] != 0:
                g += 1
            if g - f >= LOSS_MIN_FRAMES:
                out.append(f)
            f = g
        else:
            f += 1
    return out


def owner_loss_stream(owner: Owner, n_losses: int, seed: int,
                      families: tuple[str, ...] = ("lost_outdoors", "joke_while_following",
                                                   "busy_navigation", "joke_while_lost"),
                      max_eps: int = 60) -> list[int]:
    """Inter-loss structure taken from worldsim episodes; returns loss onset frames."""
    rng = np.random.default_rng(seed)
    hist = HistoryState()
    out: list[int] = []
    for k in range(max_eps):
        e = build_episode(owner, seed * 7 + k * 104729, families[k % len(families)],
                          hist, k, rng)
        out.extend(loss_events(e))
        if len(out) >= n_losses:
            break
    return out[:n_losses]
