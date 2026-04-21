"""Contract every renderer implements.

Renderers are pure formatters. The generate phase produces a
``RenderedResume`` that already has claim-scoring, narrative selection,
and redaction applied; the renderer turns that into bytes or a file in
its target format (PDF via Typst, JSON Resume, .docx, static HTML).

Keeping the renderer surface this narrow is what makes the tool
extensible: a third-party renderer only needs to consume the resolved
intermediate, not reach back into the corpus graph. That invariant
should not be relaxed even for "convenience"; if a renderer needs
additional data, we extend ``RenderedResume`` instead so every renderer
sees the same view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..schema import (
    Achievement,
    Education,
    Organization,
    Person,
    Publication,
    Role,
    Skill,
    Testimonial,
)


class RenderedSection(BaseModel):
    """An already-selected section of the final document.

    Sections are free-form so cover letters, custom blocks, and callouts
    slot into the same pipeline without dedicated schema.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    kind: str = Field(
        default="bullets",
        description=(
            "Hint for the renderer: 'bullets', 'paragraph', 'quote', etc. "
            "Unknown kinds are rendered as paragraphs by default."
        ),
    )
    body: str | None = None
    bullets: list[str] = Field(default_factory=list)


class RenderedResume(BaseModel):
    """Generator output; renderer input.

    Carries a fully-resolved, target-tailored view of the corpus. All
    scoring, narrative choice, and visibility filtering has already
    happened upstream; the renderer is a pure function of this model.
    """

    model_config = ConfigDict(extra="forbid")

    person: Person
    headline: str | None = None
    summary: str | None = None
    roles: list[Role] = Field(default_factory=list)
    organizations: list[Organization] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    testimonials: list[Testimonial] = Field(default_factory=list)
    sections: list[RenderedSection] = Field(
        default_factory=list,
        description=(
            "Optional extra blocks (cover letters, sidebars) that do not "
            "map onto the standard entity lists."
        ),
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Renderer-visible metadata: target name, run ID, git SHA, etc. "
            "Used for footers and reproducibility stamps."
        ),
    )


@runtime_checkable
class Renderer(Protocol):
    """Protocol every concrete renderer class implements.

    A renderer is registered via the ``tool_cv_corpus.renderers`` entry
    point and selected at the CLI by ``name``.
    """

    name: str
    extensions: tuple[str, ...]

    def render(self, resume: RenderedResume, out_path: Path) -> Path:
        """Write ``resume`` to ``out_path`` (or a derived path) and return it.

        Implementations may choose a suffix from ``extensions`` if
        ``out_path`` has none; they must not silently overwrite an
        unrelated file.
        """
        ...
