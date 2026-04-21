"""Smoke test: every registered default plugin imports and conforms.

Entry points are lazy; an install can succeed with a typo in a dotted
path because nothing resolves it until first use. This test forces
resolution of every ``tool_cv_corpus.*`` entry point at CI time so a
rename or accidental class removal is caught before a user hits it.
"""

from __future__ import annotations

from importlib.metadata import entry_points

import pytest

from tool_cv_corpus.generate.llm.base import LLMProvider
from tool_cv_corpus.ingest.base import Ingester
from tool_cv_corpus.render.base import Renderer

_GROUPS = {
    "tool_cv_corpus.renderers": Renderer,
    "tool_cv_corpus.ingesters": Ingester,
    "tool_cv_corpus.llm_providers": LLMProvider,
}


@pytest.mark.parametrize("group, protocol", list(_GROUPS.items()))
def test_entry_points_resolve_and_conform(group: str, protocol: type) -> None:
    eps = entry_points().select(group=group)
    assert eps, f"no entry points registered for {group}"
    for ep in eps:
        cls = ep.load()
        assert callable(cls), f"{group}:{ep.name} did not load a class"
        # Protocols are runtime_checkable; instantiate when argument-free.
        try:
            instance = cls()
        except TypeError:
            # Constructors that need args (e.g., GithubProfileIngester(username=...)).
            # We still verify the class itself can be referenced.
            continue
        assert isinstance(instance, protocol), (
            f"{group}:{ep.name} does not conform to {protocol.__name__}"
        )
