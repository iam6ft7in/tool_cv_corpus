"""Contract every LLM provider implements.

Providers are vendor adapters behind a single ``complete()`` call. The
rest of the generate layer only sees this protocol, so swapping
Anthropic for OpenAI (or for a local mock in tests) is a configuration
change, not a code change.

Intentional small surface:

- One call returns one response. Streaming and tool-use loops are
  layered on top; if we bake them into the base, every provider must
  implement them for every vendor, which is not worth it for a tool
  whose critical path is a handful of completions per resume.
- ``cache_hit`` rides on the response so the cache can be transparent:
  the caller does not know or care whether the result came from the
  provider or the SQLite store.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

MsgRole = Literal["system", "user", "assistant", "tool"]


class Msg(BaseModel):
    """One message in a chat-style completion."""

    model_config = ConfigDict(extra="forbid")
    role: MsgRole
    content: str
    name: str | None = Field(
        default=None,
        description="Tool call name when role=='tool'; ignored otherwise.",
    )


class Tool(BaseModel):
    """Tool definition advertised to the model."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalised response; providers translate their vendor shape into this."""

    model_config = ConfigDict(extra="forbid")
    text: str
    model: str
    stop_reason: str | None = None
    usage: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Token counts by bucket, e.g. "
            "{'input_tokens': N, 'output_tokens': M, 'cache_read': K}."
        ),
    )
    cache_hit: bool = False
    tool_use: dict[str, Any] | None = Field(
        default=None,
        description=(
            "First tool_use block's parsed input, when the model elected to "
            "call a tool. Synthesis uses this for structured output: the "
            "``input_schema`` is derived from a Pydantic model, so the "
            "returned dict can be round-tripped through that model for "
            "type-safe downstream access. None when the model produced only "
            "text."
        ),
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Raw vendor payload, if the provider chose to surface it. "
            "Callers should not depend on its shape."
        ),
    )


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every concrete provider class implements."""

    name: str

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
        """Return one completion for the given input.

        ``model`` overrides the provider's default when set; leaving it
        None lets the provider pick (which may be the value from
        ``Settings.model``).
        """
        ...
