"""HTML renderer.

Emits a minimal, semantic single-file HTML document. No CSS framework
and no JavaScript: static HTML is the most portable output we can
produce, and opinionated styling is better layered downstream by the
author (print stylesheet, custom theme, etc.).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import ClassVar

from .base import RenderedResume


class HtmlRenderer:
    """Render a RenderedResume as a self-contained HTML file."""

    name: ClassVar[str] = "html"
    extensions: ClassVar[tuple[str, ...]] = (".html",)

    def render(self, resume: RenderedResume, out_path: Path) -> Path:
        target = out_path if out_path.suffix else out_path.with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._document(resume), encoding="utf-8")
        return target

    def _document(self, r: RenderedResume) -> str:
        body_parts = [
            f"<header><h1>{html.escape(r.person.full_name)}</h1>",
        ]
        if r.headline or r.person.headline:
            body_parts.append(
                f'<p class="headline">'
                f"{html.escape(r.headline or r.person.headline or '')}"
                f"</p>"
            )
        body_parts.append("</header>")

        if r.summary:
            body_parts.append(
                f'<section class="summary"><p>{html.escape(r.summary)}</p></section>'
            )

        if r.roles:
            body_parts.append('<section class="roles"><h2>Experience</h2><ul>')
            for role in r.roles:
                period = f"{role.period.start} to {role.period.end or 'present'}"
                body_parts.append(
                    f"<li><strong>{html.escape(role.title)}</strong>, "
                    f"{html.escape(role.organization_id)} "
                    f"<em>({html.escape(period)})</em></li>"
                )
            body_parts.append("</ul></section>")

        if r.achievements:
            body_parts.append(
                '<section class="achievements"><h2>Selected Outcomes</h2><ul>'
            )
            for ach in r.achievements:
                body_parts.append(f"<li>{html.escape(ach.headline)}</li>")
            body_parts.append("</ul></section>")

        if r.skills:
            body_parts.append('<section class="skills"><h2>Skills</h2><ul>')
            for skill in r.skills:
                body_parts.append(
                    f"<li>{html.escape(skill.name)} "
                    f"<small>({skill.tier}, {skill.confidence})</small></li>"
                )
            body_parts.append("</ul></section>")

        return (
            "<!doctype html>\n"
            '<html lang="en"><head>'
            f'<meta charset="utf-8"><title>'
            f"{html.escape(r.person.full_name)}</title></head>"
            f"<body>{''.join(body_parts)}</body></html>\n"
        )
