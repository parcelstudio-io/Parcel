"""Bare dynamic prompting: sectioned context assembly + information tools.

This module is the hillclimbing surface for the voice agent's prompt. It
implements the two ideas the 2026 context-engineering research converged on:

1. **Two placement planes.** ``stable`` sections change rarely (persona, tool
   policy, owner profile) and render first so an LLM provider's prompt-prefix
   cache keeps hitting; ``turn`` sections are volatile (runtime state, recent
   tool results, retrieved knowledge) and render last so their churn never
   invalidates the cached prefix.
2. **Priority-budgeted packing.** Every section declares a priority and a
   character budget (a deliberate, crude token proxy — visible and tunable).
   Turn sections share one global turn budget; when it overflows, the lowest
   priority sections are dropped whole and the drop is *reported*, never
   silent.

Extension contract — adding a context source never touches the pipeline:

- Implement ``ContextSource`` (or wrap a callable in
  ``CallableContextSource``) and ``DynamicPromptComposer.register`` it.
- ``snapshot()`` MUST NOT block: no network, no disk, no model calls. Fetch
  in the background, cache, and return the cached text here. A source that
  has nothing to say returns ``None`` and simply vanishes from the prompt.

Information tools are the second half: ``ConversationToolRegistry`` holds
read-only tools (weather, web search, calendar, ...) whose definitions the
LLM sees each turn with explicit *when-to-use* guidance rendered by
``ToolPolicySource``. The model decides per turn whether to call one; the
agent dispatches through the registry and folds the result into the reply
and the conversation memory. Information tools must never produce motion —
the safety supervisor admits them by name against this registry only.

Inspect the live assembly at ``/api/prompt`` on the web panel (sections,
budgets, drops, rendered text) — that endpoint is the hillclimb loop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

PLACEMENT_STABLE = "stable"
PLACEMENT_TURN = "turn"
_PLACEMENTS = (PLACEMENT_STABLE, PLACEMENT_TURN)
TRUNCATION_MARKER = " …[truncated]"


@runtime_checkable
class ContextSource(Protocol):
    """One named contributor of prompt text.

    ``snapshot`` must return already-available text without blocking; it
    receives the current user query (may be ``None``) so a source can shape
    its output per turn.
    """

    source_id: str
    placement: str
    priority: int
    budget_chars: int

    def snapshot(self, query: str | None) -> str | None: ...


@dataclass(frozen=True)
class RenderedSection:
    source_id: str
    placement: str
    priority: int
    chars: int
    truncated: bool
    text: str


@dataclass(frozen=True)
class ComposedPrompt:
    """The assembled prompt plus everything needed to inspect the assembly."""

    text: str
    stable_text: str
    turn_text: str
    sections: tuple[RenderedSection, ...]
    dropped: tuple[str, ...]
    query: str | None
    composed_at_monotonic_s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "stable_text": self.stable_text,
            "turn_text": self.turn_text,
            "query": self.query,
            "dropped": list(self.dropped),
            "sections": [
                {
                    "source_id": section.source_id,
                    "placement": section.placement,
                    "priority": section.priority,
                    "chars": section.chars,
                    "truncated": section.truncated,
                    "text": section.text,
                }
                for section in self.sections
            ],
        }


def _validate_section_params(source_id: str, placement: str, priority: int, budget: int) -> None:
    if not source_id or not source_id.strip():
        raise ValueError("context source id must be non-empty")
    if placement not in _PLACEMENTS:
        raise ValueError(f"placement must be one of {_PLACEMENTS}, got {placement!r}")
    if priority < 0:
        raise ValueError("priority must be non-negative (lower renders first)")
    if budget < 32:
        raise ValueError("budget_chars must be at least 32")


@dataclass
class StaticContextSource:
    """A fixed block of text (persona, standing rules)."""

    source_id: str
    text: str
    placement: str = PLACEMENT_STABLE
    priority: int = 10
    budget_chars: int = 4000

    def __post_init__(self) -> None:
        _validate_section_params(self.source_id, self.placement, self.priority, self.budget_chars)

    def snapshot(self, query: str | None) -> str | None:
        del query
        return self.text or None


@dataclass
class CallableContextSource:
    """Wrap any non-blocking callable as a source (the generic plug point).

    The callable may accept the query as one positional argument or none.
    Exceptions are contained: a failing source disappears from the prompt
    with a log line instead of breaking the turn.
    """

    source_id: str
    provider: Callable[..., str | None]
    placement: str = PLACEMENT_TURN
    priority: int = 50
    budget_chars: int = 1000

    def __post_init__(self) -> None:
        _validate_section_params(self.source_id, self.placement, self.priority, self.budget_chars)

    def snapshot(self, query: str | None) -> str | None:
        try:
            try:
                return self.provider(query)
            except TypeError:
                return self.provider()
        except Exception as error:  # noqa: BLE001 - a source must not break the turn
            logger.warning("context source %s failed: %s", self.source_id, error)
            return None


class UserProfileSource:
    """Personalization facts injected into every prompt (stable plane).

    Facts are short key/value strings ("location: New York", "occupation:
    software engineer"). They are session-stable by design — per the
    research, always-injected structured profiles are what shipping
    companions do, not per-turn retrieval. ``set_fact`` takes effect on the
    next composed prompt.
    """

    def __init__(
        self,
        facts: Mapping[str, str] | None = None,
        *,
        source_id: str = "user_profile",
        priority: int = 20,
        budget_chars: int = 1200,
    ):
        self.source_id = source_id
        self.placement = PLACEMENT_STABLE
        self.priority = priority
        self.budget_chars = budget_chars
        _validate_section_params(self.source_id, self.placement, self.priority, self.budget_chars)
        self._facts: dict[str, str] = {}
        for key, value in (facts or {}).items():
            self.set_fact(str(key), str(value))

    def set_fact(self, key: str, value: str) -> None:
        clean_key = key.strip().lower().replace(" ", "_")
        clean_value = " ".join(str(value).split())
        if not clean_key or not clean_value:
            raise ValueError("profile facts need a non-empty key and value")
        self._facts[clean_key] = clean_value

    def remove_fact(self, key: str) -> None:
        self._facts.pop(key.strip().lower().replace(" ", "_"), None)

    def facts(self) -> dict[str, str]:
        return dict(self._facts)

    def snapshot(self, query: str | None) -> str | None:
        del query
        if not self._facts:
            return None
        lines = [f"- {key.replace('_', ' ')}: {value}" for key, value in self._facts.items()]
        return "What you know about your owner:\n" + "\n".join(lines)


@dataclass(frozen=True)
class ConversationTool:
    """A read-only information tool the conversation LLM may call.

    ``when_to_use`` is rendered into the prompt so the model can decide per
    turn whether a call is warranted. Handlers return a short plain-text
    result and must never produce motion or side effects on the robot.
    """

    name: str
    description: str
    when_to_use: str
    parameters: Mapping[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ConversationToolRegistry:
    """Named registry the agent dispatches information tool calls through."""

    def __init__(self) -> None:
        self._tools: dict[str, ConversationTool] = {}

    def register(self, tool: ConversationTool, *, replace: bool = False) -> None:
        if not tool.name or not tool.name.strip():
            raise ValueError("conversation tool name must be non-empty")
        if tool.name in self._tools and not replace:
            raise ValueError(f"conversation tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def get(self, name: str) -> ConversationTool:
        return self._tools[name]

    def definitions(self) -> list[dict[str, Any]]:
        """LLM tool schemas, shaped like the agent's built-in definitions."""

        return [
            {
                "name": tool.name,
                "description": f"{tool.description} Use when: {tool.when_to_use}",
                "parameters": dict(tool.parameters),
            }
            for _, tool in sorted(self._tools.items())
        ]

    def invoke(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise LookupError(f"unknown information tool: {name}")
        required = tool.parameters.get("required", ())
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ValueError(f"{name} requires arguments: {', '.join(missing)}")
        result = tool.handler(dict(arguments))
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError(f"{name} returned no usable result")
        return result.strip()


class ToolPolicySource:
    """Renders the information-tool table + decision guidance (stable)."""

    def __init__(
        self,
        registry: ConversationToolRegistry,
        *,
        source_id: str = "tool_policy",
        priority: int = 30,
        budget_chars: int = 2400,
    ):
        self.registry = registry
        self.source_id = source_id
        self.placement = PLACEMENT_STABLE
        self.priority = priority
        self.budget_chars = budget_chars
        _validate_section_params(self.source_id, self.placement, self.priority, self.budget_chars)

    def snapshot(self, query: str | None) -> str | None:
        del query
        names = self.registry.names()
        if not names:
            return None
        guidance = (
            "Information tools available this conversation — decide each turn "
            "whether the owner's request needs one. Call a tool when its "
            "when-to-use condition matches; answer directly when it does not. "
            "Never guess facts a tool can fetch:"
        )
        lines = [guidance]
        for name in names:
            tool = self.registry.get(name)
            lines.append(f"- {tool.name}: {tool.description} Use when: {tool.when_to_use}")
        return "\n".join(lines)


class RecentToolResultsSource:
    """Last N tool results, re-rendered every turn (turn plane).

    ``supplier`` returns recent memory rows (``{"role", "content"}``); only
    ``tool`` rows are rendered. This keeps fresh tool output visible to the
    next turn without permanently bloating the conversation history.
    """

    def __init__(
        self,
        supplier: Callable[[], list[dict[str, str]]],
        *,
        limit: int = 4,
        source_id: str = "recent_tool_results",
        priority: int = 40,
        budget_chars: int = 900,
    ):
        self.supplier = supplier
        self.limit = limit
        self.source_id = source_id
        self.placement = PLACEMENT_TURN
        self.priority = priority
        self.budget_chars = budget_chars
        _validate_section_params(self.source_id, self.placement, self.priority, self.budget_chars)

    def snapshot(self, query: str | None) -> str | None:
        del query
        try:
            rows = self.supplier()
        except Exception as error:  # noqa: BLE001 - a source must not break the turn
            logger.warning("recent tool results supplier failed: %s", error)
            return None
        results = [row["content"] for row in rows if row.get("role") == "tool"]
        if not results:
            return None
        recent = results[-self.limit :]
        return "Recent tool results:\n" + "\n".join(f"- {item}" for item in recent)


def build_weather_tool(
    profile: UserProfileSource | None = None,
    *,
    fetch: Callable[[str], str] | None = None,
) -> ConversationTool:
    """The canonical information-tool example: weather lookup.

    Ships with a deterministic offline stub so the decision loop is testable
    end-to-end; pass ``fetch`` (location -> report string) to back it with a
    real weather API. The default location falls back to the owner profile's
    ``location`` fact.
    """

    def handler(arguments: dict[str, Any]) -> str:
        location = str(arguments.get("location", "")).strip()
        if not location and profile is not None:
            location = profile.facts().get("location", "")
        if not location:
            raise ValueError("get_weather needs a location (none in the owner profile either)")
        if fetch is not None:
            return fetch(location)
        # Offline stub: stable, clearly labeled placeholder data.
        return (
            f"[stub weather] {location}: 22°C, partly cloudy, wind 8 km/h. "
            "(Replace the stub with a real provider via build_weather_tool(fetch=...).)"
        )

    return ConversationTool(
        name="get_weather",
        description="Look up current weather for a location.",
        when_to_use=(
            "the owner asks about weather, temperature, rain, or whether to "
            "go outside; default to the owner's known location if none is named"
        ),
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or place; omit to use the owner's location",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
    )


class DynamicPromptComposer:
    """Assembles registered sources into one inspectable prompt block."""

    def __init__(self, *, turn_budget_chars: int = 2000):
        if turn_budget_chars < 200:
            raise ValueError("turn budget must be at least 200 characters")
        self.turn_budget_chars = turn_budget_chars
        self._sources: dict[str, ContextSource] = {}
        self._last: ComposedPrompt | None = None

    def register(self, source: ContextSource, *, replace: bool = False) -> None:
        _validate_section_params(
            source.source_id, source.placement, source.priority, source.budget_chars
        )
        if source.source_id in self._sources and not replace:
            raise ValueError(f"context source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def unregister(self, source_id: str) -> None:
        self._sources.pop(source_id, None)

    def get_source(self, source_id: str) -> ContextSource | None:
        return self._sources.get(source_id)

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    @property
    def last(self) -> ComposedPrompt | None:
        return self._last

    def compose(self, query: str | None = None) -> ComposedPrompt:
        ordered = sorted(
            self._sources.values(), key=lambda s: (s.placement != PLACEMENT_STABLE, s.priority, s.source_id)
        )
        sections: list[RenderedSection] = []
        dropped: list[str] = []
        turn_spent = 0
        for source in ordered:
            text = source.snapshot(query)
            if text is None or not text.strip():
                continue
            text = text.strip()
            truncated = False
            if len(text) > source.budget_chars:
                text = text[: source.budget_chars - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
                truncated = True
            if source.placement == PLACEMENT_TURN:
                if turn_spent + len(text) > self.turn_budget_chars:
                    dropped.append(source.source_id)
                    continue
                turn_spent += len(text)
            sections.append(
                RenderedSection(
                    source_id=source.source_id,
                    placement=source.placement,
                    priority=source.priority,
                    chars=len(text),
                    truncated=truncated,
                    text=text,
                )
            )
        stable_text = "\n\n".join(s.text for s in sections if s.placement == PLACEMENT_STABLE)
        turn_text = "\n\n".join(s.text for s in sections if s.placement == PLACEMENT_TURN)
        text = "\n\n".join(part for part in (stable_text, turn_text) if part)
        composed = ComposedPrompt(
            text=text,
            stable_text=stable_text,
            turn_text=turn_text,
            sections=tuple(sections),
            dropped=tuple(dropped),
            query=query,
            composed_at_monotonic_s=time.monotonic(),
        )
        self._last = composed
        return composed


@dataclass(frozen=True)
class PromptingStack:
    """Everything the runtime wires: composer + profile + information tools."""

    composer: DynamicPromptComposer | None
    profile: UserProfileSource | None
    tools: ConversationToolRegistry
    detail: str = "disabled"


def build_prompting_stack(config: Mapping[str, Any] | None) -> PromptingStack:
    """Resolve the ``prompting:`` config section into a wired stack.

    Config shape (all keys optional)::

        prompting:
          enabled: true
          turn_budget_chars: 2000
          persona: ""                # extra stable identity text
          user_profile:              # personalization facts, key: value
            location: New York
            home: Manhattan
            occupation: software engineer
          tools:
            weather: true
    """

    config = dict(config or {})
    tools = ConversationToolRegistry()
    if not bool(config.get("enabled", True)):
        return PromptingStack(composer=None, profile=None, tools=tools, detail="disabled")

    composer = DynamicPromptComposer(
        turn_budget_chars=int(config.get("turn_budget_chars", 2000))
    )
    persona = str(config.get("persona", "") or "").strip()
    if persona:
        composer.register(StaticContextSource(source_id="persona_extra", text=persona))

    profile_config = config.get("user_profile") or {}
    if not isinstance(profile_config, Mapping):
        raise TypeError("prompting.user_profile must be a mapping of facts")
    profile = UserProfileSource(
        {str(key): str(value) for key, value in profile_config.items()}
    )
    composer.register(profile)

    tools_config = config.get("tools") or {}
    if not isinstance(tools_config, Mapping):
        raise TypeError("prompting.tools must be a mapping of tool flags")
    if bool(tools_config.get("weather", True)):
        tools.register(build_weather_tool(profile))
    composer.register(ToolPolicySource(tools))

    enabled_tools = ", ".join(tools.names()) or "none"
    facts = len(profile.facts())
    return PromptingStack(
        composer=composer,
        profile=profile,
        tools=tools,
        detail=f"enabled (facts={facts}, tools={enabled_tools})",
    )
