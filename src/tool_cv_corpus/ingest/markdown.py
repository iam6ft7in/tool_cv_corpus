"""Markdown ingester.

The corpus on disk is itself markdown with YAML frontmatter: one file
per entity, keyed by entity kind and ID. This ingester round-trips that
format, so users can hand-write or hand-edit a corpus without any other
input source.

Frontmatter keys match the pydantic schema; the markdown body is
attached as a ``context`` claim on the entity so prose notes do not get
lost but also do not bleed into the structured graph.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

import frontmatter  # python-frontmatter
from pydantic import TypeAdapter

from ..schema import AnyEntity, Claim
from .base import IngestResult

_slug_re = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _slug_re.sub("_", value.lower()).strip("_") or "claim"


class MarkdownIngester:
    """Parse markdown + YAML frontmatter files into corpus entities."""

    name: ClassVar[str] = "markdown"

    def accepts(self, src: Path) -> bool:
        return src.is_file() and src.suffix in {".md", ".markdown"}

    def ingest(self, src: Path) -> IngestResult:
        post = frontmatter.load(str(src))
        data: dict[str, Any] = dict(post.metadata)
        body = (post.content or "").strip()

        if "kind" not in data or "id" not in data:
            return IngestResult(
                warnings=[f"{src}: missing 'kind' or 'id' in frontmatter; skipped"],
            )

        adapter: TypeAdapter[AnyEntity] = TypeAdapter(AnyEntity)
        try:
            entity = adapter.validate_python(data)
        except Exception as exc:
            return IngestResult(warnings=[f"{src}: {exc}"])

        claims: list[Claim] = []
        if body:
            claims.append(
                Claim(
                    id=f"{entity.id}_{_slug(src.stem)}_body",
                    subject_id=entity.id,
                    subject_kind=entity.kind,
                    type="context",
                    text=body,
                )
            )
        return IngestResult(entities=[entity], claims=claims)
