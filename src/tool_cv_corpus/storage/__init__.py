"""Durable, out-of-repo storage for ingested originals.

The CAS lives here rather than in ``config`` because its lifecycle is
distinct from runtime settings: a CAS persists across many runs and many
corpora; settings are per-invocation.
"""

from __future__ import annotations

from .cas import ContentAddressableStore, StoredBlob

__all__ = ["ContentAddressableStore", "StoredBlob"]
