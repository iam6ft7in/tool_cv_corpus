"""SQLite-backed LLM response cache.

Rebuilding the same resume with the same corpus and target should be
deterministic and free after the first run. The cache key is
``sha256(system + messages + tools + model + max_tokens + temperature)``
so any change to the prompt invalidates only the affected entries.

SQLite over a JSONL log because:

- Concurrent CLI runs (a user rendering to PDF and HTML in parallel)
  get row-level atomicity without ad-hoc file locking.
- O(1) lookups by key on stores with tens of thousands of entries.
- Standard backup, vacuum, and inspection tooling.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .base import LLMResponse, Msg, Tool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    created_ts REAL NOT NULL,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model ON responses(model);
"""


def _canonical_json(obj: Any) -> str:
    """Stable-key JSON so dict ordering does not bust the cache."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_cache_key(
    *,
    system: str,
    messages: list[Msg],
    tools: list[Tool] | None,
    model: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Hash a request into a deterministic key.

    Message *order* is significant and intentionally part of the key:
    swapping two turns of a conversation genuinely changes the expected
    completion.
    """
    parts = {
        "system": system,
        "messages": [m.model_dump() for m in messages],
        "tools": [t.model_dump() for t in (tools or [])],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()


class LLMResponseCache:
    """Tiny write-through cache over a SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.executescript(_SCHEMA)

    def get(self, key: str) -> LLMResponse | None:
        """Return a cached response, or ``None`` on miss.

        Hits are returned with ``cache_hit=True`` so upstream code can
        log or skip usage accounting without looking it up again.
        """
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT response_json FROM responses WHERE cache_key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        resp = LLMResponse.model_validate(data)
        return resp.model_copy(update={"cache_hit": True})

    def put(self, key: str, resp: LLMResponse) -> None:
        """Insert or overwrite ``key``.

        Overwriting matters: a later run with the same key but a newer
        provider may emit slightly richer ``usage`` buckets; we keep
        the most recent payload.
        """
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT OR REPLACE INTO responses"
                " (cache_key, model, created_ts, response_json)"
                " VALUES (?, ?, ?, ?)",
                (key, resp.model, time.time(), resp.model_dump_json()),
            )
            con.commit()
