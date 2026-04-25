"""``cv-corpus author`` - guided wizard for adding entities and claims.

This is the CLI shell over ``tool_cv_corpus.author``. The wizard logic
itself is testable without a TTY; this module supplies the Rich-backed
``Prompter`` implementation and the typer-driven loop.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..author import (
    DIRECTORY_BY_KIND,
    Prompter,
    load_state,
    prompt_for_claim,
    prompt_for_entity,
    write_claim,
    write_entity,
)
from ..schema import (
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

# Map the user-facing ``kind`` string to the concrete model class. Order
# is meaningful: Person first because every corpus needs one, then the
# graph dependencies (Organization before Role, Role before Achievement).
_KIND_MODELS: dict[str, type] = {
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


class RichPrompter:
    """Concrete ``Prompter`` backed by Rich and ``typer.edit``.

    Behavior choices worth knowing:

    - The ``:e`` escape on long-form fields opens the user's
      ``$EDITOR`` with the current value pre-filled (or empty). On
      systems without an editor configured, ``typer.edit`` returns
      ``None`` and we fall back to the inline value.
    - Confirm prompts default to *false* unless explicitly defaulted
      true; the wizard's "are you sure" pattern should never default
      to yes.
    - Choice prompts list options 1..N and accept either a number or
      the literal value, so users can autocomplete by retyping.
    """

    def text(
        self,
        label: str,
        *,
        default: str | None = None,
        long_form: bool = False,
        help_text: str | None = None,
    ) -> str:
        if help_text:
            console.print(f"  [dim]{help_text}[/dim]")
        suffix = " [dim](type :e to open editor)[/dim]" if long_form else ""
        prompt = f"[bold]?[/bold] {label}{suffix}"
        default_txt = f" [dim]({default})[/dim]" if default else ""
        raw = console.input(f"{prompt}{default_txt}: ")
        if raw == "" and default is not None:
            return default
        if long_form and raw.strip() == ":e":
            edited = typer.edit(default or "")
            return edited.rstrip("\n") if edited is not None else (default or "")
        return raw

    def confirm(self, label: str, *, default: bool = False) -> bool:
        suffix = " [Y/n]" if default else " [y/N]"
        raw = console.input(f"[bold]?[/bold] {label}{suffix}: ").strip().lower()
        if raw == "":
            return default
        return raw in {"y", "yes", "true", "1"}

    def choice(
        self,
        label: str,
        options: list[tuple[str, str]],
        *,
        default: str | None = None,
        allow_none: bool = False,
        allow_freeform: bool = False,
        help_text: str | None = None,
    ) -> str | None:
        if help_text:
            console.print(f"  [dim]{help_text}[/dim]")
        if not options and not allow_freeform and not allow_none:
            console.print(f"[red]no options available for {label}[/red]")
            return None
        for idx, (_value, descr) in enumerate(options, start=1):
            console.print(f"  [cyan]{idx}[/cyan]. {descr}")
        if allow_freeform:
            console.print("  [dim]or type a value not listed[/dim]")
        if allow_none:
            console.print("  [dim]or press Enter to skip[/dim]")
        raw = console.input(f"[bold]?[/bold] {label}: ").strip()
        if raw == "":
            if allow_none:
                return None
            if default is not None:
                return default
            return options[0][0] if options else ""
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(options):
                return options[i - 1][0]
        for value, _ in options:
            if value == raw:
                return value
        if allow_freeform:
            return raw
        console.print(f"[red]not a valid choice: {raw!r}[/red]")
        return self.choice(
            label,
            options,
            default=default,
            allow_none=allow_none,
            allow_freeform=allow_freeform,
            help_text=help_text,
        )

    def info(self, message: str) -> None:
        console.print(message)

    def error(self, message: str) -> None:
        console.print(f"[red]{message}[/red]")


def author(
    corpus: Path = typer.Argument(
        ...,
        help="Corpus directory to write into. Created if missing.",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="Skip the menu and start creating an entity of this kind.",
    ),
    add_claim: bool = typer.Option(
        True,
        "--add-claim/--no-add-claim",
        help="After creating an entity, offer to attach a claim to it.",
    ),
) -> None:
    """Walk an interactive wizard to add entities and claims to a corpus.

    The wizard is schema-driven: every field the Pydantic model declares
    becomes a prompt, every ``Literal`` type becomes a numbered choice,
    every foreign-key field offers a picker over what already exists.
    Validation is deferred to Pydantic; on a ``ValidationError`` only
    the offending fields are re-prompted.
    """
    corpus.mkdir(parents=True, exist_ok=True)
    for sub in {*DIRECTORY_BY_KIND.values(), "claims"}:
        (corpus / sub).mkdir(parents=True, exist_ok=True)

    prompter: Prompter = RichPrompter()

    while True:
        state = load_state(corpus)
        if state.warnings:
            console.print(
                Panel.fit(
                    "\n".join(state.warnings[:5]),
                    title="warnings while loading existing corpus",
                    border_style="yellow",
                )
            )

        if kind is None:
            counts = {k: len(state.by_kind.get(k, [])) for k in _KIND_MODELS}
            label_lines = [
                f"  {idx + 1:2}. {k:<20} ({counts[k]} on disk)"
                for idx, k in enumerate(_KIND_MODELS)
            ]
            console.print(
                Panel.fit(
                    "\n".join(label_lines),
                    title="cv-corpus author",
                    subtitle=str(corpus),
                )
            )
            raw = console.input(
                "[bold]?[/bold] kind to add (number, name, or 'q' to quit): "
            ).strip()
            if raw in {"", "q", "quit", "exit"}:
                console.print("[green]done.[/green]")
                return
            chosen = _resolve_kind(raw)
            if chosen is None:
                console.print(f"[red]unknown kind: {raw!r}[/red]")
                continue
        else:
            chosen = kind
            if chosen not in _KIND_MODELS:
                console.print(f"[red]unknown --kind: {chosen!r}[/red]")
                raise typer.Exit(code=2)

        model = _KIND_MODELS[chosen]
        try:
            entity = prompt_for_entity(model, prompter=prompter, state=state)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]cancelled; nothing written.[/yellow]")
            return

        try:
            target_path = write_entity(corpus, entity)
        except FileExistsError as exc:
            console.print(
                f"[red]refusing to overwrite {exc}; "
                f"choose a different id and retry[/red]"
            )
            kind = None
            continue
        console.print(f"[green]wrote[/green] {target_path}")

        if add_claim and prompter.confirm(
            f"add a claim about this {entity.kind}?", default=False
        ):
            state = load_state(corpus)
            try:
                claim = prompt_for_claim(
                    prompter=prompter,
                    state=state,
                    subject_kind=entity.kind,
                    subject_id=entity.id,
                )
            except (KeyboardInterrupt, EOFError):
                console.print(
                    "\n[yellow]cancelled; entity kept, claim skipped.[/yellow]"
                )
            else:
                try:
                    cpath = write_claim(corpus, claim)
                    console.print(f"[green]wrote[/green] {cpath}")
                except FileExistsError as exc:
                    console.print(f"[red]claim id collision: {exc}[/red]")

        # If the user explicitly chose a kind via --kind, treat that as
        # one-shot and exit; the menu loop only cycles when entered
        # without an initial --kind.
        if kind is not None:
            return
        kind = None


def _resolve_kind(raw: str) -> str | None:
    if raw in _KIND_MODELS:
        return raw
    if raw.isdigit():
        idx = int(raw) - 1
        keys = list(_KIND_MODELS)
        if 0 <= idx < len(keys):
            return keys[idx]
    return None
