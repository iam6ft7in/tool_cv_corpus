"""``cv-corpus doctor`` - diagnose the local installation.

Lists discovered plugins, resolved paths, and environment so users can
triage "why isn't my plugin showing up" without reading the source.
"""

from __future__ import annotations

import shutil
import sys
from importlib.metadata import entry_points, version

from rich.console import Console
from rich.table import Table

from ..config import Settings, paths

console = Console()

_GROUPS = (
    "tool_cv_corpus.renderers",
    "tool_cv_corpus.ingesters",
    "tool_cv_corpus.llm_providers",
)


def doctor() -> None:
    """Print a diagnostic table of the environment and plugin discovery."""
    env = Table(title="Environment")
    env.add_column("key")
    env.add_column("value")
    env.add_row("tool_cv_corpus", version("tool-cv-corpus"))
    env.add_row("python", sys.version.split()[0])
    env.add_row("platform", sys.platform)
    env.add_row("typst", shutil.which("typst") or "[yellow]not on PATH[/yellow]")
    console.print(env)

    s = Settings.from_env()
    config_t = Table(title="Resolved paths")
    config_t.add_column("role")
    config_t.add_column("path")
    config_t.add_row("data_dir", str(paths.data_dir()))
    config_t.add_row("config_dir", str(paths.config_dir()))
    config_t.add_row("cache_dir", str(paths.cache_dir()))
    config_t.add_row("source_store", str(s.source_store))
    config_t.add_row("llm_cache_db", str(paths.llm_cache_db()))
    console.print(config_t)

    model_t = Table(title="LLM settings")
    model_t.add_column("key")
    model_t.add_column("value")
    model_t.add_row("model", s.model)
    model_t.add_row(
        "anthropic_api_key",
        "[green]set[/green]" if s.anthropic_api_key else "[yellow]unset[/yellow]",
    )
    model_t.add_row(
        "openai_api_key",
        "[green]set[/green]" if s.openai_api_key else "[yellow]unset[/yellow]",
    )
    console.print(model_t)

    for group in _GROUPS:
        eps = list(entry_points().select(group=group))
        plugins = Table(title=f"Plugins: {group}")
        plugins.add_column("name")
        plugins.add_column("module:attr")
        plugins.add_column("status")
        if not eps:
            plugins.add_row("[yellow]none discovered[/yellow]", "", "")
        for ep in eps:
            try:
                ep.load()
                status = "[green]ok[/green]"
            except Exception as exc:
                status = f"[red]import failed: {exc}[/red]"
            plugins.add_row(ep.name, ep.value, status)
        console.print(plugins)
