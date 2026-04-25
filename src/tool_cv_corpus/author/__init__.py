"""Interactive corpus authoring: schema-driven prompts and writers.

The ``cv-corpus author`` CLI command orchestrates these pieces; importing
from ``tool_cv_corpus.author`` is the supported way to drive the wizard
from a script (e.g., a custom front-end that wraps the same engine).

Tier 1 of the three-tier guided-authoring plan: deterministic prompts,
no LLM. Tier 2 will add paste-and-extract on top of the same primitives.
"""

from __future__ import annotations

from .prompts import (
    Prompter,
    ScriptedPrompter,
    prompt_for_claim,
    prompt_for_entity,
)
from .state import CorpusState, load_state
from .writers import (
    DIRECTORY_BY_KIND,
    suggest_entity_id,
    write_claim,
    write_entity,
)

__all__ = [
    "DIRECTORY_BY_KIND",
    "CorpusState",
    "Prompter",
    "ScriptedPrompter",
    "load_state",
    "prompt_for_claim",
    "prompt_for_entity",
    "suggest_entity_id",
    "write_claim",
    "write_entity",
]
