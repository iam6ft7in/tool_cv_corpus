"""``cv-corpus validate`` - run the validator over a corpus directory.

The heavy lifting lives in ``tool_cv_corpus.validate.runner``; this
subcommand is a thin adapter that maps the runner's result to a Rich
summary and an exit code that CI systems can key off.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..validate.runner import ValidatorRunner

console = Console()


def validate(
    corpus: Path = typer.Argument(
        Path("corpus"),
        help="Corpus directory to validate.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as errors (CI-friendly).",
    ),
) -> None:
    """Validate ``corpus`` and print a summary.

    Exit codes:
      0 - all checks passed (or only warnings, unless --strict).
      1 - at least one error.
      2 - bad invocation (missing corpus directory, etc).
      3 - invalid corpus structure that prevented the run.
    """
    if not corpus.is_dir():
        console.print(f"[red]corpus directory not found: {corpus}[/red]")
        raise typer.Exit(code=2)

    runner = ValidatorRunner(corpus)
    report = runner.run()

    table = Table(title=f"Validation: {corpus}")
    table.add_column("check")
    table.add_column("result")
    table.add_column("detail")
    for c in report.checks:
        color = {"ok": "green", "warn": "yellow", "error": "red"}[c.status]
        table.add_row(c.name, f"[{color}]{c.status}[/{color}]", c.detail or "")
    console.print(table)

    if report.errors:
        raise typer.Exit(code=1)
    if strict and report.warnings:
        raise typer.Exit(code=1)
