"""MSYS2 / Windows path translation.

Claude Code's Bash tool, Git Bash, and similar MSYS2 shells present paths
as ``/c/Users/foo`` while Windows-native binaries (python.exe, typst.exe)
expect ``C:\\Users\\foo``. Whenever a path crosses that boundary we need
to translate. Inside the program we keep everything as ``pathlib.Path``;
this module is only used at system-boundary serialisation points (argv
parsing, subprocess invocation, logging of user-facing strings).

A pure function pair is preferred to an os-sniffing shim so tests run the
same on every platform and the behaviour is explicit.
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

_MSYS_DRIVE_RE = re.compile(r"^/([a-zA-Z])(/.*)?$")


def from_msys(value: str) -> Path:
    """Convert ``/c/Users/foo`` to ``Path('C:/Users/foo')``.

    Non-drive absolute paths (``/tmp/x``) and relative paths pass through
    unchanged; they are already valid on their origin platform.
    """
    match = _MSYS_DRIVE_RE.match(value)
    if not match:
        return Path(value)
    drive = match.group(1).upper()
    rest = match.group(2) or ""
    return Path(f"{drive}:{rest}")


def to_msys(value: Path | str) -> str:
    """Convert a Windows path string back to the ``/c/...`` form.

    No-op for paths without a drive letter; callers can pass any pathlib
    object safely.
    """
    pw = PureWindowsPath(str(value))
    drive = pw.drive
    if len(drive) == 2 and drive.endswith(":"):
        body = str(pw)[2:].replace("\\", "/")
        body = body.lstrip("/")
        return f"/{drive[0].lower()}/{body}" if body else f"/{drive[0].lower()}"
    return str(value).replace("\\", "/")
