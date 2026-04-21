"""Shared YAML walker used by both the validator and the generate loader.

The validator runs in accumulate-errors mode (it must report every problem
in one pass), while the generate loader runs in fail-fast mode (it refuses
to score or synthesize against an invalid corpus). Both callers need the
same "walk every .yaml under ``root``, parse safely, reject non-mappings"
behavior, so the walk itself lives here and each caller picks its own
error policy by inspecting ``YamlParseResult.ok``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class YamlParseResult:
    """Outcome of attempting to parse one YAML file.

    ``data`` is populated on success; ``error`` on failure. Exactly one is
    set. Consumers branch on ``ok`` rather than on ``data is None`` so
    the intent is explicit at the call site.
    """

    path: Path
    data: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def iter_yaml_files(root: Path) -> Iterator[YamlParseResult]:
    """Yield one ``YamlParseResult`` per ``*.yaml`` file under ``root``.

    Results are produced in ``sorted`` path order so downstream error
    messages and entity orderings are deterministic across operating
    systems. Parse errors and non-mapping roots are both surfaced as
    ``error`` results rather than raised, so the caller chooses whether
    to short-circuit or keep scanning.
    """
    for path in sorted(Path(root).rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            yield YamlParseResult(path=path, error=f"YAML parse error: {exc}")
            continue
        if not isinstance(data, dict):
            yield YamlParseResult(path=path, error="top-level YAML must be a mapping")
            continue
        yield YamlParseResult(path=path, data=data)
