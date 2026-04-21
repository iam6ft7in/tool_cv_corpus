"""OS-standard paths for data, config, and cache.

Using ``platformdirs`` rather than hand-picking a location means the tool
behaves like a well-mannered citizen on every platform:

- Linux:   ``~/.local/share/tool_cv_corpus`` (XDG-compliant)
- macOS:   ``~/Library/Application Support/tool_cv_corpus``
- Windows: ``%LOCALAPPDATA%\\tool_cv_corpus``

The source store lives under ``data_dir`` by default so ingested binaries
(PDFs, DOCX, LinkedIn ZIPs) never end up inside the repo and therefore
never end up in git history. A user can override this via
``CV_CORPUS_SOURCE_STORE`` in ``Settings`` for shops that keep binaries on
a cloud-synced drive.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs

APP_NAME = "tool_cv_corpus"


def data_dir() -> Path:
    """User data: the CAS source store and LLM response cache live here."""
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def config_dir() -> Path:
    """User config files; currently unused but reserved for profiles."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    """Safe-to-delete cache. Anything irrecoverable belongs in ``data_dir``."""
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def source_store_dir() -> Path:
    """Default location for the content-addressable source store."""
    return data_dir() / "sources"


def llm_cache_db() -> Path:
    """Default location for the SQLite LLM response cache."""
    return cache_dir() / "llm_cache.sqlite"
