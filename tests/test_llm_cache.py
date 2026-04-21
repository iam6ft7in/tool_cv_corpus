"""LLM response cache tests."""

from __future__ import annotations

from pathlib import Path

from tool_cv_corpus.generate.llm import (
    LLMResponse,
    LLMResponseCache,
    Msg,
    Tool,
    compute_cache_key,
)


def _resp(text: str = "hi") -> LLMResponse:
    return LLMResponse(
        text=text,
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 2},
    )


def test_key_is_deterministic() -> None:
    msgs = [Msg(role="user", content="hello")]
    k1 = compute_cache_key(
        system="sys",
        messages=msgs,
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    k2 = compute_cache_key(
        system="sys",
        messages=msgs,
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    assert k1 == k2


def test_key_changes_with_system_or_messages() -> None:
    msgs = [Msg(role="user", content="hello")]
    base = compute_cache_key(
        system="sys",
        messages=msgs,
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    sys_diff = compute_cache_key(
        system="sys2",
        messages=msgs,
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    msg_diff = compute_cache_key(
        system="sys",
        messages=[Msg(role="user", content="world")],
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    assert base != sys_diff
    assert base != msg_diff


def test_key_sensitive_to_message_order() -> None:
    a = [Msg(role="user", content="one"), Msg(role="assistant", content="two")]
    b = [Msg(role="assistant", content="two"), Msg(role="user", content="one")]
    ka = compute_cache_key(
        system="", messages=a, tools=None, model="m", max_tokens=1, temperature=0.0
    )
    kb = compute_cache_key(
        system="", messages=b, tools=None, model="m", max_tokens=1, temperature=0.0
    )
    assert ka != kb


def test_key_with_tools() -> None:
    tools = [Tool(name="search", description="search the web")]
    k_with = compute_cache_key(
        system="",
        messages=[Msg(role="user", content="x")],
        tools=tools,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    k_without = compute_cache_key(
        system="",
        messages=[Msg(role="user", content="x")],
        tools=None,
        model="m",
        max_tokens=1,
        temperature=0.0,
    )
    assert k_with != k_without


def test_roundtrip_put_get(tmp_path: Path) -> None:
    cache = LLMResponseCache(tmp_path / "llm.sqlite")
    k = "deadbeef" * 8
    assert cache.get(k) is None
    r = _resp()
    cache.put(k, r)
    got = cache.get(k)
    assert got is not None
    assert got.text == r.text
    assert got.model == r.model
    assert got.cache_hit is True  # get always marks hit=True
    assert r.cache_hit is False  # put does not mutate the argument


def test_put_overwrites_same_key(tmp_path: Path) -> None:
    cache = LLMResponseCache(tmp_path / "llm.sqlite")
    k = "a" * 64
    cache.put(k, _resp("first"))
    cache.put(k, _resp("second"))
    got = cache.get(k)
    assert got is not None
    assert got.text == "second"
