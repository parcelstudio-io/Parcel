"""FL-1 policy C: a BehaviorFormer (BM-1 arm C architecture, FL-1's own retrain).

6-layer causal transformer, d=256, 4 heads, context 128 frames (12.8 s), one
act token per frame from BM-1's ``ActTokenCodec`` vocabulary.  AMENDMENTS F2
forbids inheriting BM-1's checkpoints, so this is trained from scratch on FL-1
episodes with the per-category history channel.
"""

from __future__ import annotations

import torch
import torch.nn.functional as Fn
from torch import nn

CTX = 128
D_MODEL = 256
N_LAYERS = 6
N_HEADS = 4


class Block(nn.Module):
    def __init__(self, d: int, h: int):
        super().__init__()
        self.h = h
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv = nn.Linear(d, 3 * d)
        self.proj = nn.Linear(d, d)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = self.qkv(self.n1(x)).chunk(3, dim=-1)
        shape = (B, T, self.h, D // self.h)
        q, k, v = (t.view(shape).transpose(1, 2) for t in (q, k, v))
        a = Fn.scaled_dot_product_attention(q, k, v, is_causal=True)
        x = x + self.proj(a.transpose(1, 2).reshape(B, T, D))
        return x + self.mlp(self.n2(x))


class BehaviorFormer(nn.Module):
    def __init__(self, channel_sizes, n_acts: int, d: int = D_MODEL,
                 layers: int = N_LAYERS, heads: int = N_HEADS, ctx: int = CTX):
        super().__init__()
        self.channel_sizes = tuple(channel_sizes)
        self.offsets = torch.tensor(
            [0] + list(torch.cumsum(torch.tensor(self.channel_sizes), 0)[:-1]), dtype=torch.long
        )
        self.emb = nn.Embedding(int(sum(self.channel_sizes)), d)
        self.pos = nn.Embedding(ctx, d)
        self.blocks = nn.ModuleList([Block(d, heads) for _ in range(layers)])
        self.nf = nn.LayerNorm(d)
        self.head = nn.Linear(d, n_acts)
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def features(self, ch):
        """ch: (B, T, C) int64 -> trunk features (B, T, d) (the frozen body)."""
        _B, T, _ = ch.shape
        x = self.emb(ch + self.offsets.to(ch.device)).sum(dim=2)
        x = x + self.pos(torch.arange(T, device=ch.device))[None]
        for b in self.blocks:
            x = b(x)
        return self.nf(x)

    def forward(self, ch):
        """ch: (B, T, C) int64 channel value ids -> logits (B, T, n_acts)."""
        return self.head(self.features(ch))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())
