"""FL-1 corpora: owner books -> concatenated FL-1 frame streams + joke records."""

from __future__ import annotations

from dataclasses import dataclass

import fl_world as F
import numpy as np
import worldsim as W


@dataclass
class Corpus:
    ch: np.ndarray            # (N, 42) int8
    acts: np.ndarray          # (N,) int16
    ann: np.ndarray           # (N, N_ANN) int16
    dec_mask: np.ndarray      # (N,) uint8, 1 at anticipatory-decision frames
    ep_start: np.ndarray      # (E,) int64
    ep_len: np.ndarray        # (E,) int64
    ep_owner: np.ndarray      # (E,) int64
    ep_family: np.ndarray     # (E,) int16
    jokes: list               # list of dict rows (global frame indices)
    owners: list


def build_corpus(book, n_jokes: int, seed: int, families=F.JOKE_FAMILIES,
                 q_echo: float = 0.0, m_mask: float = 0.0) -> Corpus:
    chs, acts, anns, dms = [], [], [], []
    starts, lens, owner_of, fams = [], [], [], []
    jokes: list[dict] = []
    off = 0
    for oi, o in enumerate(book):
        rng = np.random.default_rng(o.seed * 7919 + seed)
        eps, _ = F.owner_stream(o, n_jokes, o.seed + seed, rng, families=families,
                                q_echo=q_echo, m_mask=m_mask)
        seen = 0
        for e in eps:
            T = len(e.acts)
            chs.append(e.ch.astype(np.int8))
            acts.append(e.acts)
            anns.append(e.ann)
            dm = np.zeros(T, np.uint8)
            for j in e.jokes:
                if j.evaluable:
                    dm[j.decision] = 1
            dms.append(dm)
            starts.append(off)
            lens.append(T)
            owner_of.append(oi)
            fams.append(W.FAMILIES.index(e.family))
            for j in sorted(e.jokes, key=lambda x: x.punch_ref):
                if seen >= n_jokes:
                    break
                jokes.append({"owner": oi, "n": seen, "cat": j.cat,
                              "punch": off + j.punch_ref, "dec": off + j.decision,
                              "laughed": bool(j.laughed), "evaluable": bool(j.evaluable),
                              "laugh_ref": (off + j.laugh_ref) if j.laugh_ref >= 0 else -1})
                seen += 1
            off += T
    return Corpus(
        ch=np.concatenate(chs, 0), acts=np.concatenate(acts, 0),
        ann=np.concatenate(anns, 0), dec_mask=np.concatenate(dms, 0),
        ep_start=np.asarray(starts, dtype=np.int64), ep_len=np.asarray(lens, dtype=np.int64),
        ep_owner=np.asarray(owner_of, dtype=np.int64),
        ep_family=np.asarray(fams, dtype=np.int16), jokes=jokes, owners=list(book),
    )
