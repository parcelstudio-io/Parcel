from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_PROMPT_BYTES = 128_000


@dataclass(frozen=True)
class PersonalityProfile:
    id: str
    name: str
    instruction: str
    reply_style: tuple[str, ...]
    affect_actions: dict[str, str]


@dataclass(frozen=True)
class FunctionProfile:
    id: str
    name: str
    instruction: str


class PromptLibrary:
    """Loads trusted, repository-owned prompt fragments by validated IDs."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"prompt directory not found: {self.root}")
        self._cache_lock = threading.RLock()
        self._personality_cache: dict[str, PersonalityProfile] = {}
        self._function_cache: dict[str, FunctionProfile] = {}
        self._text_cache: dict[tuple[str, str], str] = {}
        self._schema_cache: dict[str, dict[str, Any]] = {}
        self._personality_id_cache: tuple[str, ...] | None = None

    def list_personalities(self) -> list[PersonalityProfile]:
        return [self.personality(profile_id) for profile_id in self._personality_ids()]

    def _personality_ids(self) -> tuple[str, ...]:
        with self._cache_lock:
            if self._personality_id_cache is None:
                self._personality_id_cache = tuple(
                    path.stem for path in sorted(self._dir("personalities").glob("*.yaml"))
                )
            return self._personality_id_cache

    def personality(self, profile_id: str) -> PersonalityProfile:
        with self._cache_lock:
            cached = self._personality_cache.get(profile_id)
            if cached is not None:
                return cached
        data = self._yaml("personalities", profile_id)
        identity = self._identity(data, profile_id)
        instruction = self._required_text(data, "instruction")
        reply_style = data.get("reply_style") or []
        affect_actions = data.get("affect_actions") or {}
        if not isinstance(reply_style, list) or not all(
            isinstance(item, str) and item.strip() for item in reply_style
        ):
            raise TypeError("personality reply_style must be a list of strings")
        if not isinstance(affect_actions, dict) or not all(
            key in {"excited", "happy", "sad"}
            and isinstance(value, str)
            and _PROFILE_ID.fullmatch(value)
            for key, value in affect_actions.items()
        ):
            raise TypeError("personality affect_actions contains an invalid mapping")
        profile = PersonalityProfile(
            id=identity,
            name=str(data.get("name", identity)),
            instruction=instruction,
            reply_style=tuple(item.strip() for item in reply_style),
            affect_actions=dict(affect_actions),
        )
        with self._cache_lock:
            self._personality_cache[profile_id] = profile
        return profile

    def function(self, profile_id: str) -> FunctionProfile:
        with self._cache_lock:
            cached = self._function_cache.get(profile_id)
            if cached is not None:
                return cached
        data = self._yaml("functions", profile_id)
        identity = self._identity(data, profile_id)
        profile = FunctionProfile(
            id=identity,
            name=str(data.get("name", identity)),
            instruction=self._required_text(data, "instruction"),
        )
        with self._cache_lock:
            self._function_cache[profile_id] = profile
        return profile

    def render_system(
        self,
        *,
        personality_id: str,
        function_ids: list[str] | tuple[str, ...],
        runtime_context: dict[str, Any],
    ) -> str:
        personality = self.personality(personality_id)
        functions = [self.function(profile_id) for profile_id in function_ids]
        core = self._text("system", "core.md")
        action_policy = self._text("system", "action_policy.md")
        dynamic_template = self._text("dynamic", "runtime_context.md.tmpl")
        if dynamic_template.count("{{RUNTIME_CONTEXT_JSON}}") != 1:
            raise ValueError("dynamic prompt must contain one runtime-context placeholder")
        encoded_context = json.dumps(
            runtime_context,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        dynamic = dynamic_template.replace("{{RUNTIME_CONTEXT_JSON}}", encoded_context)
        function_text = "\n\n".join(
            f"### {profile.name} ({profile.id})\n{profile.instruction}" for profile in functions
        )
        style = "\n".join(f"- {rule}" for rule in personality.reply_style)
        affect_map = json.dumps(personality.affect_actions, sort_keys=True)
        return "\n\n".join(
            (
                core,
                action_policy,
                (
                    f"## Active personality: {personality.name}\n{personality.instruction}\n"
                    f"Reply style:\n{style}\nAffect action preferences: {affect_map}"
                ),
                f"## Enabled functionality\n{function_text}",
                dynamic,
            )
        ).strip()

    def schema(self, filename: str) -> dict[str, Any]:
        """Load one trusted prompt schema by its exact repository filename."""

        if not isinstance(filename, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}\.schema\.json", filename
        ):
            raise ValueError(f"invalid prompt schema filename: {filename!r}")
        with self._cache_lock:
            cached = self._schema_cache.get(filename)
            if cached is not None:
                # The provider only serializes this value. A fresh JSON object
                # prevents one caller from mutating the trusted cache.
                return json.loads(json.dumps(cached))
        raw = json.loads(self._read(self._dir("schemas") / filename))
        if not isinstance(raw, dict):
            raise TypeError(f"prompt schema must be a JSON object: {filename}")
        with self._cache_lock:
            self._schema_cache[filename] = raw
        return json.loads(json.dumps(raw))

    def planner_system(self, output_contract: str = "plan_ir_v1") -> str:
        """Return the trusted instruction for one supported planner contract."""

        filenames = {
            "plan_ir_v1": "planner.md",
            "plan_sketch_v1": "planner_sketch.md",
        }
        try:
            filename = filenames[output_contract]
        except KeyError as error:
            raise ValueError(f"unsupported planner output contract: {output_contract!r}") from error
        return self._text("system", filename)

    def _yaml(self, section: str, profile_id: str) -> dict[str, Any]:
        self._validate_id(profile_id)
        path = self._dir(section) / f"{profile_id}.yaml"
        text = self._read(path)
        value = yaml.safe_load(text) or {}
        if not isinstance(value, dict):
            raise TypeError(f"prompt profile must be a mapping: {path}")
        return value

    def _text(self, section: str, filename: str) -> str:
        key = (section, filename)
        with self._cache_lock:
            cached = self._text_cache.get(key)
            if cached is not None:
                return cached
        value = self._read(self._dir(section) / filename).strip()
        with self._cache_lock:
            self._text_cache[key] = value
        return value

    def _dir(self, section: str) -> Path:
        path = (self.root / section).resolve()
        if path.parent != self.root:
            raise ValueError("prompt section escaped the configured root")
        return path

    def _read(self, path: Path) -> str:
        resolved = path.resolve()
        if self.root not in resolved.parents:
            raise ValueError("prompt path escaped the configured root")
        size = resolved.stat().st_size
        if size > _MAX_PROMPT_BYTES:
            raise ValueError(f"prompt file is too large: {resolved}")
        return resolved.read_text(encoding="utf-8")

    @staticmethod
    def _validate_id(profile_id: str) -> None:
        if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
            raise ValueError(f"invalid prompt profile id: {profile_id!r}")

    @staticmethod
    def _required_text(data: dict[str, Any], field: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"prompt profile requires non-empty {field}")
        return value.strip()

    def _identity(self, data: dict[str, Any], expected: str) -> str:
        identity = data.get("id")
        if identity != expected:
            raise ValueError(f"prompt profile id must match filename: {expected}")
        self._validate_id(identity)
        return identity
