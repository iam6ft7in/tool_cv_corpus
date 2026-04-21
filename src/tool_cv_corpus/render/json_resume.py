"""JSON Resume v1.0.0 renderer.

JSON Resume (https://jsonresume.org/schema/) is a de facto standard
consumable by dozens of themes and online viewers. Emitting it as a
first-class target gives users a portable interchange format without
committing to any one rendering chain.

We stay strictly within v1.0.0 field names; extensions go under the
``meta`` block where readers that do not know them will ignore them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from .base import RenderedResume


class JsonResumeRenderer:
    """Render a ``RenderedResume`` as JSON Resume v1.0.0."""

    name: ClassVar[str] = "json_resume"
    extensions: ClassVar[tuple[str, ...]] = (".json",)

    def render(self, resume: RenderedResume, out_path: Path) -> Path:
        target = out_path if out_path.suffix else out_path.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self._document(resume), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    def _document(self, r: RenderedResume) -> dict[str, Any]:
        basics: dict[str, Any] = {
            "name": r.person.full_name,
            "label": r.headline or r.person.headline or "",
            "email": r.person.contact.get("email", ""),
            "website": r.person.contact.get("website", ""),
            "summary": r.summary or "",
            "location": {"address": r.person.location or ""},
            "profiles": [
                {"network": net, "url": url}
                for net, url in r.person.contact.items()
                if net not in {"email", "website"}
            ],
        }
        work = [
            {
                "name": role.organization_id,
                "position": role.title,
                "startDate": role.period.start,
                "endDate": role.period.end or "",
                "location": role.location or "",
                "highlights": [
                    ach.headline for ach in r.achievements if ach.role_id == role.id
                ],
            }
            for role in r.roles
        ]
        skills = [
            {
                "name": skill.name,
                "level": skill.confidence,
                "keywords": skill.aliases,
            }
            for skill in r.skills
        ]
        education = [
            {
                "institution": edu.institution,
                "area": edu.field_of_study or "",
                "studyType": edu.credential,
                "startDate": edu.period.start if edu.period else "",
                "endDate": edu.period.end if edu.period else "",
            }
            for edu in r.education
        ]
        publications = [
            {
                "name": pub.title,
                "publisher": pub.venue or "",
                "releaseDate": pub.date or "",
                "url": pub.url or "",
            }
            for pub in r.publications
        ]
        references = [
            {
                "name": t.attribution,
                "reference": t.quote,
            }
            for t in r.testimonials
        ]
        return {
            "basics": basics,
            "work": work,
            "education": education,
            "skills": skills,
            "publications": publications,
            "references": references,
            "meta": {
                "version": "v1.0.0",
                "generator": "tool_cv_corpus",
                **r.metadata,
            },
        }
