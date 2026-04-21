"""``cv-corpus generate`` — produce a target-tailored ``RenderedResume``.

Wires together the four generate stages: ``load_corpus`` →
``score_claims`` → ``select`` → ``synthesize``. Two escape hatches for
offline / preview use:

- ``--dry-run``: stop after selection and print the manifest (what
  would be shown in each section, with scores). No LLM, no file write.
- ``--no-llm``: build the ``RenderedResume`` from raw ``Claim.text``
  (no Pass A headline/summary, no Pass B bullet rewrites) and write
  JSON. Deterministic and useful for CI.

Exit codes:
  0 - ``RenderedResume`` JSON written (or dry-run manifest printed).
  1 - synthesis error, LLM failure, write error.
  2 - bad invocation (target not found, etc).
  3 - corpus could not be loaded.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import typer
from rich.console import Console
from rich.table import Table

from ..config.paths import llm_cache_db
from ..generate.llm.base import LLMProvider
from ..generate.llm.cache import CachedLLMProvider, LLMResponseCache
from ..generate.loader import CorpusLoadError, load_corpus
from ..generate.scoring import score_claims
from ..generate.selection import select
from ..generate.synthesis import SynthesisError, synthesize, synthesize_no_llm
from ..schema import Visibility
from ..schema.entities import Target

console = Console()

_VISIBILITY_CHOICES = set(get_args(Visibility))


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
    max_visibility: str = typer.Option(
        "private",
        "--max-visibility",
        help="Redaction cap: public < nda < private. 'private' keeps all.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Stop after selection; print manifest. No LLM, no file write.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip LLM synthesis; use raw Claim.text for bullets.",
    ),
    provider_name: str = typer.Option(
        "anthropic",
        "--provider",
        help="LLM provider name (entry-point under tool_cv_corpus.llm_providers).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Provider-specific model ID; leave unset for the provider default.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Skip the SQLite LLM response cache for this run.",
    ),
) -> None:
    """Produce a target-tailored ``RenderedResume`` JSON."""
    if max_visibility not in _VISIBILITY_CHOICES:
        console.print(
            f"[red]--max-visibility must be one of {sorted(_VISIBILITY_CHOICES)}[/red]"
        )
        raise typer.Exit(code=2)

    try:
        corp = load_corpus(corpus, max_visibility=max_visibility)  # type: ignore[arg-type]
    except CorpusLoadError as exc:
        console.print(f"[red]Failed to load corpus:[/red] {exc}")
        console.print("[dim]Tip: run `cv-corpus validate` for a full diagnostic.[/dim]")
        raise typer.Exit(code=3) from exc

    target_entity = corp.entities.get(("target", target))
    if not isinstance(target_entity, Target):
        available = sorted(tid for (kind, tid) in corp.entities if kind == "target")
        console.print(f"[red]Target '{target}' not found in corpus.[/red]")
        if available:
            console.print(f"[dim]Available targets: {', '.join(available)}[/dim]")
        raise typer.Exit(code=2)

    scores = score_claims(corp, target_entity)
    selection = select(corp, target_entity, scores)

    if dry_run:
        _print_selection_manifest(corp, target_entity, selection, scores)
        return

    if no_llm:
        resume = synthesize_no_llm(corp, target_entity, selection, scores)
    else:
        try:
            provider = _build_provider(provider_name, model=model, cache=not no_cache)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        try:
            resume = synthesize(
                corp, target_entity, selection, scores, provider, model=model
            )
        except SynthesisError as exc:
            console.print(f"[red]Synthesis failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(resume.model_dump_json(indent=2), encoding="utf-8")
    console.print(
        f"[green]Wrote RenderedResume to {out}[/green] "
        f"([dim]{len(resume.roles)} roles, {len(resume.skills)} skills, "
        f"{len(resume.sections)} sections[/dim])"
    )


def _print_selection_manifest(
    corpus: "Corpus",  # noqa: UP037 - forward ref for docstring brevity
    target: Target,
    selection: "Selection",  # noqa: UP037
    scores: dict[str, "ScoreBreakdown"],  # noqa: UP037
) -> None:
    """Rich-print the selection so users can inspect a run without the LLM.

    The manifest is advisory: it shows *what would be synthesized*, not
    *how the bullets will read* (that is Pass B's job). Readers can use
    it to spot missing roles, over-aggressive skill dedup, or a target
    that bleeds too many avoid-matches into the selection.
    """
    console.print(
        f"[bold]Dry run for target:[/bold] {target.id} "
        f"([dim]{target.role_title} @ {target.organization_name}[/dim])"
    )

    roles_table = Table(title="Roles (chronological)")
    roles_table.add_column("role_id")
    roles_table.add_column("achievements (best→worst)")
    for rid in selection.role_ids:
        role_entity = corpus.entities.get(("role", rid))
        title = getattr(role_entity, "title", "?") if role_entity is not None else "?"
        aids = selection.achievement_ids_by_role.get(rid, ())
        roles_table.add_row(
            f"{rid} [dim]({title})[/dim]",
            ", ".join(aids) if aids else "[dim](none)[/dim]",
        )
    console.print(roles_table)

    if selection.skill_ids:
        console.print(
            f"[bold]Skills ({len(selection.skill_ids)}):[/bold] "
            + ", ".join(selection.skill_ids)
        )

    if selection.summary_claim_ids:
        summary_table = Table(title="Summary claims")
        summary_table.add_column("claim_id")
        summary_table.add_column("score", justify="right")
        for cid in selection.summary_claim_ids:
            sb = scores.get(cid)
            summary_table.add_row(cid, f"{sb.total:.2f}" if sb is not None else "-")
        console.print(summary_table)

    if selection.claim_ids_by_subject:
        subj_table = Table(title="Claims per selected subject")
        subj_table.add_column("subject")
        subj_table.add_column("claims (best→worst)")
        for (kind, sid), cids in sorted(selection.claim_ids_by_subject.items()):
            subj_table.add_row(f"{kind}:{sid}", ", ".join(cids))
        console.print(subj_table)


def _build_provider(name: str, *, model: str | None, cache: bool) -> LLMProvider:
    """Resolve a provider by name, optionally wrapping it in the cache.

    Only Anthropic is wired in this release; OpenAI is registered as an
    entry point but its implementation still raises ``NotImplementedError``.
    The ``--provider`` flag stays open-ended so a future release can swap
    in entry-point discovery without breaking command-line ergonomics.
    """
    if name == "anthropic":
        from ..generate.llm.anthropic_provider import AnthropicProvider

        inner: LLMProvider = AnthropicProvider(
            default_model=model or "claude-sonnet-4-6"
        )
    else:
        raise ValueError(f"Unknown provider '{name}'. Supported in v0.2: anthropic.")

    if cache:
        store = LLMResponseCache(llm_cache_db())
        return CachedLLMProvider(inner=inner, cache=store, name=name)
    return inner


# These forward references are only used in the manifest helper above and
# are imported lazily to keep the top of the module focused on runtime.
from ..generate.loader import Corpus  # noqa: E402
from ..generate.scoring import ScoreBreakdown  # noqa: E402
from ..generate.selection import Selection  # noqa: E402
