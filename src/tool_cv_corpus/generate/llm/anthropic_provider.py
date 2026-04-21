"""Anthropic provider.

Wraps ``anthropic.Anthropic``'s Messages API behind the internal
``LLMProvider`` protocol. We enable prompt caching on the system prompt
because the same system text is typically reused across many generate
calls within one run, and the cache dramatically cuts input-token cost.

The provider does not implement the internal SQLite cache itself; the
cache wraps the provider at a higher layer so caching is applied
uniformly to every provider.
"""

from __future__ import annotations

from typing import Any

from .base import LLMProvider, LLMResponse, Msg, Tool

_DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider(LLMProvider):
    """LLMProvider implementation for Anthropic's Messages API."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str = _DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic provider needs the 'anthropic' package; "
                "it is a default dependency, reinstall the project."
            ) from exc
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

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
        client = self._ensure_client()
        model_id = model or self._default_model
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in {"user", "assistant"}
        ]
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        kwargs: dict[str, Any] = {
            "model": model_id,
            "system": system_blocks,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]

        resp = client.messages.create(**kwargs)

        text = "".join(
            block.text
            for block in getattr(resp, "content", [])
            if getattr(block, "type", "") == "text"
        )
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
            "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return LLMResponse(
            text=text,
            model=getattr(resp, "model", model_id),
            stop_reason=getattr(resp, "stop_reason", None),
            usage=usage,
        )
