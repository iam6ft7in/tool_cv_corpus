"""Per-entity schema migrations.

Each corpus file carries its own ``schema_version``, so migrations run
file-by-file rather than as a global rewrite. This keeps a corpus forkable:
collaborators can merge across releases without a flag day.

Migrations live as small functions keyed by ``(from_version, kind)`` and
return a dict in the target version's shape. New upgrades register here;
the loader walks the chain until it reaches the current ``SCHEMA_VERSION``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..base import SCHEMA_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]


_REGISTRY: dict[tuple[str, str], Migration] = {}
"""``(from_version, kind) -> migration`` lookup.

Intentionally empty at 0.1.0; the scaffolding is here so the first real
bump does not require touching loader code.
"""


def register(from_version: str, kind: str) -> Callable[[Migration], Migration]:
    """Decorator that registers a migration into the table."""

    def _wrap(fn: Migration) -> Migration:
        _REGISTRY[(from_version, kind)] = fn
        return fn

    return _wrap


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Walk the chain from ``data['schema_version']`` to current.

    Returns a new dict each hop so callers can compare before/after for
    diagnostics. Unknown versions return ``data`` unchanged; validation
    then surfaces a pydantic error the user can act on.
    """
    cur = dict(data)
    guard = 0
    while cur.get("schema_version") != SCHEMA_VERSION:
        key = (cur.get("schema_version", ""), cur.get("kind", ""))
        fn = _REGISTRY.get(key)
        if fn is None:
            return cur
        cur = fn(cur)
        guard += 1
        if guard > 32:
            raise RuntimeError("migration chain exceeded 32 hops; likely a cycle")
    return cur
