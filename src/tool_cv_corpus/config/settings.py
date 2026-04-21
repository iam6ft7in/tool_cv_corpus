"""Immutable, environment-derived settings snapshot.

The rest of the code receives a frozen ``Settings`` and threads it through.
Two reasons to prefer a snapshot over ad-hoc ``os.environ.get`` calls:

1. Tests can construct a ``Settings`` directly without monkey-patching env
   vars, which is both faster and less leaky across test runs.
2. A CLI command picks up a consistent view: if the user exports a new
   value halfway through a long generation, the in-flight command still
   sees its original configuration.

API keys are loaded but not eagerly validated; the provider that actually
needs them raises at call time with a clear error. This keeps the common
``cv-corpus --help`` path fast and silent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import paths

DEFAULT_MODEL = "claude-sonnet-4-6"
"""Default Anthropic model.

Kept as a plain string (not an enum) so bumping to a newer snapshot does
not require a code change.
"""


@dataclass(frozen=True)
class Settings:
    """Read-only configuration gathered from the environment."""

    source_store: Path
    model: str
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """Build a ``Settings`` from ``os.environ`` plus platform defaults.

        Order of precedence:
        1. Explicit env var.
        2. Platform-appropriate default from ``paths``.

        The source store path is expanded (``~`` resolves to the home dir)
        but not created; the CAS ensures its own root exists on first use.
        """
        src = os.environ.get("CV_CORPUS_SOURCE_STORE")
        model = os.environ.get("CV_CORPUS_MODEL") or DEFAULT_MODEL
        source_store = Path(src).expanduser() if src else paths.source_store_dir()
        return cls(
            source_store=source_store,
            model=model,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        )
