"""``cv-corpus generate`` - produce a RenderedResume via the LLM.

The full generate pipeline (corpus loader, claim scorer, target-aware
selection, LLM prompt assembly, cache wiring) is deferred to a follow-up
release. v0.1.0 ships the CLI surface so users can script against it
and so downstream renderers are exercised, but the body raises a
clear, actionable error.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def generate(
    corpus: Path = typer.Argument(
        Path("corpus"),
        help="Corpus directory to read.",
    ),
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Target entity ID to tailor towards.",
    ),
    out: Path = typer.Option(
        Path("output/rendered_resume.json"),
        "--out",
        "-o",
        help="Where to write the resolved RenderedResume JSON.",
    ),
) -> None:
    """Produce a target-tailored RenderedResume. Not implemented in v0.1.0."""
    del corpus, target, out  # reserved for v0.2 pipeline
    console.print(
        "[yellow]generate is a stub in v0.1.0.[/yellow] "
        "Hand-craft a RenderedResume JSON and pass it to `cv-corpus render`, "
        "or track progress at "
        "https://github.com/iam6ft7in/tool_cv_corpus/issues."
    )
    raise typer.Exit(code=1)
