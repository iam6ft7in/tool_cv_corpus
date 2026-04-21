"""Settings snapshot tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tool_cv_corpus.config.settings import DEFAULT_MODEL, Settings


def test_defaults_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CV_CORPUS_SOURCE_STORE",
        "CV_CORPUS_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.model == DEFAULT_MODEL
    assert s.anthropic_api_key is None
    assert s.openai_api_key is None
    assert isinstance(s.source_store, Path)


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CV_CORPUS_SOURCE_STORE", str(tmp_path / "custom"))
    monkeypatch.setenv("CV_CORPUS_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anth")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    s = Settings.from_env()
    assert s.source_store == tmp_path / "custom"
    assert s.model == "claude-opus-4-7"
    assert s.anthropic_api_key == "sk-test-anth"
    assert s.openai_api_key == "sk-test-openai"


def test_settings_frozen() -> None:
    s = Settings(source_store=Path("/tmp"), model="x")
    with pytest.raises(FrozenInstanceError):
        s.model = "y"  # type: ignore[misc]
