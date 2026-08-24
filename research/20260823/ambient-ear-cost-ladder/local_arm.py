"""The local answer arm: the same companion prompt, served by the GPU reasoner.

A thin OpenAI-compatible client rather than ``providers.LlamaCppProvider``,
because that class exists to parse the agent's structured decision envelope and
this experiment wants the plain spoken sentence the hosted lane also produced.
Nothing here is a product seam.

THE COMPARISON IS ONLY FAIR IF THE PROMPT IS THE SAME
-----------------------------------------------------
The hosted answers in ``realtime_convo_v1`` were produced under
``render_session_instructions(profile_id=…, flags=…)`` — persona, voice
guardrails, developer flags and all. The local arm is handed that exact rendered
text as its system message, and the same thread history, so a quality
difference is a difference between the MODELS and not between two prompts.

History is the CORPUS's robot turns, for both arms, on every turn. Letting the
local arm accumulate its own history would make turn 8 of a thread a comparison
between two different conversations rather than between two answers to the same
question.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field

DEFAULT_BASE_URL = "http://127.0.0.1:8081"


class LocalArmError(RuntimeError):
    """The local server refused, timed out, or answered something unusable."""


@dataclass
class LocalArm:
    """One llama.cpp ``/v1/chat/completions`` endpoint, used for plain replies."""

    base_url: str = DEFAULT_BASE_URL
    model: str = "gemma-4-26b-a4b"
    #: 0.0 so a re-run of this experiment produces the same answers to judge.
    temperature: float = 0.0
    #: A spoken companion sentence, not an essay. The SI already says "one or
    #: two calm sentences"; this is the hard stop behind it.
    max_tokens: int = 160
    timeout_s: float = 180.0
    latencies_s: list[float] = field(default_factory=list)

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=5.0) as stream:
                return stream.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def answer(self, system: str, history: Sequence[tuple[str, str]], owner_text: str) -> str:
        messages = [{"role": "system", "content": system}]
        for role, text in history:
            messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": owner_text})
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # The reasoner is served with --reasoning auto; a companion reply
            # does not need a chain of thought and paying for one would triple
            # the latency this arm is being measured on.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": messages,
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as stream:
                body = json.loads(stream.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LocalArmError(f"local arm unreachable at {self.base_url}: {error}") from error
        except json.JSONDecodeError as error:
            raise LocalArmError(f"local arm returned non-JSON: {error}") from error
        self.latencies_s.append(time.perf_counter() - started)
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LocalArmError(f"local arm returned no choice: {body}") from error
        content = message.get("content") or ""
        return str(content).strip()


__all__ = ["DEFAULT_BASE_URL", "LocalArm", "LocalArmError"]
