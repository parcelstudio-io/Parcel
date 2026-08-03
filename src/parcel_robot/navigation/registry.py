from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .base import ModelSpec


class ModelRegistry:
    """Load multiple navigator model specs (types + versions) from YAML."""

    def __init__(self, models: dict[str, ModelSpec], *, root: Path):
        self.root = root
        self._models = models

    @classmethod
    def load(cls, models_root: str | Path) -> ModelRegistry:
        root = Path(models_root).expanduser().resolve()
        models: dict[str, ModelSpec] = {}
        for path in sorted(root.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            spec = ModelSpec(
                id=str(data["id"]),
                type=str(data["type"]),
                version=str(data.get("version", "0")),
                description=str(data.get("description", "")),
                homepage=str(data.get("homepage", "")),
                checkpoint=str(data.get("checkpoint", "")),
                device=str(data.get("device", "cpu")),
                controller=dict(data.get("controller") or {}),
                rl=dict(data.get("rl") or {}),
                source_path=str(path),
            )
            if spec.id in models:
                raise ValueError(f"duplicate navigation model id: {spec.id}")
            models[spec.id] = spec
        return cls(models, root=root)

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as error:
            raise KeyError(f"unknown navigation model: {model_id}") from error

    def list(self, model_type: str | None = None) -> list[ModelSpec]:
        specs = list(self._models.values())
        if model_type is not None:
            specs = [spec for spec in specs if spec.type == model_type]
        return specs

    def ids(self) -> list[str]:
        return list(self._models)

    def create(self, model_id: str, **kwargs: Any):
        from .models import build_navigator

        spec = self.get(model_id)
        options = dict(spec.controller)
        options.update(kwargs)
        return build_navigator(spec, **options)
