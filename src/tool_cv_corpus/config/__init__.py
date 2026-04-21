"""Runtime configuration.

``paths`` resolves OS-standard locations for data, config, and cache.
``settings`` snapshots environment variables into an immutable object the
rest of the CLI threads through.
"""

from __future__ import annotations

from . import paths
from .settings import Settings

__all__ = ["Settings", "paths"]
