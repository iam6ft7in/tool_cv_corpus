"""MSYS2 <-> Windows path translation tests.

These tests run on any OS since the conversion is pure-string; they
guarantee that crossing the MSYS boundary does not silently corrupt a
user-supplied path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tool_cv_corpus.utils.paths_windows import from_msys, to_msys


@pytest.mark.parametrize(
    "msys, expected",
    [
        ("/c/Users/foo", Path("C:/Users/foo")),
        ("/d/Data/archive/x.zip", Path("D:/Data/archive/x.zip")),
        ("/c", Path("C:")),
    ],
)
def test_from_msys_translates_drive(msys: str, expected: Path) -> None:
    assert from_msys(msys) == expected


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/x",
        "relative/path",
        "./sibling",
        "",
    ],
)
def test_from_msys_passthrough(value: str) -> None:
    assert from_msys(value) == Path(value)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("C:\\Users\\foo", "/c/Users/foo"),
        ("C:/Users/foo", "/c/Users/foo"),
        ("D:\\Data\\archive", "/d/Data/archive"),
    ],
)
def test_to_msys_translates_drive(path: str, expected: str) -> None:
    assert to_msys(path) == expected


def test_round_trip_preserves_body() -> None:
    start = "/c/Users/foo/bar baz"
    back = to_msys(from_msys(start))
    assert back == start
