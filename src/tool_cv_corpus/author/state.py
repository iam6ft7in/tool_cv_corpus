"""Read-side view of an existing corpus, used by the wizard.

We need to know what entities already exist so the wizard can:

1. Offer foreign-key pickers (``organization_id`` lists existing orgs).
2. Refuse to overwrite an existing ID without explicit confirmation.
3. Surface gaps (planned for Tier 1.5: roles with no claims, skills with
   no parent linkage).

Loading is best-effort: malformed YAML or schema-violating files are
collected as warnings rather than raised, because the wizard's job is to
help the user fix a corpus, not to gatekeep on its current health. The
strict validator is a separate command for that.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..io.yaml_loader import iter_yaml_files
from ..schema import AnyEntity


@dataclass
class CorpusState:
    """Snapshot of the entities already on disk under one corpus root.

    ``by_kind`` is the canonical view: kind name (``"role"``,
    ``"organization"``, ...) to a list of entities preserving on-disk
    order. ``ids_by_kind`` is a derived index for cheap collision and
    foreign-key existence checks.
    """

    root: Path
    by_kind: dict[str, list[AnyEntity]] = field(default_factory=dict)
    ids_by_kind: dict[str, set[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def has(self, kind: str, entity_id: str) -> bool:
        return entity_id in self.ids_by_kind.get(kind, set())

    def list_kind(self, kind: str) -> list[AnyEntity]:
        return list(self.by_kind.get(kind, []))


def load_state(root: Path) -> CorpusState:
    """Walk ``root`` and return a ``CorpusState`` of every parseable entity.

    ``Claim`` records (``kind: claim`` on disk) are intentionally skipped
    here: claims are layered on top of entities and the wizard only needs
    the entity graph to draw foreign-key pickers from. A future
    ``--gaps`` mode that wants per-entity claim counts will load claims
    separately rather than coupling them into this snapshot.
    """
    state = CorpusState(root=root)
    by_kind: dict[str, list[AnyEntity]] = defaultdict(list)
    ids_by_kind: dict[str, set[str]] = defaultdict(set)
    adapter: TypeAdapter[AnyEntity] = TypeAdapter(AnyEntity)

    for result in iter_yaml_files(root):
        if not result.ok:
            state.warnings.append(f"{result.path}: {result.error}")
            continue
        payload: dict[str, Any] = dict(result.data or {})
        kind = payload.get("kind")
        if kind == "claim" or kind is None:
            continue
        try:
            entity = adapter.validate_python(payload)
        except ValidationError as exc:
            state.warnings.append(f"{result.path}: schema error: {exc.errors()[:1]}")
            continue
        by_kind[entity.kind].append(entity)
        ids_by_kind[entity.kind].add(entity.id)

    state.by_kind = dict(by_kind)
    state.ids_by_kind = dict(ids_by_kind)
    return state
