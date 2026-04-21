"""``cv-corpus init`` - scaffold a new corpus directory from the template.

The skeleton that ships with the package lives under
``templates/init/corpus.skeleton/`` and is included in the wheel via
``force-include`` in pyproject.toml, so ``init`` works from an installed
package (no source checkout required).
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def init(
    dest: Path = typer.Argument(
        ...,
        help="Directory to create. Must not already exist.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite ``dest`` if it already exists.",
    ),
) -> None:
    """Create a new corpus directory from the bundled skeleton."""
    if dest.exists() and not force:
        console.print(
            f"[red]refusing to overwrite existing {dest}; pass --force to proceed[/red]"
        )
        raise typer.Exit(code=2)
    if dest.exists() and force:
        shutil.rmtree(dest)

    skeleton_root = resources.files("tool_cv_corpus").joinpath("_init_skeleton")
    if not skeleton_root.is_dir():
        console.print(
            "[red]skeleton missing from package; reinstall tool_cv_corpus[/red]"
        )
        raise typer.Exit(code=1)

    dest.mkdir(parents=True)
    for item in skeleton_root.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)  # type: ignore[arg-type]
        else:
            shutil.copyfile(item, target)  # type: ignore[arg-type]
    console.print(f"[green]created[/green] corpus at [bold]{dest}[/bold]")
