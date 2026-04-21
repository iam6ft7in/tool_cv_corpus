"""``cv-corpus ingest`` - pull an external source into the corpus.

Auto-dispatches by asking each registered ingester's ``accepts()`` hook
whether it can handle the input. If more than one accepts, the user
must pick explicitly via ``--using``.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

import typer
from rich.console import Console

from ..ingest.base import Ingester, IngestResult

console = Console()


def _iter_ingesters() -> dict[str, Ingester]:
    out: dict[str, Ingester] = {}
    for ep in entry_points().select(group="tool_cv_corpus.ingesters"):
        cls = ep.load()
        try:
            out[ep.name] = cls()
        except TypeError:
            # Ingester constructor needs args; user must pass --using.
            continue
    return out


def ingest(
    src: Path = typer.Argument(..., help="Path to file or directory to ingest."),
    corpus: Path = typer.Option(
        Path("corpus"),
        "--corpus",
        help="Corpus directory to append to.",
    ),
    using: str | None = typer.Option(
        None,
        "--using",
        help="Name of a specific ingester to use, overriding auto-detect.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and report without writing to the corpus.",
    ),
) -> None:
    """Ingest ``src`` into ``corpus`` using the first ingester that accepts it."""
    ingesters = _iter_ingesters()
    if using is not None:
        if using not in ingesters:
            console.print(f"[red]unknown ingester: {using}[/red]")
            console.print(f"available: {', '.join(sorted(ingesters))}")
            raise typer.Exit(code=2)
        chosen = [ingesters[using]]
    else:
        chosen = [ing for ing in ingesters.values() if ing.accepts(src)]

    if not chosen:
        console.print(
            f"[yellow]no ingester accepted {src}; pass --using to force one[/yellow]"
        )
        raise typer.Exit(code=3)

    if len(chosen) > 1:
        names = ", ".join(getattr(i, "name", "?") for i in chosen)
        console.print(
            f"[yellow]multiple ingesters accept {src}: {names}. "
            f"Pass --using to disambiguate.[/yellow]"
        )
        raise typer.Exit(code=3)

    ingester = chosen[0]
    result: IngestResult = ingester.ingest(src)
    console.print(
        f"[green]{ingester.name}[/green]: "
        f"{len(result.entities)} entities, "
        f"{len(result.claims)} claims, "
        f"{len(result.sources)} sources, "
        f"{len(result.warnings)} warnings"
    )
    for w in result.warnings:
        console.print(f"  [yellow]![/yellow] {w}")

    if dry_run:
        return

    corpus.mkdir(parents=True, exist_ok=True)
    import yaml  # local import to keep --help fast

    for entity in result.entities:
        kind_dir = corpus / f"{entity.kind}s"
        kind_dir.mkdir(exist_ok=True)
        out = kind_dir / f"{entity.id}.yaml"
        out.write_text(
            yaml.safe_dump(
                entity.model_dump(exclude_defaults=True),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    console.print(
        f"[green]wrote[/green] {len(result.entities)} entities under {corpus}"
    )
