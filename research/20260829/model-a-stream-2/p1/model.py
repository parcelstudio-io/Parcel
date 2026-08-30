"""Small deterministic P1 model definitions and checkpoint codec."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import torch
from common import canonical_bytes, file_sha256
from features import BASE_DIM, SEQUENCE_DIM
from torch import nn

MAGNITUDES = torch.tensor([0.70, 0.70, 1.0], dtype=torch.float32)
MAGIC = b"MA2P1CKPT\x00"


class SnapshotMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(BASE_DIM, 128),
            nn.SiLU(),
            nn.Linear(128, 128),
            nn.SiLU(),
        )
        self.command = nn.Linear(128, 3)
        self.stop = nn.Linear(128, 1)

    def forward(self, value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.body(value)
        scale = MAGNITUDES.to(value.device)
        return torch.tanh(self.command(hidden)) * scale, self.stop(hidden).squeeze(-1)


class CausalGRU(nn.Module):
    def __init__(self):
        super().__init__()
        self.gru = nn.GRU(SEQUENCE_DIM, 128, batch_first=True)
        self.body = nn.Sequential(nn.Linear(128, 128), nn.SiLU())
        self.command = nn.Linear(128, 3)
        self.stop = nn.Linear(128, 1)

    def forward(self, value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        output, _state = self.gru(value)
        hidden = self.body(output[:, -1, :])
        scale = MAGNITUDES.to(value.device)
        return torch.tanh(self.command(hidden)) * scale, self.stop(hidden).squeeze(-1)


def build_model(arm: str) -> nn.Module:
    if arm == "S":
        return SnapshotMLP()
    if arm == "C16":
        return CausalGRU()
    raise ValueError(f"unknown learned arm: {arm}")


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def normalized_state_digest(model: nn.Module) -> str:
    import hashlib

    value = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous().numpy().astype("<f4", copy=False)
        value.update(canonical_bytes({"name": name, "shape": list(array.shape), "dtype": "<f4"}))
        value.update(array.tobytes(order="C"))
    return value.hexdigest()


def save_checkpoint(
    path: Path,
    *,
    model: nn.Module,
    metadata: dict[str, Any],
    mean: np.ndarray,
    std: np.ndarray,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = model.state_dict()
    header = dict(metadata)
    header["mean"] = mean.astype(float).tolist()
    header["std"] = std.astype(float).tolist()
    header["tensor_names"] = sorted(state)
    header["normalized_state_digest"] = normalized_state_digest(model)
    payload = canonical_bytes(header)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(MAGIC)
        handle.write(struct.pack(">I", len(payload)))
        handle.write(payload)
        for name in sorted(state):
            array = state[name].detach().cpu().contiguous().numpy().astype("<f4", copy=False)
            tensor_header = canonical_bytes(
                {"name": name, "shape": list(array.shape), "dtype": "<f4", "bytes": array.nbytes}
            )
            handle.write(struct.pack(">I", len(tensor_header)))
            handle.write(tensor_header)
            handle.write(array.tobytes(order="C"))
    temporary.replace(path)
    return file_sha256(path)


def load_checkpoint(
    path: Path, device: torch.device
) -> tuple[nn.Module, dict[str, Any], np.ndarray, np.ndarray]:
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("bad P1 checkpoint magic")
        header_length = struct.unpack(">I", handle.read(4))[0]
        header = json.loads(handle.read(header_length))
        model = build_model(header["arm"])
        state: dict[str, torch.Tensor] = {}
        for expected_name in header["tensor_names"]:
            tensor_header_length = struct.unpack(">I", handle.read(4))[0]
            tensor_header = json.loads(handle.read(tensor_header_length))
            if tensor_header["name"] != expected_name or tensor_header["dtype"] != "<f4":
                raise ValueError("P1 checkpoint tensor order/schema mismatch")
            raw = handle.read(tensor_header["bytes"])
            array = np.frombuffer(raw, dtype="<f4").reshape(tensor_header["shape"]).copy()
            state[expected_name] = torch.from_numpy(array)
        if handle.read(1):
            raise ValueError("P1 checkpoint has trailing bytes")
    model.load_state_dict(state, strict=True)
    if normalized_state_digest(model) != header["normalized_state_digest"]:
        raise ValueError("P1 checkpoint normalized state digest mismatch")
    model.to(device).eval()
    return (
        model,
        header,
        np.asarray(header["mean"], dtype=np.float32),
        np.asarray(header["std"], dtype=np.float32),
    )
