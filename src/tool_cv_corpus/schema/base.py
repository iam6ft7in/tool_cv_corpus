"""Base types shared by every corpus entity.

The schema is a graph-of-atoms: each entity is a small, stable node on disk
that references other nodes by ID rather than embedding them. Two conventions
make that graph auditable:

1. ``extra="forbid"`` catches typos at load time rather than silently
   discarding fields, which would otherwise erase provenance.
2. A ``schema_version`` string rides on every entity so migrations can be
   applied file-by-file without a global rewrite.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"
"""Semver for the entity shape. Bump on any non-additive change.

Readers use this to dispatch through ``schema/migrations`` before validation
so older corpora still load after an upgrade.
"""

Visibility = Literal["public", "nda", "private"]
"""Three-tier redaction ladder.

- public:  may appear in any rendered output.
- nda:     may appear only when the redaction profile explicitly allows it.
- private: never leaves the corpus; useful for personal notes or
           unreleased figures that still belong in the graph for context.
"""


class Entity(BaseModel):
    """Root of every corpus entity.

    Fields common to all nodes live here so downstream loaders, validators,
    and renderers can introspect a heterogeneous list uniformly.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable slug-like identifier, unique within its entity kind. "
            "IDs are referenced from other entities, so changing them is a "
            "breaking operation; prefer adding a new entity and superseding "
            "via claims."
        ),
    )
    schema_version: str = Field(default=SCHEMA_VERSION)
    visibility: Visibility = Field(default="public")
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form labels; used by selectors at render time.",
    )
