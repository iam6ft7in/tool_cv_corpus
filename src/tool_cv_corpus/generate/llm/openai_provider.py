"""OpenAI provider stub.

Shipped as an entry-point-registered stub so the discovery surface
matches the documented plugin list. A real OpenAI integration belongs
in a follow-up PR with its own tests; raising a clear error here is
better than a half-written provider quietly producing broken output.
"""

from __future__ import annotations

from .base import LLMProvider, LLMResponse, Msg, Tool


class OpenAIProvider(LLMProvider):
    """Placeholder LLMProvider; raises on use."""

    name = "openai"

    def complete(
        self,
        *,
        system: str,
        messages: list[Msg],
        tools: list[Tool] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        raise NotImplementedError(
            "OpenAI provider is a stub in v0.1.0. "
            "Contribute an implementation via the plugin authoring guide."
        )
