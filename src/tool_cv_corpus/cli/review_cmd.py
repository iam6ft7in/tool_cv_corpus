"""``cv-corpus review`` - pretty-print a RenderedResume for eyeballing."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..render.base import RenderedResume

console = Console()


def review(
    resume_json: Path = typer.Argument(
        ...,
        help="Path to a RenderedResume JSON (from `cv-corpus generate`).",
    ),
) -> None:
    """Print the salient bits of ``resume_json`` without rendering to a file."""
    if not resume_json.is_file():
        console.print(f"[red]resume JSON not found: {resume_json}[/red]")
        raise typer.Exit(code=2)
    data = json.loads(resume_json.read_text(encoding="utf-8"))
    resume = RenderedResume.model_validate(data)

    console.print(
        Panel.fit(
            f"[bold]{resume.person.full_name}[/bold]\n"
            f"{resume.headline or resume.person.headline or ''}",
            title="Person",
        )
    )
    if resume.summary:
        console.print(Panel.fit(resume.summary, title="Summary"))
    for role in resume.roles:
        end = role.period.end or "present"
        console.print(
            f"  [bold]{role.title}[/bold] at {role.organization_id} "
            f"({role.period.start} to {end})"
        )
        for ach in resume.achievements:
            if ach.role_id == role.id:
                console.print(f"    - {ach.headline}")
    if resume.skills:
        console.print("[bold]Skills:[/bold]")
        for s in resume.skills:
            console.print(f"  - {s.name} ({s.tier}, {s.confidence})")
