"""``cv-corpus render`` - format a resolved RenderedResume to a target format.

The input is a RenderedResume JSON (produced by ``cv-corpus generate``
or hand-crafted). This command is format-agnostic: the renderer is
selected from the ``--format`` flag which maps to a registered plugin.
"""

from __future__ import annotations

import json
from importlib.metadata import entry_points
from pathlib import Path

import typer
from rich.console import Console

from ..render.base import RenderedResume, Renderer

console = Console()


def _iter_renderers() -> dict[str, Renderer]:
    out: dict[str, Renderer] = {}
    for ep in entry_points().select(group="tool_cv_corpus.renderers"):
        cls = ep.load()
        try:
            out[ep.name] = cls()
        except TypeError:
            continue
    return out


def render(
    resume_json: Path = typer.Argument(
        ...,
        help="Path to a RenderedResume JSON (from `cv-corpus generate`).",
    ),
    fmt: str = typer.Option(
        "html",
        "--format",
        "-f",
        help="Renderer plugin name (html, typst, json_resume, docx, ...).",
    ),
    out: Path = typer.Option(
        Path("output/resume"),
        "--out",
        "-o",
        help="Output path; the suffix is chosen by the renderer if absent.",
    ),
) -> None:
    """Render ``resume_json`` using the selected format plugin."""
    if not resume_json.is_file():
        console.print(f"[red]resume JSON not found: {resume_json}[/red]")
        raise typer.Exit(code=2)

    data = json.loads(resume_json.read_text(encoding="utf-8"))
    resume = RenderedResume.model_validate(data)

    renderers = _iter_renderers()
    if fmt not in renderers:
        console.print(f"[red]unknown renderer: {fmt}[/red]")
        console.print(f"available: {', '.join(sorted(renderers))}")
        raise typer.Exit(code=2)

    target = renderers[fmt].render(resume, out)
    console.print(f"[green]wrote[/green] {target}")
