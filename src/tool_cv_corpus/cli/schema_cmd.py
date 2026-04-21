"""``cv-corpus schema`` - export JSON Schemas for every entity kind.

Useful for editor integration (schema-aware YAML completion) and for
third-party validators that want to check corpora without running
Python. Schemas are emitted per kind so a diff across releases stays
focused.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import BaseModel
from rich.console import Console

from ..schema.entities import (
    Achievement,
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

console = Console()

_ENTITIES: dict[str, type[BaseModel]] = {
    "person": Person,
    "organization": Organization,
    "role": Role,
    "project": Project,
    "achievement": Achievement,
    "skill": Skill,
    "education": Education,
    "publication": Publication,
    "artifact": Artifact,
    "testimonial": Testimonial,
    "cover_letter_seed": CoverLetterSeed,
    "target": Target,
    "source_doc": SourceDoc,
}


def schema(
    out: Path = typer.Option(
        Path("schemas"),
        "--out",
        help="Directory to write <kind>.schema.json files to.",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        help="Emit a single kind instead of all of them.",
    ),
) -> None:
    """Dump pydantic JSON Schemas for each entity kind."""
    out.mkdir(parents=True, exist_ok=True)
    if kind is not None and kind not in _ENTITIES:
        console.print(f"[red]unknown kind: {kind}[/red]")
        console.print(f"available: {', '.join(sorted(_ENTITIES))}")
        raise typer.Exit(code=2)
    targets = {kind: _ENTITIES[kind]} if kind else _ENTITIES
    for name, cls in targets.items():
        path = out / f"{name}.schema.json"
        path.write_text(
            json.dumps(cls.model_json_schema(), indent=2),
            encoding="utf-8",
        )
        console.print(f"[green]wrote[/green] {path}")


__all__ = ["schema"]
