"""Filesystem-backed content-addressable source store.

Every ingested original (resume PDF, LinkedIn ZIP, performance-review
transcript) is copied into the CAS under its sha256. The corpus on disk
references these blobs by digest via ``SourceDoc`` entities; the blobs
themselves live outside the repo so:

- Git history never grows with binaries.
- Two forks of the same corpus can share a local CAS without pushing
  terabytes through a remote.
- A blob can be removed (or re-captured) without touching the corpus,
  preserving the claim graph.

Layout under ``root``::

    <aa>/<aa...digest>.bin          # bytes, keyed by sha256
    <aa>/<aa...digest>.meta.json    # sidecar (original_name, mime, captured_at)

Sharding by the first two hex characters keeps any single directory under
~4096 files at 1M blobs, well within the limits file explorers render
smoothly.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class StoredBlob:
    """Metadata handle returned by the CAS; the bytes live at ``path``."""

    sha256: str
    size: int
    original_name: str | None
    mime_type: str | None
    captured_at: str | None
    path: Path


def _hash_stream(fh: BinaryIO) -> tuple[str, int]:
    """Incrementally hash ``fh`` and return ``(hex_digest, bytes_read)``.

    Streaming avoids loading multi-megabyte source documents into memory
    just to key them.
    """
    hasher = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: fh.read(_CHUNK), b""):
        hasher.update(chunk)
        size += len(chunk)
    return hasher.hexdigest(), size


class ContentAddressableStore:
    """Simple sha256-keyed blob store with a JSON sidecar per blob.

    Thread-safe for readers. Concurrent writers of the *same* blob are
    benign (same digest yields identical bytes), but the sidecar may flap
    if two writers race; callers that need atomicity should serialise at
    a higher level.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.bin"

    def _meta_path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.meta.json"

    def put_file(
        self,
        src: Path,
        *,
        original_name: str | None = None,
        mime_type: str | None = None,
        captured_at: str | None = None,
    ) -> StoredBlob:
        """Copy ``src`` into the store; returns a handle.

        Re-adding identical bytes is a no-op on the blob. The sidecar is
        refreshed so a later, better-labelled ingest (e.g., now we know
        the MIME type) replaces the earlier stub without duplicating the
        blob.
        """
        src = Path(src)
        with src.open("rb") as fh:
            digest, size = _hash_stream(fh)
        blob = self._blob_path(digest)
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            shutil.copyfile(src, blob)
        resolved_name = original_name or src.name
        meta: dict[str, object] = {
            "sha256": digest,
            "size": size,
            "original_name": resolved_name,
            "mime_type": mime_type,
            "captured_at": captured_at,
        }
        self._meta_path(digest).write_text(
            json.dumps(meta, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return StoredBlob(
            sha256=digest,
            size=size,
            original_name=resolved_name,
            mime_type=mime_type,
            captured_at=captured_at,
            path=blob,
        )

    def get(self, digest: str) -> StoredBlob | None:
        """Look up a stored blob by digest; ``None`` if absent."""
        blob = self._blob_path(digest)
        if not blob.exists():
            return None
        meta_path = self._meta_path(digest)
        meta: dict[str, object] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        size_raw = meta.get("size")
        size = int(size_raw) if isinstance(size_raw, int) else blob.stat().st_size
        original_name = meta.get("original_name")
        mime_type = meta.get("mime_type")
        captured_at = meta.get("captured_at")
        return StoredBlob(
            sha256=digest,
            size=size,
            original_name=original_name if isinstance(original_name, str) else None,
            mime_type=mime_type if isinstance(mime_type, str) else None,
            captured_at=captured_at if isinstance(captured_at, str) else None,
            path=blob,
        )

    def exists(self, digest: str) -> bool:
        return self._blob_path(digest).exists()
