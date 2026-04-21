"""Content-addressable source store tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tool_cv_corpus.storage.cas import ContentAddressableStore


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def test_put_file_creates_blob_and_sidecar(tmp_path: Path) -> None:
    store = ContentAddressableStore(tmp_path / "sources")
    src = tmp_path / "resume.txt"
    _write(src, b"hello, corpus")
    blob = store.put_file(src, mime_type="text/plain", captured_at="2026-04-21")

    digest = hashlib.sha256(b"hello, corpus").hexdigest()
    assert blob.sha256 == digest
    assert blob.path.exists()
    assert blob.path.parent.name == digest[:2]
    sidecar = json.loads((blob.path.parent / f"{digest}.meta.json").read_text())
    assert sidecar["original_name"] == "resume.txt"
    assert sidecar["mime_type"] == "text/plain"
    assert sidecar["captured_at"] == "2026-04-21"
    assert sidecar["size"] == len(b"hello, corpus")


def test_put_file_idempotent(tmp_path: Path) -> None:
    store = ContentAddressableStore(tmp_path / "sources")
    src = tmp_path / "a.txt"
    _write(src, b"same bytes")
    first = store.put_file(src)
    first_mtime = first.path.stat().st_mtime

    src2 = tmp_path / "renamed.txt"
    _write(src2, b"same bytes")
    second = store.put_file(src2, original_name="renamed.txt")

    assert first.sha256 == second.sha256
    assert first.path.stat().st_mtime == first_mtime  # blob untouched
    sidecar = json.loads((first.path.parent / f"{first.sha256}.meta.json").read_text())
    assert sidecar["original_name"] == "renamed.txt"  # sidecar refreshed


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = ContentAddressableStore(tmp_path / "sources")
    assert store.get("0" * 64) is None


def test_get_returns_handle(tmp_path: Path) -> None:
    store = ContentAddressableStore(tmp_path / "sources")
    src = tmp_path / "x.bin"
    _write(src, b"\x00\x01\x02")
    stored = store.put_file(src, mime_type="application/octet-stream")
    got = store.get(stored.sha256)
    assert got is not None
    assert got.sha256 == stored.sha256
    assert got.mime_type == "application/octet-stream"
    assert got.path.read_bytes() == b"\x00\x01\x02"


def test_sharding_groups_by_prefix(tmp_path: Path) -> None:
    store = ContentAddressableStore(tmp_path / "sources")
    for i in range(5):
        src = tmp_path / f"f{i}.txt"
        _write(src, f"payload {i}".encode())
        store.put_file(src)
    for shard in (tmp_path / "sources").iterdir():
        assert shard.is_dir()
        assert len(shard.name) == 2
