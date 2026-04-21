"""Concrete corpus entities.

Each class is a small, sharp node in the graph-of-atoms. Prose belongs in
``Claim`` records; fields here are structured attributes only, so that:

1. The graph can be traversed without NLP.
2. Renderers can format consistently (dates, org names, links) even when
   the underlying claims change tone for different targets.
3. Merging corpora from different people or time ranges stays mechanical.

A ``kind`` discriminator is present on every entity so the loader can
resolve a mixed list without path-based dispatch and so ``Claim.subject_kind``
stays consistent with the entity it references.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import Entity
from .dates import DateRange, PartialDate
from .impact import ImpactMetric
from .taxonomy import SkillConfidence, SkillTier


class Person(Entity):
    """The subject of the corpus.

    A corpus may contain exactly one ``Person`` today; the field is kept
    first-class so future "team bio" or coauthor features can land without a
    schema break.
    """

    kind: Literal["person"] = "person"
    full_name: str = Field(..., min_length=1)
    preferred_name: str | None = None
    headline: str | None = Field(
        default=None,
        description="One-line positioning statement for profile/CV headers.",
    )
    pronouns: str | None = None
    location: str | None = None
    contact: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Keys like 'email', 'website', 'github', 'linkedin'. Each entry "
            "is redaction-filtered by its enclosing entity's visibility."
        ),
    )


class Organization(Entity):
    """An employer, client, school, or publishing venue."""

    kind: Literal["organization"] = "organization"
    name: str = Field(..., min_length=1)
    website: str | None = None
    industry: str | None = None
    size: str | None = Field(
        default=None,
        description="Free-form bracket, e.g. '1-10', '51-200', '5k+'.",
    )
    description: str | None = Field(
        default=None,
        description="Short neutral description; personal opinions belong in claims.",
    )


class Role(Entity):
    """A tenure at one organization.

    Roles own no prose of their own. The bullet-point narrative a CV needs
    comes from claims targeting ``role.id`` and from the linked achievements.
    """

    kind: Literal["role"] = "role"
    title: str = Field(..., min_length=1)
    organization_id: str
    employment_type: Literal[
        "full_time",
        "part_time",
        "contract",
        "consulting",
        "internship",
        "volunteer",
        "founder",
        "self_employed",
    ] = "full_time"
    period: DateRange
    location: str | None = None
    remote: bool = False
    headline: str | None = Field(
        default=None,
        description=(
            "One-line summary used on cards where full narrative would not fit."
        ),
    )
    project_ids: list[str] = Field(default_factory=list)
    achievement_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class Project(Entity):
    """A bounded effort within or across roles.

    Projects sit between roles and achievements: they group outcomes under a
    named initiative so the generator can pick "highlight the X launch"
    without scanning every achievement.
    """

    kind: Literal["project"] = "project"
    name: str = Field(..., min_length=1)
    organization_id: str | None = None
    role_id: str | None = None
    period: DateRange | None = None
    headline: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    achievement_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class Achievement(Entity):
    """One discrete outcome, usually the atom a CV bullet is built from.

    ``headline`` is the only prose here and is deliberately terse; fuller
    rewordings should live as claims so the generator can choose among
    alternates per target.
    """

    kind: Literal["achievement"] = "achievement"
    headline: str = Field(..., min_length=1)
    role_id: str | None = None
    project_id: str | None = None
    date: PartialDate | None = None
    metrics: list[ImpactMetric] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class Skill(Entity):
    """A discrete competency, tiered by layer and self-rated by confidence.

    ``parent_id`` is optional and used only when the author wants the graph
    to reflect hierarchy (react -> javascript, kubernetes -> docker). The
    renderer does not require it.
    """

    kind: Literal["skill"] = "skill"
    name: str = Field(..., min_length=1)
    tier: SkillTier
    confidence: SkillConfidence = "working"
    years: float | None = Field(
        default=None,
        ge=0.0,
        description="Approximate years of hands-on use; may be fractional.",
    )
    last_used: PartialDate | None = None
    aliases: list[str] = Field(
        default_factory=list,
        description=(
            "Alternate spellings or ATS keyword variants, e.g. 'k8s' for 'kubernetes'."
        ),
    )
    parent_id: str | None = None


class Education(Entity):
    """A formal credential or substantial training program."""

    kind: Literal["education"] = "education"
    institution: str = Field(..., min_length=1)
    credential: str = Field(
        ...,
        min_length=1,
        description=(
            "e.g. 'BSc Computer Science', 'MS (Statistics)', 'Certificate: ...'."
        ),
    )
    field_of_study: str | None = None
    period: DateRange | None = None
    honors: list[str] = Field(default_factory=list)
    location: str | None = None


class Publication(Entity):
    """A paper, article, talk, or podcast the subject authored or contributed to."""

    kind: Literal["publication"] = "publication"
    title: str = Field(..., min_length=1)
    venue: str | None = None
    date: PartialDate | None = None
    authors: list[str] = Field(default_factory=list)
    url: str | None = None
    doi: str | None = None


class Artifact(Entity):
    """A linkable deliverable: code repo, demo, design doc, talk recording.

    Artifacts are separate from ``Publication`` because CVs typically treat
    code and design work differently from formal publications, and the
    fields that matter differ (stars vs citations).
    """

    kind: Literal["artifact"] = "artifact"
    name: str = Field(..., min_length=1)
    type: Literal[
        "repo",
        "demo",
        "paper",
        "design_doc",
        "talk",
        "podcast",
        "product",
        "other",
    ] = "other"
    url: str | None = None
    role_id: str | None = None
    project_id: str | None = None
    description: str | None = None


class Testimonial(Entity):
    """A third-party quote about the subject.

    Kept as a dedicated entity (not just a claim) because endorsements have
    their own rendering surfaces and their own visibility rules: a quote
    marked ``public`` by the subject still requires the attributed author's
    consent, which is enforced at render time via the redaction profile.
    """

    kind: Literal["testimonial"] = "testimonial"
    quote: str = Field(..., min_length=1)
    attribution: str = Field(..., min_length=1)
    relationship: str | None = Field(
        default=None,
        description="e.g. 'manager at ACME, 2021-2023'.",
    )
    source_url: str | None = None


class CoverLetterSeed(Entity):
    """Reusable narrative fragment for cover-letter generation.

    Seeds are first person, target-agnostic prose the author has already
    polished. The generator may paraphrase or concatenate them; it never
    interpolates a specific job posting into a seed, which would leak
    target text into the corpus.
    """

    kind: Literal["cover_letter_seed"] = "cover_letter_seed"
    purpose: str = Field(
        ...,
        min_length=1,
        description="When to reach for this seed, e.g. 'senior IC role at B2B SaaS'.",
    )
    body: str = Field(..., min_length=1)


class Target(Entity):
    """A specific job application the corpus is being targeted at.

    Targets are first-class so a run is reproducible: the same corpus plus
    the same target should produce byte-identical structured output. The job
    description itself lives in the source store; the target carries only
    metadata and selector hints.
    """

    kind: Literal["target"] = "target"
    role_title: str = Field(..., min_length=1)
    organization_name: str = Field(..., min_length=1)
    job_posting_url: str | None = None
    job_description_source_id: str | None = Field(
        default=None,
        description="SourceDoc ID for the scraped or pasted JD text.",
    )
    requirements: list[str] = Field(default_factory=list)
    emphasis_skill_ids: list[str] = Field(
        default_factory=list,
        description="Skills the generator should bias towards when selecting claims.",
    )
    avoid_skill_ids: list[str] = Field(
        default_factory=list,
        description="Skills to suppress even if otherwise strong matches.",
    )


class SourceDoc(Entity):
    """Pointer into the content-addressable source store.

    The actual bytes live outside the repo (see ``config.paths``) keyed by
    sha256. The corpus holds only this metadata so the repo stays textual
    and shareable: a reviewer can see that a claim is backed by e.g. a
    performance review PDF without that PDF ending up in version control.
    """

    kind: Literal["source_doc"] = "source_doc"
    origin: Literal[
        "manual",
        "linkedin_export",
        "github_profile",
        "orcid",
        "website",
        "pdf_upload",
        "email",
        "other",
    ] = "manual"
    sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(..., min_length=1)
    original_name: str | None = None
    captured_at: PartialDate | None = None
    url: str | None = None


AnyEntity = Annotated[
    (
        Person
        | Organization
        | Role
        | Project
        | Achievement
        | Skill
        | Education
        | Publication
        | Artifact
        | Testimonial
        | CoverLetterSeed
        | Target
        | SourceDoc
    ),
    Field(discriminator="kind"),
]
"""Discriminated union of every entity kind.

Used by the loader when a single YAML stream mixes kinds, and by tests that
want to assert type-safe round-trips without path-based dispatch.
"""
