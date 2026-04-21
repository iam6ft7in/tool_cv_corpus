"""Claims: sourced assertions layered over entities.

The claims-over-overwrites pattern is the core of this schema. Rather than
mutating an entity's field when a fact is refined ("increased ARR by 20%" ->
"increased ARR by 22% after rebaseline"), we append a new ``Claim`` pointing
at the same subject. The generator selects among claims at render time based
on recency, source strength, and target fit.

Two consequences worth remembering:

1. Provenance never gets erased. Every claim names the ``SourceDoc`` IDs
   backing it, so a reviewer can walk from rendered prose to an original
   document.
2. Retractions are explicit. A later claim can set ``superseded_by`` on an
   earlier one, marking it excluded without deleting it; audit trails and
   time-travel renders remain possible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .base import Visibility

ClaimType = Literal[
    "fact",
    "outcome",
    "impact",
    "responsibility",
    "context",
    "quote",
]
"""Coarse tag for what kind of assertion this is.

Renderers may filter by ``type`` (a CV's "Selected Achievements" section
may want only ``outcome`` + ``impact``, never ``context``).
"""


class Claim(BaseModel):
    """One sourced assertion about one subject entity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1)
    subject_id: str = Field(
        ...,
        description="ID of the entity this claim is about.",
    )
    subject_kind: str = Field(
        ...,
        description=(
            "Kind name of the subject, e.g. 'role' or 'achievement'. "
            "Stored alongside subject_id because IDs are only unique "
            "within a kind."
        ),
    )
    type: ClaimType = Field(default="fact")
    text: str = Field(..., min_length=1)
    visibility: Visibility = Field(default="public")
    sources: list[str] = Field(
        default_factory=list,
        description="SourceDoc IDs backing this claim; empty means unsourced.",
    )
    superseded_by: str | None = Field(
        default=None,
        description=(
            "Claim ID that replaces this one. Superseded claims are kept "
            "for audit, but excluded from rendering by default."
        ),
    )
    tags: list[str] = Field(default_factory=list)
