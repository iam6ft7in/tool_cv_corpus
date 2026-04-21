"""Contract every ingester implements.

An ingester reads from an external source (LinkedIn export, GitHub
profile, ORCID, local markdown files) and emits corpus deltas:

- entities to append or upsert
- claims to attach to those entities
- source documents describing where the data came from
- warnings for anything that needs human attention

Ingesters never write to the corpus directly. The CLI composes an
``IngestResult`` and a separate merge step applies it transactionally,
so a half-parsed LinkedIn export cannot corrupt an existing corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..schema import AnyEntity, Claim, SourceDoc


class IngestResult(BaseModel):
    """The delta an ingester wants applied to the corpus."""

    model_config = ConfigDict(extra="forbid")

    entities: list[AnyEntity] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SourceDoc] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Human-readable notes the CLI surfaces at the end of an "
            "ingest run: unresolved references, skipped attachments, "
            "ambiguous mappings. Never a hard error; blockers raise."
        ),
    )


@runtime_checkable
class Ingester(Protocol):
    """Protocol every concrete ingester class implements."""

    name: str

    def accepts(self, src: Path) -> bool:
        """Return True if this ingester can handle ``src``.

        Used by the CLI's auto-detect path. Cheap inspection only
        (extension, magic bytes); full parsing happens in ``ingest``.
        """
        ...

    def ingest(self, src: Path) -> IngestResult:
        """Parse ``src`` and return the corpus delta.

        Heavy work lives here. Implementations must be idempotent on the
        same input so repeated runs produce the same result.
        """
        ...
