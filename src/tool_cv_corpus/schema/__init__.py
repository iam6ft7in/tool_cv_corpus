"""Public surface of the corpus schema.

Importing from ``tool_cv_corpus.schema`` should be enough for downstream
code; reaching into submodules is allowed but not required. Keeping the
re-export list tight makes breaking-change surface easier to audit.
"""

from __future__ import annotations

from .base import SCHEMA_VERSION, Entity, Visibility
from .claims import Claim, ClaimType
from .dates import DateRange, PartialDate
from .entities import (
    Achievement,
    AnyEntity,
    Artifact,
    CoverLetterSeed,
    Education,
    Organization,
    Person,
    Project,
    Publication,
    Role,
    Skill,
    SourceDoc,
    Target,
    Testimonial,
)
from .impact import Direction, ImpactMetric
from .taxonomy import SkillConfidence, SkillTier

__all__ = [
    "SCHEMA_VERSION",
    "Achievement",
    "AnyEntity",
    "Artifact",
    "Claim",
    "ClaimType",
    "CoverLetterSeed",
    "DateRange",
    "Direction",
    "Education",
    "Entity",
    "ImpactMetric",
    "Organization",
    "PartialDate",
    "Person",
    "Project",
    "Publication",
    "Role",
    "Skill",
    "SkillConfidence",
    "SkillTier",
    "SourceDoc",
    "Target",
    "Testimonial",
    "Visibility",
]
